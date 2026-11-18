/**
 * 潘扬-异动波段策略弹窗页 (/panyang 路由, window.open 打开)
 *
 * 跨资产回测:
 *   信号源 = 上证指数 000001.SH (写死, 后端在指数上算买卖信号)
 *   交易标的 = 用户配置 (默认 512100.SH 中证1000ETF), 前端用信号日对齐 K 线重算盈亏
 *   matching = open_t+1 (信号次日开盘成交)
 *
 * URL 参数 (由「单独回测」按钮构造):
 *   ?run=1&trade_symbol=512100.SH&start=2026-09-01&end=2026-11-17
 *   &buy_mom_thr=2.0&mom_period=5&ma_period=5&max_hold_days=30&cooldown_days=5
 */
import { useState, useMemo, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api, type StrategyBacktestResult, type StrategyBacktestTrade, type KlineRow } from '@/lib/api'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { PanYangChart } from './PanYangChart'
import { PanYangStats } from './PanYangStats'
import { PanYangTradesTable } from './PanYangTradesTable'

const STRATEGY_ID = 'custom_panyang_anomaly_wave'
const SIGNAL_SYMBOL = '000001.SH' // 上证指数, 写死

const DEFAULT_TRADE_SYMBOL = '512100.SH' // 中证1000ETF
const DEFAULT_START = '2026-09-01'
const DEFAULT_END = '2026-11-17'

/** 交易标的重算后的 trade (entry/exit price 来自交易标的 K 线) */
interface RemappedTrade extends StrategyBacktestTrade {
  signal_entry_price: number // 信号源(指数)入场价, 仅供参考
  signal_exit_price: number
}

/** 跨资产回测结果: trades/stats/equity_curve 均基于交易标的重算 */
interface CrossAssetResult {
  trades: RemappedTrade[]
  stats: Record<string, any>
  equityCurve: { date: string; value: number }[]
  benchmarkCurve: { date: string; value: number; close?: number }[]
  rawResult: StrategyBacktestResult // 后端指数回测原始结果
}

/** 用信号日对齐交易标的 K 线, 重算 trades 盈亏 (matching=open_t+1) */
function remapTradesToTradeAsset(
  signalTrades: StrategyBacktestTrade[],
  klineRows: KlineRow[],
  initialCapital: number,
): { trades: RemappedTrade[]; equityCurve: { date: string; value: number }[]; stats: Record<string, any> } {
  if (!klineRows.length || !signalTrades.length) {
    return { trades: [], equityCurve: [], stats: {} }
  }

  // 构建日期 → K 线索引 (用于查找次日 open)
  const dateToIdx = new Map<string, number>()
  klineRows.forEach((r, i) => dateToIdx.set(r.date, i))

  // 查找信号日的次日 open 作为成交价 (matching=open_t+1)
  const fillPrice = (signalDate: string): { price: number; fillDate: string } | null => {
    const idx = dateToIdx.get(signalDate)
    if (idx === undefined) {
      // 信号日不在 K 线中 (可能是非交易日), 找下一个交易日
      const sorted = klineRows.filter((r) => r.date > signalDate).sort((a, b) => a.date.localeCompare(b.date))
      if (sorted.length === 0) return null
      return { price: sorted[0].open, fillDate: sorted[0].date }
    }
    // 信号日次日的 open
    if (idx + 1 < klineRows.length) {
      const next = klineRows[idx + 1]
      return { price: next.open, fillDate: next.date }
    }
    // 信号日是最后一天, 用当日 close 兜底
    return { price: klineRows[idx].close, fillDate: klineRows[idx].date }
  }

  const remapped: RemappedTrade[] = []
  for (const t of signalTrades) {
    const entry = fillPrice(t.entry_date)
    const exit = fillPrice(t.exit_date)
    if (!entry || !exit) continue
    const pnlPct = (exit.price - entry.price) / entry.price
    remapped.push({
      ...t,
      entry_price: entry.price,
      exit_price: exit.price,
      entry_date: entry.fillDate,
      exit_date: exit.fillDate,
      pnl_pct: pnlPct,
      signal_entry_price: t.entry_price,
      signal_exit_price: t.exit_price,
    })
  }

  // 重算 equity_curve: 按交易日逐日累计, 持仓期间用交易标的收盘价估值
  const equityCurve: { date: string; value: number }[] = []
  let capital = initialCapital
  let position: { entryPrice: number; shares: number } | null = null

  for (const row of klineRows) {
    // 检查当日是否有入场
    const entryTrade = remapped.find((t) => t.entry_date === row.date)
    if (entryTrade && !position) {
      const shares = Math.floor(capital / entryTrade.entry_price)
      capital -= shares * entryTrade.entry_price
      position = { entryPrice: entryTrade.entry_price, shares }
    }

    // 检查当日是否有出场
    const exitTrade = remapped.find((t) => t.exit_date === row.date)
    if (exitTrade && position) {
      capital += position.shares * exitTrade.exit_price
      position = null
    }

    // 当日净值 = 现金 + 持仓市值 (用当日 close 估值)
    const holdingValue = position ? position.shares * row.close : 0
    equityCurve.push({ date: row.date, value: capital + holdingValue })
  }

  // 重算 stats
  const nTrades = remapped.length
  const wins = remapped.filter((t) => t.pnl_pct > 0)
  const winRate = nTrades > 0 ? wins.length / nTrades : 0
  const totalReturn = equityCurve.length > 0
    ? (equityCurve[equityCurve.length - 1].value - initialCapital) / initialCapital
    : 0

  // 最大回撤
  let peak = -Infinity
  let mdd = 0
  for (const p of equityCurve) {
    if (p.value > peak) peak = p.value
    const dd = (p.value - peak) / peak
    if (dd < mdd) mdd = dd
  }

  // 年化 (按交易日 252 天近似)
  const days = equityCurve.length
  const cagr = days > 0 ? Math.pow(1 + totalReturn, 252 / days) - 1 : 0

  // 平均收益
  const avgReturn = nTrades > 0 ? remapped.reduce((s, t) => s + t.pnl_pct, 0) / nTrades : 0

  // 盈亏比
  const winAvg = wins.length > 0 ? wins.reduce((s, t) => s + t.pnl_pct, 0) / wins.length : 0
  const losses = remapped.filter((t) => t.pnl_pct <= 0)
  const lossAvg = losses.length > 0 ? Math.abs(losses.reduce((s, t) => s + t.pnl_pct, 0) / losses.length) : 0
  const plRatio = lossAvg > 0 ? winAvg / lossAvg : 0

  const stats = {
    n_trades: nTrades,
    win_rate: winRate,
    total_return: totalReturn,
    cagr,
    max_drawdown: mdd,
    avg_return: avgReturn,
    profit_loss_ratio: plRatio,
  }

  return { trades: remapped, equityCurve, stats }
}

export function PanYangPage() {
  const [searchParams] = useSearchParams()

  // 从 URL 读参数 (弹窗模式: run=1 时自动触发回测)
  const [tradeSymbol, setTradeSymbol] = useState(searchParams.get('trade_symbol') ?? DEFAULT_TRADE_SYMBOL)
  const [startDate, setStartDate] = useState(searchParams.get('start') ?? DEFAULT_START)
  const [endDate, setEndDate] = useState(searchParams.get('end') ?? DEFAULT_END)
  const [buyMomThr, setBuyMomThr] = useState(parseFloat(searchParams.get('buy_mom_thr') ?? '2.0'))
  const [momPeriod, setMomPeriod] = useState(parseInt(searchParams.get('mom_period') ?? '5', 10))
  const [maPeriod, setMaPeriod] = useState(parseInt(searchParams.get('ma_period') ?? '5', 10))
  const [maxHoldDays, setMaxHoldDays] = useState(parseInt(searchParams.get('max_hold_days') ?? '30', 10))
  const [cooldownDays, setCooldownDays] = useState(parseInt(searchParams.get('cooldown_days') ?? '5', 10))

  const [runKey, setRunKey] = useState(searchParams.get('run') === '1' ? 1 : 0)

  // 后端回测: 在上证指数上算信号
  const backtest = useQuery<StrategyBacktestResult>({
    queryKey: ['panyang-signal', runKey],
    queryFn: () =>
      api.strategyBacktestRun({
        strategy_id: STRATEGY_ID,
        symbols: [SIGNAL_SYMBOL],
        start: startDate,
        end: endDate,
        asset_type: 'index',
        max_positions: 1,
        initial_capital: 1_000_000,
        matching: 'open_t+1',
        params: {
          mom_period: momPeriod,
          buy_mom_thr: buyMomThr,
          ma_period: maPeriod,
          max_hold_days: maxHoldDays,
          cooldown_days: cooldownDays,
          use_ma_exit: true,
          use_mom_neg_exit: true,
        },
      }),
    enabled: runKey > 0,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  })

  // 拉交易标的 K 线 (用于跨资产盈亏重算 + K 线图表)
  const kline = useQuery({
    queryKey: ['panyang-trade-kline', tradeSymbol, startDate, endDate, runKey],
    queryFn: () =>
      api.klineDaily(tradeSymbol.trim(), undefined, { start: startDate, end: endDate }),
    enabled: runKey > 0 && !!tradeSymbol.trim() && !!backtest.data,
    staleTime: 5 * 60_000,
    gcTime: 30 * 60_000,
  })

  const klineRows: KlineRow[] = kline.data?.rows ?? []

  // 跨资产重算: 用信号日对齐交易标的 K 线, 重算 trades/stats/equity_curve
  const crossAssetResult: CrossAssetResult | null = useMemo(() => {
    if (!backtest.data || klineRows.length === 0) return null
    const signalTrades = backtest.data.trades ?? []
    const { trades, equityCurve, stats } = remapTradesToTradeAsset(
      signalTrades,
      klineRows,
      1_000_000,
    )
    // benchmark = 交易标的自身净值 (用首日 close 归一化)
    const firstClose = klineRows[0]?.close ?? 1
    const benchmarkCurve = klineRows.map((r) => ({
      date: r.date,
      value: r.close / firstClose,
      close: r.close,
      symbol: tradeSymbol,
    }))
    return {
      trades,
      stats,
      equityCurve,
      benchmarkCurve,
      rawResult: backtest.data,
    }
  }, [backtest.data, klineRows, tradeSymbol])

  const isPopup = searchParams.get('run') === '1'

  const handleRun = () => setRunKey((k) => k + 1)

  // 弹窗模式自动触发回测
  useEffect(() => {
    if (isPopup && runKey === 0) setRunKey(1)
  }, [isPopup, runKey])

  const stats = crossAssetResult?.stats ?? {}
  const trades = crossAssetResult?.trades ?? []
  const equityCurve = crossAssetResult?.equityCurve ?? []
  const benchmarkCurve = crossAssetResult?.benchmarkCurve ?? []
  const hasKline = klineRows.length > 0

  return (
    <div className="flex flex-col gap-3 h-full p-3">
      <PageHeader
        title="上证指数跟踪 — 异动波段策略"
        subtitle={`信号源: 上证指数 ${SIGNAL_SYMBOL} (写死) → 交易标的: ${tradeSymbol} | matching=open_t+1`}
      />

      {/* 参数面板 */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          handleRun()
        }}
        className="flex flex-wrap items-end gap-3 p-3 bg-elevated rounded-btn"
      >
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">交易标的</span>
          <input
            type="text"
            value={tradeSymbol}
            onChange={(e) => setTradeSymbol(e.target.value)}
            placeholder="512100.SH / 510300.SH / 股票代码"
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-40"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">起始日期</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">结束日期</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">买入动量阈值(%)</span>
          <input
            type="number"
            step="0.1"
            min="0.5"
            max="10"
            value={buyMomThr}
            onChange={(e) => setBuyMomThr(parseFloat(e.target.value))}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-24"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">动量EMA周期</span>
          <input
            type="number"
            step="1"
            min="3"
            max="20"
            value={momPeriod}
            onChange={(e) => setMomPeriod(parseInt(e.target.value, 10))}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">卖出均线天数</span>
          <input
            type="number"
            step="1"
            min="3"
            max="60"
            value={maPeriod}
            onChange={(e) => setMaPeriod(parseInt(e.target.value, 10))}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">最大持仓天数</span>
          <input
            type="number"
            step="1"
            min="5"
            max="60"
            value={maxHoldDays}
            onChange={(e) => setMaxHoldDays(parseInt(e.target.value, 10))}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted">冷却期天数</span>
          <input
            type="number"
            step="1"
            min="0"
            max="30"
            value={cooldownDays}
            onChange={(e) => setCooldownDays(parseInt(e.target.value, 10))}
            className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
          />
        </label>
        <button
          type="submit"
          disabled={backtest.isFetching || !tradeSymbol.trim()}
          className="h-8 min-w-[80px] px-3 py-1 rounded-[3px] bg-accent text-white text-sm font-normal leading-[1.42857143] transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {backtest.isFetching ? '回测中…' : '单独回测'}
        </button>
      </form>

      {backtest.isError ? (
        <EmptyState title="回测失败" hint="请检查服务状态或参数 (信号源需为 index 资产类型)" />
      ) : backtest.isFetching && !backtest.data ? (
        <EmptyState title="在上证指数上计算信号中…" />
      ) : !backtest.data ? (
        <EmptyState title="点击「单独回测」按钮开始" />
      ) : kline.isFetching && !klineRows.length ? (
        <EmptyState title="拉取交易标的 K 线…" />
      ) : !crossAssetResult ? (
        <EmptyState title="重算跨资产盈亏中…" />
      ) : (
        <>
          {/* 统计卡片 — 基于交易标的重算 */}
          <PanYangStats stats={stats} strategyInfo={backtest.data.strategy_info} />

          {/* 净值对比图 — 策略净值(交易标的) vs 基准(交易标的自身) */}
          <section className="bg-elevated rounded-btn p-3">
            <div className="text-sm font-medium mb-2">
              净值对比（策略 vs {tradeSymbol} 基准）
            </div>
            <PanYangChart
              equityCurve={equityCurve}
              benchmarkCurve={benchmarkCurve}
              trades={trades}
              height={340}
              mode="nav"
            />
          </section>

          {/* K线 + 买卖点 — 交易标的 K 线上标 B/S */}
          <section className="bg-elevated rounded-btn p-3">
            <div className="text-sm font-medium mb-2">
              买卖点 ({tradeSymbol} K线, 信号源 {SIGNAL_SYMBOL})
            </div>
            <PanYangChart
              equityCurve={equityCurve}
              benchmarkCurve={[]}
              trades={trades}
              height={480}
              mode={hasKline ? 'kline' : 'signals'}
              klineRows={hasKline ? klineRows : undefined}
            />
          </section>

          {/* trades 表格 */}
          <section className="bg-elevated rounded-btn p-3 min-h-0 flex-1 overflow-hidden flex flex-col">
            <div className="text-sm font-medium mb-2">交易明细 ({trades.length} 笔, 基于 {tradeSymbol} 重算)</div>
            <PanYangTradesTable trades={trades} />
          </section>

          <div className="text-xs text-muted shrink-0">
            信号源 {SIGNAL_SYMBOL} · 交易标的 {tradeSymbol} · matching=open_t+1
            · 后端耗时 {backtest.data.elapsed_ms}ms
            {backtest.data.error ? ` · 信号源错误: ${backtest.data.error}` : ''}
            {trades.length === 0 && !backtest.data.error ? ' · 信号源未产生买卖信号' : ''}
          </div>
        </>
      )}
    </div>
  )
}
