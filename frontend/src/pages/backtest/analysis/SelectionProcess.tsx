import { useState, useMemo } from 'react'
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

  // 当前选中日期的数据
  const dayData = useMemo(() => {
    if (!log.length) return null
    const target = selectedDate || log[0].date
    return log.find(d => d.date === target) ?? log[0]
  }, [log, selectedDate])

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

      {/* 日期选择器 */}
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex items-center gap-3">
          <div className="text-sm font-semibold text-foreground">逐日选股明细</div>
          <select
            value={selectedDate || (dates[0] ?? '')}
            onChange={e => setSelectedDate(e.target.value)}
            className="h-8 rounded-lg border border-border bg-base px-2 text-xs text-foreground focus:outline-none focus:border-accent/50"
          >
            {dates.map(d => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
        </div>

        {dayData && (
          <div className="flex flex-col gap-2">
            {/* 日期摘要 */}
            <div className="flex items-center gap-4 text-xs text-muted">
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
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-muted">
                    <th className="py-2 pr-3 text-left font-normal">排名</th>
                    <th className="py-2 pr-3 text-left font-normal">代码</th>
                    <th className="py-2 pr-3 text-left font-normal">名称</th>
                    <th className="py-2 pr-3 text-right font-normal">评分</th>
                    <th className="py-2 pr-3 text-center font-normal">状态</th>
                    <th className="py-2 pr-3 text-left font-normal">原因</th>
                  </tr>
                </thead>
                <tbody>
                  {dayData.candidates.map((c, i) => (
                    <tr
                      key={`${c.symbol}-${i}`}
                      className="border-b border-border/50 hover:bg-base/50"
                    >
                      <td className="py-2 pr-3 font-mono text-muted">
                        {c.rank ?? '-'}
                      </td>
                      <td className="py-2 pr-3 font-mono text-foreground">{c.symbol}</td>
                      <td className="py-2 pr-3 text-secondary">{c.name || c.symbol}</td>
                      <td className="py-2 pr-3 text-right font-mono text-foreground">
                        {c.score != null ? c.score.toFixed(2) : '-'}
                      </td>
                      <td className="py-2 pr-3 text-center">
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
                      <td className="py-2 pr-3 text-muted">
                        {c.reason ? (REASON_LABELS[c.reason] ?? c.reason) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
