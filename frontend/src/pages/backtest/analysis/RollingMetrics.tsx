import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'

export function RollingMetrics({ data }: { data: BacktestData }) {
  const ec = data.equityCurve
  const windowSize = 20

  // Rolling returns
  const rollingReturns: (number | null)[] = ec.map((_, i) => {
    if (i < windowSize) return null
    const start = ec[i - windowSize].equity
    const end = ec[i].equity
    return ((end / start) - 1) * 100
  })

  // Rolling Sharpe (daily, annualized)
  const rollingSharpe: (number | null)[] = ec.map((_, i) => {
    if (i < windowSize) return null
    const window = ec.slice(i - windowSize + 1, i + 1)
    const dailyReturns: number[] = []
    for (let j = 1; j < window.length; j++) {
      dailyReturns.push((window[j].equity / window[j - 1].equity) - 1)
    }
    const mean = dailyReturns.reduce((s, v) => s + v, 0) / dailyReturns.length
    const std = Math.sqrt(dailyReturns.reduce((s, v) => s + (v - mean) ** 2, 0) / dailyReturns.length)
    return std > 0 ? (mean / std) * Math.sqrt(252) : 0
  })

  // Rolling max drawdown
  const rollingDd: (number | null)[] = ec.map((_, i) => {
    if (i < windowSize) return null
    const window = ec.slice(i - windowSize + 1, i + 1)
    let peak = window[0].equity
    let maxDd = 0
    for (const p of window) {
      if (p.equity > peak) peak = p.equity
      const dd = (p.equity / peak - 1) * 100
      if (dd < maxDd) maxDd = dd
    }
    return maxDd
  })

  // Rolling win rate
  const trades = data.trades
  const rollingWinRate: (number | null)[] = ec.map((p, i) => {
    const windowTrades = trades.filter(t => t.exitDate <= p.date && t.exitDate >= ec[Math.max(0, i - windowSize * 2)].date)
    if (windowTrades.length < 3) return null
    const wins = windowTrades.filter(t => t.pnlPct > 0).length
    return (wins / windowTrades.length) * 100
  })

  const dates = ec.map(p => p.date)
  const validIdx = ec.map((_, i) => i).filter(i => rollingReturns[i] !== null)

  const makeOption = (values: (number | null)[], name: string, color: string, formatter?: string): EChartsOption => ({
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => {
        if (!p || p.length === 0) return ''
        const v = p[0].value
        return `${p[0].axisValueLabel}<br/>${p[0].marker} ${name}: ${v == null ? '-' : Number(v).toFixed(1)}${formatter ? '%' : ''}`
      },
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: { type: 'category', data: dates, axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: chartColors.text, formatter: formatter || '{value}' } },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [{
      name,
      type: 'line',
      data: values.map(v => v === null ? null : +Number(v).toFixed(1)),
      showSymbol: true,
      symbolSize: 3,
      lineStyle: { width: 1.5, color },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: color + '22' }, { offset: 1, color: color + '00' },
      ]}},
    }],
  })

  const avgSharpe = validIdx.length > 0
    ? validIdx.reduce((s, i) => s + (rollingSharpe[i] || 0), 0) / validIdx.length
    : 0

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">滚动窗口</div>
          <div className="mt-1 text-2xl font-bold text-foreground">{windowSize} 天</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">平均滚动Sharpe</div>
          <div className="mt-1 text-2xl font-bold text-blue-500">{avgSharpe.toFixed(2)}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">最大滚动收益</div>
          <div className="mt-1 text-2xl font-bold text-red-500">
            {Math.max(...validIdx.map(i => rollingReturns[i] || 0)).toFixed(1)}%
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">最小滚动收益</div>
          <div className="mt-1 text-2xl font-bold text-green-500">
            {Math.min(...validIdx.map(i => rollingReturns[i] || 0)).toFixed(1)}%
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">滚动收益率（{windowSize}日窗口）</div>
        <div className="h-56"><Chart option={makeOption(rollingReturns, '滚动收益', chartColors.purple, '{value}%')} /></div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">滚动夏普比率（{windowSize}日窗口，年化）</div>
        <div className="h-56"><Chart option={makeOption(rollingSharpe, '滚动Sharpe', chartColors.blue)} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">滚动最大回撤</div>
          <div className="h-48"><Chart option={makeOption(rollingDd, '滚动回撤', chartColors.loss, '{value}%')} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">滚动胜率</div>
          <div className="h-48"><Chart option={makeOption(rollingWinRate, '滚动胜率', chartColors.profit, '{value}%')} /></div>
        </div>
      </div>
    </div>
  )
}
