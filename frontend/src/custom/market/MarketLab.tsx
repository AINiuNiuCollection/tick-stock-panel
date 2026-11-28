/**
 * 大盘研究 — 策略实验室 Tab (双K线信号/回测/寻优)
 *
 * 信号源 = 上证指数 (M1/M2/M3 注册表模块, GET /api/market/stats/modules 驱动
 * 模块下拉与参数面板自动渲染); 交易标的 = 宽基 ETF (默认 510300)。
 *
 * 左右分栏: 左 = 参数面板 (单组回测 + 网格寻优), 右 = 结果区
 *   - 统计卡片 (回测 metrics)
 *   - 双K线联动图 (上=ETF 蜡烛 + 逐笔 B/S, 下=指数蜡烛 + 信号点)
 *   - 逐笔明细表 / 寻优结果表 (train/validation 三段对照 + 过拟合标红)
 *
 * 统计口径: 信号 T 日收盘确认 → T+1 开盘成交 / 停牌顺延 / 一字板不追 /
 * 费用滑点 (后端 /api/market 引擎, 与统计页同源)。
 */
import { useState, useMemo, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  api,
  type KlineRow,
  type MarketStatsModule,
  type MarketBacktestResponse,
  type MarketOptimizeResponse,
  type MarketMetrics,
  type MarketCostSpec,
} from '@/lib/api'
import { EmptyState } from '@/components/EmptyState'
import { MarketLabChart } from './MarketLabChart'

const DEFAULT_INDEX = '000001.SH'
const TARGET_PRESETS = ['510300.SH', '510500.SH', '512100.SH', '588000.SH', '159915.SZ']
const DEFAULT_TARGET = '510300.SH'
const EXIT_MODES = [
  { value: 'time', label: '持仓 N 日' },
  { value: 'reverse', label: '反向信号平仓' },
  { value: 'profit_stop', label: '止盈止损' },
] as const

const inputCls = 'h-8 px-2 rounded-btn border border-border bg-base text-sm'

/** select 选项的中文可读标签 (无映射时回退原值) */
const OPTION_LABELS: Record<string, string> = {
  single: '单日急跌',
  cumulative: 'N日累计跌速',
}

/** ? 悬浮解释 — 不占版面, hover 出说明 (可解释性优先, v3-②) */
function HelpTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="ml-1 inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full border border-muted text-[9px] font-bold leading-none text-muted hover:border-accent hover:text-accent select-none"
    >
      ?
    </span>
  )
}

/** 费用/仓位预设 — 交易员口径: ETF 免印花税; 股票口径含单边印花税 */
const COST_PRESETS: { label: string; cost: MarketCostSpec; position: number }[] = [
  {
    label: 'ETF 默认',
    cost: { commission_rate: 0.00025, stamp_tax_rate: 0, slippage_rate: 0.001 },
    position: 1.0,
  },
  {
    label: '股票口径',
    cost: { commission_rate: 0.00025, stamp_tax_rate: 0.0005, slippage_rate: 0.001 },
    position: 0.8,
  },
]

/** 请求费用与响应生效费用一致性断言 (任何字段不等 = 后端未按请求生效, 标红警示) */
function costMismatch(req: MarketCostSpec | undefined, resp: MarketCostSpec | undefined): boolean {
  if (!req || !resp) return false
  return (
    req.commission_rate !== resp.commission_rate ||
    req.stamp_tax_rate !== resp.stamp_tax_rate ||
    req.slippage_rate !== resp.slippage_rate
  )
}

function costSummary(c: MarketCostSpec | undefined, position: number | undefined): string {
  if (!c) return '—'
  return `佣金${(c.commission_rate * 10000).toFixed(1)}‱ · 印花${(c.stamp_tax_rate * 10000).toFixed(1)}‱ · 滑点${(c.slippage_rate * 100).toFixed(2)}% · 仓位${((position ?? 1) * 100).toFixed(0)}%`
}

/** ParamSpec 类型 → 受控值 (select 存 string, 数值存 number) */
function paramDefault(p: MarketStatsModule['params'][number]): number | string {
  return p.type === 'select' ? String(p.default) : Number(p.default)
}

function fmtPct(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(2)}%`
}

function fmtNum(v: number | null | undefined): string {
  return v == null || !Number.isFinite(v) ? '—' : v.toFixed(2)
}

/** 统计卡片行 — 一行 metrics 关键值 */
function MetricsRow({ label, m }: { label: string; m: MarketMetrics }) {
  return (
    <div className="p-2 rounded-btn border border-border text-xs leading-5">
      <div className="text-muted">{label}</div>
      <div className={(m.total_return_pct ?? 0) >= 0 ? 'text-danger' : 'text-bear'}>
        总收益 {fmtPct(m.total_return_pct)}
      </div>
      <div className="text-secondary">年化 {fmtPct(m.annual_return_pct)}</div>
      <div className="text-secondary">回撤 {fmtPct(m.max_drawdown_pct)}</div>
      <div className="text-secondary">{m.n_trades} 笔 · 胜率 {fmtPct(m.win_rate)}</div>
    </div>
  )
}

export function MarketLab() {
  // ---- 参数状态 ----
  const [indexSymbol, setIndexSymbol] = useState(DEFAULT_INDEX)
  const [targetSymbol, setTargetSymbol] = useState(DEFAULT_TARGET)
  const [startDate, setStartDate] = useState('2018-01-01')
  const [endDate, setEndDate] = useState('')
  const [moduleId, setModuleId] = useState('')
  const [entryParams, setEntryParams] = useState<Record<string, number | string>>({})
  const [exitMode, setExitMode] = useState<'time' | 'reverse' | 'profit_stop'>('time')
  const [holdDays, setHoldDays] = useState(5)
  const [takeProfit, setTakeProfit] = useState(5)
  const [stopLoss, setStopLoss] = useState(3)
  const [trainRatio, setTrainRatio] = useState(0.7)
  // ---- 费用与仓位 (设计 §8.5 全可配; 默认=后端缺省 ETF 口径) ----
  const [commission, setCommission] = useState(0.00025)
  const [stampTax, setStampTax] = useState(0)
  const [slippage, setSlippage] = useState(0.001)
  const [positionRatio, setPositionRatio] = useState(1.0)
  const [runKey, setRunKey] = useState(0)
  const [optKey, setOptKey] = useState(0)

  // ---- 信号模块注册表 ----
  const modulesQuery = useQuery({
    queryKey: ['market-stats-modules'],
    queryFn: () => api.marketStatsModules(),
    staleTime: 60 * 60_000,
  })
  const modules = modulesQuery.data?.modules ?? []
  const activeModule = modules.find((m) => m.id === moduleId)

  // 模块列表到达后选第一个模块并填充参数默认值 (仅一次/换模块时)
  useEffect(() => {
    if (!modules.length) return
    if (!modules.some((m) => m.id === moduleId)) {
      setModuleId(modules[0].id)
    }
  }, [modules, moduleId])
  useEffect(() => {
    if (!activeModule) return
    setEntryParams(Object.fromEntries(activeModule.params.map((p) => [p.name, paramDefault(p)])))
  }, [activeModule])

  const exitSpec = useMemo(
    () => ({
      mode: exitMode,
      hold_days: holdDays,
      take_profit_pct: takeProfit,
      stop_loss_pct: stopLoss,
    }),
    [exitMode, holdDays, takeProfit, stopLoss],
  )

  const costSpec = useMemo<MarketCostSpec>(
    () => ({
      commission_rate: commission,
      stamp_tax_rate: stampTax,
      slippage_rate: slippage,
    }),
    [commission, stampTax, slippage],
  )

  // ---- 单组回测 ----
  const backtest = useQuery<MarketBacktestResponse>({
    queryKey: ['market-backtest', runKey],
    queryFn: () =>
      api.marketBacktest({
        index_symbol: indexSymbol,
        target_symbol: targetSymbol,
        module_id: moduleId,
        entry_params: entryParams,
        exit: exitSpec,
        start: startDate || undefined,
        end: endDate || undefined,
        cost: costSpec,
        position_ratio: positionRatio,
      }),
    enabled: runKey > 0,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
  })

  // ---- 寻优 ----
  const optimize = useQuery<MarketOptimizeResponse>({
    queryKey: ['market-optimize', optKey],
    queryFn: () =>
      api.marketOptimize({
        index_symbol: indexSymbol,
        target_symbol: targetSymbol,
        module_id: moduleId,
        entry_params: entryParams,
        entry_grid: Object.fromEntries(
          Object.entries(entryParams).map(([k, v]) => [k, [v as number]]),
        ),
        exit: exitSpec,
        exit_grid: null,
        train_ratio: trainRatio,
        start: startDate || undefined,
        end: endDate || undefined,
        cost: costSpec,
        position_ratio: positionRatio,
      }),
    enabled: optKey > 0,
    staleTime: 30 * 60_000,
    gcTime: 60 * 60_000,
  })

  // ---- 双K线数据: 回测响应内嵌 raw 分区 OHLCV (深历史) ----
  const bt = backtest.data
  const opt = optimize.data
  const targetRows: KlineRow[] = bt?.target_bars ?? []
  const indexRows: KlineRow[] = bt?.index_bars ?? []

  return (
    <div className="flex h-full min-h-0">
      {/* 左: 参数面板 */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setRunKey((k) => k + 1)
        }}
        className="w-72 shrink-0 border-r border-border overflow-y-auto p-3 flex flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">信号源 (指数)</span>
          <select value={indexSymbol} onChange={(e) => setIndexSymbol(e.target.value)} className={inputCls}>
            <option value="000001.SH">上证指数 000001.SH</option>
            <option value="399001.SZ">深证成指 399001.SZ</option>
            <option value="399006.SZ">创业板指 399006.SZ</option>
            <option value="000300.SH">沪深300 000300.SH</option>
            <option value="000905.SH">中证500 000905.SH</option>
            <option value="000852.SH">中证1000 000852.SH</option>
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">交易标的 (ETF)</span>
          <select value={targetSymbol} onChange={(e) => setTargetSymbol(e.target.value)} className={inputCls}>
            {TARGET_PRESETS.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">开始</span>
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className={inputCls} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">结束</span>
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className={inputCls} />
          </label>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">信号模块</span>
          <select
            value={moduleId}
            onChange={(e) => setModuleId(e.target.value)}
            className={inputCls}
          >
            {modules.map((m) => (
              <option key={m.id} value={m.id}>{m.label} ({m.id})</option>
            ))}
          </select>
          {activeModule && <p className="text-xs text-secondary leading-4">{activeModule.description}</p>}
        </div>

        {/* 注册表驱动参数面板 — 说明收敛为 ? 悬浮, 留出版面 (v3-②) */}
        {activeModule && (
          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium text-muted">入场参数 (注册表驱动)</span>
            {activeModule.params.map((p) => {
              // 联动规则: kind=single 时累计天数锁 1 且禁改 (单日口径无累计窗口)
              const lockToOne = p.name === 'cum_days' && String(entryParams['kind']) === 'single'
              return (
                <label key={p.name} className="flex flex-col gap-1">
                  <span className="text-xs text-secondary">
                    {p.label}
                    {p.description && <HelpTip text={p.description} />}
                  </span>
                  {p.type === 'select' && p.options?.length ? (
                    <select
                      value={String(entryParams[p.name] ?? '')}
                      onChange={(e) => {
                        const v = e.target.value
                        setEntryParams((prev) => ({
                          ...prev,
                          [p.name]: v,
                          ...(p.name === 'kind' && v === 'single' ? { cum_days: 1 } : {}),
                        }))
                      }}
                      className={inputCls}
                    >
                      {p.options.map((o) => (
                        <option key={o} value={o}>{OPTION_LABELS[o] ?? o}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="number"
                      disabled={lockToOne}
                      value={lockToOne ? 1 : Number(entryParams[p.name] ?? 0)}
                      min={p.min ?? undefined}
                      max={p.max ?? undefined}
                      step={p.type === 'float' ? 'any' : 1}
                      onChange={(e) =>
                        setEntryParams((prev) => ({ ...prev, [p.name]: Number(e.target.value) }))
                      }
                      className={lockToOne ? `${inputCls} opacity-50 cursor-not-allowed` : inputCls}
                    />
                  )}
                </label>
              )
            })}
          </div>
        )}

        {/* 出场参数 */}
        <div className="flex flex-col gap-2">
          <span className="text-xs font-medium text-muted">出场规则</span>
          <select value={exitMode} onChange={(e) => setExitMode(e.target.value as typeof exitMode)} className={inputCls}>
            {EXIT_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          {exitMode === 'reverse' && (
            <div className="rounded-btn border border-border bg-elevated p-2 text-[11px] leading-4 text-secondary">
              <span className="font-medium text-foreground">反向信号从哪来？</span>
              <HelpTip text="反向信号不是独立设置项 — 由当前信号模块按入场参数自产 (direction=-1): 急涨急跌=急涨日/累计涨超阈值; 均线状态机=收盘跌破均线; 量价组合=成交额分位≥90%。改入场参数即改反向信号。" />
              <p className="mt-1">
                由所选信号模块自产生 (direction=-1 的信号): 例如「急涨急涨」的急涨日、「均线状态机」的跌破均线、「量价组合」的极端放量。改入场参数 = 同时改反向信号口径。
              </p>
              {bt && (
                <p className={`mt-1 ${bt.signals.filter((s) => s.direction < 0).length === 0 ? 'text-yellow-600' : ''}`}>
                  当前参数下反向信号{' '}
                  <b>{bt.signals.filter((s) => s.direction < 0).length}</b> 条
                  {bt.signals.filter((s) => s.direction < 0).length === 0 &&
                    ' ⚠ 本参数组不产生反向信号 — 持仓将一直持有到数据结束 (end_of_data)'}
                </p>
              )}
            </div>
          )}
          {exitMode === 'time' && (
            <label className="flex flex-col gap-1">
              <span className="text-xs text-secondary">持仓天数</span>
              <input type="number" min={1} max={250} value={holdDays}
                onChange={(e) => setHoldDays(Number(e.target.value))} className={inputCls} />
            </label>
          )}
          {exitMode === 'profit_stop' && (
            <div className="grid grid-cols-2 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-secondary">止盈 %</span>
                <input type="number" step="any" min={0.1} max={100} value={takeProfit}
                  onChange={(e) => setTakeProfit(Number(e.target.value))} className={inputCls} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-secondary">止损 %</span>
                <input type="number" step="any" min={0.1} max={50} value={stopLoss}
                  onChange={(e) => setStopLoss(Number(e.target.value))} className={inputCls} />
              </label>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-xs font-medium text-muted">
            寻优 train 占比
            <HelpTip text="样本切分比例: 前 train% 用于选参数 (train 段), 其余段作为未见样本验证是否过拟合。寻优表按 train 收益选出的参数若在 validation 段明显掉收益 → 标红「过拟合」。建议 0.6~0.75。" />
          </span>
          <input type="number" step="0.05" min={0.15} max={0.9} value={trainRatio}
            onChange={(e) => setTrainRatio(Number(e.target.value))} className={inputCls} />
        </div>

        {/* 费用与仓位 — 收起式面板, 默认折叠只显示生效摘要 (设计 §8.5 全可配) */}
        <details className="rounded-btn border border-border">
          <summary className="px-2 py-1.5 text-xs font-medium text-muted cursor-pointer select-none">
            费用与仓位
            <span className="ml-1.5 font-normal text-secondary">{costSummary(costSpec, positionRatio)}</span>
          </summary>
          <div className="px-2 pb-2 flex flex-col gap-2">
            <div className="flex gap-1.5">
              {COST_PRESETS.map((p) => (
                <button
                  key={p.label}
                  type="button"
                  onClick={() => {
                    setCommission(p.cost.commission_rate)
                    setStampTax(p.cost.stamp_tax_rate)
                    setSlippage(p.cost.slippage_rate)
                    setPositionRatio(p.position)
                  }}
                  className="flex-1 px-1 py-0.5 rounded text-[11px] border border-border text-secondary hover:border-accent hover:text-foreground"
                >
                  {p.label}
                </button>
              ))}
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-secondary">佣金率 (小数, 万2.5=0.00025)</span>
              <input type="number" step="any" min={0} max={0.01} value={commission}
                onChange={(e) => setCommission(Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-secondary">印花税率 (ETF=0)</span>
              <input type="number" step="any" min={0} max={0.01} value={stampTax}
                onChange={(e) => setStampTax(Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-secondary">滑点 (小数, 不利方向)</span>
              <input type="number" step="any" min={0} max={0.05} value={slippage}
                onChange={(e) => setSlippage(Number(e.target.value))} className={inputCls} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-secondary">仓位比例 (0.1–1.0)</span>
              <input type="number" step="0.05" min={0.1} max={1} value={positionRatio}
                onChange={(e) => setPositionRatio(Number(e.target.value))} className={inputCls} />
            </label>
          </div>
        </details>

        <div className="flex flex-col gap-2">
          <button
            type="submit"
            disabled={backtest.isFetching || !moduleId}
            className="h-8 px-3 rounded-[3px] bg-accent text-white text-sm font-normal leading-[1.42857143] transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {backtest.isFetching ? '回测中…' : '运行回测'}
          </button>
          <button
            type="button"
            disabled={optimize.isFetching || !moduleId}
            onClick={(e) => {
              e.preventDefault()
              setOptKey((k) => k + 1)
            }}
            className="h-8 px-3 rounded-[3px] border border-border bg-base text-sm font-normal leading-[1.42857143] transition-colors hover:bg-elevated disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {optimize.isFetching ? '寻优中…' : '网格寻优'}
          </button>
        </div>
      </form>

      {/* 右: 结果区 */}
      <div className="flex-1 min-w-0 overflow-y-auto p-3 flex flex-col gap-3">
        {runKey === 0 ? (
          <EmptyState title="策略实验室" hint="左侧选择信号模块与参数, 点击「运行回测」— 信号源=指数, 交易标的=ETF, T+1 开盘成交" />
        ) : backtest.isError ? (
          <EmptyState title="回测失败" hint="请确认后端已加载 /api/market 路由且指数/ETF 日K数据已回填" />
        ) : backtest.isFetching && !bt ? (
          <EmptyState title="回测计算中…" />
        ) : !bt ? (
          <EmptyState title="无回测结果" />
        ) : (
          <>
            {/* 生效费用回显 + 一致性断言 (§8.5 可溯源) */}
            {costMismatch(costSpec, bt.cost) ? (
              <div className="px-2 py-1.5 rounded-btn border border-danger/50 bg-danger/10 text-xs text-danger shrink-0">
                ⚠ 后端生效费用与请求不一致 — 请求 {costSummary(costSpec, positionRatio)} / 生效 {costSummary(bt.cost, undefined)}
              </div>
            ) : (
              <p className="text-[11px] text-muted shrink-0">生效费用: {costSummary(bt.cost, positionRatio)}</p>
            )}

            {/* 统计卡片 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2 shrink-0">
              <MetricsRow label="全区间" m={bt.metrics} />
              <div className="p-2 rounded-btn border border-border text-xs leading-5">
                <div className="text-muted">期末权益</div>
                <div className="text-sm">{bt.metrics.final_equity?.toFixed(0) ?? '—'}</div>
                <div className="text-secondary">初始 {bt.metrics.initial_capital?.toFixed(0) ?? '—'}</div>
                <div className="text-secondary">夏普 {fmtNum(bt.metrics.sharpe)}</div>
                <div className="text-secondary">盈亏比 {fmtNum(bt.metrics.profit_loss_ratio)}</div>
              </div>
              <div className="p-2 rounded-btn border border-border text-xs leading-5">
                <div className="text-muted">窗口</div>
                <div className="text-secondary">{bt.window.start} →</div>
                <div className="text-secondary">{bt.window.end}</div>
                <div className="text-secondary">平均持仓 {bt.metrics.avg_hold_days ?? '—'} 日</div>
              </div>
              <div className="p-2 rounded-btn border border-border text-xs leading-5">
                <div className="text-muted">信号</div>
                <div>{bt.signals.length} 条 (做多 {bt.buy_signals.length})</div>
                <div className="text-secondary">成交 {bt.trades.length} 笔</div>
                <div className="text-secondary">{bt.module_id}</div>
              </div>
            </div>

            {/* 双K线联动图 */}
            <section className="bg-elevated rounded-btn p-3 shrink-0">
              <div className="text-sm font-medium mb-2">
                双K线联动 — 上: {bt.target_symbol} (B/S 逐笔) / 下: {bt.index_symbol} (▲做多 ▼反向)
              </div>
              {targetRows.length && indexRows.length ? (
                <MarketLabChart
                  targetSymbol={bt.target_symbol}
                  indexSymbol={bt.index_symbol}
                  targetRows={targetRows}
                  indexRows={indexRows}
                  trades={bt.trades}
                  signals={bt.signals}
                />
              ) : (
                <EmptyState title="拉取双K线数据中…" />
              )}
            </section>

            {/* 逐笔明细 */}
            <section className="bg-elevated rounded-btn p-3 shrink-0">
              <div className="text-sm font-medium mb-2">逐笔明细 ({bt.trades.length} 笔)</div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted border-b border-border">
                      <th className="py-1 pr-3">信号日</th>
                      <th className="py-1 pr-3">买入日</th>
                      <th className="py-1 pr-3">买价</th>
                      <th className="py-1 pr-3">卖出日</th>
                      <th className="py-1 pr-3">卖价</th>
                      <th className="py-1 pr-3">原因</th>
                      <th className="py-1 pr-3">股数</th>
                      <th className="py-1 pr-3">盈亏</th>
                      <th className="py-1 pr-3">收益率</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bt.trades.map((t, i) => (
                      <tr key={i} className="border-b border-border/50">
                        <td className="py-1 pr-3">{t.entry_signal_dt}</td>
                        <td className="py-1 pr-3">{t.entry_dt}</td>
                        <td className="py-1 pr-3">{t.entry_price.toFixed(3)}</td>
                        <td className="py-1 pr-3">{t.exit_dt ?? '—'}</td>
                        <td className="py-1 pr-3">{t.exit_price?.toFixed(3) ?? '—'}</td>
                        <td className="py-1 pr-3">{t.exit_reason}</td>
                        <td className="py-1 pr-3">{t.shares}</td>
                        <td className={`py-1 pr-3 ${t.pnl >= 0 ? 'text-danger' : 'text-bear'}`}>
                          {t.pnl.toFixed(0)}
                        </td>
                        <td className={`py-1 pr-3 ${t.return_pct >= 0 ? 'text-danger' : 'text-bear'}`}>
                          {fmtPct(t.return_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!bt.trades.length && <p className="text-xs text-muted py-2">本参数组未产生交易</p>}
              </div>
            </section>
          </>
        )}

        {/* 寻优结果 */}
        {optKey > 0 && (
          <section className="bg-elevated rounded-btn p-3 shrink-0">
            <div className="text-sm font-medium mb-2">
              网格寻优 ({opt?.n_combos ?? '…'} 组合
              {opt?.window?.split ? `, train/validation 分割 ${opt.window.split}` : ''})
            </div>
            {optimize.isError ? (
              <p className="text-xs text-bear">寻优失败</p>
            ) : optimize.isFetching ? (
              <p className="text-xs text-muted">全枚举网格计算中…</p>
            ) : !opt ? null : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-muted border-b border-border">
                      <th className="py-1 pr-3">入场参数</th>
                      <th className="py-1 pr-3">出场</th>
                      <th className="py-1 pr-3">全区间收益</th>
                      <th className="py-1 pr-3">train 收益</th>
                      <th className="py-1 pr-3">validation 收益</th>
                      <th className="py-1 pr-3">回撤</th>
                      <th className="py-1 pr-3">笔数</th>
                      <th className="py-1 pr-3">过拟合</th>
                    </tr>
                  </thead>
                  <tbody>
                    {opt.rows.map((r, i) => (
                      <tr
                        key={i}
                        className="border-b border-border/50 cursor-pointer hover:bg-elevated/60"
                        title="点击应用该参数组并运行回测"
                        onClick={() => {
                          setEntryParams((prev) => ({
                            ...prev,
                            ...Object.fromEntries(
                              Object.entries(r.entry_params).map(([k, v]) => [k, Number(v)]),
                            ),
                          }))
                          setExitMode((r.exit.mode as typeof exitMode) ?? 'time')
                          if (typeof r.exit.hold_days === 'number') setHoldDays(r.exit.hold_days)
                          if (typeof r.exit.take_profit_pct === 'number') setTakeProfit(r.exit.take_profit_pct)
                          if (typeof r.exit.stop_loss_pct === 'number') setStopLoss(r.exit.stop_loss_pct)
                          setRunKey((k) => k + 1)
                        }}
                      >
                        <td className="py-1 pr-3">
                          {Object.entries(r.entry_params).map(([k, v]) => `${k}=${v}`).join(' ')}
                        </td>
                        <td className="py-1 pr-3">
                          {r.exit.mode}
                          {r.exit.mode !== 'reverse' && r.exit.hold_days != null ? `/${r.exit.hold_days}d` : ''}
                          {r.exit.take_profit_pct != null && r.exit.stop_loss_pct != null
                            ? ` tp${r.exit.take_profit_pct}/sl${r.exit.stop_loss_pct}`
                            : ''}
                        </td>
                        <td className={`py-1 pr-3 ${(r.full.total_return_pct ?? 0) >= 0 ? 'text-danger' : 'text-bear'}`}>
                          {fmtPct(r.full.total_return_pct)}
                        </td>
                        <td className={`py-1 pr-3 ${(r.train.total_return_pct ?? 0) >= 0 ? 'text-danger' : 'text-bear'}`}>
                          {fmtPct(r.train.total_return_pct)}
                        </td>
                        <td className={`py-1 pr-3 ${(r.validation.total_return_pct ?? 0) >= 0 ? 'text-danger' : 'text-bear'}`}>
                          {fmtPct(r.validation.total_return_pct)}
                        </td>
                        <td className="py-1 pr-3">{fmtPct(r.full.max_drawdown_pct)}</td>
                        <td className="py-1 pr-3">{r.full.n_trades}</td>
                        <td className="py-1 pr-3">
                          {r.overfit_flag ? <span className="text-danger font-medium">⚠ 过拟合</span> : '—'}
                      </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}
