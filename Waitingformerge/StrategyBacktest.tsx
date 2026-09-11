import { useState, useMemo, useEffect, useRef, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, FlaskConical, Clock, Loader2, Square, Search, Plus, X, SlidersHorizontal, BarChart3, Gauge, Zap, ListPlus, HelpCircle, ChevronRight, AlertTriangle, Layers, BookmarkPlus, Download, PieChart } from 'lucide-react'
import {
  api,
  type StrategyBacktestResult,
  type ResearchCandidate,
  type StrategyBacktestTrade,
  type StrategyDetail,
  type StrategyParamDef,
  type ScoringDirection,
  REGIME_STATE_LABELS,
  REGIME_STATE_COLORS,
} from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { storage } from '@/lib/storage'
import { fmtPct, fmtPrice, priceColorClass } from '@/lib/format'
import { boardTag } from '@/lib/board'
import { boardTag as boardBadge } from '@/components/stock-table/primitives'
import { BUILTIN_COLUMNS } from '@/lib/watchlist-columns'
import { cnSignal } from '@/lib/signals'
import { SignalPicker } from '@/components/screener/SignalPicker'
import { startBacktest, stopBacktest, tryReconnect, useBacktestTask } from '@/lib/backtestTask'
import { useDataStatus, useCapabilities } from '@/lib/useSharedQueries'
import { EmptyState } from '@/components/EmptyState'
import { WarmupBadge } from '@/components/WarmupBadge'
import { DatePicker } from '@/components/DatePicker'
import { toast } from '@/components/Toast'
import { setSharedResult } from './analysis/sharedData'
import { StrategyNavChart } from './charts/StrategyNavChart'
import { ReturnDistributionChart } from './charts/ReturnDistributionChart'
import { TradeKlineModal } from './components/TradeKlineModal'
import { PicksSymbolKlineModal } from './components/PicksSymbolKlineModal'
import { SignalTriggerActions } from '@/components/signals/SignalTriggerActions'
import { WatchlistGroupMenu } from '@/components/WatchlistAddMenu'
import { ScoringEditor } from '@/components/ScoringEditor'
import { strategyResultCandidate } from './researchCandidates'












const buildDefaultOverrides = (detail: StrategyDetail) => normalizeStrategyOverrides(detail, {
  basic_filter: { ...detail.basic_filter },
  entry_signals: detail.entry_signals.map(toSignalId),
  exit_signals: detail.exit_signals.map(toSignalId),
  scoring: { ...detail.scoring },
  scoring_directions: { ...(detail.scoring_directions ?? {}) },
  scoring_replace: true,
  stop_loss: detail.stop_loss,
  take_profit: detail.take_profit,
  trailing_stop: detail.trailing_stop,
  trailing_take_profit_activate: detail.trailing_take_profit_activate,
  trailing_take_profit_drawdown: detail.trailing_take_profit_drawdown,
  score_min: null,
  score_max: null,
  max_hold_days: detail.max_hold_days,
  cooldown_loss_streak: detail.cooldown_loss_streak,
  cooldown_days: detail.cooldown_days,
})

const strategyBacktestConfigSignature = (detail: StrategyDetail) => JSON.stringify({
  execution_backend: detail.execution_backend,
  basic_filter: detail.basic_filter,
  params: detail.params,
  params_defaults: detail.params_defaults,
  scoring: detail.scoring,
  scoring_directions: detail.scoring_directions,
  entry_signals: detail.entry_signals,
  exit_signals: detail.exit_signals,
  stop_loss: detail.stop_loss,
  take_profit: detail.take_profit,
  trailing_stop: detail.trailing_stop,
  trailing_take_profit_activate: detail.trailing_take_profit_activate,
  trailing_take_profit_drawdown: detail.trailing_take_profit_drawdown,
  max_hold_days: detail.max_hold_days,
  cooldown_loss_streak: detail.cooldown_loss_streak,
  cooldown_days: detail.cooldown_days,
})

const fmtMoney = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
































export function StrategyBacktest({ loadCandidate, onLoadConsumed }: {
  /** 候选方案「载入复测」: 回填保存的回测配置 (消费后由父组件清空) */
  loadCandidate?: ResearchCandidate | null
  onLoadConsumed?: () => void
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const signalNames = useSignalNames()
  const [saved] = useState(() => storage.strategyBacktestLast.get(null))
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(saved?.selectedStrategy ?? null)
  const [strategyGroup, setStrategyGroup] = useState<StrategyGroup>('all')
  const [symbols, setSymbols] = useState(saved?.symbols ?? '')
  const [assetType, setAssetType] = useState<'stock' | 'etf'>(saved?.assetType ?? 'stock')
  const [start, setStart] = useState(saved?.start ?? THREE_MONTHS_AGO)
  const [end, setEnd] = useState(saved?.end ?? TODAY)
  // 成交口径: 建仓/清仓可独立配置。向后兼容老 matching (派生为 entry=exit=matching)。
  const [matching] = useState<'close_t' | 'open_t+1'>(saved?.matching ?? 'open_t+1')
  const [entryFill, setEntryFill] = useState<'close_t' | 'open_t+1'>(saved?.entryFill ?? saved?.matching ?? 'open_t+1')
  const [exitFill, setExitFill] = useState<'close_t' | 'open_t+1' | 'signal_next_minute'>(
    saved ? (saved.exitFill ?? saved.matching ?? 'close_t') : 'open_t+1',
  )
  const [fees, setFees] = useState(saved?.fees ?? '2')
  const [stampTax, setStampTax] = useState(saved?.stampTax ?? '1')
  const [slippage, setSlippage] = useState(saved?.slippage ?? '5')
  const [maxPositions, setMaxPositions] = useState(saved?.maxPositions ?? '10')
  const [maxExposure, setMaxExposure] = useState(saved?.maxExposure ?? '100')
  const [initialCapital, setInitialCapital] = useState(saved?.initialCapital ?? '1000000')
  const [positionSizing, setPositionSizing] = useState<'equal' | 'score_weight'>(saved?.positionSizing ?? 'equal')
  const [simMode, setSimMode] = useState<'position' | 'full'>(saved?.mode ?? 'position')
  const [holdingDays, setHoldingDays] = useState(saved?.holdingDays ?? '5')
  const [highGranularity, setHighGranularity] = useState(saved?.minuteFill ?? false)
  // 市场环境过滤(空=不过滤)
  const [regimeStates, setRegimeStates] = useState<string[]>(saved?.regimeStates ?? [])
  const [regimeMinScore, setRegimeMinScore] = useState<number | ''>(saved?.regimeMinScore ?? '')
  const [settingsOpen, setSettingsOpen] = useState(false)
  // 分钟K成交价细化: 不改变信号日或成交日, 依赖分钟K批量数据
  const { data: caps } = useCapabilities()
  const hasMinuteBatch = !!caps?.capabilities?.['kline.minute.batch']
  const toggleMinuteFill = () => {
    if (!hasMinuteBatch) return
    if (highGranularity) {
      if (exitFill === 'signal_next_minute') setExitFill('close_t')
    }
    setHighGranularity(value => !value)
  }
  const [rangeSettingsOpen, setRangeSettingsOpen] = useState(false)
  const [quickRanges, setQuickRanges] = useState(loadQuickRanges)
  const [settingsTab, setSettingsTab] = useState<AdvancedSettingsTab>('params')
  const [strategyParams, setStrategyParams] = useState<Record<string, any>>(saved?.params ?? {})
  const [overrides, setOverrides] = useState<Record<string, any>>(saved?.overrides ?? {})
  // result 不从 localStorage 恢复:它是运行产物(净值/交易),大且易过时,
  // 跨会话/拉新代码后自动渲染一个可能对应已失效策略的旧结果会造成困惑
  // (切页不卸载组件,内存中的 result 仍保留,无需靠 localStorage 恢复)。
  const [result, setResult] = useState<StrategyBacktestResult | null>(null)

  // 候选方案「载入复测」: 把保存的 23 项回测配置回填到表单 (字段缺失时保留当前值)
  useEffect(() => {
    if (!loadCandidate) return
    const cfg = (loadCandidate.config ?? {}) as Record<string, any>
    if (cfg.strategy_id) setSelectedStrategy(String(cfg.strategy_id))
    if (cfg.asset_type === 'stock' || cfg.asset_type === 'etf') setAssetType(cfg.asset_type)
    if (cfg.symbols != null) {
      setSymbols(Array.isArray(cfg.symbols) ? cfg.symbols.join(',') : String(cfg.symbols))
    }
    if (cfg.start) setStart(String(cfg.start).slice(0, 10))
    if (cfg.end) setEnd(String(cfg.end).slice(0, 10))
    if (cfg.entry_fill === 'close_t' || cfg.entry_fill === 'open_t+1') setEntryFill(cfg.entry_fill)
    if (cfg.exit_fill === 'close_t' || cfg.exit_fill === 'open_t+1' || cfg.exit_fill === 'signal_next_minute') {
      setExitFill(cfg.exit_fill)
    }
    if (cfg.commission_pct != null) setFees(String(Math.round(Number(cfg.commission_pct) * 10000)))
    if (cfg.stamp_tax_pct != null) setStampTax(String(Number(cfg.stamp_tax_pct) * 1000))
    if (cfg.slippage_bps != null) setSlippage(String(cfg.slippage_bps))
    if (cfg.max_positions != null) setMaxPositions(String(cfg.max_positions))
    if (cfg.max_exposure_pct != null) setMaxExposure(String(Math.round(Number(cfg.max_exposure_pct) * 100)))
    if (cfg.initial_capital != null) setInitialCapital(String(cfg.initial_capital))
    if (cfg.position_sizing === 'equal' || cfg.position_sizing === 'score_weight') {
      setPositionSizing(cfg.position_sizing)
    }
    if (cfg.mode === 'position' || cfg.mode === 'full') setSimMode(cfg.mode)
    if (cfg.holding_days != null) setHoldingDays(String(cfg.holding_days))
    if (cfg.minute_fill != null) setHighGranularity(Boolean(cfg.minute_fill))
    if (cfg.params && typeof cfg.params === 'object') setStrategyParams(cfg.params)
    if (cfg.overrides && typeof cfg.overrides === 'object') setOverrides(cfg.overrides)
    const rf = cfg.regime_filter
    if (rf && typeof rf === 'object' && !Array.isArray(rf)) {
      setRegimeStates(Array.isArray(rf.states) ? rf.states.map(String) : [])
      setRegimeMinScore(rf.min_score != null ? Number(rf.min_score) : '')
    } else {
      setRegimeStates([])
      setRegimeMinScore('')
    }
    toast(`已载入「${loadCandidate.name}」配置，可直接复测`, 'success')
    onLoadConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅在切换候选时执行一次性回填
  }, [loadCandidate])
  const [resultTab, setResultTab] = useState<'daily' | 'trades' | 'picks' | 'attribution'>('daily')
  // 因子归因表的 id → 中文标签 (字段视图 + 因子库合并, 自定义因子也在库内)
  const factorMetaQ = useQuery({ queryKey: QK.factorColumns, queryFn: api.factorColumns, staleTime: 300_000 })
  const factorLibQ = useQuery({ queryKey: QK.factorLibrary('all'), queryFn: () => api.factorLibrary(), staleTime: 60_000 })
  const factorLabels = useMemo(() => {
    const m = new Map<string, string>()
    for (const c of factorMetaQ.data?.columns ?? []) m.set(c.id, c.label)
    for (const f of factorLibQ.data?.factors ?? []) if (!m.has(f.id)) m.set(f.id, f.label)
    return m
  }, [factorMetaQ.data, factorLibQ.data])
  const [dailyPage, setDailyPage] = useState(0)
  const [tradePage, setTradePage] = useState(0)
  const [tradePageSize, setTradePageSize] = useState(10)
  /** 回测K线覆盖层: 单笔交易回放 / 标的全区间回放, 由 union 保证至多开一个 */
  const [chartOverlay, setChartOverlay] = useState<
    | { kind: 'trade'; trade: StrategyBacktestTrade }
    | { kind: 'symbol'; symbol: string }
    | null
  >(null)
  const selectedTrade = chartOverlay?.kind === 'trade' ? chartOverlay.trade : null
  const picksSymbol = chartOverlay?.kind === 'symbol' ? chartOverlay.symbol : null
  const loadedStrategyRef = useRef<string | null>(null)

  const strategies = useQuery({
    queryKey: QK.screenerStrategies(assetType, 'all'),
    queryFn: () => api.screenerStrategies(assetType, 'all'),
  })
  const strategyList = useMemo(() => strategies.data?.presets ?? [], [strategies.data])
  const filteredStrategyList = useMemo(() => (
    strategyGroup === 'all' ? strategyList : strategyList.filter(st => st.source === strategyGroup)
  ), [strategyGroup, strategyList])
  // 校验 localStorage 里保存的上次选中策略是否仍存在(本地开发残留的自定义策略
  // 拉新代码后会失效,导致 strategyGet 一直 404/加载中)。列表就绪后若失效,
  // 连带清除其专属的 params/overrides/result(这些是该策略的运行配置/产物,
  // 策略失效后留着会造成"孤儿"状态:界面显示旧回测结果却无对应策略)。
  useEffect(() => {
    if (strategies.isLoading || strategyList.length === 0) return
    if (selectedStrategy && !strategyList.some(st => st.id === selectedStrategy)) {
      setSelectedStrategy(null)
      setStrategyParams({})
      setOverrides({})
      setResult(null)
    }
  }, [strategies.isLoading, strategyList, selectedStrategy])

  const strategyDetail = useQuery({
    queryKey: QK.strategyDetail(selectedStrategy ?? ''),
    queryFn: () => api.strategyGet(selectedStrategy!),
    enabled: !!selectedStrategy,
  })

  const backtestTask = useBacktestTask()
  const isPending = backtestTask?.isPending ?? false
  const saveCandidate = useMutation({
    mutationFn: () => {
      if (!result) throw new Error('暂无策略结果')
      return api.researchCandidateCreate(strategyResultCandidate(result))
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QK.researchCandidates })
      toast('已保存到候选方案', 'success')
    },
    onError: error => toast(`保存失败 · ${String((error as Error).message || error)}`, 'error'),
  })

  const dataStatus = useDataStatus()
  const backtestDataStatus = assetType === 'etf'
    ? dataStatus.data?.etf_enriched
    : dataStatus.data?.enriched
  const earliestDate = backtestDataStatus?.earliest_date ?? null
  const backtestDataUnavailable = dataStatus.isSuccess && !earliestDate
  const backtestDataLabel = assetType === 'etf' ? 'ETF 指标数据' : '股票指标数据'

  const resetConfigFromDetail = (detail: StrategyDetail) => {
    setStrategyParams(strategyDefaultParams(detail))
    setOverrides(buildDefaultOverrides(detail))
  }

  // 「应用到策略」: 把弹窗里当前编辑的 overrides + params 持久化为策略定义,
  // 使所有页面加载该策略时都用这些参数(后端 save_config → 落盘 strategy_overrides/{id}.json)。
  const [applying, setApplying] = useState(false)
  const handleApplyToStrategy = async () => {
    if (!detail || !selectedStrategy) return
    setApplying(true)
    try {
      // 合并 params 进 overrides(后端 _strategy_detail 会把 params 合并进 params_defaults)
      const payload = { ...normalizeStrategyOverrides(detail, overrides), params: strategyParams }
      await api.strategySaveConfig(selectedStrategy, payload)
      toast('已应用到策略定义', 'success')
      await strategyDetail.refetch()
      setSettingsOpen(false)
    } catch (e) {
      toast(`应用失败 · ${String((e as Error)?.message || e)}`, 'error')
    } finally {
      setApplying(false)
    }
  }

  // 刷新页面后: 从 localStorage 恢复未完成的回测任务
  useEffect(() => {
    tryReconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const detail = strategyDetail.data
    if (!detail) return
    const configSignature = strategyBacktestConfigSignature(detail)
    const configKey = `${assetType}:${detail.id}:${configSignature}`
    if (loadedStrategyRef.current === configKey) return
    loadedStrategyRef.current = configKey
    if (
      saved?.assetType === assetType
      && saved.selectedStrategy === detail.id
      && saved.strategyConfigSignature === configSignature
      && (saved.params || saved.overrides)
    ) {
      setStrategyParams(mergeStrategyParams(detail, saved.params))
      setOverrides(normalizeStrategyOverrides(detail, saved.overrides ?? buildDefaultOverrides(detail)))
      return
    }
    resetConfigFromDetail(detail)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assetType, strategyDetail.data])

  // 当全局回测任务完成时, 把结果写入组件 (切页回来也能恢复)
  useEffect(() => {
    if (backtestTask && !backtestTask.isPending && backtestTask.result) {
      setResult(backtestTask.result)
      setSharedResult(backtestTask.result)  // 自动保存到共享存储, 供分析页面使用
      setResultTab('daily')
      setDailyPage(0)
      setTradePage(0)
      storage.strategyBacktestLast.set({
        selectedStrategy,
        symbols,
        assetType,
        start,
        end,
        matching,
        entryFill,
        exitFill,
        fees,
        stampTax,
        slippage,
        maxPositions,
        maxExposure,
        initialCapital,
        positionSizing,
        mode: simMode,
        holdingDays,
        minuteFill: isMinuteStrategy ? false : highGranularity,
        regimeStates,
        regimeMinScore,
        params: strategyParams,
        overrides,
        strategyConfigSignature: strategyDetail.data
          ? strategyBacktestConfigSignature(strategyDetail.data)
          : undefined,
        result: backtestTask.result,
      })
    }
  }, [backtestTask])

  const handleRun = () => {
    if (!selectedStrategy || backtestDataUnavailable) return
    const requestOverrides = detail
      ? normalizeStrategyOverrides(detail, overrides)
      : overrides
    startBacktest({
      strategy_id: selectedStrategy,
      asset_type: assetType,
      symbols: symbols ? symbols.split(',').map(s => s.trim()).filter(Boolean) : null,
      start: start || null,
      end: end || undefined,
      matching,
      entry_fill: entryFill,
      exit_fill: exitFill,
      commission_pct: Number(fees) / 10000,
      stamp_tax_pct: Number(stampTax) / 1000,
      slippage_bps: Number(slippage),
      max_positions: Number(maxPositions),
      max_exposure_pct: Number(maxExposure) / 100,
      initial_capital: Number(initialCapital),
      position_sizing: positionSizing,
      params: strategyParams,
      overrides: requestOverrides,
      mode: simMode,
      holding_days: Number(holdingDays) || 5,
      minute_fill: isMinuteStrategy ? false : highGranularity,
      regime_filter: regimeStates.length > 0 || regimeMinScore !== ''
        ? {
            ...(regimeStates.length > 0 ? { states: regimeStates } : {}),
            ...(regimeMinScore !== '' ? { min_score: Number(regimeMinScore) } : {}),
          }
        : null,
    })
  }

  // 环境数据缺口识别: fail-closed 报错文案中提取缺失首日, 供"一键补算并重跑"。
  // 「数据为空」变体无日期, 用回测起点兜底; 预热区间不足的变体不在此处理(文案已自说明)。
  const regimeGapStart = useMemo(() => {
    const msg = backtestTask?.error ?? result?.error ?? ''
    if (msg.includes('市场环境数据覆盖不完整') && msg.includes('请先补算')) {
      const m = msg.match(/缺少前一交易日环境[：:\s]*(\d{4}-\d{2}-\d{2})/)
      return m?.[1] ?? start
    }
    if (msg.includes('市场环境数据为空')) return start
    return null
  }, [backtestTask?.error, result?.error, start])

  const regimeRecompute = useMutation({
    mutationFn: () => api.regimeRecompute(regimeGapStart ?? undefined, end || undefined),
    onSuccess: data => {
      toast(`环境数据补算完成 (新增 ${data.computed} 天)，自动重新回测`, 'success')
      handleRun()
    },
    onError: e => toast(`环境数据补算失败 · ${String((e as Error)?.message || e)}`, 'error'),
  })

  // 提取统计
  const s = result?.stats
  const pick = (...keys: string[]) => {
    for (const k of keys) {
      if (s && k in s && s[k] != null) return s[k]
    }
    return null
  }

  const benchmarkReturn = useMemo(() => {
    const values = (result?.benchmark_curve ?? [])
      .map(r => Number(r.close ?? r.value))
      .filter(v => Number.isFinite(v) && v > 0)
    if (values.length < 2) return null
    return values[values.length - 1] / values[0] - 1
  }, [result?.benchmark_curve])

  const strategyReturn = pick('total_return') as number | null
  const excessReturn = strategyReturn != null && benchmarkReturn != null
    ? strategyReturn - benchmarkReturn
    : null

  /** 导出回测结果 CSV (带 BOM, Excel 可直接打开): 概要 + 净值曲线 + 交易明细 + 分标的统计 */
  const exportResultCsv = () => {
    if (!result) return
    const s = result.stats ?? {}
    const name = result.strategy_info?.name ?? result.strategy_info?.id ?? '策略'
    const start = String(result.config?.start ?? resultStartDate).slice(0, 10)
    const end = String(result.config?.end ?? resultEndDate).slice(0, 10)
    const pct = (v: unknown) => (v == null ? '' : fmtPct(Number(v)))
    const num = (v: unknown) => (v == null || Number.isNaN(Number(v)) ? '' : String(v))

    const lines: string[] = []
    lines.push('# 概要', '指标,数值')
    lines.push(`策略名称,${name}`)
    if (result.strategy_info?.id) lines.push(`策略ID,${result.strategy_info.id}`)
    lines.push(`回测区间,${start} ~ ${end}`)
    lines.push(`净值曲线天数,${result.equity_curve?.length ?? 0}`)
    lines.push(`完成交易数,${result.trades?.length ?? 0}`)
    lines.push(`总收益,${pct(strategyReturn)}`)
    lines.push(`年化收益,${pct(s.annual_return)}`)
    lines.push(`同期基准,${pct(benchmarkReturn)}`)
    lines.push(`超额收益,${pct(excessReturn)}`)
    for (const [label, key] of [
      ['夏普比率', 'sharpe'], ['索提诺', 'sortino'], ['最大回撤', 'max_drawdown'],
      ['胜率', 'win_rate'], ['平均收益', 'avg_return'], ['中位数收益', 'median_return'],
      ['盈亏比', 'profit_factor'], ['最终权益', 'final_equity'], ['平均持仓天数', 'avg_duration'],
    ] as const) {
      const v = s[key as keyof typeof s]
      if (v != null) lines.push(`${label},${key.includes('return') || key === 'win_rate' || key === 'max_drawdown' ? pct(v) : num(v)}`)
    }

    const ddMap = new Map((result.drawdown_curve ?? []).map(r => [r.date, r.value]))
    const benchMap = new Map((result.benchmark_curve ?? []).map(r => [r.date, r.close ?? r.value]))
    lines.push('', '# 净值曲线', 'date,equity,cash,positions,exposure,drawdown,benchmark')
    for (const r of result.equity_curve ?? []) {
      lines.push([r.date, num(r.value), num(r.cash), num(r.positions), num(r.exposure),
        num(ddMap.get(r.date)), num(benchMap.get(r.date))].join(','))
    }

    lines.push('', '# 交易明细',
      'symbol,name,entry_date,entry_price,exit_date,exit_price,pnl_pct,duration,exit_reason,shares,entry_value,exit_value,pnl_amount,entry_score')
    for (const t of result.trades ?? []) {
      lines.push([t.symbol, t.name ?? '', t.entry_date, num(t.entry_price), t.exit_date,
        num(t.exit_price), num(t.pnl_pct), num(t.duration), t.exit_reason ?? '',
        num(t.shares), num(t.entry_value), num(t.exit_value), num(t.pnl_amount),
        t.entry_score != null ? num(t.entry_score) : ''].map(csvEsc).join(','))
    }

    lines.push('', '# 分标的统计', 'symbol,n_trades,total_return,win_rate,best,worst')
    for (const p of result.per_symbol_stats ?? []) {
      lines.push([p.symbol, num(p.n_trades), num(p.total_return), num(p.win_rate),
        num(p.best), num(p.worst)].join(','))
    }

    const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `回测_${name.replace(/[\\/:*?"<>|]/g, '_')}_${start}_${end}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const applyRange = (months: number) => {
    setStart(monthsAgo(months))
    setEnd(formatDate(new Date()))
  }

  const applyAllRange = () => {
    setStart(earliestDate ?? '')
    setEnd(formatDate(new Date()))
  }

  // 进入页面/还在加载时就点了"全部": earliestDate 就绪后回填, 让 DatePicker 显示真实起始日
  useEffect(() => {
    if (earliestDate && start === '' && end === TODAY) {
      setStart(earliestDate)
    }
  }, [earliestDate, start, end])

  const applyQuickRange = (range: QuickRangeConfig) => {
    if (range.unit === 'all') {
      applyAllRange()
      return
    }
    applyRange(quickRangeMonths(range))
  }

  const saveQuickRanges = (next: QuickRangeConfig[]) => {
    const normalized = normalizeQuickRanges(next)
    storage.strategyBacktestQuickRanges.set(normalized)
    return normalized
  }

  const updateQuickRange = (id: string, patch: Partial<Pick<QuickRangeConfig, 'enabled' | 'unit' | 'value'>>) => {
    setQuickRanges(prev => {
      const current = prev.find(range => range.id === id)
      if (patch.enabled === false && current?.enabled && prev.filter(range => range.enabled).length <= 1) return prev
      return saveQuickRanges(prev.map(range => range.id === id
        ? normalizeQuickRange({ ...range, ...patch }, range)
        : range
      ))
    })
  }

  const visibleQuickRanges = quickRanges.filter(range => range.enabled)
  const matchedQuickRange = visibleQuickRanges.find(range => range.unit === 'all'
    ? end === TODAY && (start === earliestDate || start === '')
    : end === TODAY && start === monthsAgo(quickRangeMonths(range))
  )
  const rangeKey = matchedQuickRange?.id ?? 'custom'
  const rangeTitle = matchedQuickRange ? quickRangeTitle(matchedQuickRange) : '自定义区间'
  const rangeButtonCls = (key: string) => `rounded-btn px-2 py-1 text-[11px] font-medium transition-colors ${rangeKey === key
    ? 'bg-accent/15 text-accent'
    : 'text-muted hover:bg-elevated/70 hover:text-secondary'
  }`

  const sortedTrades = useMemo(() => {
    return [...(result?.trades ?? [])].sort((a, b) => {
      const exitCmp = String(b.exit_date).localeCompare(String(a.exit_date))
      if (exitCmp !== 0) return exitCmp
      return String(b.entry_date).localeCompare(String(a.entry_date))
    })
  }, [result?.trades])

  const dailyTradeRows = useMemo<DailyTradeRow[]>(() => {
    const rows = new Map<string, Omit<DailyTradeRow, 'cumulativePnl'>>()
    const ensure = (date: string) => {
      if (!rows.has(date)) {
        rows.set(date, { date, buys: [], sells: [], buyValue: 0, sellValue: 0, realizedPnl: 0 })
      }
      return rows.get(date)!
    }

    for (const t of result?.trades ?? []) {
      const entryDate = String(t.entry_date).slice(0, 10)
      const exitDate = String(t.exit_date).slice(0, 10)
      const buyRow = ensure(entryDate)
      buyRow.buys.push(t)
      buyRow.buyValue += Number(t.entry_value ?? 0)

      const sellRow = ensure(exitDate)
      sellRow.sells.push(t)
      sellRow.sellValue += Number(t.exit_value ?? 0)
      sellRow.realizedPnl += Number(t.pnl_amount ?? 0)
    }

    let cumulativePnl = 0
    return [...rows.values()]
      .sort((a, b) => a.date.localeCompare(b.date))
      .map(row => {
        cumulativePnl += row.realizedPnl
        return { ...row, cumulativePnl }
      })
      .reverse()
  }, [result?.trades])

  const tradePageCount = sortedTrades.length
    ? Math.ceil(sortedTrades.length / tradePageSize)
    : 0
  const dailyPageSize = 10
  const dailyPageCount = dailyTradeRows.length
    ? Math.ceil(dailyTradeRows.length / dailyPageSize)
    : 0
  const safeDailyPage = Math.min(dailyPage, Math.max(dailyPageCount - 1, 0))
  const dailyStart = safeDailyPage * dailyPageSize
  const visibleDailyRows = dailyTradeRows.slice(dailyStart, dailyStart + dailyPageSize)
  const dailyEnd = Math.min(dailyStart + visibleDailyRows.length, dailyTradeRows.length)
  const safeTradePage = Math.min(tradePage, Math.max(tradePageCount - 1, 0))
  const tradeStart = safeTradePage * tradePageSize
  const visibleTrades = sortedTrades.slice(tradeStart, tradeStart + tradePageSize)
  const tradeEnd = Math.min(tradeStart + visibleTrades.length, sortedTrades.length)
  const symbolNames = useMemo(() => {
    const names: Record<string, string> = {}
    result?.trades.forEach(t => {
      if (t.name) names[t.symbol] = t.name
    })
    return names
  }, [result?.trades])

  const detail = strategyDetail.data
  const matrixStrategy = detail?.execution_backend === 'matrix_native'
  const compositeStrategy = detail?.source === 'composite'
  const visibleAdvancedTabs = useMemo(
    () => matrixStrategy
      ? ADVANCED_TABS.filter(tab => tab.id !== 'entry' && tab.id !== 'exit')
      : compositeStrategy
        // composite 的 entry/exit/scoring 由子策略决定, composite 层只调合并参数(params Tab)
        ? ADVANCED_TABS.filter(tab => tab.id !== 'entry' && tab.id !== 'exit' && tab.id !== 'scoring')
        : ADVANCED_TABS,
    [matrixStrategy, compositeStrategy],
  )
  const basicFilter = (overrides.basic_filter ?? {}) as Record<string, any>
  const entrySignals = (overrides.entry_signals ?? []) as string[]
  const exitSignals = (overrides.exit_signals ?? []) as string[]
  const effectiveExitSignals = (overrides.exit_signals ?? detail?.exit_signals ?? []) as string[]
  const minuteTriggerSignals = detail?.minute_exit_trigger_supported_signals ?? []
  const unsupportedMinuteExitSignals = effectiveExitSignals.filter(signal => !minuteTriggerSignals.includes(signal))
  const minuteExitTriggerSupported = effectiveExitSignals.length > 0 && unsupportedMinuteExitSignals.length === 0
  // 分钟策略: 入场在盘中触发分钟成交, 日线专属的成交口径选项不适用
  const isMinuteStrategy = detail?.execution_backend === 'minute_filter'
  const { data: minuteDataStatus } = useQuery({
    queryKey: QK.dataStatus,
    queryFn: api.dataStatus,
    enabled: isMinuteStrategy,
    staleTime: 60_000,
  })
  // 分钟回测窗口守卫: 开始日期早于本地分钟K起点会被后端拒绝, 前置警示
  const minuteEarliest = minuteDataStatus?.minute?.earliest_date
  const minuteStartMismatch = isMinuteStrategy && !!minuteEarliest && start < minuteEarliest

  useEffect(() => {
    if (highGranularity && minuteExitTriggerSupported && !isMinuteStrategy) return
    if (exitFill === 'signal_next_minute') setExitFill('close_t')
  }, [exitFill, highGranularity, minuteExitTriggerSupported, isMinuteStrategy])

  const scoring = useMemo(() => (overrides.scoring ?? {}) as Record<string, number>, [overrides.scoring])
  const scoringDirections = useMemo(
    () => (overrides.scoring_directions ?? {}) as Record<string, ScoringDirection>,
    [overrides.scoring_directions],
  )
  const scoreMinValue = overrides.score_min == null ? '' : String(overrides.score_min)
  const scoreMaxValue = overrides.score_max == null ? '' : String(overrides.score_max)
  const stopLossPct = overrides.stop_loss == null ? '' : String(round4(Math.abs(Number(overrides.stop_loss)) * 100))
  const takeProfitPct = overrides.take_profit == null ? '' : String(round4(Math.abs(Number(overrides.take_profit)) * 100))
  const trailingStopPct = overrides.trailing_stop == null ? '' : String(round4(Math.abs(Number(overrides.trailing_stop)) * 100))
  const trailingTakeProfitActivatePct = overrides.trailing_take_profit_activate == null ? '' : String(round4(Math.abs(Number(overrides.trailing_take_profit_activate)) * 100))
  const trailingTakeProfitDrawdownPct = overrides.trailing_take_profit_drawdown == null ? '' : String(round4(Math.abs(Number(overrides.trailing_take_profit_drawdown)) * 100))
  const maxHoldDaysValue = overrides.max_hold_days == null ? '' : String(overrides.max_hold_days)
  const cooldownLossStreakValue = overrides.cooldown_loss_streak == null ? '' : String(overrides.cooldown_loss_streak)
  const cooldownDaysValue = overrides.cooldown_days == null ? '' : String(overrides.cooldown_days)
  const targetPositionPct = Number(maxPositions) > 0 ? Number(maxExposure) / Number(maxPositions) : 0

  useEffect(() => {
    if (matrixStrategy && (settingsTab === 'entry' || settingsTab === 'exit')) {
      setSettingsTab('params')
    }
  }, [matrixStrategy, settingsTab])

  const updateOverride = (key: string, value: any) => {
    setOverrides(prev => ({ ...prev, [key]: value }))
  }
  const updateBasicFilter = (key: string, value: any) => {
    updateOverride('basic_filter', { ...basicFilter, [key]: value })
  }
  const scoreFilterSummary = scoreMinValue !== '' && scoreMaxValue !== ''
    ? `评分 ${scoreMinValue}~${scoreMaxValue}`
    : scoreMinValue !== ''
      ? `评分 ≥${scoreMinValue}`
      : scoreMaxValue !== ''
        ? `评分 ≤${scoreMaxValue}`
        : '评分不过滤'
  const advancedSummary = detail
    ? [
        detail.params.length > 0 ? `参数 ${detail.params.length}` : '无策略参数',
        basicFilter.enabled !== false ? '过滤开' : '过滤关',
        `买点 ${entrySignals.length}`,
        `卖点 ${exitSignals.length}`,
        scoreFilterSummary,
        stopLossPct !== '' ? `止损 ${stopLossPct}%` : '止损未设',
        takeProfitPct !== '' ? `止盈 ${takeProfitPct}%` : '止盈未设',
        trailingStopPct !== '' ? `移损 ${trailingStopPct}%` : '移损未设',
        trailingTakeProfitActivatePct !== '' && trailingTakeProfitDrawdownPct !== '' ? `回撤 ${trailingTakeProfitActivatePct}-${trailingTakeProfitDrawdownPct}点` : '回撤未设',
        maxHoldDaysValue !== '' ? `最长 ${maxHoldDaysValue}天` : '不限持仓',
        cooldownLossStreakValue !== '' && cooldownDaysValue !== '' ? `连亏${cooldownLossStreakValue}笔冷却${cooldownDaysValue}天` : '冷却未设',
      ].join(' · ')
    : '选择策略后可调整参数 / 过滤 / 买卖触发器 / 评分 / 风控'
  const selectedStrategyName = detail?.name ?? strategyList.find(st => st.id === selectedStrategy)?.name ?? '未选择策略'
  const selectedStrategySource = detail?.source ?? strategyList.find(st => st.id === selectedStrategy)?.source
  const stockPoolCount = symbols.split(',').map(s => s.trim()).filter(Boolean).length
  const stockPoolSummary = stockPoolCount > 0 ? `股票池 已限定 ${stockPoolCount} 只` : '股票池 全市场'
  const resultStartDate = result?.config?.start ?? result?.equity_curve?.[0]?.date ?? start
  const resultEndDate = result?.config?.end ?? result?.equity_curve?.[result.equity_curve.length - 1]?.date ?? end
  const resultTradeDays = result?.equity_curve?.length ?? 0
  const resultRegimeFilter = result?.config?.regime_filter as {
    states?: string[]
    min_score?: number
  } | null | undefined
  const resultRegimeSummary = resultRegimeFilter
    ? [
        resultRegimeFilter.states?.length
          ? resultRegimeFilter.states.map(state => REGIME_STATE_LABELS[state as keyof typeof REGIME_STATE_LABELS] ?? state).join('/')
          : null,
        resultRegimeFilter.min_score != null ? `最低 ${resultRegimeFilter.min_score} 分` : null,
      ].filter(Boolean).join(' · ')
    : ''
  const selectionStats = result?.stats?.selection as Record<string, number | boolean> | undefined
  const selectionStages = selectionStats
    ? [
        {
          key: 'strategy',
          label: result?.stats?.execution_backend === 'matrix_native' ? '策略信号' : '策略命中',
          value: Number(selectionStats.strategy_matches ?? 0),
        },
        ...(selectionStats.entry_trigger_enabled === true
          ? [{ key: 'entry', label: '入场候选', value: Number(selectionStats.entry_candidates ?? 0) }]
          : []),
        { key: 'trades', label: '完成交易', value: Number(result?.stats?.n_trades ?? result?.trades.length ?? 0) },
      ]
    : []
  const executionStats = (result?.stats?.execution ?? {}) as Record<string, number>
  const executionSummary = [
    ['buy_no_slot', '满仓未买'],
    ['buy_exposure', '仓位上限'],
    ['buy_score_filter', '评分过滤'],
    ['buy_limit_up', '涨停未买'],
    ['buy_suspended', '停牌未买'],
    ['sell_limit_down', '跌停阻塞'],
    ['sell_suspended', '停牌阻塞'],
    ['pending_exit', '待卖阻塞'],
    ['sell_minute_trigger_fallback', '分钟信号顺延'],
  ]
    .map(([key, label]) => ({ key, label, value: Number(executionStats[key] ?? 0) }))
    .filter(item => item.value > 0)

  return (
    <div className="h-full min-h-0 overflow-hidden rounded-card border border-border bg-surface/80 grid grid-cols-1 xl:grid-cols-[18rem_minmax(0,1fr)]">
      {/* 配置面板 */}
      <section className="space-y-3 border-b xl:border-b-0 xl:border-r border-border bg-base/25 px-3 py-3 xl:overflow-y-auto">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-secondary">选择策略</label>
            {/* 分钟K成交 — 日线策略专属 (分钟策略入场天然按触发分钟成交) */}
            {!isMinuteStrategy && (
            <div className="flex items-center gap-1">
              <Gauge className={`h-3 w-3 ${highGranularity ? 'text-amber-400' : 'text-muted/50'}`} />
              <button
                onClick={toggleMinuteFill}
                disabled={!hasMinuteBatch}
                title={!hasMinuteBatch
                  ? '分钟K成交价：分钟K(批量)数据不可用'
                  : '分钟K成交：细化成交价，并为兼容的卖出信号提供下一分钟成交。'
                }
                className={`group relative inline-flex h-3.5 w-6 items-center rounded-full shrink-0 transition-colors duration-200 ${
                  !hasMinuteBatch ? 'bg-elevated opacity-50 cursor-not-allowed'
                  : highGranularity ? 'bg-amber-500 cursor-pointer'
                  : 'bg-elevated cursor-pointer'
                }`}
              >
                <span className={`inline-block h-2.5 w-2.5 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                  highGranularity ? 'translate-x-[13px]' : 'translate-x-0.5'
                }`} />
              </button>
              <span className={`text-[9px] font-medium ${highGranularity ? 'text-amber-400' : 'text-muted/50'}`}>分钟成交</span>
              {!hasMinuteBatch && (
                <span className="text-[8px] text-accent/70 font-medium bg-accent/10 px-1 py-px rounded">分钟K</span>
              )}
            </div>
            )}
          </div>
          {/* 分钟策略提示条: 数据窗口 + 成交语义 */}
          {isMinuteStrategy && (
            <div className="mb-2 flex items-start gap-1.5 rounded-btn border border-sky-500/30 bg-sky-500/5 px-2 py-1.5">
              <Clock className="h-3 w-3 text-sky-400 shrink-0 mt-px" />
              <div className="text-[10px] leading-snug text-sky-400/90">
                <span className="font-medium">分钟策略回测</span>
                ：逐日回放分钟K，信号分钟收盘价买入；日线条件按 T-1 完成态评估。
                {minuteDataStatus?.minute?.earliest_date
                  ? ` 本地分钟K ${minuteDataStatus.minute.earliest_date} ~ ${minuteDataStatus.minute.latest_date}（${minuteDataStatus.minute.trading_days} 个交易日），缺分区的日子自动跳过。`
                  : ' 本地暂无分钟K数据，请先在数据页拉取。'}
                {minuteStartMismatch && (
                  <span className="mt-0.5 block text-amber-400">
                    当前开始日期 {start} 早于分钟数据起点 {minuteEarliest}，运行会被拒绝 — 请把开始日期调整到 {minuteEarliest} 之后，或先用「扩展分钟K历史」拉取。
                  </span>
                )}
              </div>
            </div>
          )}
          {/* 分钟K开启时的提示条 */}
          {highGranularity && hasMinuteBatch && !isMinuteStrategy && (
            <div className="mb-2 flex items-start gap-1.5 rounded-btn border border-amber-400/30 bg-amber-400/5 px-2 py-1.5">
              <Zap className="h-3 w-3 text-amber-400 shrink-0 mt-px" />
              <div className="text-[10px] leading-snug text-amber-400/90">
                <span className="font-medium">分钟K成交价</span>
                ：默认在成交日细化穿越价/VWAP；选择“信号触发卖出”时，会对兼容的卖出信号做分钟回放。需本地有足够的分钟K历史。
              </div>
            </div>
          )}
          <div className="overflow-hidden rounded-input border border-border bg-surface">
            <div className="flex border-b border-border/60 bg-base/30 p-0.5">
              {STRATEGY_GROUPS.map(group => (
                <button
                  key={group.id}
                  type="button"
                  onClick={() => setStrategyGroup(group.id)}
                  className={`flex-1 rounded-[6px] px-1.5 py-1 text-[10px] font-medium transition-colors ${strategyGroup === group.id
                    ? 'bg-accent/15 text-accent shadow-sm'
                    : 'text-muted hover:bg-elevated/70 hover:text-secondary'
                  }`}
                >
                  {group.label}
                </button>
              ))}
            </div>
            <div className="flex max-h-[128px] flex-wrap gap-1 overflow-y-auto p-1">
            {strategies.isLoading && (
              <span className="text-xs text-muted px-2 py-1">加载中…</span>
            )}
            {!strategies.isLoading && filteredStrategyList.length === 0 && (
              <span className="text-xs text-muted px-2 py-1">当前分组暂无策略</span>
            )}
            {filteredStrategyList.map(st => (
              <button
                key={st.id}
                onClick={() => setSelectedStrategy(st.id)}
                className={`px-2 py-1 rounded-btn text-[11px] border transition-all duration-150 ease-smooth cursor-pointer
                  ${selectedStrategy === st.id
                    ? 'border-accent/50 bg-accent/10 text-accent shadow-[0_0_10px_rgba(59,130,246,0.1)]'
                    : 'border-border bg-base text-secondary hover:border-accent/40'
                  }`}
              >
                <span className="font-medium">{st.name}</span>
                {st.timeframes?.includes('1m') && (
                  <span className="ml-1 text-[8px] px-1 py-px rounded border border-sky-500/30 bg-sky-500/10 text-sky-400">分钟</span>
                )}
                {st.source && st.source !== 'builtin' && (
                  <span className={`ml-1 text-[8px] px-1 py-px rounded border ${BADGE_CLS_MAP[st.source] ?? ''}`}>
                    {SRC_MAP[st.source] ?? ''}
                  </span>
                )}
              </button>
            ))}
            </div>
          </div>
        </div>

        {selectedStrategy && strategyDetail.isLoading && (
          <div className="rounded-btn border border-border bg-surface px-2.5 py-2 text-xs text-muted">加载策略配置…</div>
        )}

        <button
          type="button"
          onClick={() => detail && setSettingsOpen(true)}
          disabled={!detail || strategyDetail.isLoading}
          className="group w-full rounded-btn border border-border bg-surface px-3 py-2.5 text-left transition-colors hover:border-accent/40 hover:bg-elevated/70 disabled:cursor-not-allowed disabled:opacity-55"
        >
          <span className="flex items-center gap-2 text-xs font-semibold text-foreground">
            <SlidersHorizontal className="h-3.5 w-3.5 text-accent" />
            策略设置
            <span className="ml-auto text-[10px] font-normal text-muted group-hover:text-accent">编辑</span>
          </span>
          <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[11px] font-medium text-secondary">
            <span className="truncate">{selectedStrategyName}</span>
            {selectedStrategySource && (
              <span className={`shrink-0 text-[8px] px-1 py-px rounded border ${BADGE_CLS_MAP[selectedStrategySource] ?? ''}`}>
                {SRC_MAP[selectedStrategySource] ?? selectedStrategySource}
              </span>
            )}
          </span>
          <span className="mt-1 block text-[10px] font-medium text-secondary">{stockPoolSummary}</span>
          <span className="mt-1 block text-[10px] leading-4 text-muted">{advancedSummary}</span>
        </button>

        <div className="rounded-btn border border-border bg-surface p-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <div className="text-xs font-medium text-foreground">回测区间</div>
              <WarmupBadge />
            </div>
            <span className="shrink-0 rounded-full border border-accent/25 bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
              {rangeTitle}
            </span>
          </div>

          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <label className="text-[11px] text-secondary block mb-1">开始</label>
              <DatePicker
                value={start}
                onChange={setStart}
                max={end || undefined}
                placeholder="全部历史"
                className="w-full"
                buttonClassName="w-full justify-start"
                align="left"
              />
            </div>
            <div>
              <label className="text-[11px] text-secondary block mb-1">结束</label>
              <DatePicker
                value={end}
                onChange={setEnd}
                min={start || undefined}
                className="w-full"
                buttonClassName="w-full justify-start"
              />
            </div>
          </div>

          <div className="mt-2 flex items-center gap-1">
            <div className="flex min-w-0 flex-1 rounded-input bg-base/60 p-0.5">
              {visibleQuickRanges.map(range => (
                <button
                  key={range.id}
                  type="button"
                  onClick={() => applyQuickRange(range)}
                  className={`${rangeButtonCls(range.id)} flex-1`}
                >
                  {quickRangeLabel(range)}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setRangeSettingsOpen(v => !v)}
              title="设置快捷区间"
              aria-label="设置快捷区间"
              className={`shrink-0 rounded-btn border px-2 py-1.5 transition-colors ${rangeSettingsOpen
                ? 'border-accent/40 bg-accent/10 text-accent'
                : 'border-border bg-base text-secondary hover:border-accent/40 hover:text-accent'
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </button>
          </div>

          {rangeSettingsOpen && (
            <div className="mt-2 rounded-input border border-border/60 bg-base/50 p-2">
              <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px] text-muted">
                <span>快捷区间</span>
                <span>月 1-120 / 年 1-10</span>
              </div>
              <div className="space-y-1.5">
                {quickRanges.map((range, index) => {
                  const limits = range.unit === 'all' ? null : QUICK_RANGE_LIMITS[range.unit]
                  return (
                    <div key={range.id} className="grid grid-cols-[3rem_1fr_4.5rem] items-center gap-1.5">
                      <label className="flex items-center gap-1 text-[11px] text-secondary">
                        <input
                          type="checkbox"
                          checked={range.enabled}
                          onChange={e => updateQuickRange(range.id, { enabled: e.target.checked })}
                          className="h-3 w-3 accent-accent"
                        />
                        {index + 1}
                      </label>
                      <select
                        value={range.unit}
                        onChange={e => updateQuickRange(range.id, { unit: e.target.value as QuickRangeUnit })}
                        className={INPUT_CLS}
                      >
                        <option value="month">月</option>
                        <option value="year">年</option>
                        <option value="all">全部</option>
                      </select>
                      <input
                        type="number"
                        min={limits?.min}
                        max={limits?.max}
                        disabled={range.unit === 'all'}
                        value={range.unit === 'all' ? '' : range.value}
                        onChange={e => updateQuickRange(range.id, { value: Number(e.target.value) })}
                        placeholder="—"
                        className={`${INPUT_CLS} ${range.unit === 'all' ? 'opacity-50' : ''}`}
                      />
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="mb-1.5 flex items-center gap-1">
              <label className="text-xs font-medium text-secondary">建仓口径</label>
              <FillRuleHint />
            </div>
            {isMinuteStrategy ? (
              <div className={`${INPUT_CLS} flex items-center gap-1.5`} title="信号在盘中触发分钟成交，无次日开盘口径">
                <Clock className="h-3 w-3 text-sky-400 shrink-0" />
                <span className="text-secondary">信号分钟收盘</span>
                <span className="text-[8px] px-1 py-px rounded border border-sky-500/30 bg-sky-500/10 text-sky-400">分钟</span>
              </div>
            ) : (
              <select value={entryFill} onChange={e => setEntryFill(e.target.value as 'close_t' | 'open_t+1')} className={INPUT_CLS}>
                <option value="open_t+1">次日开盘（推荐）</option>
                <option value="close_t">信号日收盘</option>
              </select>
            )}
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-secondary">清仓口径</label>
            <select
              value={exitFill}
              onChange={e => setExitFill(e.target.value as 'close_t' | 'open_t+1' | 'signal_next_minute')}
              className={INPUT_CLS}
            >
              <option value="close_t">信号日收盘（推荐）</option>
              <option value="open_t+1">次日开盘</option>
              {highGranularity && minuteExitTriggerSupported && !isMinuteStrategy && (
                <option value="signal_next_minute">信号触发卖出 BETA</option>
              )}
            </select>
          </div>
          {!isMinuteStrategy && (entryFill === 'close_t' || exitFill === 'close_t') && (
            <div className="col-span-2 flex items-start gap-1 text-[10px] leading-4 text-warning">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              <span>信号日收盘仅适合收盘前已确认的信号</span>
            </div>
          )}
          {exitFill === 'signal_next_minute' && (
            <div className="col-span-2 text-[10px] leading-4 text-accent">
              分钟收盘确认卖出信号后，按下一分钟开盘成交；尾盘或分钟数据缺失时顺延到下一交易日开盘
            </div>
          )}
          {highGranularity && effectiveExitSignals.length > 0 && !minuteExitTriggerSupported && (
            <div className="col-span-2 flex items-start gap-1 text-[10px] leading-4 text-muted">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              <span>当前卖出信号暂不支持分钟触发回放</span>
            </div>
          )}
        </div>

        {simMode === 'position' && (
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs font-medium text-secondary block mb-1.5">初始资金</label>
            <input type="number" value={initialCapital} onChange={e => setInitialCapital(e.target.value)}
              className={INPUT_CLS} />
          </div>
          <div>
            <label className="text-xs font-medium text-secondary block mb-1.5">买入权重</label>
            <select value={positionSizing} onChange={e => setPositionSizing(e.target.value as any)} className={INPUT_CLS}>
              <option value="equal">等权买入</option>
              <option value="score_weight">评分加权</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-secondary block mb-1.5">最大持仓数</label>
            <input type="number" value={maxPositions} onChange={e => setMaxPositions(e.target.value)}
              className={INPUT_CLS} />
          </div>
          <div>
            <label className="text-xs font-medium text-secondary block mb-1.5">最大总仓位(%)</label>
            <input type="number" min={0} max={100} value={maxExposure} onChange={e => setMaxExposure(e.target.value)}
              className={INPUT_CLS} />
          </div>
        </div>
        )}
        {simMode === 'position' && (
        <div className="grid grid-cols-3 gap-2">
          <div>
            <label className="text-[10px] font-medium text-secondary block mb-1">佣金 ‱</label>
            <input type="number" min={0} value={fees} onChange={e => setFees(e.target.value)} className={INPUT_CLS} />
          </div>
          <div>
            <label className="text-[10px] font-medium text-secondary block mb-1">印花税 ‰</label>
            <input type="number" min={0} value={stampTax} onChange={e => setStampTax(e.target.value)} className={INPUT_CLS} />
          </div>
          <div>
            <label className="text-[10px] font-medium text-secondary block mb-1">滑点 ‱</label>
            <input type="number" min={0} value={slippage} onChange={e => setSlippage(e.target.value)} className={INPUT_CLS} />
          </div>
        </div>
        )}
        {simMode === 'position' && (
        <div className="text-[10px] leading-4 text-muted">
          单票目标约 {Number.isFinite(targetPositionPct) ? targetPositionPct.toFixed(1) : '—'}%。最大总仓位控制资金投入；剩余现金不是新增持仓名额，只有实际卖出成功才释放持仓数。
        </div>
        )}
        {simMode === 'full' && (
        <div className="rounded-btn border border-accent/20 bg-accent/5 px-3 py-2.5 text-[11px] leading-relaxed text-secondary">
          <span className="font-medium text-foreground">全量模拟</span>：每日将策略选出的全部候选独立买入，不受资金/最大持仓数限制；每一笔仍按策略卖点、止损、移动止盈/止损和最长持仓执行，用于评估策略本身的选股 + 交易规则质量。
        </div>
        )}

        {backtestDataUnavailable && (
          <div className="flex items-start gap-1.5 rounded-btn border border-danger/30 bg-danger/10 px-3 py-2 text-[11px] leading-4 text-danger">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            <span>缺少{backtestDataLabel}，请先在数据页面同步日K并完成指标计算。</span>
          </div>
        )}

        {isPending ? (
          <button
            onClick={stopBacktest}
            className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-btn
              bg-danger/15 border border-danger/40 text-sm font-medium text-danger hover:bg-danger/25
              transition-colors duration-150 ease-smooth"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            停止回测
          </button>
        ) : (
          <button
            onClick={handleRun}
            disabled={!selectedStrategy || strategyDetail.isLoading || backtestDataUnavailable}
            className="group w-full inline-flex items-center justify-center gap-2.5 rounded-btn border border-accent/40
              bg-gradient-to-r from-accent to-blue-500 px-3 py-2.5 text-white shadow-[0_10px_24px_rgba(59,130,246,0.22)]
              transition-all duration-150 ease-smooth hover:-translate-y-0.5 hover:shadow-[0_14px_28px_rgba(59,130,246,0.28)]
              disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
          >
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white/18 ring-1 ring-white/25 transition-transform group-hover:scale-105">
              <Play className="h-3.5 w-3.5 translate-x-px fill-current" />
            </span>
            <span className="text-sm font-semibold tracking-wide">运行回测</span>
          </button>
        )}
      </section>

      {/* 结果面板 */}
      <section className="min-w-0 space-y-3 bg-base/15 px-3 py-3 xl:overflow-y-auto">
        {/* 模式切换: 仓位模拟 / 全量模拟 */}
        <div className="flex items-center justify-between gap-2">
          <div className="inline-flex rounded-btn border border-border bg-surface/80 p-0.5 shadow-sm">
            {([['position', '仓位模拟'], ['full', '全量模拟']] as const).map(([val, label]) => (
              <button
                key={val}
                onClick={() => setSimMode(val)}
                className={`inline-flex items-center gap-1.5 rounded-[5px] px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer ${
                  simMode === val
                    ? 'bg-accent text-white shadow-sm'
                    : 'text-secondary hover:bg-elevated hover:text-foreground'
                }`}
                title={val === 'position' ? '受仓位/资金约束的真实账户模拟' : '全部候选独立执行，不受资金和持仓数量约束'}
              >
                {val === 'position' ? <Play className="h-3.5 w-3.5" /> : <BarChart3 className="h-3.5 w-3.5" />}
                {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {simMode === 'full' && (
              maxHoldDaysValue !== '' ? (
                <div className="rounded-btn border border-border bg-surface px-2 py-1 text-[11px] text-secondary">
                  策略最长 <span className="font-mono text-foreground">{maxHoldDaysValue}</span> 天
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-[11px] text-secondary">
                  <span>兜底上限</span>
                  <div className="flex rounded-btn border border-border overflow-hidden">
                    {(['1', '5', '10', '20'] as const).map(d => (
                      <button
                        key={d}
                        onClick={() => setHoldingDays(d)}
                        className={`px-2 py-1 text-[11px] font-medium transition-colors cursor-pointer ${
                          holdingDays === d
                            ? 'bg-accent/10 text-accent'
                            : 'text-muted hover:text-secondary hover:bg-elevated'
                        }`}
                      >
                        {d}天
                      </button>
                    ))}
                  </div>
                </div>
              )
            )}
            {result && !result.error && (
              <button
                type="button"
                onClick={() => saveCandidate.mutate()}
                disabled={saveCandidate.isPending}
                className="inline-flex h-8 items-center gap-1.5 rounded-btn border border-border bg-surface px-2.5 text-[11px] text-secondary transition-colors hover:border-accent/40 hover:text-accent disabled:opacity-50"
              >
                <BookmarkPlus className="h-3.5 w-3.5" />
                {saveCandidate.isPending ? '保存中' : '保存候选'}
              </button>
            )}
          </div>
        </div>

        {/* 市场环境过滤: 只在指定环境的交易日入场(强制 T-1, 用前一日环境判定) */}
        <div className="rounded-btn border border-border bg-surface/50 px-3 py-2 space-y-1.5">
          <div className="flex items-center gap-2">
            <Gauge className="h-3.5 w-3.5 text-accent" />
            <span className="text-xs font-medium text-foreground">环境过滤</span>
            <span className="text-[10px] text-muted">仅在前一日环境满足时入场(防未来函数)</span>
            <div className="ml-auto flex items-center gap-1">
              <span className="text-[10px] text-muted">最低分</span>
              <input type="number" min={0} max={100} value={regimeMinScore} placeholder="不限"
                onChange={e => setRegimeMinScore(e.target.value ? Number(e.target.value) : '')}
                className="w-14 h-6 px-1 rounded border border-border bg-base text-[11px] text-foreground text-center focus:outline-none focus:border-accent/50" />
            </div>
          </div>
          <div className="flex flex-wrap gap-1">
            {(Object.keys(REGIME_STATE_LABELS) as (keyof typeof REGIME_STATE_LABELS)[]).map(s => {
              const active = regimeStates.includes(s)
              return (
                <button key={s} onClick={() => setRegimeStates(prev => active ? prev.filter(x => x !== s) : [...prev, s])}
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] transition-colors cursor-pointer ${
                    active ? 'border-transparent text-white' : 'border-border text-muted hover:text-secondary'
                  }`}
                  style={active ? { backgroundColor: REGIME_STATE_COLORS[s] } : undefined}>
                  <span className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: active ? '#fff' : REGIME_STATE_COLORS[s] }} />
                  {REGIME_STATE_LABELS[s]}
                </button>
              )
            })}
            {(regimeStates.length > 0 || regimeMinScore !== '') && (
              <button onClick={() => { setRegimeStates([]); setRegimeMinScore('') }}
                className="text-[10px] text-muted hover:text-danger px-1">清除</button>
            )}
          </div>
        </div>

        {result?.error && (
          <div className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-btn px-3 py-2">
            {result.error}
            {regimeGapStart && (
              <RegimeRecomputeButton
                from={regimeGapStart}
                to={end}
                pending={regimeRecompute.isPending || isPending}
                onClick={() => regimeRecompute.mutate()}
              />
            )}
          </div>
        )}

        {backtestTask?.error && (
          <div className="text-sm text-danger bg-danger/10 border border-danger/30 rounded-btn px-3 py-2">
            <div>{backtestTask.error}</div>
            {result && (
              <div className="mt-1 text-xs text-secondary">本次回测未生成新结果，下方仍展示上一次成功结果。</div>
            )}
            {regimeGapStart && (
              <RegimeRecomputeButton
                from={regimeGapStart}
                to={end}
                pending={regimeRecompute.isPending || isPending}
                onClick={() => regimeRecompute.mutate()}
              />
            )}
          </div>
        )}

        {!result && !isPending && (
          <EmptyState
            icon={FlaskConical}
            title="选择策略并开始回测"
            hint="策略回测复用策略定义 ( 买入/卖出触发器、止损、最大持仓 ) 做全周期模拟。服务器建议优先使用最近3个月；长周期建议本机或 8GB 以上内存环境运行。"
          />
        )}

        {isPending && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-card border border-accent/40 bg-accent/10 px-4 py-2.5"
          >
            <div className="flex items-center gap-2.5">
              <span className="relative flex h-4 w-4 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent/50" />
                <Loader2 className="relative h-4 w-4 animate-spin text-accent" />
              </span>
              <div className="min-w-0">
                <div className={backtestTask?.reconnecting ? 'text-xs font-medium text-warning' : 'text-xs font-medium text-accent'}>
                  {backtestTask?.reconnecting
                    ? '连接中断，重试中…'
                    : backtestTask?.progress
                      ? `回测中 · 第 ${backtestTask.progress.day}/${backtestTask.progress.total} 天 (${backtestTask.progress.date})`
                      : '正在重新计算回测…'}
                </div>
                <div className="mt-0.5 text-[11px] text-secondary">
                  {backtestTask?.reconnecting
                    ? '正在尝试恢复连接，若持续失败可停止后重试'
                    : result ? '当前展示上次结果，完成后自动替换' : '正在加载回测数据…'}
                </div>
              </div>
              {backtestTask?.progress && (
                <span className="ml-auto shrink-0 font-mono text-sm font-semibold text-accent">
                  {((backtestTask.progress.day / backtestTask.progress.total) * 100).toFixed(0)}%
                </span>
              )}
              <button
                type="button"
                onClick={stopBacktest}
                className="inline-flex shrink-0 items-center gap-1 rounded-btn border border-danger/40 bg-danger/10 px-2 py-1 text-[11px] text-danger transition-colors hover:bg-danger/20"
              >
                <Square className="h-3 w-3 fill-current" />
                停止
              </button>
            </div>
            {backtestTask?.progress && (
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-base/60">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-300 ease-out"
                  style={{ width: `${(backtestTask.progress.day / backtestTask.progress.total) * 100}%` }}
                />
              </div>
            )}
          </motion.div>
        )}

        {/* 旧全量模拟结果: 固定前瞻收益统计 (兼容历史缓存结果) */}
        {result && !result.error && result.stats && result.stats.mode === 'full' && result.stats.full_kind !== 'candidate_execution' && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-4"
          >
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-foreground">{result.strategy_info?.name ?? '策略'}</span>
              <span className="text-[10px] px-1 py-px rounded border border-accent/30 bg-accent/10 text-accent">全量模拟</span>
              {resultRegimeSummary && (
                <span className="inline-flex items-center gap-1 rounded border border-accent/25 bg-accent/10 px-1.5 py-px text-[10px] text-accent">
                  <Gauge className="h-2.5 w-2.5" />
                  环境 {resultRegimeSummary}
                </span>
              )}
              <span className="text-[10px] text-secondary">持有 {result.config?.holding_days ?? 5} 天</span>
              <button
                type="button"
                onClick={exportResultCsv}
                title="导出回测结果 CSV (概要 + 净值曲线 + 交易明细 + 分标的统计)"
                className="ml-1 inline-flex h-6 shrink-0 items-center gap-1 rounded border border-border bg-base px-2 text-[10px] text-secondary transition-colors hover:border-accent/40 hover:text-accent"
              >
                <Download className="h-3 w-3" />
                导出
              </button>
              <button
                type="button"
                onClick={() => {
                  setSharedResult(result)
                  navigate('/backtest-analysis')
                }}
                title="将当前回测结果直接送入分析面板（无需导出CSV）"
                className="ml-1 inline-flex h-6 shrink-0 items-center gap-1 rounded border border-accent/30 bg-accent/10 px-2 text-[10px] text-accent transition-colors hover:bg-accent/20"
              >
                <PieChart className="h-3 w-3" />
                分析
              </button>
              <span className="ml-auto text-[11px] text-muted font-mono">
                {String(result.config?.start).slice(0,10)} ~ {String(result.config?.end).slice(0,10)}
              </span>
            </div>

            {/* 统计卡片 */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Stat label={<MetricLabel label="平均收益" metric="avgReturn" />} value={fmtPct(result.stats.avg_return)} color={statValueColor(result.stats.avg_return)} />
              <Stat label={<MetricLabel label="中位数" metric="medianReturn" />} value={fmtPct(result.stats.median_return)} color={statValueColor(result.stats.median_return)} />
              <Stat label={<MetricLabel label="胜率" metric="winRate" />} value={fmtPct(result.stats.win_rate)} color={statValueColor(result.stats.win_rate)} />
              <Stat label={<MetricLabel label="盈亏比" metric="profitFactor" />} value={result.stats.profit_factor != null ? Number(result.stats.profit_factor).toFixed(2) : '—'} />
              <Stat label={<MetricLabel label="超额(vs基准)" metric="excessReturn" />} value={fmtPct(result.stats.excess)} color={statValueColor(result.stats.excess)} />
              <Stat label={<MetricLabel label="夏普" metric="sharpe" />} value={result.stats.sharpe != null ? Number(result.stats.sharpe).toFixed(2) : '—'} />
              <Stat label={<MetricLabel label="最大回撤" metric="maxDrawdown" />} value={fmtPct(result.stats.max_drawdown)} color={statValueColor(result.stats.max_drawdown)} />
              <Stat label={<MetricLabel label="累计收益" metric="totalReturn" />} value={fmtPct(result.stats.total_return)} color={statValueColor(result.stats.total_return)} />
            </div>

            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
              <span>候选样本 <b className="text-foreground num">{result.stats.n_candidates ?? 0}</b> (标的×信号日)</span>
              <span>信号天数 <b className="text-foreground num">{result.stats.n_days ?? 0}</b></span>
              <span>日均候选 <b className="text-foreground num">{result.stats.avg_daily_candidates ?? 0}</b></span>
              <span>最佳 <b className="text-bull num">{fmtPct(result.stats.best)}</b></span>
              <span>最差 <b className="text-bear num">{fmtPct(result.stats.worst)}</b></span>
              <span>基准(上证) <b className="text-foreground num">{fmtPct(result.stats.benchmark_return)}</b></span>
            </div>

            {/* 累计超额曲线 (复用 StrategyNavChart) */}
            {result.equity_curve.length > 1 && (
              <div className="rounded-card border border-border p-3">
                <div className="mb-2 text-xs font-medium text-secondary">累计收益曲线(日均复利)</div>
                <StrategyNavChart result={result} />
              </div>
            )}

            {/* 收益分布直方图 */}
            {Array.isArray(result.stats.return_distribution) && result.stats.return_distribution.length > 0 && (
              <div className="rounded-card border border-border p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-xs font-medium text-secondary">候选标的收益分布(持有 {result.config?.holding_days ?? 5} 天)</span>
                  <span className="text-[10px] text-muted">红=正收益 · 绿=负收益</span>
                </div>
                <ReturnDistributionChart distribution={result.stats.return_distribution} />
              </div>
            )}

            <div className="text-[11px] text-muted">run_id: {result.run_id}</div>
          </motion.div>
        )}

        {result && !result.error && result.stats && !result.stats.error && (result.stats.mode !== 'full' || result.stats.full_kind === 'candidate_execution') && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-4"
          >
            {/* 策略信息 */}
            {result.strategy_info && (
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium text-foreground">{result.strategy_info.name}</span>
                  {result.stats.full_kind === 'candidate_execution' && (
                    <span className="text-[9px] px-1 py-px rounded border border-accent/30 bg-accent/10 text-accent">全量独立执行</span>
                  )}
                  {result.strategy_info.source && (
                    <span className={`text-[9px] px-1 py-px rounded border ${BADGE_CLS_MAP[result.strategy_info.source] ?? ''}`}>
                      {SRC_MAP[result.strategy_info.source] ?? ''}
                    </span>
                  )}
                  {resultRegimeSummary && (
                    <span className="inline-flex items-center gap-1 rounded border border-accent/25 bg-accent/10 px-1.5 py-px text-[9px] text-accent">
                      <Gauge className="h-2.5 w-2.5" />
                      环境 {resultRegimeSummary}
                    </span>
                  )}
                </div>
                {/* 叠加策略: 子策略构成归因 */}
                {result.strategy_info.composite_children && result.strategy_info.composite_children.length > 0 && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Layers className="h-3 w-3 text-teal-400 shrink-0" />
                    <span className="text-[10px] text-muted">叠加 {result.strategy_info.composite_children.length} 策略</span>
                    {result.strategy_info.composite_children.map(c => (
                      <span key={c.id} className="text-[9px] px-1.5 py-px rounded border border-teal-500/25 bg-teal-500/10 text-teal-400">
                        {c.id}<span className="text-teal-400/60 ml-0.5">{(c.weight * 100).toFixed(0)}%</span>
                      </span>
                    ))}
                  </div>
                )}
                {result.strategy_info.stop_loss != null && (
                  <span className="text-[10px] text-secondary">止损 {fmtPct(result.strategy_info.stop_loss)}</span>
                )}
                {result.strategy_info.take_profit != null && (
                  <span className="text-[10px] text-secondary">止盈 {fmtPct(result.strategy_info.take_profit)}</span>
                )}
                {result.strategy_info.trailing_stop != null && (
                  <span className="text-[10px] text-secondary">移损 {fmtPct(result.strategy_info.trailing_stop)}</span>
                )}
                {result.strategy_info.trailing_take_profit_activate != null && result.strategy_info.trailing_take_profit_drawdown != null && (
                  <span className="text-[10px] text-secondary">回撤 {fmtPct(result.strategy_info.trailing_take_profit_activate)}-{fmtPct(result.strategy_info.trailing_take_profit_drawdown)}</span>
                )}
                {result.strategy_info.max_hold_days != null && (
                  <span className="text-[10px] text-secondary">最长 {result.strategy_info.max_hold_days} 天</span>
                )}
                {result.strategy_info.cooldown_loss_streak != null && result.strategy_info.cooldown_days != null && (
                  <span className="text-[10px] text-secondary">连亏{result.strategy_info.cooldown_loss_streak}笔冷却{result.strategy_info.cooldown_days}天</span>
                )}
                {resultTradeDays > 0 && (
                  <span className="ml-auto flex items-center gap-2 text-[11px] text-muted">
                    <span className="font-mono">{String(resultStartDate).slice(0, 10)} ~ {String(resultEndDate).slice(0, 10)}</span>
                    <span>{resultTradeDays} 天</span>
                  </span>
                )}
                {result.elapsed_ms > 0 && (
                  <span className={`flex items-center gap-1 text-[11px] text-muted ${resultTradeDays > 0 ? '' : 'ml-auto'}`}>
                    <Clock className="h-3 w-3" />
                    <span>总耗时</span>
                    <span className="num">{fmtDuration(result.elapsed_ms)}</span>
                  </span>
                )}
                <button
                  type="button"
                  onClick={exportResultCsv}
                  title="导出回测结果 CSV (概要 + 净值曲线 + 交易明细 + 分标的统计)"
                  className="ml-1 inline-flex h-6 shrink-0 items-center gap-1 rounded border border-border bg-base px-2 text-[10px] text-secondary transition-colors hover:border-accent/40 hover:text-accent"
                >
                  <Download className="h-3 w-3" />
                  导出
                </button>
              </div>
            )}


































              {settingsTab === 'risk' && (
                <ConfigSection title="风控">
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">止损(%)</span>
                      <NumberField
                        value={numOrNull(stopLossPct)}
                        min={0} max={99} step={0.5}
                        onChange={n => updateOverride('stop_loss', n == null ? null : -Math.abs(n) / 100)}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">止盈(%)</span>
                      <NumberField
                        value={numOrNull(takeProfitPct)}
                        min={1} max={500} step={0.5}
                        onChange={n => updateOverride('take_profit', n == null ? null : Math.abs(n) / 100)}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">移动止损(%)</span>
                      <NumberField
                        value={numOrNull(trailingStopPct)}
                        min={0.5} max={50} step={0.5}
                        onChange={n => updateOverride('trailing_stop', n == null ? null : -Math.abs(n) / 100)}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">回撤止盈启动(%)</span>
                      <NumberField
                        value={numOrNull(trailingTakeProfitActivatePct)}
                        min={1} max={200} step={0.5}
                        onChange={n => {
                          const next = n == null ? null : Math.abs(n) / 100
                          updateOverride('trailing_take_profit_activate', next)
                          // 联动: 回撤不能超过启动值
                          const drawdown = numOrNull(trailingTakeProfitDrawdownPct)
                          if (next != null && drawdown != null && drawdown / 100 > next) {
                            updateOverride('trailing_take_profit_drawdown', next)
                          }
                        }}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">回撤止盈回撤(点)</span>
                      <NumberField
                        value={numOrNull(trailingTakeProfitDrawdownPct)}
                        min={0.5} max={50} step={0.5}
                        onChange={n => updateOverride('trailing_take_profit_drawdown', n == null ? null : Math.abs(n) / 100)}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">最长持仓(天)</span>
                      <NumberField
                        value={numOrNull(maxHoldDaysValue)}
                        min={1} step={1}
                        onChange={n => updateOverride('max_hold_days', n == null ? null : Math.round(n))}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">连亏冷却(笔)</span>
                      <NumberField
                        value={numOrNull(cooldownLossStreakValue)}
                        min={2} step={1}
                        onChange={n => updateOverride('cooldown_loss_streak', n == null ? null : Math.round(n))}
                        className={INPUT_CLS}
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-[11px] text-secondary">冷却天数(天)</span>
                      <NumberField
                        value={numOrNull(cooldownDaysValue)}
                        min={1} step={1}
                        onChange={n => updateOverride('cooldown_days', n == null ? null : Math.round(n))}
                        className={INPUT_CLS}
                      />
                    </label>
                  </div>
                </ConfigSection>
              )}
            </div>






















