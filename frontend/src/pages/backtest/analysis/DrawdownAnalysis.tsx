import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function DrawdownAnalysis({ data }: { data: BacktestData }) {
  const ec = data.equityCurve
  const drawdown = ec.map(p => p.drawdown * 100)

  // Find all drawdown periods (from peak to recovery)
  interface DdPeriod { peakDate: string; troughDate: string; recoveryDate: string | null; depth: number; duration: number; recoveryDuration: number | null }
  const periods: DdPeriod[] = []
  let inDd = false
  let peakIdx = 0
  let troughIdx = 0

  for (let i = 1; i < ec.length; i++) {
    if (drawdown[i] < 0 && !inDd) {
      inDd = true
      peakIdx = i - 1
      troughIdx = i
    }
    if (inDd) {
      if (drawdown[i] < drawdown[troughIdx]) troughIdx = i
      if (drawdown[i] >= 0) {
        periods.push({
          peakDate: ec[peakIdx].date,
          troughDate: ec[troughIdx].date,
          recoveryDate: ec[i].date,
          depth: drawdown[troughIdx],
          duration: troughIdx - peakIdx,
          recoveryDuration: i - troughIdx,
        })
        inDd = false
      }
    }
  }
  if (inDd) {
    periods.push({
      peakDate: ec[peakIdx].date,
      troughDate: ec[troughIdx].date,
      recoveryDate: null,
      depth: drawdown[troughIdx],
      duration: troughIdx - peakIdx,
      recoveryDuration: null,
    })
  }

  // Sort by depth
  const topPeriods = [...periods].sort((a, b) => a.depth - b.depth).slice(0, 10)

  // Underwater chart
  const underwaterOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        const val = typeof p.value === 'number' ? p.value : (p.data ?? 0)
        return `${p.axisValue}<br/>回撤: ${val.toFixed(1)}%`
      },
    },
    grid: { left: '6%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: { type: 'category', data: ec.map(p => p.date), axisLabel: { color: chartColors.text, fontSize: 10 } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: (v: number) => `${v.toFixed(1)}%` }, max: 0 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 16 }],
    series: [{
      type: 'line',
      data: drawdown,
      showSymbol: false,
      lineStyle: { width: 1, color: chartColors.loss },
      areaStyle: {
        color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
          { offset: 0, color: 'rgba(34,197,94,0)' },
          { offset: 1, color: 'rgba(34,197,94,0.3)' },
        ]},
      },
      markPoint: {
        data: topPeriods.slice(0, 3).map(p => ({
          coord: [p.troughDate, p.depth],
          value: p.depth,
          name: '最大回撤',
          itemStyle: { color: chartColors.loss },
          label: { formatter: () => `${p.depth.toFixed(1)}%`, color: '#fff', fontSize: 10 },
        })),
        symbolSize: 36,
      },
    }],
  }

  // DD duration distribution
  const durationBuckets = [0, 5, 10, 20, 30, 50, 100, 200]
  const bucketCounts = durationBuckets.map((b, i) => {
    const next = durationBuckets[i + 1] || Infinity
    return {
      label: i < durationBuckets.length - 1 ? `${b}~${next}天` : `${b}天+`,
      count: periods.filter(p => p.duration >= b && p.duration < next).length,
    }
  })

  const durBarOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: bucketCounts.map(b => b.label), axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [{
      type: 'bar',
      data: bucketCounts.map(b => b.count),
      itemStyle: { color: chartColors.orange },
      label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 },
      barWidth: '60%',
    }],
  }

  const maxDd = periods.length > 0 ? Math.min(...periods.map(p => p.depth)) : 0
  const avgDd = periods.length > 0 ? periods.reduce((s, p) => s + p.depth, 0) / periods.length : 0
  const avgDuration = periods.length > 0 ? periods.reduce((s, p) => s + p.duration, 0) / periods.length : 0
  const unrecovered = periods.filter(p => p.recoveryDate === null).length

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">最大回撤</div>
          <div className="mt-1 text-2xl font-bold text-green-500">{maxDd.toFixed(2)}%</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">平均回撤</div>
          <div className="mt-1 text-2xl font-bold text-orange-500">{avgDd.toFixed(2)}%</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">回撤次数</div>
          <div className="mt-1 text-2xl font-bold text-foreground">{periods.length}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">未恢复回撤</div>
          <div className="mt-1 text-2xl font-bold text-green-500">{unrecovered}</div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">水下曲线（Underwater Plot）</div>
        <div className="h-72"><Chart option={underwaterOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">回撤持续天数分布</div>
          <div className="h-56"><Chart option={durBarOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">回撤统计</div>
          <div className="space-y-2 text-sm text-muted">
            <p>平均回撤持续天数: <span className="text-foreground font-medium">{avgDuration.toFixed(0)}天</span></p>
            <p>最长回撤持续天数: <span className="text-foreground font-medium">{Math.max(...periods.map(p => p.duration), 0)}天</span></p>
            <p>平均回撤深度: <span className="text-orange-500 font-medium">{avgDd.toFixed(2)}%</span></p>
            <p>最大回撤深度: <span className="text-green-500 font-medium">{maxDd.toFixed(2)}%</span></p>
            <p>已恢复回撤: <span className="text-red-500">{periods.length - unrecovered}</span> / 未恢复: <span className="text-green-500">{unrecovered}</span></p>
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">排名</th>
              <th className="px-4 py-2 text-center font-bold text-sm">峰值日</th>
              <th className="px-4 py-2 text-center font-bold text-sm">谷底日</th>
              <th className="px-4 py-2 text-center font-bold text-sm">恢复日</th>
              <th className="px-4 py-2 text-center font-bold text-sm">回撤深度</th>
              <th className="px-4 py-2 text-center font-bold text-sm">下行天数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">恢复天数</th>
            </tr>
          </thead>
          <tbody>
            {topPeriods.map((p, i) => (
              <tr key={i} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center font-medium text-foreground">#{i + 1}</td>
                <td className="px-4 py-2 text-center text-muted">{p.peakDate}</td>
                <td className="px-4 py-2 text-center text-muted">{p.troughDate}</td>
                <td className={cn('px-4 py-2 text-center', p.recoveryDate ? 'text-red-500' : 'text-green-500')}>
                  {p.recoveryDate || '未恢复'}
                </td>
                <td className="px-4 py-2 text-center tabular-nums text-green-500">{p.depth.toFixed(2)}%</td>
                <td className="px-4 py-2 text-center tabular-nums text-muted">{p.duration}</td>
                <td className="px-4 py-2 text-center tabular-nums text-muted">{p.recoveryDuration ?? '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
