import { useRef, useEffect } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

const CHART_TEXT_COLOR = '#a1a1aa'
const CHART_GRID_COLOR = '#27272a'

export function useChart(option: EChartsOption | null, deps: any[] = []) {
  const ref = useRef<HTMLDivElement>(null)
  const instanceRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    instanceRef.current = echarts.init(ref.current, 'dark', { renderer: 'canvas' })
    const ro = new ResizeObserver(() => instanceRef.current?.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); instanceRef.current?.dispose(); instanceRef.current = null }
  }, [])

  useEffect(() => {
    if (!instanceRef.current || !option) return
    instanceRef.current.setOption({
      ...option,
      textStyle: { color: CHART_TEXT_COLOR, fontFamily: 'inherit' },
      ...option.textStyle ? { textStyle: { color: CHART_TEXT_COLOR, fontFamily: 'inherit', ...option.textStyle } } : {},
    }, { notMerge: true })
  }, [option, ...deps])

  return ref
}

export function Chart({ option, className, deps }: { option: EChartsOption | null; className?: string; deps?: any[] }) {
  const ref = useChart(option, deps)
  return <div ref={ref} className={className} style={{ width: '100%', height: '100%' }} />
}

export const chartColors = {
  text: CHART_TEXT_COLOR,
  grid: CHART_GRID_COLOR,
  // 中国股市惯例：涨红跌绿。profit=红色(盈利/正向)，loss=绿色(亏损/负向)
  profit: '#ef4444',
  loss: '#22c55e',
  blue: '#3b82f6',
  orange: '#f59e0b',
  purple: '#a855f7',
  cyan: '#06b6d4',
  gray: '#71717a',
}
