import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'

export function EquityCurve({ data }: { data: BacktestData }) {
  const dates = data.equityCurve.map(p => p.date)
  const equity = data.equityCurve.map(p => p.equity)
  const drawdown = data.equityCurve.map(p => p.drawdown * 100)
  const benchmark = data.equityCurve.map(p => p.benchmark)

  // Total return rate curve
  const initialEquity = equity[0] || 1
  const totalReturn = equity.map(v => ((v / initialEquity) - 1) * 100)

  // Benchmark return rate (normalized to start at 0%)
  const initialBenchmark = benchmark[0] || 0
  const hasBenchmark = initialBenchmark > 0 && benchmark.some(v => v > 0)
  const benchmarkReturn = hasBenchmark
    ? benchmark.map(v => ((v / initialBenchmark) - 1) * 100)
    : []

  // Find max drawdown point
  let maxDdIdx = 0
  for (let i = 1; i < drawdown.length; i++) {
    if (drawdown[i] < drawdown[maxDdIdx]) maxDdIdx = i
  }
  const maxDdValue = drawdown[maxDdIdx]

  const seriesList: any[] = [
    {
      name: '净值', type: 'line', data: equity, xAxisIndex: 0, yAxisIndex: 0,
      showSymbol: false, lineStyle: { width: 2, color: chartColors.purple },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: 'rgba(168,85,247,0.15)' }, { offset: 1, color: 'rgba(168,85,247,0)' }
      ]}},
    },
    {
      name: '总收益率', type: 'line', data: totalReturn.map(v => +v.toFixed(2)), xAxisIndex: 0, yAxisIndex: 1,
      showSymbol: false, lineStyle: { width: 2, color: chartColors.profit },
    },
  ]

  if (hasBenchmark) {
    seriesList.push({
      name: '基准收益率', type: 'line', data: benchmarkReturn.map((v: number) => +v.toFixed(2)), xAxisIndex: 0, yAxisIndex: 1,
      showSymbol: false, lineStyle: { width: 1, color: chartColors.gray, type: 'dashed' },
    })
  }

  seriesList.push({
    name: '回撤', type: 'line', data: drawdown.map(v => +v.toFixed(2)), xAxisIndex: 1, yAxisIndex: 2,
    showSymbol: false, lineStyle: { width: 1, color: chartColors.loss },
    areaStyle: { color: 'rgba(34,197,94,0.15)' },
    markPoint: {
      data: [
        { coord: [maxDdIdx, maxDdValue], name: '最大回撤',
          itemStyle: { color: chartColors.loss },
          label: { formatter: `最大回撤\n${maxDdValue.toFixed(1)}%`, color: '#fff', fontSize: 10 } },
      ],
      symbolSize: 50,
    },
  })

  const option: EChartsOption = {
    legend: { data: hasBenchmark ? ['净值', '总收益率', '基准收益率', '回撤'] : ['净值', '总收益率', '回撤'], textStyle: { color: chartColors.text }, top: 0 },
    grid: [{ left: '8%', right: '8%', top: '10%', bottom: '28%' }, { left: '8%', right: '8%', top: '78%', bottom: '14%' }],
    xAxis: [
      { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false } },
      { type: 'category', data: dates, gridIndex: 1, axisLabel: { color: chartColors.text, fontSize: 10 } },
    ],
    yAxis: [
      { type: 'value', gridIndex: 0, scale: true, name: '净值', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
      { type: 'value', gridIndex: 0, scale: true, name: '收益率', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' }, splitLine: { show: false } },
      { type: 'value', gridIndex: 1, name: '回撤', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' }, max: 0 },
    ],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        if (!params || params.length === 0) return ''
        let s = params[0].axisValueLabel + '<br/>'
        for (const p of params) {
          const val = typeof p.value === 'number' ? p.value.toFixed(2) : p.value
          const suffix = (p.seriesName === '净值') ? '' : '%'
          s += `${p.marker} ${p.seriesName}: ${val}${suffix}<br/>`
        }
        return s
      },
    },
    dataZoom: [{ type: 'inside', xAxisIndex: [0, 1] }, { type: 'slider', xAxisIndex: [0, 1], bottom: 2, height: 16 }],
    series: seriesList,
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 text-sm font-semibold text-foreground">净值曲线与回撤</div>
      <div className="h-[600px]"><Chart option={option} /></div>
      <div className="mt-2 flex flex-wrap gap-4 text-xs text-muted">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded bg-purple-500" />策略净值</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded" style={{ background: chartColors.profit }} />总收益率</span>
        {hasBenchmark && <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded bg-gray-500" />基准(上证)收益率</span>}
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded" style={{ background: chartColors.loss }} />回撤</span>
        {!hasBenchmark && <span className="text-muted">（CSV中无基准数据）</span>}
      </div>
    </div>
  )
}
