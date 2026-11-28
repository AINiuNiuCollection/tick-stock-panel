/**
 * 策略实验室双K线联动图 (echarts 上下 grid)
 *
 * 上 grid: 交易标的 (ETF) 蜡烛 + 逐笔 B/S 标记
 * 下 grid: 信号源 (指数) 蜡烛 + 信号点标记 (+1 红上三角 / -1 绿下三角)
 * 两 grid 共享 dataZoom (inside + slider), 联动缩放平移。
 *
 * 两标的交易日历可能不同, 各用独立 category 轴, dataZoom 按百分比联动。
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { KlineRow, MarketTrade } from '@/lib/api'

const UP_COLOR = '#e24b4a'
const DN_COLOR = '#1d9e75'
const BUY_COLOR = '#2563eb'
const SELL_COLOR = '#f59e0b'
const SIGNAL_UP = '#c0392b'
const SIGNAL_DN = '#1d9e75'

interface Props {
  height?: number
  targetSymbol: string
  indexSymbol: string
  targetRows: KlineRow[]
  indexRows: KlineRow[]
  trades: MarketTrade[]
  signals: { dt: string; direction: number; note: string }[]
}

export function MarketLabChart({
  height = 480,
  targetSymbol,
  indexSymbol,
  targetRows,
  indexRows,
  trades,
  signals,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
    }
    const chart = chartRef.current

    const targetDates = targetRows.map((r) => r.date)
    const indexDates = indexRows.map((r) => r.date)

    // 逐笔 B/S 标记 (交易标的)
    const tradePoints = trades
      .flatMap((t) => {
        const pts: any[] = []
        const eIdx = targetDates.indexOf(t.entry_dt)
        if (eIdx >= 0) {
          pts.push({
            coord: [eIdx, targetRows[eIdx].low * 0.99],
            symbol: 'triangle',
            symbolSize: 11,
            itemStyle: { color: BUY_COLOR },
            label: { show: true, formatter: 'B', fontSize: 9, color: BUY_COLOR, offset: [0, 11] },
          })
        }
        if (t.exit_dt) {
          const xIdx = targetDates.indexOf(t.exit_dt)
          if (xIdx >= 0) {
            pts.push({
              coord: [xIdx, targetRows[xIdx].high * 1.01],
              symbol: 'triangle',
              symbolSize: 11,
              symbolRotate: 180,
              itemStyle: { color: SELL_COLOR },
              label: { show: true, formatter: 'S', fontSize: 9, color: SELL_COLOR, offset: [0, -11] },
            })
          }
        }
        return pts
      })

    // 信号点标记 (指数): +1 低点下方 / -1 高点上方, note 提示
    const signalPoints = signals
      .flatMap((s) => {
        const idx = indexDates.indexOf(s.dt)
        if (idx < 0) return []
        const row = indexRows[idx]
        return [
          {
            coord: [idx, s.direction > 0 ? row.low * 0.985 : row.high * 1.015],
            symbol: 'triangle',
            symbolSize: 10,
            symbolRotate: s.direction > 0 ? 0 : 180,
            itemStyle: { color: s.direction > 0 ? SIGNAL_UP : SIGNAL_DN },
            label: {
              show: true,
              formatter: s.direction > 0 ? '▲' : '▼',
              fontSize: 8,
              color: s.direction > 0 ? SIGNAL_UP : SIGNAL_DN,
              position: s.direction > 0 ? 'bottom' : 'top',
            },
          },
        ] as any[]
      })

    const option: echarts.EChartsCoreOption = {
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 8, right: 16, top: 24, height: '38%', containLabel: true },
        { left: 8, right: 16, top: '58%', height: '32%', containLabel: true },
      ],
      xAxis: [
        {
          type: 'category',
          gridIndex: 0,
          data: targetDates,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: '#e5e7eb' } },
        },
        {
          type: 'category',
          gridIndex: 1,
          data: indexDates,
          axisLabel: {
            formatter: (val: string) => val.slice(0, 7),
            width: 56,
            overflow: 'truncate',
          },
          axisLine: { lineStyle: { color: '#e5e7eb' } },
        },
      ],
      yAxis: [
        {
          type: 'value',
          gridIndex: 0,
          scale: true,
          splitLine: { lineStyle: { color: '#eef0f3' } },
        },
        {
          type: 'value',
          gridIndex: 1,
          scale: true,
          splitLine: { lineStyle: { color: '#eef0f3' } },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 0, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 2, height: 16 },
      ],
      series: [
        {
          name: targetSymbol,
          type: 'candlestick',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: targetRows.map((r) => [r.open, r.close, r.low, r.high]),
          itemStyle: {
            color: UP_COLOR,
            color0: DN_COLOR,
            borderColor: UP_COLOR,
            borderColor0: DN_COLOR,
          },
          markPoint: { data: tradePoints, animation: false },
        },
        {
          name: indexSymbol,
          type: 'candlestick',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: indexRows.map((r) => [r.open, r.close, r.low, r.high]),
          itemStyle: {
            color: UP_COLOR,
            color0: DN_COLOR,
            borderColor: UP_COLOR,
            borderColor0: DN_COLOR,
            opacity: 0.85,
          },
          markPoint: { data: signalPoints, animation: false },
        },
      ],
    }
    chart.setOption(option, { notMerge: true })
  }, [targetSymbol, indexSymbol, targetRows, indexRows, trades, signals])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  return <div ref={ref} style={{ height, width: '100%' }} />
}
