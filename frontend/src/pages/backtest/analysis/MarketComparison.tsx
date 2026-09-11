import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function MarketComparison({ data }: { data: BacktestData }) {
  const ec = data.equityCurve
  if (ec.length === 0) return <div className="text-muted">暂无净值数据</div>

  // Check if benchmark data exists (non-zero values)
  const hasBenchmark = ec.some(p => p.benchmark > 0)
  const firstBenchmark = hasBenchmark ? (ec.find(p => p.benchmark > 0)?.benchmark || 1) : 0

  // Normalize both to 100 at start
  const strategyNorm = ec.map(p => (p.equity / ec[0].equity) * 100)
  const benchmarkNorm = hasBenchmark
    ? ec.map(p => firstBenchmark > 0 ? (p.benchmark / firstBenchmark) * 100 : 100)
    : []
  const dates = ec.map(p => p.date)

  // Excess return
  const excess = hasBenchmark
    ? strategyNorm.map((v, i) => v - (benchmarkNorm[i] || 100))
    : strategyNorm.map(v => v - 100)

  // Strategy drawdown
  const strategyDd = ec.map(p => p.drawdown * 100)

  // Benchmark drawdown (compute from benchmark series)
  let bPeak = firstBenchmark
  const benchmarkDd = hasBenchmark
    ? ec.map(p => {
        if (p.benchmark > bPeak) bPeak = p.benchmark
        return bPeak > 0 ? (p.benchmark / bPeak - 1) * 100 : 0
      })
    : []

  // Normalized dual-axis comparison
  const compareSeries: any[] = [
    {
      name: '策略净值',
      type: 'line',
      data: strategyNorm.map(v => +v.toFixed(2)),
      showSymbol: false,
      lineStyle: { width: 2, color: chartColors.purple },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: 'rgba(168,85,247,0.1)' }, { offset: 1, color: 'rgba(168,85,247,0)' },
      ]}},
    },
  ]
  if (hasBenchmark) {
    compareSeries.push({
      name: '上证指数',
      type: 'line',
      data: benchmarkNorm.map((v: number) => +v.toFixed(2)),
      showSymbol: false,
      lineStyle: { width: 1.5, color: chartColors.cyan, type: 'dashed' },
    })
  }

  const compareOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: hasBenchmark ? ['策略净值', '上证指数'] : ['策略净值'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '6%', right: '5%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', name: '归一化(=100)', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text }, scale: true },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: compareSeries,
  }

  // Excess return area
  const excessOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => `${params[0].axisValue}<br/>超额收益: ${params[0].data >= 0 ? '+' : ''}${params[0].data.toFixed(2)}%`,
    },
    grid: { left: '6%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', name: '超额(%)', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [{
      type: 'line',
      data: excess.map(v => +v.toFixed(2)),
      showSymbol: false,
      lineStyle: { width: 1.5, color: chartColors.profit },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
            { offset: 0, color: 'rgba(239,68,68,0.2)' },
            { offset: 1, color: 'rgba(239,68,68,0)' },
          ],
        },
      },
      markLine: { data: [{ yAxis: 0, lineStyle: { color: chartColors.gray, type: 'dashed' } }], silent: true },
    }],
  }

  // Drawdown comparison
  const ddSeries: any[] = [
    {
      name: '策略回撤',
      type: 'line',
      data: strategyDd.map(v => +v.toFixed(2)),
      showSymbol: false,
      lineStyle: { width: 1.5, color: chartColors.loss },
      areaStyle: { color: 'rgba(34,197,94,0.1)' },
    },
  ]
  if (hasBenchmark) {
    ddSeries.push({
      name: '基准回撤',
      type: 'line',
      data: benchmarkDd.map((v: number) => +v.toFixed(2)),
      showSymbol: false,
      lineStyle: { width: 1, color: chartColors.gray, type: 'dashed' },
    })
  }

  const ddCompareOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: hasBenchmark ? ['策略回撤', '基准回撤'] : ['策略回撤'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '6%', right: '5%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: '{value}%' }, max: 0 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: ddSeries,
  }

  // Summary stats
  const strategyReturn = strategyNorm[strategyNorm.length - 1] - 100
  const benchmarkReturn = hasBenchmark ? (benchmarkNorm[benchmarkNorm.length - 1] - 100) : 0
  const totalExcess = strategyReturn - benchmarkReturn
  const strategyMaxDd = Math.min(...strategyDd)
  const benchmarkMaxDd = hasBenchmark ? Math.min(...benchmarkDd) : 0
  const ddRatio = benchmarkMaxDd !== 0 ? strategyMaxDd / benchmarkMaxDd : 0
  const calmarRatio = strategyMaxDd < 0 ? (strategyReturn / 100) / Math.abs(strategyMaxDd / 100) : 0

  // Rolling correlation (30-day window between strategy and benchmark daily returns)
  const window = 30
  const rollingCorr: (number | null)[] = hasBenchmark ? ec.map((_, i) => {
    if (i < window) return null
    const sRets: number[] = []
    const bRets: number[] = []
    for (let j = i - window + 1; j <= i; j++) {
      sRets.push((ec[j].equity / ec[j - 1].equity) - 1)
      if (ec[j - 1].benchmark > 0) {
        bRets.push((ec[j].benchmark / ec[j - 1].benchmark) - 1)
      } else {
        bRets.push(0)
      }
    }
    const sMean = sRets.reduce((s, v) => s + v, 0) / sRets.length
    const bMean = bRets.reduce((s, v) => s + v, 0) / bRets.length
    const cov = sRets.reduce((s, v, k) => s + (v - sMean) * (bRets[k] - bMean), 0) / sRets.length
    const sStd = Math.sqrt(sRets.reduce((s, v) => s + (v - sMean) ** 2, 0) / sRets.length)
    const bStd = Math.sqrt(bRets.reduce((s, v) => s + (v - bMean) ** 2, 0) / bRets.length)
    return sStd > 0 && bStd > 0 ? cov / (sStd * bStd) : 0
  }) : []

  const corrOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '6%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', min: -1, max: 1, axisLabel: { color: chartColors.text } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [{
      type: 'line',
      data: rollingCorr,
      showSymbol: false,
      lineStyle: { width: 1.5, color: chartColors.cyan },
    }],
  }

  const cards = [
    { label: '策略收益', value: `${strategyReturn >= 0 ? '+' : ''}${strategyReturn.toFixed(2)}%`, accent: strategyReturn >= 0 ? 'text-red-500' : 'text-green-500' },
    { label: '基准收益', value: hasBenchmark ? `${benchmarkReturn >= 0 ? '+' : ''}${benchmarkReturn.toFixed(2)}%` : '无数据', accent: hasBenchmark ? (benchmarkReturn >= 0 ? 'text-red-500' : 'text-green-500') : 'text-muted' },
    { label: '超额收益', value: hasBenchmark ? `${totalExcess >= 0 ? '+' : ''}${totalExcess.toFixed(2)}%` : '—', accent: hasBenchmark ? (totalExcess >= 0 ? 'text-red-500' : 'text-green-500') : 'text-muted' },
    { label: '策略最大回撤', value: `${strategyMaxDd.toFixed(2)}%`, accent: 'text-green-500' },
    { label: '基准最大回撤', value: hasBenchmark ? `${benchmarkMaxDd.toFixed(2)}%` : '无数据', accent: 'text-muted' },
    { label: '回撤比(策略/基准)', value: hasBenchmark ? ddRatio.toFixed(2) : '—', accent: hasBenchmark ? (ddRatio < 1 ? 'text-red-500' : 'text-orange-500') : 'text-muted' },
    { label: 'Calmar比率', value: calmarRatio.toFixed(2), accent: 'text-blue-500' },
    { label: '收益回撤比', value: strategyMaxDd < 0 ? (strategyReturn / Math.abs(strategyMaxDd)).toFixed(2) : '-', accent: 'text-purple-500' },
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
        <div className="mb-2 text-sm font-semibold text-foreground">策略净值 vs 上证指数（归一化至100）</div>
        <div className="h-80"><Chart option={compareOption} /></div>
        {!hasBenchmark && <p className="mt-2 text-xs text-muted">CSV中未包含基准(上证)数据，仅显示策略净值。请更新回测导出代码以包含benchmark字段。</p>}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">超额收益曲线（策略 - 基准）</div>
        <div className="h-56"><Chart option={excessOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">回撤对比</div>
          <div className="h-64"><Chart option={ddCompareOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">滚动相关性（30日窗口）</div>
          <div className="h-64"><Chart option={corrOption} /></div>
          <p className="mt-2 text-xs text-muted">高相关性说明策略收益受市场涨跌驱动；低相关性说明策略有独立Alpha。</p>
        </div>
      </div>
    </div>
  )
}
