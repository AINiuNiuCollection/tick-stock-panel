import { useState } from 'react'
import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'

type Dimension = 'pnlPct' | 'duration' | 'entryPrice' | 'exitPrice' | 'entryScore' | 'pnlAmount'

const DIM_OPTIONS: { value: Dimension; label: string; format: (v: number) => string }[] = [
  { value: 'pnlPct', label: '收益率', format: v => `${(v * 100).toFixed(2)}%` },
  { value: 'duration', label: '持仓天数', format: v => `${v}天` },
  { value: 'entryPrice', label: '买入价', format: v => v.toFixed(2) },
  { value: 'exitPrice', label: '卖出价', format: v => v.toFixed(2) },
  { value: 'entryScore', label: '评分', format: v => v?.toFixed(1) ?? '-' },
  { value: 'pnlAmount', label: '盈亏额', format: v => v.toLocaleString(undefined, { maximumFractionDigits: 0 }) },
]

export function ScatterMatrix({ data }: { data: BacktestData }) {
  const [xDim, setXDim] = useState<Dimension>('duration')
  const [yDim, setYDim] = useState<Dimension>('pnlPct')

  const validDims = data.hasScore
    ? DIM_OPTIONS
    : DIM_OPTIONS.filter(d => d.value !== 'entryScore')

  const getValue = (t: any, dim: Dimension): number => {
    if (dim === 'entryScore' && t.entryScore == null) return NaN
    return t[dim]
  }

  const scatterData = data.trades
    .filter(t => !isNaN(getValue(t, xDim)) && !isNaN(getValue(t, yDim)))
    .map(t => [getValue(t, xDim), getValue(t, yDim), t.symbol, t.name, t.pnlPct > 0])

  const xFmt = DIM_OPTIONS.find(d => d.value === xDim)!
  const yFmt = DIM_OPTIONS.find(d => d.value === yDim)!

  const option: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => {
        const d = p.data
        return `${d[2]} (${d[3]})<br/>${xFmt.label}: ${xFmt.format(d[0])}<br/>${yFmt.label}: ${yFmt.format(d[1])}<br/>${d[4] ? '盈利' : '亏损'}`
      },
    },
    grid: { left: '10%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'value', name: xFmt.label, nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', name: yFmt.label, nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: yDim === 'pnlPct' ? '{value}%' : '{value}' } },
    series: [{
      type: 'scatter',
      data: scatterData as any,
      symbolSize: (val: any) => Math.max(6, Math.min(25, Math.abs(val[1]) * 5 + 6)),
      itemStyle: {
        color: ((p: any) => p.data[4] ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)') as any,
        borderColor: ((p: any) => p.data[4] ? chartColors.profit : chartColors.loss) as any,
      },
    }],
  }

  // Correlation matrix
  const corrDims = validDims.map(d => d.value)
  const corrMatrix = corrDims.map(dim1 => {
    return corrDims.map(dim2 => {
      const pairs = data.trades
        .map(t => [getValue(t, dim1), getValue(t, dim2)])
        .filter(([a, b]) => !isNaN(a) && !isNaN(b))
      if (pairs.length < 3) return 0
      const n = pairs.length
      const mean1 = pairs.reduce((s, p) => s + p[0], 0) / n
      const mean2 = pairs.reduce((s, p) => s + p[1], 0) / n
      const cov = pairs.reduce((s, p) => s + (p[0] - mean1) * (p[1] - mean2), 0) / n
      const std1 = Math.sqrt(pairs.reduce((s, p) => s + (p[0] - mean1) ** 2, 0) / n)
      const std2 = Math.sqrt(pairs.reduce((s, p) => s + (p[1] - mean2) ** 2, 0) / n)
      return std1 > 0 && std2 > 0 ? cov / (std1 * std2) : 0
    })
  })

  const corrOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => `${validDims[p.data[1]].label} vs ${validDims[p.data[0]].label}<br/>相关系数: ${p.data[2].toFixed(3)}`,
    },
    grid: { left: '15%', right: '10%', top: '8%', bottom: '18%' },
    xAxis: { type: 'category', data: validDims.map(d => d.label), axisLabel: { color: chartColors.text, fontSize: 10, rotate: 30 } },
    yAxis: { type: 'category', data: validDims.map(d => d.label), axisLabel: { color: chartColors.text, fontSize: 10 } },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 2,
      textStyle: { color: chartColors.text },
      inRange: { color: [chartColors.loss, '#27272a', chartColors.profit] },
    },
    series: [{
      type: 'heatmap',
      data: corrMatrix.flatMap((row, i) => row.map((v, j) => [j, i, +v.toFixed(3)])),
      label: { show: true, formatter: (p: any) => p.data[2].toFixed(2), color: '#fff', fontSize: 9 },
    }],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <span className="text-sm font-semibold text-foreground">散点图维度选择</span>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">X轴:</span>
            <select value={xDim} onChange={e => setXDim(e.target.value as Dimension)}
              className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground">
              {validDims.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted">Y轴:</span>
            <select value={yDim} onChange={e => setYDim(e.target.value as Dimension)}
              className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground">
              {validDims.map(d => <option key={d.value} value={d.value}>{d.label}</option>)}
            </select>
          </div>
          <span className="ml-auto text-xs text-muted">红=盈利 · 绿=亏损 · 点大小∝|Y值|</span>
        </div>
        <div className="h-96"><Chart option={option} /></div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">相关系数矩阵</div>
        <div className="h-96"><Chart option={corrOption} /></div>
        <p className="mt-2 text-xs text-muted">红色=正相关，绿色=负相关，深色=弱相关。关注收益率行/列与其他维度的关联强度。</p>
      </div>
    </div>
  )
}
