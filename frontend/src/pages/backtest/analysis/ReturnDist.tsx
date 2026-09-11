import { useMemo } from 'react'
import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function ReturnDist({ data }: { data: BacktestData }) {
  const pnls = data.trades.map(t => t.pnlPct * 100)

  const stats = useMemo(() => {
    if (pnls.length === 0) return null
    const sorted = [...pnls].sort((a, b) => a - b)
    const sum = pnls.reduce((s, v) => s + v, 0)
    const mean = sum / pnls.length
    const variance = pnls.reduce((s, v) => s + (v - mean) ** 2, 0) / pnls.length
    const std = Math.sqrt(variance)
    const pct = (p: number) => sorted[Math.min(Math.floor(p * sorted.length), sorted.length - 1)]
    return {
      mean,
      std,
      min: sorted[0],
      max: sorted[sorted.length - 1],
      median: pct(0.5),
      q1: pct(0.25),
      q3: pct(0.75),
      skew: std > 0 ? (mean - pct(0.5)) / std : 0,
      kurtosis: std > 0 ? pnls.reduce((s, v) => s + ((v - mean) / std) ** 4, 0) / pnls.length - 3 : 0,
    }
  }, [pnls])

  // Histogram
  const binSize = 5 // 5% bins
  const binStart = Math.floor(Math.min(...pnls, -20) / binSize) * binSize
  const binEnd = Math.ceil(Math.max(...pnls, 20) / binSize) * binSize
  const bins: { range: string; count: number; start: number }[] = []
  for (let b = binStart; b < binEnd; b += binSize) {
    const count = pnls.filter(v => v >= b && v < b + binSize).length
    bins.push({ range: `${b}%~${b + binSize}%`, count, start: b })
  }

  const histOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: bins.map(b => `${b.start}%`),
      axisLabel: { color: chartColors.text, fontSize: 12, fontWeight: 'bold', interval: 0 },
      name: '收益率',
      nameTextStyle: { color: chartColors.text, fontSize: 12 },
    },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [{
      type: 'bar',
      data: bins.map(b => ({
        value: b.count,
        itemStyle: { color: b.start >= 0 ? chartColors.profit : chartColors.loss },
      })),
      label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 },
      barWidth: '90%',
    }],
  }

  // Box plot by win/loss
  const winPnls = pnls.filter(v => v > 0)
  const lossPnls = pnls.filter(v => v <= 0)
  const boxData = (arr: number[]) => {
    if (arr.length === 0) return [0, 0, 0, 0, 0]
    const sorted = [...arr].sort((a, b) => a - b)
    const q = (p: number) => sorted[Math.min(Math.floor(p * sorted.length), sorted.length - 1)]
    return [sorted[0], q(0.25), q(0.5), q(0.75), sorted[sorted.length - 1]]
  }

  const boxOption: EChartsOption = {
    tooltip: { trigger: 'item', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '10%', right: '8%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: ['全部', '盈利', '亏损'], axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'boxplot',
      data: [boxData(pnls), boxData(winPnls), boxData(lossPnls)],
      itemStyle: { color: 'rgba(168,85,247,0.3)', borderColor: chartColors.purple },
    }],
  }

  if (!stats) return <div className="text-muted">暂无数据</div>

  // Market vs Return rate dual-axis chart
  const ec = data.equityCurve
  const hasBenchmark = ec.some(p => p.benchmark > 0)
  const initialEquity = ec[0]?.equity || 1
  const initialBenchmark = ec[0]?.benchmark || 0
  const marketVsReturnOption: EChartsOption | null = hasBenchmark && initialBenchmark > 0 ? {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const date = params[0]?.axisValue ?? ''
        const mkt = params.find((p: any) => p.seriesName === '上证指数')?.data?.[1] ?? 0
        const ret = params.find((p: any) => p.seriesName === '策略收益率')?.data?.[1] ?? 0
        const mktRate = ((mkt / initialBenchmark) - 1) * 100
        return `${date}<br/>上证指数: <span style="color:${chartColors.blue}">${mkt.toFixed(2)}</span> (${mktRate >= 0 ? '+' : ''}${mktRate.toFixed(2)}%)<br/>策略收益: <span style="color:${chartColors.profit}">${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%</span>`
      },
    },
    legend: { data: ['上证指数', '策略收益率'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '10%', right: '10%', top: '12%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: ec.map(p => p.date),
      axisLabel: { color: chartColors.text, fontSize: 10, rotate: 30 },
    },
    yAxis: [
      {
        type: 'value',
        name: '上证指数',
        scale: true,
        axisLabel: { color: chartColors.blue, formatter: '{value}' },
        splitLine: { lineStyle: { color: 'rgba(59,130,246,0.08)' } },
      },
      {
        type: 'value',
        name: '收益率',
        axisLabel: { color: chartColors.profit, formatter: '{value}%' },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '上证指数',
        type: 'line',
        yAxisIndex: 0,
        data: ec.map(p => [p.date, p.benchmark]),
        showSymbol: false,
        lineStyle: { width: 1.5, color: chartColors.blue },
        itemStyle: { color: chartColors.blue },
        emphasis: { focus: 'series' },
      },
      {
        name: '策略收益率',
        type: 'line',
        yAxisIndex: 1,
        data: ec.map(p => [p.date, +(((p.equity / initialEquity) - 1) * 100).toFixed(2)]),
        showSymbol: false,
        lineStyle: { width: 2, color: chartColors.profit },
        itemStyle: { color: chartColors.profit },
        emphasis: { focus: 'series' },
      },
    ],
  } : null

  const cards = [
    { label: '平均值', value: `${stats.mean >= 0 ? '+' : ''}${stats.mean.toFixed(2)}%`, accent: stats.mean >= 0 ? 'text-red-500' : 'text-green-500' },
    { label: '中位数', value: `${stats.median >= 0 ? '+' : ''}${stats.median.toFixed(2)}%`, accent: stats.median >= 0 ? 'text-red-500' : 'text-green-500' },
    { label: '标准差', value: `${stats.std.toFixed(2)}%`, accent: 'text-blue-500' },
    { label: '偏度', value: stats.skew.toFixed(3), accent: 'text-purple-500' },
    { label: '最大值', value: `+${stats.max.toFixed(2)}%`, accent: 'text-red-500' },
    { label: '最小值', value: `${stats.min.toFixed(2)}%`, accent: 'text-green-500' },
    { label: 'Q1 (25%)', value: `${stats.q1.toFixed(2)}%`, accent: 'text-muted' },
    { label: 'Q3 (75%)', value: `${stats.q3.toFixed(2)}%`, accent: 'text-muted' },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-8">
        {cards.map(c => (
          <div key={c.label} className="rounded-xl border border-border bg-surface p-3">
            <div className="text-xs text-muted">{c.label}</div>
            <div className={cn('mt-1 text-lg font-bold tabular-nums', c.accent)}>{c.value}</div>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">收益率直方图（{binSize}%区间）</div>
        <div className="h-72"><Chart option={histOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">箱线图对比</div>
          <div className="h-64"><Chart option={boxOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">分布解读</div>
          <div className="space-y-2 text-sm text-muted">
            <p>平均收益 <span className={stats.mean >= 0 ? 'text-red-500' : 'text-green-500'}>{stats.mean.toFixed(2)}%</span>，中位数 <span className={stats.median >= 0 ? 'text-red-500' : 'text-green-500'}>{stats.median.toFixed(2)}%</span>。</p>
            <p>偏度 {stats.skew.toFixed(3)} {stats.skew > 0 ? '（右偏，少数大赢拉高均值）' : stats.skew < 0 ? '（左偏，少数大亏拖累均值）' : '（对称分布）'}。</p>
            <p>收益区间 [{stats.min.toFixed(2)}%, +{stats.max.toFixed(2)}%]，标准差 {stats.std.toFixed(2)}%。</p>
            <p>四分位距 (IQR): [{stats.q1.toFixed(2)}%, {stats.q3.toFixed(2)}%]，中间50%交易落于此区间。</p>
            <p>峰度 {stats.kurtosis.toFixed(3)} {stats.kurtosis > 0 ? '（厚尾，极端收益比正态分布更频繁）' : '（薄尾，收益集中 near 均值）'}。</p>
          </div>
        </div>
      </div>

      {marketVsReturnOption && (
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">收益与大盘走势关系图</div>
          <div className="h-80"><Chart option={marketVsReturnOption} /></div>
          <p className="mt-2 text-xs text-muted">左轴（蓝）为上证指数收盘点位，右轴（红）为策略累计收益率。两线分离度越大，策略与大盘相关性越低。</p>
        </div>
      )}
    </div>
  )
}
