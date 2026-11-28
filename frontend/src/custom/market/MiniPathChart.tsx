/**
 * 迷你路径折线图 — 事件前5日→后60日归一化 (基期=事件前收盘=100), 同期指数基线对比。
 * 检视层抽屉与叠加层扇形共用。支持多条淡色细线 + 均值粗线 (spaghetti)。
 *
 * 易用性 (v3-①): 悬停单条线时高亮该线、其余变暗 (扇形图线条多时可快速锁定单事件);
 * tooltip 按该 offset 有值的线排序展示 (只列出非空序列, 不刷 23 行 null)。
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export interface SeriesLine {
  /** 线条名 (单事件=事件名; 扇形=各事件 id/日期标签) */
  name: string
  /** x = offset (-5..59), y = value */
  points: { x: number; y: number }[]
  /** 扇形均值线加粗 */
  bold?: boolean
  /** 淡色细线 */
  faint?: boolean
  dashed?: boolean
  /** 值是否已是百分比偏离 (tooltip 显示 +x.x% 而非基期值) */
  isPct?: boolean
}

interface Props {
  height?: number | string
  lines: SeriesLine[]
  /** x 轴标签生成 (默认 offset) */
  showLegend?: boolean
}

const MAIN_COLOR = '#2563eb'
const BASELINE_COLOR = '#f59e0b'

export function MiniPathChart({ height = 220, lines, showLegend = false }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  // lines 存 ref, hover 处理器只注册一次但总读到最新线集
  const linesRef = useRef(lines)
  linesRef.current = lines

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
      const chart = chartRef.current
      // 悬停高亮: 该线加深加粗, 其余淡出; 移出恢复
      const setFocus = (hoverName: string | null) => {
        chart.setOption({
          series: linesRef.current.map((l) => ({
            lineStyle: {
              width: hoverName == null ? (l.bold ? 3 : 1) : l.name === hoverName ? 2.5 : l.bold ? 2 : 1,
              opacity:
                hoverName == null
                  ? l.faint
                    ? 0.35
                    : 1
                  : l.name === hoverName
                    ? 1
                    : l.faint
                      ? 0.06
                      : 0.25,
            },
          })),
        })
      }
      chart.on('mouseover', (p: any) => {
        if (p?.seriesName) setFocus(String(p.seriesName))
      })
      chart.on('mouseout', () => setFocus(null))
    }
    const chart = chartRef.current

    const xSet = new Set<number>()
    lines.forEach((l) => l.points.forEach((p) => xSet.add(p.x)))
    const xs = Array.from(xSet).sort((a, b) => a - b)

    const option: echarts.EChartsCoreOption = {
      tooltip: {
        trigger: 'axis',
        // 只列出该 offset 有值的线 (扇形图 23 条线不全等长), 按值降序
        formatter: (params: any) => {
          const ps = Array.isArray(params) ? params : [params]
          const xs0 = String(ps[0]?.axisValue ?? '')
          const rows = ps
            .filter((p: any) => p.value != null && p.seriesName)
            .sort((a: any, b: any) => Number(b.value) - Number(a.value))
            .map(
              (p: any) =>
                `<div style="display:flex;justify-content:space-between;gap:12px">` +
                `<span style="color:${p.color ?? '#999'};max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.seriesName}</span>` +
                `<b>${Number(p.value).toFixed(1)}${p.seriesName === '均值' ? '' : ''}</b></div>`,
            )
          return `<div style="max-width:320px"><b>T${xs0}</b>${rows.length ? '' : ' <span style="color:#999">无数据</span>'}<div style="margin-top:2px">${rows.join('')}</div></div>`
        },
      },
      legend: showLegend ? { bottom: 0, textStyle: { fontSize: 10 } } : undefined,
      grid: { left: 8, right: 12, top: 12, bottom: showLegend ? 40 : 24, containLabel: true },
      xAxis: {
        type: 'category',
        data: xs,
        axisLabel: { formatter: (v: string) => (Number(v) % 10 === 0 ? `T+${v}` : '') },
        axisLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { formatter: (v: number) => v.toFixed(0) },
        splitLine: { lineStyle: { color: '#eef0f3' } },
      },
      series: lines.map((l) => ({
        name: l.name,
        type: 'line' as const,
        data: xs.map((x) => {
          const p = l.points.find((pt) => pt.x === x)
          return p ? p.y : null
        }),
        showSymbol: false,
        connectNulls: true,
        lineStyle: {
          width: l.bold ? 3 : 1,
          opacity: l.faint ? 0.35 : 1,
          type: l.dashed ? 'dashed' : 'solid',
          color: l.bold ? MAIN_COLOR : l.dashed ? BASELINE_COLOR : undefined,
        },
        itemStyle: l.bold ? { color: MAIN_COLOR } : l.dashed ? { color: BASELINE_COLOR } : undefined,
        z: l.bold ? 3 : l.dashed ? 2 : 1,
      })),
    }
    chart.setOption(option, { notMerge: true })
  }, [lines, showLegend])

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
