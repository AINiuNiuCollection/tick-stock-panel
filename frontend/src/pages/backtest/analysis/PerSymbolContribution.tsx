import { useMemo, useState } from 'react'
import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function PerSymbolContribution({ data }: { data: BacktestData }) {
  const trades = data.trades
  const totalPnl = trades.reduce((s, t) => s + t.pnlAmount, 0)

  // Aggregate by symbol
  const symbolStats = useMemo(() => {
    const map = new Map<string, { symbol: string; name: string; count: number; totalPnl: number; totalPnlPct: number; wins: number; best: number; worst: number }>()
    for (const t of trades) {
      const key = t.symbol
      if (!map.has(key)) {
        map.set(key, { symbol: t.symbol, name: t.name, count: 0, totalPnl: 0, totalPnlPct: 0, wins: 0, best: -Infinity, worst: Infinity })
      }
      const s = map.get(key)!
      s.count++
      s.totalPnl += t.pnlAmount
      s.totalPnlPct += t.pnlPct
      if (t.pnlPct > 0) s.wins++
      if (t.pnlPct > s.best) s.best = t.pnlPct
      if (t.pnlPct < s.worst) s.worst = t.pnlPct
    }
    return [...map.values()].map(s => ({
      ...s,
      avgPnlPct: s.count > 0 ? s.totalPnlPct / s.count : 0,
      contribution: totalPnl !== 0 ? s.totalPnl / Math.abs(totalPnl) : 0,
      winRate: s.count > 0 ? s.wins / s.count : 0,
    })).sort((a, b) => b.totalPnl - a.totalPnl)
  }, [trades, totalPnl])

  const [showAll, setShowAll] = useState(false)
  const displayed = showAll ? symbolStats : symbolStats.slice(0, 20)

  // Pareto chart: contribution bar + cumulative line (top 30 for readability)
  const paretoSymbols = symbolStats.slice(0, 30)
  let cumPct = 0
  const paretoData = paretoSymbols.map(s => {
    cumPct += Math.abs(s.contribution) * 100
    return { symbol: s.symbol, pnl: s.totalPnl, cumPct }
  })

  const paretoOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['个股盈亏额', '累计占比'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '10%', right: '12%', top: '12%', bottom: '25%' },
    xAxis: {
      type: 'category',
      data: paretoData.map(d => d.symbol),
      axisLabel: { color: chartColors.text, fontSize: 9, rotate: 60, interval: 'auto' },
    },
    yAxis: [
      { type: 'value', name: '盈亏额', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
      { type: 'value', name: '累计%', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' }, max: 100, splitLine: { show: false } },
    ],
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [
      {
        name: '个股盈亏额',
        type: 'bar',
        data: paretoData.map(d => ({
          value: d.pnl,
          itemStyle: { color: d.pnl >= 0 ? chartColors.profit : chartColors.loss },
        })),
        label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 },
      },
      {
        name: '累计占比',
        type: 'line',
        yAxisIndex: 1,
        data: paretoData.map(d => +d.cumPct.toFixed(1)),
        showSymbol: true,
        symbolSize: 4,
        lineStyle: { width: 2, color: chartColors.orange },
        label: { show: true, formatter: '{c}%', color: chartColors.orange, fontSize: 9 },
        markLine: { data: [{ yAxis: 80, lineStyle: { color: chartColors.gray, type: 'dashed' } }], silent: true },
      },
    ],
  }

  // Waterfall chart (top 20 contributions)
  const waterfallData = displayed.map((s, i) => {
    if (i === 0) return { symbol: s.symbol, value: s.totalPnl, base: 0, avgPnlPct: s.avgPnlPct }
    const prevBase = displayed.slice(0, i).reduce((sum, p) => sum + p.totalPnl, 0)
    return { symbol: s.symbol, value: s.totalPnl, base: prevBase, avgPnlPct: s.avgPnlPct }
  })

  const waterfallOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const d = waterfallData[params[0]?.dataIndex]
        if (!d) return ''
        return `${d.symbol}<br/>盈亏额: ${d.value >= 0 ? '+' : ''}${d.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}<br/>平均收益率: ${d.avgPnlPct >= 0 ? '+' : ''}${(d.avgPnlPct * 100).toFixed(2)}%<br/>累计: ${d.base.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
      },
    },
    grid: { left: '10%', right: '5%', top: '8%', bottom: '20%' },
    xAxis: {
      type: 'category',
      data: waterfallData.map(d => d.symbol),
      axisLabel: { color: chartColors.text, fontSize: 9, rotate: 45, interval: 0 },
    },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [
      {
        name: '基础',
        type: 'bar',
        stack: 'wf',
        itemStyle: { borderColor: 'transparent', color: 'transparent' },
        data: waterfallData.map(d => d.base),
        silent: true,
      },
      {
        name: '盈亏额',
        type: 'bar',
        stack: 'wf',
        data: waterfallData.map(d => ({
          value: d.value,
          itemStyle: { color: d.value >= 0 ? chartColors.profit : chartColors.loss },
        })),
        label: { show: true, position: 'top', formatter: (p: any) => {
          const d = waterfallData[p.dataIndex]
          if (!d) return ''
          return `${d.value >= 0 ? '+' : ''}${d.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}\n${d.avgPnlPct >= 0 ? '+' : ''}${(d.avgPnlPct * 100).toFixed(1)}%`
        }, color: chartColors.text, fontSize: 9 },
      },
    ],
  }

  // Top 5 positive and top 5 negative
  const topPositive = symbolStats.filter(s => s.totalPnl > 0).slice(0, 5)
  const topNegative = symbolStats.filter(s => s.totalPnl < 0).reverse().slice(0, 5)

  const rankOption = (stats: typeof topPositive, color: string, title: string): EChartsOption => ({
    title: { text: title, left: 'center', textStyle: { color: chartColors.text, fontSize: 13 } },
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '15%', right: '10%', top: '15%', bottom: '8%' },
    xAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    yAxis: { type: 'category', data: stats.map(s => s.symbol).reverse(), axisLabel: { color: chartColors.text, fontSize: 11 } },
    series: [{
      type: 'bar',
      data: stats.map(s => s.totalPnl).reverse(),
      itemStyle: { color },
      label: { show: true, position: 'right', formatter: (p: any) => `${p.value >= 0 ? '+' : ''}${p.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`, color: chartColors.text, fontSize: 10 },
      barWidth: '60%',
    }],
  })

  // Scatter: nTrades vs avgPnl (high frequency low efficiency)
  const scatterOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => `${p.data[2]}<br/>交易${p.data[0]}次 · 盈亏${p.data[1] >= 0 ? '+' : ''}${p.data[1].toLocaleString(undefined, { maximumFractionDigits: 0 })}<br/>胜率${(p.data[3] * 100).toFixed(0)}%`,
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'value', name: '交易次数', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', name: '总盈亏', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
    series: [{
      type: 'scatter',
      data: symbolStats.map(s => [s.count, s.totalPnl, s.symbol, s.winRate]),
      symbolSize: (val: any) => Math.max(8, val[0] * 3),
      itemStyle: {
        color: ((p: any) => p.data[1] >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)') as any,
        borderColor: ((p: any) => p.data[1] >= 0 ? chartColors.profit : chartColors.loss) as any,
      },
    }],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">个股贡献率帕累托图</div>
        <div className="h-80"><Chart option={paretoOption} /></div>
        <p className="mt-2 text-xs text-muted">柱状为个股盈亏额，折线为累计贡献占比，虚线为80%阈值</p>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">盈亏瀑布图（Top {displayed.length}）</div>
        <div className="h-72"><Chart option={waterfallOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="h-56"><Chart option={rankOption(topPositive, chartColors.profit, '贡献最大 Top 5')} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="h-56"><Chart option={rankOption(topNegative, chartColors.loss, '拖累最大 Top 5')} /></div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">交易频次 vs 贡献额（点大小=交易次数）</div>
        <div className="h-64"><Chart option={scatterOption} /></div>
        <p className="mt-2 text-xs text-muted">高频低效个股位于右上角（次数多但亏损），高频高效位于左上角</p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">代码</th>
              <th className="px-4 py-2 text-center font-bold text-sm">名称</th>
              <th className="px-4 py-2 text-center font-bold text-sm">交易次数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">胜率</th>
              <th className="px-4 py-2 text-center font-bold text-sm">总盈亏</th>
              <th className="px-4 py-2 text-center font-bold text-sm">贡献占比</th>
              <th className="px-4 py-2 text-center font-bold text-sm">最佳</th>
              <th className="px-4 py-2 text-center font-bold text-sm">最差</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map(s => (
              <tr key={s.symbol} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center font-mono text-xs text-foreground">{s.symbol}</td>
                <td className="px-4 py-2 text-center text-foreground">{s.name}</td>
                <td className="px-4 py-2 text-center tabular-nums">{s.count}</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', s.winRate >= 0.5 ? 'text-red-500' : 'text-green-500')}>
                  {(s.winRate * 100).toFixed(0)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums font-medium', s.totalPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {s.totalPnl >= 0 ? '+' : ''}{s.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
                <td className="px-4 py-2 text-center tabular-nums text-muted">
                  {(Math.abs(s.contribution) * 100).toFixed(1)}%
                </td>
                <td className="px-4 py-2 text-center tabular-nums text-red-500">+{(s.best * 100).toFixed(1)}%</td>
                <td className="px-4 py-2 text-center tabular-nums text-green-500">{(s.worst * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {symbolStats.length > 20 && (
          <div className="border-t border-border/50 p-2 text-center">
            <button onClick={() => setShowAll(!showAll)} className="text-xs text-primary hover:underline">
              {showAll ? '收起' : `展开全部 ${symbolStats.length} 只`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
