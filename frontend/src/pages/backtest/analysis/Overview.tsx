import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

function StatCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: 'green' | 'red' | 'blue' | 'purple' | 'default' }) {
  const colorClass = {
    green: 'text-red-500',
    red: 'text-green-500',
    blue: 'text-blue-500',
    purple: 'text-purple-500',
    default: 'text-foreground',
  }[accent || 'default']
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className={cn('mt-1 text-2xl font-bold', colorClass)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </div>
  )
}

export function Overview({ data }: { data: BacktestData }) {
  const s = data.summary
  const wins = data.trades.filter(t => t.pnlPct > 0).length
  const losses = data.trades.filter(t => t.pnlPct <= 0).length

  // Sparkline
  const sparkOption: EChartsOption = {
    grid: { left: 0, right: 0, top: 4, bottom: 0 },
    xAxis: { type: 'category', show: false, data: data.equityCurve.map(p => p.date) },
    yAxis: { type: 'value', show: false, scale: true },
    series: [{
      type: 'line',
      data: data.equityCurve.map(p => p.equity),
      showSymbol: false,
      lineStyle: { width: 1.5, color: chartColors.purple },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [
        { offset: 0, color: 'rgba(168,85,247,0.15)' }, { offset: 1, color: 'rgba(168,85,247,0)' }
      ]}},
    }],
  }

  // Win/loss donut
  const donutOption: EChartsOption = {
    series: [{
      type: 'pie',
      radius: ['55%', '75%'],
      center: ['50%', '50%'],
      label: { show: true, formatter: '{b}\n{d}%', color: chartColors.text, fontSize: 12 },
      data: [
        { value: wins, name: '盈利', itemStyle: { color: chartColors.profit } },
        { value: losses, name: '亏损', itemStyle: { color: chartColors.loss } },
      ],
    }],
  }

  // Strategy vs benchmark
  const benchmarkReturn = data.equityCurve.length > 1
    ? ((data.equityCurve[data.equityCurve.length - 1].benchmark / data.equityCurve[0].benchmark) - 1) * 100
    : 0
  const barOption: EChartsOption = {
    grid: { left: '15%', right: '5%', top: '10%', bottom: '10%' },
    xAxis: { type: 'value', axisLabel: { formatter: '{value}%', color: chartColors.text } },
    yAxis: { type: 'category', data: ['基准', '策略'], axisLabel: { color: chartColors.text } },
    series: [{
      type: 'bar',
      data: [
        { value: benchmarkReturn, itemStyle: { color: chartColors.gray } },
        { value: parseFloat(s['总收益']?.replace('%', '') || '0'), itemStyle: { color: chartColors.purple } },
      ],
      label: { show: true, position: 'right', formatter: '{c}%', color: chartColors.text },
      barWidth: '40%',
    }],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
        <StatCard label="总收益" value={s['总收益'] || '-'} accent="green" />
        <StatCard label="年化收益" value={s['年化收益'] || '-'} accent="green" />
        <StatCard label="夏普比率" value={s['夏普比率'] || '-'} accent="blue" />
        <StatCard label="索提诺" value={s['索提诺'] || '-'} accent="blue" />
        <StatCard label="最大回撤" value={s['最大回撤'] || '-'} accent="red" />
        <StatCard label="胜率" value={s['胜率'] || '-'} accent="purple" />
        <StatCard label="盈亏比" value={s['盈亏比'] || '-'} />
        <StatCard label="完成交易" value={s['完成交易数'] || '-'} />
        <StatCard label="净值天数" value={s['净值曲线天数'] || '-'} />
        <StatCard label="超额收益" value={s['超额收益'] || '-'} accent="green" />
        <StatCard label="同期基准" value={s['同期基准'] || '-'} sub="上证指数" />
        <StatCard label="最终权益" value={s['最终权益'] || '-'} sub="起始100万" />
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">净值走势</div>
        <div className="h-32"><Chart option={sparkOption} /></div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">盈亏分布</div>
          <div className="h-56"><Chart option={donutOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">策略 vs 基准</div>
          <div className="h-56"><Chart option={barOption} /></div>
        </div>
      </div>
    </div>
  )
}
