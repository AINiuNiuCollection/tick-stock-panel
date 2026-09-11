import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function DurationAnalysis({ data }: { data: BacktestData }) {
  const trades = data.trades

  // Group by duration
  const durationGroups = [...new Set(trades.map(t => t.duration))].sort((a, b) => a - b)
  const groupStats = durationGroups.map(d => {
    const group = trades.filter(t => t.duration === d)
    const wins = group.filter(t => t.pnlPct > 0).length
    const avgPnl = group.reduce((s, t) => s + t.pnlPct, 0) / group.length
    return {
      duration: d,
      count: group.length,
      wins,
      winRate: wins / group.length,
      avgPnl,
      totalPnl: group.reduce((s, t) => s + t.pnlAmount, 0),
    }
  })

  // Scatter: duration vs pnlPct
  const scatterOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => `${p.data[2]} (${p.data[3]})<br/>持仓 ${p.data[0]}天 · ${(p.data[1] * 100).toFixed(2)}%`,
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'value', name: '持仓天数', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', name: '收益率', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'scatter',
      data: trades.map(t => [t.duration, t.pnlPct * 100, t.symbol, t.name]),
      symbolSize: (val: any) => Math.max(6, Math.min(20, Math.abs(val[1]) / 3 + 6)),
      itemStyle: {
        color: ((p: any) => p.data[1] >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)') as any,
        borderColor: ((p: any) => p.data[1] >= 0 ? chartColors.profit : chartColors.loss) as any,
      },
    }],
  }

  // Grouped bar: count + avgPnl
  const barOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['交易笔数', '平均收益'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '8%', top: '12%', bottom: '12%' },
    xAxis: { type: 'category', data: groupStats.map(g => `${g.duration}天`), axisLabel: { color: chartColors.text } },
    yAxis: [
      { type: 'value', name: '笔数', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
      { type: 'value', name: '平均收益', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    ],
    series: [
      { name: '交易笔数', type: 'bar', data: groupStats.map(g => g.count), itemStyle: { color: chartColors.blue }, label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 }, barWidth: '30%' },
      { name: '平均收益', type: 'bar', yAxisIndex: 1, data: groupStats.map(g => +(g.avgPnl * 100).toFixed(2)), itemStyle: { color: chartColors.orange }, label: { show: true, position: 'top', formatter: '{c}%', color: chartColors.text, fontSize: 10 }, barWidth: '30%' },
    ],
  }

  // Box plot by duration
  const boxData = (d: number) => {
    const group = trades.filter(t => t.duration === d).map(t => t.pnlPct * 100).sort((a, b) => a - b)
    if (group.length === 0) return [0, 0, 0, 0, 0]
    const q = (p: number) => group[Math.min(Math.floor(p * group.length), group.length - 1)]
    return [group[0], q(0.25), q(0.5), q(0.75), group[group.length - 1]]
  }
  const boxOption: EChartsOption = {
    tooltip: { trigger: 'item', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: groupStats.map(g => `${g.duration}天`), axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'boxplot',
      data: durationGroups.map(d => boxData(d)),
      itemStyle: { color: 'rgba(59,130,246,0.3)', borderColor: chartColors.blue },
    }],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">持仓天数 vs 收益率散点图</div>
        <div className="h-72"><Chart option={scatterOption} /></div>
        <p className="mt-2 text-xs text-muted">点大小与收益绝对值成正比，红赚绿亏</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">各持仓天数统计</div>
          <div className="h-64"><Chart option={barOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">各持仓天数收益率分布</div>
          <div className="h-64"><Chart option={boxOption} /></div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">持仓天数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">笔数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">占比</th>
              <th className="px-4 py-2 text-center font-bold text-sm">胜率</th>
              <th className="px-4 py-2 text-center font-bold text-sm">平均收益</th>
              <th className="px-4 py-2 text-center font-bold text-sm">总盈亏额</th>
            </tr>
          </thead>
          <tbody>
            {groupStats.map(g => (
              <tr key={g.duration} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center font-medium text-foreground">{g.duration}天</td>
                <td className="px-4 py-2 text-center tabular-nums">{g.count}</td>
                <td className="px-4 py-2 text-center tabular-nums text-muted">{(g.count / trades.length * 100).toFixed(1)}%</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', g.winRate >= 0.5 ? 'text-red-500' : 'text-green-500')}>
                  {(g.winRate * 100).toFixed(1)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', g.avgPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {g.avgPnl >= 0 ? '+' : ''}{(g.avgPnl * 100).toFixed(2)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', g.totalPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {g.totalPnl >= 0 ? '+' : ''}{g.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
