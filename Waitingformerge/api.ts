
// ── 0AMV (活跃市值) ──
export interface AmvRow {
  date: string
  amv: number
  active_count: number
  amv_ma5: number | null
  amv_ma20: number | null
}

export interface AmvHistory {
  rows: AmvRow[]
  total: number
}

export interface AmvCoverage {
  rows: number
  earliest_date: string | null
  latest_date: string | null
}

// ── 市场阶段(情绪周期) 与 主线 ──
export type MarketPhase = 'ice' | 'ignite' | 'rally' | 'climax' | 'ebb' | 'repair'

export const MARKET_PHASE_LABELS: Record<MarketPhase, string> = {
  ice: '冰点',
  ignite: '启动',
  rally: '主升',
  climax: '高潮',
  ebb: '退潮',
  repair: '修复',
}












export interface StrategyDetail {
  id: string
  name: string
  description: string
  tags: string[]
  source: 'builtin' | 'custom' | 'ai' | 'composite'
  research_only?: boolean
  execution_backend: 'polars_expr' | 'matrix_native' | 'python_history_legacy' | 'composite' | 'minute_filter'
  asset_types: string[]
  timeframes: string[]
  version: string
  basic_filter: Record<string, any>
  params: StrategyParamDef[]
  params_defaults: Record<string, any>
  scoring: Record<string, number>
  scoring_directions: Record<string, ScoringDirection>
  entry_signals: string[]
  exit_signals: string[]
  minute_exit_trigger_supported_signals: string[]
  stop_loss: number | null
  take_profit: number | null
  trailing_stop: number | null
  trailing_take_profit_activate: number | null
  trailing_take_profit_drawdown: number | null
  max_hold_days: number | null
  cooldown_loss_streak: number | null
  cooldown_days: number | null
  display_limit?: number
  order_by: string
  descending: boolean
  limit: number
  // 叠加策略(composite)专属: 子策略列表与合并模式。非 composite 时为 null。
  composite_children?: CompositeChildInfo[] | null
}












export interface StrategyBacktestResult {
  run_id: string
  config: Record<string, any>
  stats: Record<string, any>
  equity_curve: { date: string; value: number; cash?: number; positions?: number; exposure?: number }[]
  drawdown_curve: { date: string; value: number }[]
  benchmark_curve?: { date: string; value: number; close?: number; name?: string; symbol?: string }[]
  trades: StrategyBacktestTrade[]
  /** v1 因子归因: 入场信号日因子值快照 × 成交盈亏 (胜/败单均值对比); 无评分因子或分钟路径时为 null */
  factor_attribution?: {
    factors: { factor: string; win_mean: number | null; lose_mean: number | null; win_n: number; lose_n: number }[]
    n_win: number
    n_lose: number
  } | null
  per_symbol_stats: {
    symbol: string
    n_trades: number
    total_return: number
    win_rate: number
    best: number
    worst: number
  }[]
  strategy_info: {
    id: string
    name: string
    description: string
    entry_signals: string[]
    exit_signals: string[]
    stop_loss: number | null
    take_profit: number | null
    trailing_stop: number | null
    trailing_take_profit_activate: number | null
    trailing_take_profit_drawdown: number | null
    score_min: number | null
    score_max: number | null
    max_hold_days: number | null
    cooldown_loss_streak: number | null
    cooldown_days: number | null
    source: string
    execution_backend?: string
    // 叠加策略回测: 子策略构成与权重归因
    composite_children?: { id: string; weight: number }[]
  }
  elapsed_ms: number
  error: string | null
}













marketSnapshot: () =>
    request<{ as_of: string | null; rows: MarketSnapshotRow[] }>('/api/screener/market-snapshot'),
  overviewMarket: (asOf?: string) => request<OverviewMarket>(`/api/overview/market${asOf ? `?as_of=${asOf}` : ''}`),

  // 概念涨幅轮动矩阵: 每列(日期)各自把所有概念按当天涨幅从高到低排序
  rpsRotation: (days: number, kind?: 'concept' | 'industry', level?: number) =>
    request<RpsRotationData>(`/api/rps/rotation?days=${days}${kind ? `&kind=${kind}` : ''}${level ? `&level=${level}` : ''}`),

  // 市场环境(Regime)
  regimeHistory: (start?: string, end?: string, limit?: number) => {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    if (limit) params.set('limit', String(limit))
    const qs = params.toString()
    return request<RegimeHistory>(`/api/regime/history${qs ? `?${qs}` : ''}`)
  },
  regimeLatest: () => request<{ row: RegimeRow | null }>('/api/regime/latest'),
  regimeStates: (days = 60) => request<RegimeStates>(`/api/regime/states?days=${days}`),
  regimeCoverage: () => request<RegimeCoverage>('/api/regime/coverage'),
  regimeRecompute: (start?: string, end?: string) => {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const qs = params.toString()
    // 补算需扫 enriched 全市场数据, 大区间耗时超过默认超时, 放宽到 5 分钟
    return request<{ ok: boolean; computed: number; phase_days?: number; mainline_rows?: number; amv_days?: number }>(`/api/regime/recompute${qs ? `?${qs}` : ''}`, { method: 'POST', timeoutMs: 300_000 })
  },
  regimePhases: (start?: string, end?: string) => {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const qs = params.toString()
    return request<PhaseSegments>(`/api/regime/phases${qs ? `?${qs}` : ''}`)
  },
  regimeMainline: (start?: string, end?: string, top = 10, kind: 'concept' | 'industry' = 'concept') => {
    const params = new URLSearchParams({ top: String(top), kind })
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    return request<MainlineResult>(`/api/regime/mainline?${params.toString()}`)
  },
  regimeMainlineRecompute: () =>
    request<{ ok: boolean; rows: number }>('/api/regime/mainline/recompute', { method: 'POST' }),

  // 0AMV (活跃市值)
  amvHistory: (start?: string, end?: string, limit?: number) => {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    if (limit) params.set('limit', String(limit))
    const qs = params.toString()
    return request<AmvHistory>(`/api/market-amv/history${qs ? `?${qs}` : ''}`)
  },
  amvCoverage: () => request<AmvCoverage>('/api/market-amv/coverage'),
  amvRecompute: (start?: string, end?: string) => {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    const qs = params.toString()
    return request<{ ok: boolean; computed: number }>(`/api/market-amv/recompute${qs ? `?${qs}` : ''}`, { method: 'POST', timeoutMs: 300_000 })
  },
  mainlineFilterUpdate: (payload: { min_members?: number; max_members?: number; blacklist?: string[]; exclude_st?: boolean }) =>
    request<MainlineFilter>('/api/settings/preferences/mainline-filter', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  limitLadder: (asOf?: string, extColumns?: string, direction?: 'up' | 'down') => {
    const params = new URLSearchParams()
    if (asOf) params.set('as_of', asOf)
    if (extColumns) params.set('ext_columns', extColumns)
    if (direction === 'down') params.set('direction', 'down')
    const qs = params.toString()
    return request<LimitLadderResult>(
      `/api/screener/limit-ladder${qs ? `?${qs}` : ''}`,
    )
  },























// ===== 回测历史记录 =====

export interface BacktestHistoryMeta {
  id: string
  name: string
  created_at: string
  strategy_name: string
  strategy_id: string
  start: string | null
  end: string | null
  total_return: number | null
  max_drawdown: number | null
  sharpe: number | null
  n_trades: number | null
  win_rate: number | null
  elapsed_ms: number | null
}

export interface BacktestHistoryRecord {
  id: string
  name: string
  created_at: string
  config: Record<string, any>
  labels: Record<string, any>
  stats: Record<string, any>
  result: StrategyBacktestResult
}

// ===== Settings =====

/** 端点发现清单 —— 对应 tickflow.org/endpoints.json */
