import { useState, useMemo, useRef, useEffect } from 'react'
import type { BacktestData, SelectionLogEntry } from './types'
import { cn } from '@/lib/cn'

// ── 淘汰原因中文映射 ──
const REASON_LABELS: Record<string, string> = {
  already_held: '已持仓',
  same_day_reentry: '同日卖出再买入',
  invalid_price: '无效价格',
  suspended: '停牌',
  limit_up: '涨停',
  score_filter: '评分过滤',
  no_slot: '无可用槽位',
  exposure: '敞口不足',
  lot_size: '不足一手',
  cash: '资金不足',
  cooldown: '连亏冷却',
  buy_suspended: '停牌',
  buy_invalid_price: '无效价格',
  buy_limit_up: '涨停',
  buy_same_day_reentry: '同日卖出再买入',
  buy_score_filter: '评分过滤',
  buy_no_slot: '无可用槽位',
  buy_exposure: '敞口不足',
  buy_lot_size: '不足一手',
  buy_cash: '资金不足',
}

export function SelectionProcess({ data }: { data: BacktestData }) {
  const log: SelectionLogEntry[] = data.selectionLog ?? []
  const [selectedDate, setSelectedDate] = useState<string>('')
  const dateListRef = useRef<HTMLDivElement>(null)

  // 统计摘要
  const summary = useMemo(() => {
    if (!log.length) return null
    const totalDays = log.length
    const totalSignals = log.reduce((s, d) => s + d.signal_count, 0)
    const totalSelected = log.reduce(
      (s, d) => s + d.candidates.filter(c => c.status === 'selected').length, 0
    )
    const totalRejected = log.reduce(
      (s, d) => s + d.candidates.filter(c => c.status === 'rejected').length, 0
    )
    const reasonCounts: Record<string, number> = {}
    for (const day of log) {
      for (const c of day.candidates) {
        if (c.status === 'rejected' && c.reason) {
          const label = REASON_LABELS[c.reason] ?? c.reason
          reasonCounts[label] = (reasonCounts[label] ?? 0) + 1
        }
      }
    }
    const topReasons = Object.entries(reasonCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
    return { totalDays, totalSignals, totalSelected, totalRejected, topReasons }
  }, [log])

  // 日期列表
  const dates = useMemo(() => log.map(d => d.date), [log])

  // 当前选中日期索引
  const selectedIndex = useMemo(() => {
    const target = selectedDate || (dates[0] ?? '')
    const idx = dates.indexOf(target)
    return idx >= 0 ? idx : 0
  }, [dates, selectedDate])

  // 当前选中日期的数据
  const dayData = useMemo(() => {
    if (!log.length) return null
    return log[selectedIndex] ?? log[0]
  }, [log, selectedIndex])

  // 键盘上下键切换日期
  useEffect(() => {
    const container = dateListRef.current
    if (!container) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedDate(prev => {
          const cur = prev || (dates[0] ?? '')
          const idx = dates.indexOf(cur)
          if (idx >= 0 && idx < dates.length - 1) return dates[idx + 1]
          return prev
        })
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedDate(prev => {
          const cur = prev || (dates[0] ?? '')
          const idx = dates.indexOf(cur)
          if (idx > 0) return dates[idx - 1]
          return prev
        })
      }
    }
    container.addEventListener('keydown', handleKeyDown)
    return () => container.removeEventListener('keydown', handleKeyDown)
  }, [dates])

  // 选中日期滚动到可视区域
  useEffect(() => {
    const container = dateListRef.current
    if (!container) return
    const item = container.querySelector(`[data-date-idx="${selectedIndex}"]`) as HTMLElement | null
    if (item) {
      item.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [selectedIndex])

  if (!log.length) {
    return (
      <div className="flex items-center justify-center py-20 text-sm text-muted">
        暂无选股过程数据
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 摘要 */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="text-xs text-muted">选股天数</div>
            <div className="mt-1 text-2xl font-bold text-foreground">{summary.totalDays}</div>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="text-xs text-muted">信号总数</div>
            <div className="mt-1 text-2xl font-bold text-foreground">{summary.totalSignals}</div>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="text-xs text-muted">买入数</div>
            <div className="mt-1 text-2xl font-bold text-red-500">{summary.totalSelected}</div>
          </div>
          <div className="rounded-xl border border-border bg-surface p-4">
            <div className="text-xs text-muted">淘汰数</div>
            <div className="mt-1 text-2xl font-bold text-green-500">{summary.totalRejected}</div>
          </div>
        </div>
      )}

      {/* 淘汰原因分布 */}
      {summary && summary.topReasons.length > 0 && (
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-3 text-sm font-semibold text-foreground">淘汰原因分布</div>
          <div className="flex flex-col gap-2">
            {summary.topReasons.map(([reason, count]) => {
              const pct = (count / summary.totalRejected) * 100
              return (
                <div key={reason} className="flex items-center gap-3">
                  <div className="w-28 shrink-0 text-xs text-secondary">{reason}</div>
                  <div className="flex-1 h-5 rounded bg-base overflow-hidden">
                    <div
                      className="h-full rounded bg-green-500/60"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="w-16 shrink-0 text-right text-xs font-mono text-muted">{count}</div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 逐日选股明细: 左侧日期列 + 右侧明细 */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 text-sm font-semibold text-foreground">逐日选股明细</div>
        <div className="flex gap-4" style={{ minHeight: '400px', maxHeight: '70vh' }}>
          {/* 左侧日期列 */}
          <div
            ref={dateListRef}
            tabIndex={0}
            className="w-36 shrink-0 overflow-y-auto rounded-lg border border-border bg-base focus:outline-none focus:border-accent/50"
          >
            {dates.map((d, idx) => {
              const dayLog = log[idx]
              const buyCount = dayLog.candidates.filter(c => c.status === 'selected').length
              const isActive = idx === selectedIndex
              return (
                <div
                  key={d}
                  data-date-idx={idx}
                  onClick={() => setSelectedDate(d)}
                  className={cn(
                    'relative cursor-pointer border-b border-border/50 px-3 py-2 text-xs transition-colors',
                    isActive
                      ? 'bg-accent/10 text-foreground font-semibold'
                      : 'text-secondary hover:bg-base/80'
                  )}
                >
                  {buyCount > 0 && (
                    <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-red-500" />
                  )}
                  <div>{d}</div>
                  <div className={cn('mt-0.5 text-[10px]', isActive ? 'text-red-500' : 'text-muted')}>
                    买入{buyCount} / 信号{dayLog.signal_count}
                  </div>
                </div>
              )
            })}
          </div>

          {/* 右侧明细 */}
          <div className="flex-1 flex flex-col gap-2 overflow-hidden">
            {dayData && (
              <>
                {/* 日期摘要 */}
                <div className="flex items-center gap-4 text-xs text-muted shrink-0">
                  <span className="font-semibold text-foreground">{dayData.date}</span>
                  <span>信号 {dayData.signal_count} 只</span>
                  <span>可用槽位 {dayData.slots_available}</span>
                  <span className="text-red-500">
                    买入 {dayData.candidates.filter(c => c.status === 'selected').length}
                  </span>
                  <span className="text-green-500">
                    淘汰 {dayData.candidates.filter(c => c.status === 'rejected').length}
                  </span>
                </div>

                {/* 候选列表 */}
                <div className="overflow-auto flex-1">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-surface">
                      <tr className="border-b-2 border-border">
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">排名</th>
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">代码</th>
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">名称</th>
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">评分</th>
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">状态</th>
                        <th className="py-2 px-3 text-center text-sm font-bold text-foreground">原因</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...dayData.candidates].sort((a, b) => (b.score ?? -Infinity) - (a.score ?? -Infinity)).map((c, i) => (
                        <tr
                          key={`${c.symbol}-${i}`}
                          className="border-b border-border/50 hover:bg-base/50"
                        >
                          <td className="py-2 px-3 text-center font-mono text-muted">
                            {c.rank ?? '-'}
                          </td>
                          <td className="py-2 px-3 text-center font-mono text-foreground">{c.symbol}</td>
                          <td className="py-2 px-3 text-center text-secondary">{c.name || c.symbol}</td>
                          <td className="py-2 px-3 text-center font-mono text-foreground">
                            {c.score != null ? c.score.toFixed(2) : '-'}
                          </td>
                          <td className="py-2 px-3 text-center">
                            <span
                              className={cn(
                                'inline-block rounded px-1.5 py-0.5 text-[10px] font-medium',
                                c.status === 'selected'
                                  ? 'bg-red-500/15 text-red-500'
                                  : 'bg-green-500/15 text-green-500'
                              )}
                            >
                              {c.status === 'selected' ? '买入' : '淘汰'}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-center text-muted">
                            {c.reason ? (REASON_LABELS[c.reason] ?? c.reason) : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
