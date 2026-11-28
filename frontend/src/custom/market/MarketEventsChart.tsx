/**
 * 政策事件主图 — 上证指数全历史蜡烛 + 事件旗标 (恒在层, 设计 §2.3 第一层)
 *
 * 旗标: 利好▲(红, low 下方) / 利空▼(绿, high 上方) / 中性◆(灰, high 上方),
 *       大小按 importance (major 12 / medium 9 / minor 6), hover tooltip, click 选中。
 * 选中态: [T, T+20] 半透明事件区间带 (markArea, 检视层 §2.3 第二层)。
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { MarketPolicyEvent } from '@/lib/api'

const UP_COLOR = '#e24b4a'
const DN_COLOR = '#1d9e75'
const POS_COLOR = '#c0392b'
const NEG_COLOR = '#1d9e75'
const NEU_COLOR = '#94a3b8'
const BAND_COLOR = 'rgba(37, 99, 235, 0.10)'

interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

interface Props {
  height?: number | string
  bars: Bar[]
  /** 图上事件 (approved, 非 draft — draft 不上图) */
  events: MarketPolicyEvent[]
  selectedEvent: MarketPolicyEvent | null
  onSelect: (ev: MarketPolicyEvent) => void
  onHover?: (ev: MarketPolicyEvent | null) => void
}

export function MarketEventsChart({
  height = 420,
  bars,
  events,
  selectedEvent,
  onSelect,
  onHover,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  // onSelect/onHover 存 ref, 避免闭包过期 (chart 只 init 一次)
  const selectRef = useRef(onSelect)
  const hoverRef = useRef(onHover)
  selectRef.current = onSelect
  hoverRef.current = onHover

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
      chartRef.current.on('click', (params: any) => {
        if (params.componentType === 'markPoint' && params.data?.eventId) {
          const ev = events.find((e) => e.id === params.data.eventId)
          if (ev) selectRef.current(ev)
        }
      })
    }
    const chart = chartRef.current

    const dates = bars.map((b) => b.date)
    const dateIdx = new Map(dates.map((d, i) => [d, i]))

    const flagPoints = events
      .map((ev) => {
        const idx = dateIdx.get(ev.date)
        if (idx == null) return null
        const bar = bars[idx]
        const isPos = ev.direction === 'positive'
        const isNeg = ev.direction === 'negative'
        const size = ev.importance === 'major' ? 13 : ev.importance === 'medium' ? 9 : 6
        return {
          coord: [idx, isPos ? bar.low * 0.985 : bar.high * 1.015],
          symbol: isPos || isNeg ? 'triangle' : 'diamond',
          symbolSize: size,
          symbolRotate: isPos ? 0 : 180,
          itemStyle: { color: isPos ? POS_COLOR : isNeg ? NEG_COLOR : NEU_COLOR },
          label: {
            show: true,
            formatter: isPos ? '▲' : isNeg ? '▼' : '◆',
            fontSize: isPos ? size : size - 3,
            color: isPos ? POS_COLOR : isNeg ? NEG_COLOR : NEU_COLOR,
            position: isPos ? 'bottom' : 'top',
          },
          eventId: ev.id,
          eventTitle: `${ev.date} ${ev.title}`,
          eventMeta: `${ev.category} / ${ev.direction} / ${ev.importance}`,
        }
      })
      .filter((p): p is NonNullable<typeof p> => p !== null)

    // 选中事件: [T, T+20] 区间带 (T+20 = 事件日起第 20 个交易日, 与后端口径一致)
    let markArea: any
    // 联动规则 (设计 §2.3): 选中 → 图滚动定位到事件窗口 (dataZoom 重定位)
    let zoomStart = 0
    let zoomEnd = 100
    if (selectedEvent) {
      const tIdx = dateIdx.get(selectedEvent.date)
      if (tIdx != null) {
        const end = Math.min(tIdx + 19, dates.length - 1)
        markArea = {
          silent: true,
          itemStyle: { color: BAND_COLOR },
          data: [[{ xAxis: tIdx }, { xAxis: end }]],
        }
        // 窗口 = 事件前 60 根 → 事件后 120 根, 保证区间带与前后语境可见
        zoomStart = Math.max(0, ((tIdx - 60) / dates.length) * 100)
        zoomEnd = Math.min(100, ((tIdx + 120) / dates.length) * 100)
      }
    }

    const option: echarts.EChartsCoreOption = {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      grid: { left: 8, right: 16, top: 20, bottom: 56, containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { formatter: (val: string) => val.slice(0, 7) },
        axisLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#eef0f3' } } },
      dataZoom: [
        { type: 'inside', start: zoomStart, end: zoomEnd },
        { type: 'slider', bottom: 2, height: 20, start: zoomStart, end: zoomEnd },
      ],
      series: [
        {
          name: '上证指数',
          type: 'candlestick',
          data: bars.map((b) => [b.open, b.close, b.low, b.high]),
          itemStyle: {
            color: UP_COLOR,
            color0: DN_COLOR,
            borderColor: UP_COLOR,
            borderColor0: DN_COLOR,
          },
          markPoint: {
            data: flagPoints as any[],
            animation: false,
            label: { fontSize: 10 },
          },
          ...(markArea ? { markArea } : {}),
        },
      ],
    }
    chart.setOption(option, { notMerge: true })
  }, [bars, events, selectedEvent])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    // 全屏 / flex 占比变化时容器尺寸变化不触发 window resize, 用 ResizeObserver 兜底
    let ro: ResizeObserver | undefined
    if (typeof ResizeObserver !== 'undefined' && ref.current) {
      ro = new ResizeObserver(onResize)
      ro.observe(ref.current)
    }
    return () => {
      window.removeEventListener('resize', onResize)
      ro?.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  return <div ref={ref} style={{ height, width: '100%' }} />
}
