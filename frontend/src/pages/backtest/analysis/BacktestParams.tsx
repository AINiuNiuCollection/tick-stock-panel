/**
 * 回测参数 Tab — 展示每次回测运行时的完整配置参数, 供回看和复现。
 *
 * UI 设计: 左侧渐变区标题条(整行底色高亮) + 右侧小卡片网格(4列紧凑)。
 * 卡片: 圆角长方形, 渐变标题条, 参数 label/value 同行排列。
 */
import type { BacktestHistoryRecord } from '@/lib/api'
import { REGIME_STATE_LABELS } from '@/lib/api'

interface Props {
  record: BacktestHistoryRecord | null
}

// ── 枚举值 → UI 中文名称映射 ──
const VALUE_LABELS: Record<string, string> = {
  stock: '股票',
  etf: 'ETF',
  'close_t': '信号日收盘',
  'open_t+1': '次日开盘',
  'signal_next_minute': '信号触发卖出(BETA)',
  equal: '等权买入',
  score_weight: '评分加权',
  position: '仓位模拟',
  full: '全量模拟',
  high: '看多(高值优先)',
  low: '看空(低值优先)',
  none: '不排序',
  true: '是',
  false: '否',
}

const STATE_LABELS: Record<string, string> = REGIME_STATE_LABELS

function signalLabel(id: string, signalLabels?: Record<string, string>): string {
  return signalLabels?.[id] ?? id
}
function factorLabel(id: string, factorLabels?: Record<string, string>): string {
  return factorLabels?.[id] ?? id
}
function paramLabel(id: string, paramLabels?: Record<string, string>): string {
  return paramLabels?.[id] ?? id
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'boolean') return VALUE_LABELS[String(v)] ?? String(v)
  if (typeof v === 'string' && v in VALUE_LABELS) return `${VALUE_LABELS[v]}(${v})`
  if (Array.isArray(v)) {
    if (v.length === 0) return '空'
    return v.map(item => {
      if (typeof item === 'string' && item in STATE_LABELS) return `${STATE_LABELS[item]}(${item})`
      if (typeof item === 'string' && item in VALUE_LABELS) return `${VALUE_LABELS[item]}(${item})`
      return String(item)
    }).join(', ')
  }
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—'
  const num = Number(v)
  if (isNaN(num)) return String(v)
  return `${(num * 100).toFixed(4)}%(${num})`
}

function fmtBps(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return `${v}bp`
}

function fmtRange(min: unknown, max: unknown): string {
  const hasMin = min !== null && min !== undefined
  const hasMax = max !== null && max !== undefined
  if (!hasMin && !hasMax) return '不限'
  if (hasMin && hasMax) return `${min} ~ ${max}`
  if (hasMin) return `≥ ${min}`
  return `≤ ${max}`
}

// ── 颜色配置 ──
type CardColor = {
  gradFrom: string
  gradTo: string
  border: string
  text: string
  dot: string
}

const COLORS: Record<string, CardColor> = {
  basic:    { gradFrom: 'rgba(59,130,246,0.15)',  gradTo: 'rgba(59,130,246,0.04)',  border: '#3b82f6', text: '#60a5fa', dot: '#3b82f6' },
  trading:  { gradFrom: 'rgba(20,184,166,0.15)',  gradTo: 'rgba(20,184,166,0.04)',  border: '#14b8a6', text: '#2dd4bf', dot: '#14b8a6' },
  regime:   { gradFrom: 'rgba(139,92,246,0.15)',  gradTo: 'rgba(139,92,246,0.04)',  border: '#8b5cf6', text: '#a78bfa', dot: '#8b5cf6' },
  strategy: { gradFrom: 'rgba(245,158,11,0.15)',  gradTo: 'rgba(245,158,11,0.04)',  border: '#f59e0b', text: '#fbbf24', dot: '#f59e0b' },
  filter:   { gradFrom: 'rgba(249,115,22,0.15)',  gradTo: 'rgba(249,115,22,0.04)',  border: '#f97316', text: '#fb923c', dot: '#f97316' },
  entry:    { gradFrom: 'rgba(34,197,94,0.15)',   gradTo: 'rgba(34,197,94,0.04)',   border: '#22c55e', text: '#4ade80', dot: '#22c55e' },
  exit:     { gradFrom: 'rgba(132,204,22,0.15)',  gradTo: 'rgba(132,204,22,0.04)',  border: '#84cc16', text: '#a3e635', dot: '#84cc16' },
  scoring:  { gradFrom: 'rgba(236,72,153,0.15)',  gradTo: 'rgba(236,72,153,0.04)',  border: '#ec4899', text: '#f472b6', dot: '#ec4899' },
  risk:     { gradFrom: 'rgba(239,68,68,0.15)',   gradTo: 'rgba(239,68,68,0.04)',   border: '#ef4444', text: '#f87171', dot: '#ef4444' },
}

// ── 区标题: 左侧渐变高亮整行 ──
const SECTION_STYLES: Record<string, { gradFrom: string; gradTo: string; accent: string }> = {
  basic: { gradFrom: 'rgba(59,130,246,0.12)', gradTo: 'rgba(59,130,246,0.01)', accent: '#3b82f6' },
  adv:   { gradFrom: 'rgba(168,85,247,0.12)', gradTo: 'rgba(168,85,247,0.01)', accent: '#a855f7' },
}

function SectionHeader({ label, variant }: { label: string; variant: 'basic' | 'adv' }) {
  const s = SECTION_STYLES[variant]
  return (
    <div
      className="flex items-center gap-3 rounded-btn py-2.5 px-4"
      style={{
        background: `linear-gradient(to right, ${s.gradFrom}, ${s.gradTo})`,
        borderLeft: `4px solid ${s.accent}`,
      }}
    >
      <span
        className="inline-block h-2.5 w-2.5 rounded-full shrink-0"
        style={{ backgroundColor: s.accent, boxShadow: `0 0 8px ${s.accent}` }}
      />
      <span className="text-base font-bold tracking-wide text-foreground">{label}</span>
    </div>
  )
}

// ── 小卡片 ──
function MiniCard({ title, color, children }: {
  title: string
  color: CardColor
  children: React.ReactNode
}) {
  return (
    <div
      className="rounded-card bg-surface overflow-hidden flex flex-col transition-shadow hover:shadow-md"
      style={{ border: `1px solid hsl(var(--border))` }}
    >
      {/* 渐变标题条 */}
      <div
        className="flex items-center gap-2 px-3 py-2 shrink-0"
        style={{
          background: `linear-gradient(135deg, ${color.gradFrom}, ${color.gradTo})`,
          borderLeft: `3px solid ${color.border}`,
          borderBottom: `1px solid hsl(var(--border))`,
        }}
      >
        <span
          className="inline-block h-2 w-2 rounded-full shrink-0"
          style={{ backgroundColor: color.dot, boxShadow: `0 0 6px ${color.dot}` }}
        />
        <span className="text-sm font-bold tracking-wide" style={{ color: color.text }}>
          {title}
        </span>
      </div>
      {/* 参数内容 */}
      <div className="space-y-1.5 px-3 py-2.5 flex-1">
        {children}
      </div>
    </div>
  )
}

/** label 左 value 右, 同行排列, 底部分隔线 */
function ParamRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 min-w-0 py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs font-medium text-secondary shrink-0">{label}</span>
      <span className="text-sm font-semibold text-foreground text-right break-words">{value}</span>
    </div>
  )
}

/** label 在上 value 在下, 适合长文本, 底部分隔线 */
function ParamBlock({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 py-1.5 border-b border-border/40 last:border-0">
      <div className="text-xs font-medium text-secondary mb-0.5">{label}</div>
      <div className="text-sm font-semibold text-foreground break-words leading-relaxed">{value}</div>
    </div>
  )
}

export function BacktestParams({ record }: Props) {
  if (!record) {
    return (
      <div className="flex items-center justify-center py-20 text-muted">
        未加载回测记录
      </div>
    )
  }

  const cfg = record.config ?? {}
  const labels = record.labels ?? {}
  const paramLabels = labels.param_labels as Record<string, string> | undefined
  const signalLabels = labels.signal_labels as Record<string, string> | undefined
  const factorLabels = labels.factor_labels as Record<string, string> | undefined
  const overrides = cfg.overrides ?? {}
  const basicFilter = overrides.basic_filter ?? {}
  const regimeFilter = cfg.regime_filter ?? {}

  const params = cfg.params ?? {}
  const strategyParamEntries = Object.entries(params)

  const entrySignals = (overrides.entry_signals ?? []) as string[]
  const exitSignals = (overrides.exit_signals ?? []) as string[]

  const scoring = overrides.scoring ?? {}
  const scoringDirs = overrides.scoring_directions ?? {}
  const scoringEntries = Object.entries(scoring)

  const boards = Array.isArray(basicFilter.boards) ? basicFilter.boards as string[] : []

  return (
    <div className="space-y-4">
      {/* ═══ 基础区 ═══ */}
      <div
        className="rounded-card overflow-hidden"
        style={{ border: `1px solid hsl(var(--border))` }}
      >
      <SectionHeader label="基础" variant="basic" />
      <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <MiniCard title="基础" color={COLORS.basic}>
          <ParamRow label="策略" value={`${labels.strategy_name ?? '—'}(${cfg.strategy_id ?? '—'})`} />
          <ParamRow label="资产类型" value={fmtVal(cfg.asset_type)} />
          <ParamRow label="股票代码" value={fmtVal(cfg.symbols)} />
          <ParamRow label="回测区间" value={`${fmtVal(cfg.start)} ~ ${fmtVal(cfg.end)}`} />
        </MiniCard>

        <MiniCard title="交易设置" color={COLORS.trading}>
          <ParamRow label="建仓口径" value={fmtVal(cfg.entry_fill ?? cfg.matching)} />
          <ParamRow label="清仓口径" value={fmtVal(cfg.exit_fill ?? cfg.matching)} />
          <ParamRow label="分钟K成交" value={fmtVal(cfg.minute_fill)} />
          <ParamRow label="模拟模式" value={fmtVal(cfg.mode)} />
          <ParamRow label="初始资金" value={fmtVal(cfg.initial_capital)} />
          <ParamRow label="买入权重" value={fmtVal(cfg.position_sizing)} />
          <ParamRow label="最大持仓数" value={fmtVal(cfg.max_positions)} />
          <ParamRow label="最大总仓位" value={fmtVal(cfg.max_exposure_pct)} />
          <ParamRow label="持仓天数" value={fmtVal(cfg.holding_days)} />
          <ParamRow label="佣金率" value={fmtPct(cfg.commission_pct)} />
          <ParamRow label="印花税率" value={fmtPct(cfg.stamp_tax_pct)} />
          <ParamRow label="滑点" value={fmtBps(cfg.slippage_bps)} />
        </MiniCard>

        <MiniCard title="市场环境过滤" color={COLORS.regime}>
          <ParamRow label="状态过滤" value={regimeFilter.states ? fmtVal(regimeFilter.states) : '不过滤'} />
          <ParamRow label="最低评分" value={fmtVal(regimeFilter.min_score ?? '不过滤')} />
        </MiniCard>
      </div>
      </div>

      {/* ═══ 高级区 ═══ */}
      <div
        className="rounded-card overflow-hidden"
        style={{ border: `1px solid hsl(var(--border))` }}
      >
      <SectionHeader label="高级" variant="adv" />
      <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {strategyParamEntries.length > 0 && (
          <MiniCard title="策略参数" color={COLORS.strategy}>
            {strategyParamEntries.map(([k, v]) => (
              <ParamRow key={k} label={paramLabel(k, paramLabels)} value={fmtVal(v)} />
            ))}
          </MiniCard>
        )}

        <MiniCard title="基础过滤" color={COLORS.filter}>
          <ParamRow label="过滤开关" value={fmtVal(basicFilter.enabled ?? true)} />
          <ParamRow label="排除 ST / 退市" value={fmtVal(basicFilter.exclude_st ?? false)} />
          <ParamRow label="价格(元)" value={fmtRange(basicFilter.price_min, basicFilter.price_max)} />
          <ParamRow label="流通市值(亿)" value={fmtRange(basicFilter.float_cap_min, basicFilter.float_cap_max)} />
          <ParamRow label="总市值(亿)" value={fmtRange(basicFilter.market_cap_min, basicFilter.market_cap_max)} />
          <ParamRow label="成交额(亿)" value={fmtRange(basicFilter.amount_min, basicFilter.amount_max)} />
          <ParamRow label="换手率(%)" value={fmtRange(basicFilter.turnover_min, basicFilter.turnover_max)} />
          {boards.length > 0 && (
            <ParamBlock label="板块" value={boards.join(', ')} />
          )}
        </MiniCard>

        <MiniCard title="入场触发器" color={COLORS.entry}>
          {entrySignals.length > 0 ? (
            <ParamBlock label={`共 ${entrySignals.length} 个触发器`} value={
              entrySignals.map(s => `${signalLabel(s, signalLabels)}(${s})`).join(', ')
            } />
          ) : (
            <ParamRow label="触发器" value="无" />
          )}
        </MiniCard>

        <MiniCard title="出场触发器" color={COLORS.exit}>
          {exitSignals.length > 0 ? (
            <ParamBlock label={`共 ${exitSignals.length} 个触发器`} value={
              exitSignals.map(s => `${signalLabel(s, signalLabels)}(${s})`).join(', ')
            } />
          ) : (
            <ParamRow label="触发器" value="无" />
          )}
        </MiniCard>

        <MiniCard title="评分权重" color={COLORS.scoring}>
          <ParamRow label="评分替换模式" value={fmtVal(overrides.scoring_replace)} />
          {scoringEntries.map(([k, v]) => {
            const dir = scoringDirs[k] ?? 'high'
            const dirLabel = VALUE_LABELS[dir] ?? dir
            return (
              <ParamRow
                key={k}
                label={factorLabel(k, factorLabels)}
                value={`${v} · ${dirLabel}(${k}:${dir})`}
              />
            )
          })}
          <ParamRow label="最小评分" value={fmtVal(overrides.score_min)} />
          <ParamRow label="最大评分" value={fmtVal(overrides.score_max)} />
        </MiniCard>

        <MiniCard title="风控" color={COLORS.risk}>
          <ParamRow label="止损" value={fmtVal(overrides.stop_loss)} />
          <ParamRow label="止盈" value={fmtVal(overrides.take_profit)} />
          <ParamRow label="移动止损" value={fmtVal(overrides.trailing_stop)} />
          <ParamRow label="移动止盈激活" value={fmtVal(overrides.trailing_take_profit_activate)} />
          <ParamRow label="移动止盈回撤" value={fmtVal(overrides.trailing_take_profit_drawdown)} />
          <ParamRow label="最大持有天数" value={fmtVal(overrides.max_hold_days)} />
          <ParamRow label="连亏冷却次数" value={fmtVal(overrides.cooldown_loss_streak)} />
          <ParamRow label="冷却天数" value={fmtVal(overrides.cooldown_days)} />
        </MiniCard>
      </div>
      </div>
    </div>
  )
}
