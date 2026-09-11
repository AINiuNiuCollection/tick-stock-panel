import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function StreakAnalysis({ data }: { data: BacktestData }) {
  const trades = data.trades

  // Build streaks
  interface Streak { type: 'win' | 'loss'; length: number; totalPnl: number; trades: typeof trades }
  const streaks: Streak[] = []
  let current: Streak | null = null
  for (const t of trades) {
    const type = t.pnlPct > 0 ? 'win' : 'loss'
    if (!current || current.type !== type) {
      if (current) streaks.push(current)
      current = { type, length: 0, totalPnl: 0, trades: [] }
    }
    current.length++
    current.totalPnl += t.pnlAmount
    current.trades.push(t)
  }
  if (current) streaks.push(current)

  const winStreaks = streaks.filter(s => s.type === 'win')
  const lossStreaks = streaks.filter(s => s.type === 'loss')
  const maxWinStreak = winStreaks.length > 0 ? Math.max(...winStreaks.map(s => s.length)) : 0
  const maxLossStreak = lossStreaks.length > 0 ? Math.max(...lossStreaks.map(s => s.length)) : 0
  const avgWinStreak = winStreaks.length > 0 ? winStreaks.reduce((s, st) => s + st.length, 0) / winStreaks.length : 0
  const avgLossStreak = lossStreaks.length > 0 ? lossStreaks.reduce((s, st) => s + st.length, 0) / lossStreaks.length : 0

  // Streak bar chart
  const fmtDate = (d: string) => d ? d.slice(5).replace('-', '/') : ''
  const streakOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => {
        const s = streaks[p.dataIndex]
        const startDate = s.trades[0]?.entryDate || ''
        const endDate = s.trades[s.trades.length - 1]?.exitDate || ''
        return `${s.type === 'win' ? '连胜' : '连败'} ${s.length}笔<br/>${startDate} ~ ${endDate}<br/>累计盈亏: ${s.totalPnl >= 0 ? '+' : ''}${s.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      },
    },
    grid: { left: '3%', right: '3%', top: '8%', bottom: '18%' },
    xAxis: { type: 'category', data: streaks.map(s => `${fmtDate(s.trades[0]?.entryDate || '')}~${fmtDate(s.trades[s.trades.length - 1]?.exitDate || '')}`), axisLabel: { color: chartColors.text, fontSize: 8, rotate: 30, interval: 0 } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [{
      type: 'bar',
      data: streaks.map(s => ({
        value: s.length,
        itemStyle: { color: s.type === 'win' ? chartColors.profit : chartColors.loss },
      })),
      label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 },
      barWidth: '80%',
    }],
  }

  // Cumulative pnl curve
  let cumulative = 0
  const cumData = trades.map(t => { cumulative += t.pnlAmount; return cumulative })
  const cumOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: trades.map((_, i) => `${i + 1}`), axisLabel: { color: chartColors.text, fontSize: 9 } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [{
      type: 'line',
      data: cumData,
      showSymbol: false,
      lineStyle: { width: 2, color: chartColors.purple },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: 'rgba(168,85,247,0.15)' }, { offset: 1, color: 'rgba(168,85,247,0)' },
      ]}},
    }],
  }

  // Streak length distribution
  const maxLen = Math.max(maxWinStreak, maxLossStreak, 1)
  const lenDist: { len: number; wins: number; losses: number }[] = []
  for (let l = 1; l <= maxLen; l++) {
    lenDist.push({
      len: l,
      wins: winStreaks.filter(s => s.length === l).length,
      losses: lossStreaks.filter(s => s.length === l).length,
    })
  }
  const distOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['连胜次数', '连败次数'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '5%', top: '12%', bottom: '12%' },
    xAxis: { type: 'category', data: lenDist.map(d => `${d.len}笔`), axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [
      { name: '连胜次数', type: 'bar', data: lenDist.map(d => d.wins), itemStyle: { color: chartColors.profit }, label: { show: true, position: 'inside', color: '#fff', fontSize: 10 } },
      { name: '连败次数', type: 'bar', data: lenDist.map(d => d.losses), itemStyle: { color: chartColors.loss }, label: { show: true, position: 'inside', color: '#fff', fontSize: 10 } },
    ],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">最大连胜</div>
          <div className="mt-1 text-2xl font-bold text-red-500">{maxWinStreak} 笔</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">最大连败</div>
          <div className="mt-1 text-2xl font-bold text-green-500">{maxLossStreak} 笔</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">平均连胜</div>
          <div className="mt-1 text-2xl font-bold text-red-500">{avgWinStreak.toFixed(1)} 笔</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">平均连败</div>
          <div className="mt-1 text-2xl font-bold text-green-500">{avgLossStreak.toFixed(1)} 笔</div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">连续盈亏序列（红=连胜，绿=连败）</div>
        <div className="h-56"><Chart option={streakOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">累计盈亏曲线（按交易序号）</div>
          <div className="h-56"><Chart option={cumOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">连胜/连败长度分布</div>
          <div className="h-56"><Chart option={distOption} /></div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">类型</th>
              <th className="px-4 py-2 text-center font-bold text-sm">长度</th>
              <th className="px-4 py-2 text-center font-bold text-sm">累计盈亏</th>
              <th className="px-4 py-2 text-center font-bold text-sm">起始交易</th>
              <th className="px-4 py-2 text-center font-bold text-sm">结束交易</th>
            </tr>
          </thead>
          <tbody>
            {streaks.map((s, i) => (
              <tr key={i} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center">
                  <span className={cn('rounded px-1.5 py-0.5 text-xs', s.type === 'win' ? 'bg-red-500/20 text-red-400' : 'bg-green-500/20 text-green-400')}>
                    {s.type === 'win' ? '连胜' : '连败'}
                  </span>
                </td>
                <td className="px-4 py-2 text-center tabular-nums font-medium">{s.length} 笔</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', s.totalPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {s.totalPnl >= 0 ? '+' : ''}{s.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
                <td className="px-4 py-2 text-center text-muted text-xs">{s.trades[0]?.symbol} {s.trades[0]?.entryDate}</td>
                <td className="px-4 py-2 text-center text-muted text-xs">{s.trades[s.trades.length - 1]?.symbol} {s.trades[s.trades.length - 1]?.exitDate}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
