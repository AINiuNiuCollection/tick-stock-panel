import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

const REASON_LABELS: Record<string, string> = {
  stop_loss: '止损',
  trailing_stop: '移动止损',
  max_hold: '到期平仓',
  end: '回测结束',
  signal: '信号退出',
  take_profit: '止盈',
}

const REASON_COLORS: Record<string, string> = {
  stop_loss: chartColors.loss,
  trailing_stop: chartColors.blue,
  max_hold: chartColors.orange,
  end: chartColors.gray,
  signal: chartColors.profit,
  take_profit: chartColors.purple,
}

export function ExitAnalysis({ data }: { data: BacktestData }) {
  const trades = data.trades
  const reasons = [...new Set(trades.map(t => t.exitReason))]

  // Aggregate by exitReason
  const stats = reasons.map(r => {
    const group = trades.filter(t => t.exitReason === r)
    const wins = group.filter(t => t.pnlPct > 0).length
    const totalPnl = group.reduce((s, t) => s + t.pnlAmount, 0)
    return {
      reason: r,
      label: REASON_LABELS[r] || r,
      count: group.length,
      wins,
      losses: group.length - wins,
      winRate: group.length > 0 ? wins / group.length : 0,
      avgPnl: group.length > 0 ? group.reduce((s, t) => s + t.pnlPct, 0) / group.length : 0,
      totalPnl,
    }
  }).sort((a, b) => b.count - a.count)

  // Donut chart
  const donutOption: EChartsOption = {
    tooltip: { trigger: 'item', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { bottom: 0, textStyle: { color: chartColors.text, fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['50%', '45%'],
      label: { show: true, formatter: '{b}\n{c}笔', color: chartColors.text, fontSize: 11 },
      data: stats.map(s => ({
        value: s.count,
        name: s.label,
        itemStyle: { color: REASON_COLORS[s.reason] || chartColors.gray },
      })),
    }],
  }

  // Stacked bar: wins vs losses by reason
  const barOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['盈利', '亏损'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '5%', top: '12%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: stats.map(s => s.label),
      axisLabel: { color: chartColors.text, fontSize: 11, rotate: 20 },
    },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text } },
    series: [
      { name: '盈利', type: 'bar', stack: 'total', data: stats.map(s => s.wins), itemStyle: { color: chartColors.profit }, label: { show: true, position: 'inside', color: '#fff', fontSize: 10 } },
      { name: '亏损', type: 'bar', stack: 'total', data: stats.map(s => s.losses), itemStyle: { color: chartColors.loss }, label: { show: true, position: 'inside', color: '#fff', fontSize: 10 } },
    ],
  }

  // Avg PnL by reason
  const pnlBarOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '15%' },
    xAxis: {
      type: 'category',
      data: stats.map(s => s.label),
      axisLabel: { color: chartColors.text, fontSize: 11, rotate: 20 },
    },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: stats.map(s => ({
        value: +(s.avgPnl * 100).toFixed(2),
        itemStyle: { color: s.avgPnl >= 0 ? chartColors.profit : chartColors.loss },
      })),
      label: { show: true, position: 'top', formatter: '{c}%', color: chartColors.text, fontSize: 10 },
      barWidth: '50%',
    }],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">退出原因分布</div>
          <div className="h-72"><Chart option={donutOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">盈亏笔数堆叠</div>
          <div className="h-72"><Chart option={barOption} /></div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">各退出原因平均收益率</div>
        <div className="h-64"><Chart option={pnlBarOption} /></div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">退出原因</th>
              <th className="px-4 py-2 text-center font-bold text-sm">笔数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">占比</th>
              <th className="px-4 py-2 text-center font-bold text-sm">盈利</th>
              <th className="px-4 py-2 text-center font-bold text-sm">亏损</th>
              <th className="px-4 py-2 text-center font-bold text-sm">胜率</th>
              <th className="px-4 py-2 text-center font-bold text-sm">平均收益</th>
              <th className="px-4 py-2 text-center font-bold text-sm">总盈亏额</th>
            </tr>
          </thead>
          <tbody>
            {stats.map(s => (
              <tr key={s.reason} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center">
                  <span className="rounded px-1.5 py-0.5 text-xs" style={{ backgroundColor: (REASON_COLORS[s.reason] || chartColors.gray) + '33', color: REASON_COLORS[s.reason] || chartColors.gray }}>
                    {s.label}
                  </span>
                </td>
                <td className="px-4 py-2 text-center tabular-nums">{s.count}</td>
                <td className="px-4 py-2 text-center tabular-nums text-muted">{(s.count / trades.length * 100).toFixed(1)}%</td>
                <td className="px-4 py-2 text-center tabular-nums text-red-500">{s.wins}</td>
                <td className="px-4 py-2 text-center tabular-nums text-green-500">{s.losses}</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', s.winRate >= 0.5 ? 'text-red-500' : 'text-green-500')}>
                  {(s.winRate * 100).toFixed(1)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', s.avgPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {s.avgPnl >= 0 ? '+' : ''}{(s.avgPnl * 100).toFixed(2)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', s.totalPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {s.totalPnl >= 0 ? '+' : ''}{s.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
