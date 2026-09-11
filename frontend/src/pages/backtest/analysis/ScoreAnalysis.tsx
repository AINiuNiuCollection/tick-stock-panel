import type { BacktestData } from './types'
import { Chart, chartColors } from './Chart'
import type { EChartsOption } from 'echarts'
import { cn } from '@/lib/cn'

export function ScoreAnalysis({ data }: { data: BacktestData }) {
  const scored = data.trades.filter(t => t.entryScore != null && !isNaN(t.entryScore))

  if (scored.length === 0) {
    return (
      <div className="rounded-xl border border-border bg-surface p-8 text-center">
        <div className="text-muted">CSV 文件中未包含 entry_score 列</div>
        <div className="mt-2 text-sm text-muted">请更新回测导出代码，在交易明细中包含 entry_score 字段</div>
      </div>
    )
  }

  const scores = scored.map(t => t.entryScore!)
  const pnls = scored.map(t => t.pnlPct * 100)
  const scoreMin = Math.min(...scores)
  const scoreMax = Math.max(...scores)

  // Correlation
  const n = scored.length
  const meanS = scores.reduce((s, v) => s + v, 0) / n
  const meanP = pnls.reduce((s, v) => s + v, 0) / n
  const cov = scores.reduce((s, v, i) => s + (v - meanS) * (pnls[i] - meanP), 0) / n
  const stdS = Math.sqrt(scores.reduce((s, v) => s + (v - meanS) ** 2, 0) / n)
  const stdP = Math.sqrt(pnls.reduce((s, v) => s + (v - meanP) ** 2, 0) / n)
  const correlation = stdS > 0 && stdP > 0 ? cov / (stdS * stdP) : 0

  // Scatter: score vs pnl
  const scatterOption: EChartsOption = {
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (p: any) => `${p.data[2]} (${p.data[3]})<br/>评分: ${p.data[0].toFixed(1)}<br/>收益: ${p.data[1] >= 0 ? '+' : ''}${p.data[1].toFixed(2)}%`,
    },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'value', name: '买入评分', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text }, min: Math.floor(scoreMin - 1), max: Math.ceil(scoreMax + 1) },
    yAxis: { type: 'value', name: '收益率', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'scatter',
      data: scored.map(t => [t.entryScore, t.pnlPct * 100, t.symbol, t.name]),
      symbolSize: 10,
      itemStyle: {
        color: ((p: any) => p.data[1] >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)') as any,
        borderColor: ((p: any) => p.data[1] >= 0 ? chartColors.profit : chartColors.loss) as any,
      },
      markLine: {
        data: [
          { type: 'average', xAxis: 'average', lineStyle: { color: chartColors.blue, type: 'dashed' } },
          { type: 'average', yAxis: 'average', lineStyle: { color: chartColors.blue, type: 'dashed' } },
        ],
        silent: true,
      },
    }],
  }

  // Bin analysis: divide scores into 5 quantiles
  const sorted = [...scored].sort((a, b) => (a.entryScore! - b.entryScore!))
  const binSize = Math.ceil(sorted.length / 5)
  const quintiles: { label: string; range: string; count: number; avgPnl: number; winRate: number; totalPnl: number }[] = []
  for (let i = 0; i < 5; i++) {
    const group = sorted.slice(i * binSize, (i + 1) * binSize)
    if (group.length === 0) continue
    const minScore = Math.min(...group.map(t => t.entryScore!))
    const maxScore = Math.max(...group.map(t => t.entryScore!))
    const wins = group.filter(t => t.pnlPct > 0).length
    const avgPnl = group.reduce((s, t) => s + t.pnlPct, 0) / group.length
    const totalPnl = group.reduce((s, t) => s + t.pnlAmount, 0)
    quintiles.push({
      label: `Q${i + 1}`,
      range: `${minScore.toFixed(1)}~${maxScore.toFixed(1)}`,
      count: group.length,
      avgPnl,
      winRate: wins / group.length,
      totalPnl,
    })
  }

  const quintileBarOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['平均收益', '胜率'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '8%', top: '12%', bottom: '12%' },
    xAxis: {
      type: 'category',
      data: quintiles.map(q => `${q.label}\n(${q.range})`),
      axisLabel: { color: chartColors.text, fontSize: 10, interval: 0 },
    },
    yAxis: [
      { type: 'value', name: '平均收益', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
      { type: 'value', name: '胜率', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    ],
    series: [
      {
        name: '平均收益',
        type: 'bar',
        data: quintiles.map(q => ({
          value: +(q.avgPnl * 100).toFixed(2),
          itemStyle: { color: q.avgPnl >= 0 ? chartColors.profit : chartColors.loss },
        })),
        label: { show: true, position: 'top', formatter: '{c}%', color: chartColors.text, fontSize: 10 },
      },
      {
        name: '胜率',
        type: 'line',
        yAxisIndex: 1,
        data: quintiles.map(q => +(q.winRate * 100).toFixed(1)),
        lineStyle: { width: 2, color: chartColors.purple },
        itemStyle: { color: chartColors.purple },
        label: { show: true, formatter: '{c}%', color: chartColors.purple, fontSize: 10 },
      },
    ],
  }

  // Box plot by quintile
  const boxData = quintiles.map((_, qi) => {
    const group = sorted.slice(qi * binSize, (qi + 1) * binSize).map(t => t.pnlPct * 100).sort((a, b) => a - b)
    if (group.length === 0) return [0, 0, 0, 0, 0]
    const q = (p: number) => group[Math.min(Math.floor(p * group.length), group.length - 1)]
    return [group[0], q(0.25), q(0.5), q(0.75), group[group.length - 1]]
  })
  const boxOption: EChartsOption = {
    tooltip: { trigger: 'item', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    grid: { left: '8%', right: '5%', top: '8%', bottom: '12%' },
    xAxis: { type: 'category', data: quintiles.map(q => q.label), axisLabel: { color: chartColors.text } },
    yAxis: { type: 'value', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    series: [{
      type: 'boxplot',
      data: boxData,
      itemStyle: { color: 'rgba(168,85,247,0.3)', borderColor: chartColors.purple },
    }],
  }

  // Score distribution histogram with win/loss breakdown
  const scoreBins = 10
  const scoreBinSize = (scoreMax - scoreMin) / scoreBins || 1
  const scoreHist: { label: string; count: number; avgPnl: number; winCount: number; lossCount: number }[] = []
  for (let i = 0; i < scoreBins; i++) {
    const lo = scoreMin + i * scoreBinSize
    const hi = lo + scoreBinSize
    const group = scored.filter(t => t.entryScore! >= lo && t.entryScore! < hi)
    const wins = group.filter(t => t.pnlPct > 0).length
    scoreHist.push({
      label: `${lo.toFixed(1)}`,
      count: group.length,
      avgPnl: group.length > 0 ? group.reduce((s, t) => s + t.pnlPct, 0) / group.length : 0,
      winCount: wins,
      lossCount: group.length - wins,
    })
  }

  const histOption: EChartsOption = {
    tooltip: { trigger: 'axis', backgroundColor: '#1e1e1e', borderColor: '#3f3f46', textStyle: { color: '#e4e4e7' } },
    legend: { data: ['交易笔数', '平均收益'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '8%', top: '12%', bottom: '12%' },
    xAxis: { type: 'category', data: scoreHist.map(h => h.label), axisLabel: { color: chartColors.text, fontSize: 9, rotate: 30 } },
    yAxis: [
      { type: 'value', name: '笔数', axisLabel: { color: chartColors.text } },
      { type: 'value', name: '平均收益', axisLabel: { color: chartColors.text, formatter: '{value}%' } },
    ],
    series: [
      { name: '交易笔数', type: 'bar', data: scoreHist.map(h => h.count), itemStyle: { color: chartColors.blue }, label: { show: true, position: 'top', color: chartColors.text, fontSize: 10 } },
      { name: '平均收益', type: 'line', yAxisIndex: 1, data: scoreHist.map(h => +(h.avgPnl * 100).toFixed(2)), lineStyle: { width: 2, color: chartColors.purple }, itemStyle: { color: chartColors.purple }, label: { show: true, formatter: '{c}%', color: chartColors.purple, fontSize: 10 } },
    ],
  }

  // Win/Loss distribution by score bin (stacked bar)
  const winLossOption: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1e1e1e',
      borderColor: '#3f3f46',
      textStyle: { color: '#e4e4e7' },
      formatter: (params: any) => {
        const bin = params[0]?.axisValue ?? ''
        const win = params.find((p: any) => p.seriesName === '盈利笔数')?.data ?? 0
        const loss = params.find((p: any) => p.seriesName === '亏损笔数')?.data ?? 0
        const total = win + loss
        const winRate = total > 0 ? ((win / total) * 100).toFixed(1) : '0.0'
        return `评分 ${bin}<br/>盈利: <span style="color:${chartColors.profit}">${win}</span> 笔<br/>亏损: <span style="color:${chartColors.loss}">${loss}</span> 笔<br/>合计: ${total} 笔<br/>胜率: ${winRate}%`
      },
    },
    legend: { data: ['盈利笔数', '亏损笔数'], textStyle: { color: chartColors.text }, top: 0 },
    grid: { left: '8%', right: '5%', top: '12%', bottom: '12%' },
    xAxis: { type: 'category', data: scoreHist.map(h => h.label), name: '买入评分', nameTextStyle: { color: chartColors.text }, axisLabel: { color: chartColors.text, fontSize: 9, rotate: 30 } },
    yAxis: { type: 'value', name: '笔数', axisLabel: { color: chartColors.text } },
    series: [
      {
        name: '盈利笔数',
        type: 'bar',
        stack: 'pnl',
        data: scoreHist.map(h => h.winCount),
        itemStyle: { color: chartColors.profit },
        label: { show: true, position: 'inside', color: '#fff', fontSize: 10, formatter: (p: any) => p.data > 0 ? String(p.data) : '' },
      },
      {
        name: '亏损笔数',
        type: 'bar',
        stack: 'pnl',
        data: scoreHist.map(h => h.lossCount),
        itemStyle: { color: chartColors.loss },
        label: { show: true, position: 'inside', color: '#fff', fontSize: 10, formatter: (p: any) => p.data > 0 ? String(p.data) : '' },
      },
    ],
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">评分-收益相关系数</div>
          <div className={cn('mt-1 text-2xl font-bold', correlation > 0 ? 'text-red-500' : 'text-green-500')}>
            {correlation.toFixed(3)}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">评分范围</div>
          <div className="mt-1 text-2xl font-bold text-foreground">{scoreMin.toFixed(1)}~{scoreMax.toFixed(1)}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">有效样本</div>
          <div className="mt-1 text-2xl font-bold text-foreground">{scored.length}</div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="text-xs text-muted">相关性强度</div>
          <div className={cn('mt-1 text-2xl font-bold',
            Math.abs(correlation) > 0.3 ? 'text-red-500' :
            Math.abs(correlation) > 0.1 ? 'text-blue-500' : 'text-muted')}>
            {Math.abs(correlation) > 0.3 ? '强' : Math.abs(correlation) > 0.1 ? '中' : '弱'}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">评分 vs 收益率散点图</div>
        <div className="h-72"><Chart option={scatterOption} /></div>
        <p className="mt-2 text-xs text-muted">
          {correlation > 0
            ? `正相关 (${correlation.toFixed(3)})：评分越高，收益倾向越高，评分有预测力。`
            : correlation < 0
            ? `负相关 (${correlation.toFixed(3)})：评分越高反而收益越低，评分反向有效或需调参。`
            : '无显著相关性，评分对收益预测力弱。'}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">五分位平均收益与胜率</div>
          <div className="h-64"><Chart option={quintileBarOption} /></div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-2 text-sm font-semibold text-foreground">五分位箱线图</div>
          <div className="h-64"><Chart option={boxOption} /></div>
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">评分分箱统计（直方图+平均收益折线）</div>
        <div className="h-56"><Chart option={histOption} /></div>
      </div>

      <div className="rounded-xl border border-border bg-surface p-4">
        <div className="mb-2 text-sm font-semibold text-foreground">盈亏分布与评分区间（堆叠图）</div>
        <div className="h-56"><Chart option={winLossOption} /></div>
        <p className="mt-2 text-xs text-muted">红色为盈利笔数，绿色为亏损笔数。堆叠高度反映该评分区间的交易集中度，红绿比例反映胜率。</p>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface text-sm text-muted">
            <tr>
              <th className="px-4 py-2 text-center font-bold text-sm">分位</th>
              <th className="px-4 py-2 text-center font-bold text-sm">评分范围</th>
              <th className="px-4 py-2 text-center font-bold text-sm">样本数</th>
              <th className="px-4 py-2 text-center font-bold text-sm">平均收益</th>
              <th className="px-4 py-2 text-center font-bold text-sm">胜率</th>
              <th className="px-4 py-2 text-center font-bold text-sm">总盈亏额</th>
            </tr>
          </thead>
          <tbody>
            {quintiles.map((q, i) => (
              <tr key={i} className="border-t border-border/50 hover:bg-surface/50">
                <td className="px-4 py-2 text-center font-medium text-foreground">{q.label}</td>
                <td className="px-4 py-2 text-center text-muted">{q.range}</td>
                <td className="px-4 py-2 text-center tabular-nums">{q.count}</td>
                <td className={cn('px-4 py-2 text-center tabular-nums', q.avgPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {q.avgPnl >= 0 ? '+' : ''}{(q.avgPnl * 100).toFixed(2)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', q.winRate >= 0.5 ? 'text-red-500' : 'text-green-500')}>
                  {(q.winRate * 100).toFixed(1)}%
                </td>
                <td className={cn('px-4 py-2 text-center tabular-nums', q.totalPnl >= 0 ? 'text-red-500' : 'text-green-500')}>
                  {q.totalPnl >= 0 ? '+' : ''}{q.totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
