/**
 * 缠论分析 ECharts 可视化 — K 线叠加分型/笔/中枢标记 (Q6 方案A)
 *
 * 复用 echarts 依赖, 不引入新前端库。
 * 标记规则:
 *   - 分型: 顶分型 ▲ 红色, 底分型 ▽ 绿色
 *   - 笔: 连线 + 方向色 (上红下绿)
 *   - 中枢: 半透明矩形
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { CzscAnalyzeResult } from '@/lib/api'

interface Props {
  result: CzscAnalyzeResult
  /** K 线数据 (symbol+freq+日期范围对应的 OHLC), 由调用方提供 */
  klines?: Array<{ date: string; open: number; high: number; low: number; close: number; vol: number }>
  height?: number
}

export function CzscChart({ result, klines = [], height = 480 }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
    }
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!chartRef.current) return

    // K 线数据 (如未提供, 用分析结果中的分型/笔构造占位)
    const candleData = klines.length
      ? klines.map(k => [k.open, k.close, k.low, k.high])
      : []

    // 分型标记
    const fxMarks = result.fx_list.map(fx => ({
      name: fx.dt,
      coord: [fx.dt, fx.mark === 'Mark.G' ? fx.high : fx.low],
      symbol: fx.mark === 'Mark.G' ? 'triangle' : 'pin',
      symbolSize: 12,
      itemStyle: {
        color: fx.mark === 'Mark.G' ? '#ef4444' : '#22c55e',
      },
      label: {
        show: false,
      },
    }))

    // 笔连线 (series: lines)
    const biLines = result.bi_list.map(bi => ({
      coords: [
        [bi.sdt, bi.direction === 'Direction.Up' ? bi.low : bi.high],
        [bi.edt, bi.direction === 'Direction.Up' ? bi.high : bi.low],
      ],
      lineStyle: {
        color: bi.direction === 'Direction.Up' ? '#ef4444' : '#22c55e',
        width: 1.5,
        type: 'solid' as const,
      },
    }))

    // 中枢矩形 (markArea)
    const zsAreas = result.zs_list.map(zs => ([
      {
        xAxis: zs.start_dt,
        yAxis: zs.zs_range[0],
      },
      {
        xAxis: zs.end_dt,
        yAxis: zs.zs_range[1],
      },
    ]))

    const option = {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { data: ['K线', '分型', '笔', '中枢'], top: 0 },
      grid: { left: '5%', right: '5%', top: 40, bottom: 60 },
      xAxis: {
        type: 'category',
        data: klines.map(k => k.date),
      },
      yAxis: { scale: true, splitLine: { show: false } },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { show: true, type: 'slider', top: '90%', start: 0, end: 100 },
      ],
      series: [
        ...(candleData.length ? [{
          name: 'K线',
          type: 'candlestick' as const,
          data: candleData,
          itemStyle: {
            color: '#ef4444',
            color0: '#22c55e',
            borderColor: '#ef4444',
            borderColor0: '#22c55e',
          },
        }] : []),
        {
          name: '分型',
          type: 'scatter' as const,
          data: [],
          markPoint: { data: fxMarks },
        },
        {
          name: '笔',
          type: 'lines' as const,
          coordinateSystem: 'cartesian2d',
          polyline: false,
          data: biLines,
        },
        {
          name: '中枢',
          type: 'line' as const,
          data: [],
          markArea: {
            silent: true,
            itemStyle: {
              color: 'rgba(59, 130, 246, 0.15)',
              borderColor: 'rgba(59, 130, 246, 0.4)',
              borderWidth: 1,
            },
            data: zsAreas,
          },
        },
      ],
    } as echarts.EChartsOption

    chartRef.current.setOption(option, true)
  }, [result, klines])

  return <div ref={ref} style={{ width: '100%', height }} />
}
