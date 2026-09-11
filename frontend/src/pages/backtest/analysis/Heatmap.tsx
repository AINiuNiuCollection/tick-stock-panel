import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function Heatmap({ data }: { data: BacktestData }) {
  const trades = data.trades

  // Build monthly returns
  const monthlyMap = new Map<string, { year: string; month: number; pnl: number; count: number; wins: number }>()
  for (const t of trades) {
    const d = new Date(t.exitDate)
    const year = String(d.getFullYear())
    const month = d.getMonth() + 1
    const key = `${year}-${month}`
    if (!monthlyMap.has(key)) {
      monthlyMap.set(key, { year, month, pnl: 0, count: 0, wins: 0 })
    }
    const m = monthlyMap.get(key)!
    m.pnl += t.pnlAmount
    m.count++
    if (t.pnlPct > 0) m.wins++
  }

  const years = [...new Set([...monthlyMap.values()].map(m => m.year))].sort()
  const months = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

  // Heatmap data: [monthIdx, yearIdx, value]
  const heatData: [number, number, number][] = []
  const heatPnl: [number, number, number][] = []
  years.forEach((y, yi) => {
    months.forEach((m, mi) => {
      const key = `${y}-${m}`
      const entry = monthlyMap.get(key)
      if (entry) {
        heatData.push([mi, yi, entry.count])
        heatPnl.push([mi, yi, entry.pnl])
      } else {
        heatData.push([mi, yi, 0])
        heatPnl.push([mi, yi, 0])
      }
    })
  })

  const monthLabels = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

  // PnL heatmap
  const maxPnl = Math.max(...heatPnl.map(d => Math.abs(d[2])), 1)
  const pnlHeatOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => {
        const entry = monthlyMap.get(`${years[p.data[1]]}-${p.data[0] + 1}`)
        if (!entry || entry.count === 0) return `${years[p.data[1]]}年${p.data[0] + 1}月<br/>无交易`
        return `${years[p.data[1]]}年${p.data[0] + 1}月<br/>盈亏: ${p.data[2] >= 0 ? '+' : ''}${p.data[2].toLocaleString(undefined, { maximumFractionDigits: 0 })}<br/>交易: ${entry.count}笔 · 胜率${((entry.wins / entry.count) * 100).toFixed(0)}%`
      },
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: monthLabels, axisLabel: { color: chartColors.text }, splitArea: { show: true } },
    yAxis: { type: 'category', data: years, axisLabel: { color: chartColors.text }, splitArea: { show: true } },
    visualMap: {
      min: -maxPnl,
      max: maxPnl,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 2,
      textStyle: { color: chartColors.text },
      inRange: { color: [chartColors.loss, '#27272a', chartColors.profit] },
    },
    series: [{
      type: 'heatmap',
      data: heatPnl,
      label: { show: true, formatter: (p: any) => p.data[2] !== 0 ? (p.data[2] >= 0 ? '+' : '') + (p.data[2] / 1000).toFixed(1) + 'k' : '', color: '#fff', fontSize: 10 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.5)' } },
    }],
  }

  // Trade count heatmap
  const maxCount = Math.max(...heatData.map(d => d[2]), 1)
  const countHeatOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => `${years[p.data[1]]}年${p.data[0] + 1}月<br/>交易 ${p.data[2]} 笔`,
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: monthLabels, axisLabel: { color: chartColors.text }, splitArea: { show: true } },
    yAxis: { type: 'category', data: years, axisLabel: { color: chartColors.text }, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: maxCount,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 2,
      textStyle: { color: chartColors.text },
      inRange: { color: ['#27272a', chartColors.purple] },
    },
    series: [{
      type: 'heatmap',
      data: heatData,
      label: { show: true, formatter: (p: any) => p.data[2] > 0 ? String(p.data[2]) : '', color: '#fff', fontSize: 10 },
    }],
  }

  // Day of week distribution
  const dowLabels = ['周一', '周二', '周三', '周四', '周五']
  const dowStats = dowLabels.map((label, i) => {
    const dayTrades = trades.filter(t => {
      const d = new Date(t.entryDate)
      return d.getDay() === i + 1
    })
    return {
      label,
      count: dayTrades.length,
      avgPnl: dayTrades.length > 0 ? dayTrades.reduce((s, t) => s + t.pnlPct, 0) / dayTrades.length : 0,
    }
  })

  const dowOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['交易笔数', '平均收益'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '8%', top: '12%', bottom: '12%' },
    xAxis: { type: 'category', data: dowLabels, axisLabel: { color: chartColors.text } },
    yAxis: [
      { type: 'value', name: '笔数', axisLabel: { color: chartColors.text } },
      { type: 'value', name: '平均收益', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    ],
    series: [
      { name: '交易笔数', type: 'bar', data: dowStats.map(d => d.count), itemStyle: { color: chartColors.blue }, label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 } },
      { name: '平均收益', type: 'bar', yAxisIndex: 1, data: dowStats.map(d => +(d.avgPnl * 100).toFixed(2)), itemStyle: { color: chartColors.orange }, label: { show: true, position: 'top', formatter: '{c}%', color: chartColors.text, fontSize: 10 } },
    ],
  }

  // Monthly summary table
  const monthlyList = [...monthlyMap.values()].sort((a, b) => {
    return a.year === b.year ? a.month - b.month : a.year.localeCompare(b.year)
  })

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">月度盈亏热力图</div>
        <div className="h-72"><Chart option={pnlHeatOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">月度交易笔数热力图</div>
          <div className="h-64"><Chart option={countHeatOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">买入日星期分布</div>
          <div className="h-64"><Chart option={dowOption} /></div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">年月</th>
              <th className="px-4 py-2 text-center font-bold text-sm">交易笔数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">盈利笔数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">胜率</th>
              <th className="px-4 py-2 text-center font-bold text-sm">月度盈亏</th>
            </tr>
          </thead>
          <tbody>
            {monthlyList.map(m => (
              <tr key={`${m.year}-${m.month}`} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center font-medium text-foreground">{m.year}年{m.month}月</td>
                <td className="px-4 py-2 text-center tabular-nums">{m.count}</td>
                <td className="px-4 py-2 text-center tabular-nums text-red-500">{m.wins}</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', m.wins / m.count >= 0.5 ? 'text-red-500' : 'text-green-500')}>
                  {((m.wins / m.count) * 100).toFixed(0)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums font-medium', m.pnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {m.pnl >= 0 ? '+' : ''}{m.pnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
