/**
 * 交易明细表格 — 对齐 HTML 的 tblwrap (sticky header + 可滚动 + tabular-nums)
 */
import { useMemo, useState } from 'react'
import type { StrategyBacktestTrade } from '@/lib/api'

interface Props {
  trades: StrategyBacktestTrade[]
}

type SortKey = 'seq' | 'entry_date' | 'exit_date' | 'pnl_pct' | 'duration'
type SortDir = 'asc' | 'desc'

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function PanYangTradesTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('seq')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const sorted = useMemo(() => {
    const arr = [...trades]
    arr.sort((a, b) => {
      let av: number | string = 0
      let bv: number | string = 0
      if (sortKey === 'seq') {
        av = a.symbol + a.entry_date
        bv = b.symbol + b.entry_date
      } else if (sortKey === 'entry_date') {
        av = a.entry_date
        bv = b.entry_date
      } else if (sortKey === 'exit_date') {
        av = a.exit_date
        bv = b.exit_date
      } else if (sortKey === 'pnl_pct') {
        av = a.pnl_pct
        bv = b.pnl_pct
      } else if (sortKey === 'duration') {
        av = a.duration
        bv = b.duration
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
    return arr
  }, [trades, sortKey, sortDir])

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const thClass = (key: SortKey) =>
    `cursor-pointer hover:bg-base ${sortKey === key ? 'srt' : ''} ${sortKey === key && sortDir === 'asc' ? 'asc' : ''}`

  return (
    <div className="max-h-[520px] overflow-auto border border-border rounded-btn">
      <table className="w-full text-xs tabular-nums">
        <thead>
          <tr className="bg-base text-muted">
            <th className="text-center px-3 py-1.5 sticky top-0 z-2">#</th>
            <th className="text-left px-2 py-1.5 sticky top-0 z-2">标的</th>
            <th className={thClass('entry_date')} onClick={() => onSort('entry_date')}>买入日</th>
            <th className={thClass('exit_date')} onClick={() => onSort('exit_date')}>卖出日</th>
            <th className={thClass('duration')} onClick={() => onSort('duration')}>持仓天数</th>
            <th className="px-2 py-1.5">买入价</th>
            <th className="px-2 py-1.5">卖出价</th>
            <th className={thClass('pnl_pct')} onClick={() => onSort('pnl_pct')}>收益率</th>
            <th className="px-2 py-1.5">退出原因</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t, i) => {
            const pos = t.pnl_pct >= 0
            return (
              <tr key={`${t.symbol}-${t.entry_date}-${i}`} className="hover:bg-base/50">
                <td className="text-center px-3 py-1 text-muted">{i + 1}</td>
                <td className="text-left px-2 py-1">{t.symbol} {t.name ?? ''}</td>
                <td className="px-2 py-1">{t.entry_date}</td>
                <td className="px-2 py-1">{t.exit_date}</td>
                <td className="px-2 py-1">{t.duration}</td>
                <td className="px-2 py-1">{t.entry_price.toFixed(3)}</td>
                <td className="px-2 py-1">{t.exit_price.toFixed(3)}</td>
                <td className={`px-2 py-1 font-medium ${pos ? 'text-red-500' : 'text-green-500'}`}>
                  {fmtPct(t.pnl_pct)}
                </td>
                <td className="px-2 py-1 text-muted">{t.exit_reason || '—'}</td>
              </tr>
            )
          })}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={9} className="text-center py-6 text-muted">无交易记录</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
