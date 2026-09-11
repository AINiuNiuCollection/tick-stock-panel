import { useState, useMemo } from 'react'
import type { BacktestData, Trade } from './types'
import type { StrategyBacktestTrade } from '@/lib/api'
import { cn } from '@/lib/cn'
import { TradeKlineModal } from '../components/TradeKlineModal'

const REASON_COLORS: Record<string, string> = {
  stop_loss: 'bg-red-500/20 text-red-400',
  trailing_stop: 'bg-blue-500/20 text-blue-400',
  max_hold: 'bg-orange-500/20 text-orange-400',
  end: 'bg-gray-500/20 text-gray-400',
  signal: 'bg-green-500/20 text-green-400',
  take_profit: 'bg-purple-500/20 text-purple-400',
}

/** 将分析页 Trade (camelCase) 转换为 API StrategyBacktestTrade (snake_case)，以复用 TradeKlineModal */
function toApiTrade(t: Trade): StrategyBacktestTrade {
  return {
    symbol: t.symbol,
    name: t.name,
    entry_date: t.entryDate,
    exit_date: t.exitDate,
    entry_price: t.entryPrice,
    exit_price: t.exitPrice,
    pnl_pct: t.pnlPct,
    duration: t.duration,
    exit_reason: t.exitReason,
    shares: t.shares,
    entry_value: t.entryValue,
    exit_value: t.exitValue,
    pnl_amount: t.pnlAmount,
    entry_score: t.entryScore ?? null,
  }
}

export function TradeTable({ data }: { data: BacktestData }) {
  const [reasonFilter, setReasonFilter] = useState('')
  const [winFilter, setWinFilter] = useState('')
  const [search, setSearch] = useState('')
  const [sortBy, setSortBy] = useState<'date' | 'pnl' | 'duration' | 'amount'>('date')
  const [sortDesc, setSortDesc] = useState(true)
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  const reasons = useMemo(() => [...new Set(data.trades.map(t => t.exitReason))], [data.trades])

  const filtered = useMemo(() => {
    let rows = data.trades
    if (reasonFilter) rows = rows.filter(t => t.exitReason === reasonFilter)
    if (winFilter === 'win') rows = rows.filter(t => t.pnlPct > 0)
    if (winFilter === 'loss') rows = rows.filter(t => t.pnlPct <= 0)
    if (search) {
      const q = search.toLowerCase()
      rows = rows.filter(t => t.symbol.toLowerCase().includes(q) || t.name.toLowerCase().includes(q))
    }
    const sorted = [...rows].sort((a, b) => {
      let cmp = 0
      if (sortBy === 'date') cmp = a.entryDate.localeCompare(b.entryDate)
      else if (sortBy === 'pnl') cmp = a.pnlPct - b.pnlPct
      else if (sortBy === 'duration') cmp = a.duration - b.duration
      else if (sortBy === 'amount') cmp = a.pnlAmount - b.pnlAmount
      return sortDesc ? -cmp : cmp
    })
    return sorted
  }, [data.trades, reasonFilter, winFilter, search, sortBy, sortDesc])

  const totalPnl = filtered.reduce((s, t) => s + t.pnlAmount, 0)
  const winCount = filtered.filter(t => t.pnlPct > 0).length

  const sortBtn = (col: typeof sortBy, label: string) => (
    <button
      onClick={() => { if (sortBy === col) setSortDesc(!sortDesc); else { setSortBy(col); setSortDesc(true) } }}
      className="hover:text-foreground"
    >
      {label} {sortBy === col ? (sortDesc ? '↓' : '↑') : ''}
    </button>
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <select value={reasonFilter} onChange={e => setReasonFilter(e.target.value)}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground">
          <option value="">全部退出原因</option>
          {reasons.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
        <select value={winFilter} onChange={e => setWinFilter(e.target.value)}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground">
          <option value="">全部交易</option>
          <option value="win">仅盈利</option>
          <option value="loss">仅亏损</option>
        </select>
        <input placeholder="搜索代码/名称" value={search} onChange={e => setSearch(e.target.value)}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground placeholder:text-muted" />
        <div className="ml-auto text-sm text-muted">
          {filtered.length} 笔 · 胜率 {(winCount / filtered.length * 100).toFixed(1)}% · 总盈亏 {totalPnl >= 0 ? '+' : ''}{totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-3 py-2 text-center font-bold text-sm">代码</th>
              <th className="px-3 py-2 text-center font-bold text-sm">名称</th>
              <th className="px-3 py-2 text-center font-bold text-sm">买入日</th>
              <th className="px-3 py-2 text-center font-bold text-sm">买入价</th>
              <th className="px-3 py-2 text-center font-bold text-sm">卖出日</th>
              <th className="px-3 py-2 text-center font-bold text-sm">卖出价</th>
              <th className="px-3 py-2 text-center font-bold text-sm">{sortBtn('pnl', '收益率')}</th>
              <th className="px-3 py-2 text-center font-bold text-sm">{sortBtn('duration', '持仓天')}</th>
              <th className="px-3 py-2 text-center font-bold text-sm">退出原因</th>
              <th className="px-3 py-2 text-center font-bold text-sm">{sortBtn('amount', '盈亏额')}</th>
              {data.hasScore && <th className="px-3 py-2 text-center font-bold text-sm">评分</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((t: Trade, i) => (
              <tr
                key={i}
                onClick={() => setSelectedTrade(t)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedTrade(t) } }}
                role="button"
                tabIndex={0}
                title="点击查看该笔交易的K线回放"
                className="border-t border-border/50 cursor-pointer hover:bg-surface/70 focus:outline-none focus:bg-surface/70"
              >
                <td className="px-3 py-1.5 text-center font-mono text-xs text-foreground">{t.symbol}</td>
                <td className="px-3 py-1.5 text-center text-foreground">{t.name}</td>
                <td className="px-3 py-1.5 text-center text-muted">{t.entryDate}</td>
                <td className="px-3 py-1.5 text-center tabular-nums">{t.entryPrice.toFixed(2)}</td>
                <td className="px-3 py-1.5 text-center text-muted">{t.exitDate}</td>
                <td className="px-3 py-1.5 text-center tabular-nums">{t.exitPrice.toFixed(2)}</td>
                <td className={cn('px-3 py-1.5 text-center tabular-nums font-medium',
                  t.pnlPct > 0 ? 'text-red-500' : t.pnlPct < 0 ? 'text-green-500' : 'text-muted')}>
                  {t.pnlPct > 0 ? '+' : ''}{(t.pnlPct * 100).toFixed(2)}%
                </td>
                <td className="px-3 py-1.5 text-center tabular-nums text-muted">{t.duration}</td>
                <td className="px-3 py-1.5 text-center">
                  <span className={cn('rounded px-1.5 py-0.5 text-xs', REASON_COLORS[t.exitReason] || 'bg-gray-500/20 text-gray-400')}>
                    {t.exitReason}
                  </span>
                </td>
                <td className={cn('px-3 py-1.5 text-center tabular-nums',
                  t.pnlAmount >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {t.pnlAmount >= 0 ? '+' : ''}{t.pnlAmount.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
                {data.hasScore && <td className="px-3 py-1.5 text-center tabular-nums text-muted">{t.entryScore?.toFixed(1) ?? '-'}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <TradeKlineModal
        trade={selectedTrade ? toApiTrade(selectedTrade) : null}
        onClose={() => setSelectedTrade(null)}
      />
    </div>
  )
}
