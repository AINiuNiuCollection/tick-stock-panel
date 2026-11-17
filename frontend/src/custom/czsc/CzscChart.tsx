/**
 * 缠论分析 ECharts 可视化 — K 线叠加分型/笔/中枢标记 (Q6 方案A)
 *
 * 复用 echarts 依赖, 不引入新前端库。
 * 标记规则:
 *   - 分型: 顶分型 ▲ 红色, 底分型 ▽ 绿色
 *   - 笔: 连线 + 方向色 (上红下绿)
 *   - 中枢: 半透明矩形
 */
import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react'
import * as echarts from 'echarts'
import type { CzscAnalyzeResult } from '@/lib/api'

/** 判断顶分型: czsc 1.0.2 返回 mark='顶分型' (旧版 'Mark.G') */
function isTopMark(mark: string): boolean {
  return mark === 'Mark.G' || mark === '顶分型' || mark.includes('顶')
}

/** 判断向上笔: czsc 1.0.2 返回 direction='向上' (旧版 'Direction.Up') */
function isUpDirection(direction: string): boolean {
  return direction === 'Direction.Up' || direction === '向上' || direction.includes('上')
}

/**
 * 主题配色 — 对齐 czsc 库原生 lightweight-charts 主题 (czsc/utils/plotting/lightweight/_theme.py)。
 * light "量化年鉴" 暖纸色调 / dark "Deep Cosmos" 深空配色, 与本工程 html.dark 切换联动。
 * 中枢矩形色为本工程自定义 (czsc 原生不画中枢), 选用与 bi 笔色同系的靛蓝/淡蓝, 与 K 线红绿区分。
 */
interface ChartTheme {
  background: string
  text: string
  grid: string
  up: string       // K 线涨色 (阳线)
  down: string     // K 线跌色 (阴线)
  fx: string       // 分型标记色
  bi: string       // 笔色
  zsFill: string   // 中枢矩形填充
  zsBorder: string // 中枢矩形边框
  zsLine: string   // 中枢上下沿虚线
}

function getChartTheme(): ChartTheme {
  const isDark = typeof document !== 'undefined'
    && document.documentElement.classList.contains('dark')
  if (isDark) {
    // czsc dark "Deep Cosmos"
    return {
      background: '#0E1116',
      text: '#EFEBE0',
      grid: '#1F242E',
      up: '#E94B3C',
      down: '#5BB85B',
      fx: '#E6A93B',     // SMA5 古铜色, 让分型标记与 K 线红绿区分
      bi: '#A8B8E8',     // 笔淡蓝
      zsFill: 'rgba(168, 184, 232, 0.18)',
      zsBorder: 'rgba(168, 184, 232, 0.7)',
      zsLine: 'rgba(168, 184, 232, 0.6)',
    }
  }
  // czsc light "量化年鉴" 暖纸色
  return {
    background: '#FBF9F4',
    text: '#1A1A17',
    grid: '#E8E2D4',
    up: '#C03A2B',
    down: '#2E7D32',
    fx: '#C78A2E',      // SMA5 古铜
    bi: '#1F3C6E',      // 笔深靛蓝
    zsFill: 'rgba(31, 60, 110, 0.18)',
    zsBorder: 'rgba(31, 60, 110, 0.7)',
    zsLine: 'rgba(31, 60, 110, 0.6)',
  }
}

export interface CzscChartHandle {
  /** 导出当前图表为 base64 PNG dataURL (供 HTML 报告嵌入) */
  getDataURL: () => string | null
}

interface Props {
  result: CzscAnalyzeResult
  /**
   * K 线数据 (OHLCV), 由调用方提供。
   * 若不传, 自动从 result.bars 推导 (后端 analyze 响应已含 bars 字段)。
   * 兼容旧调用方传 {date, open, ...} 格式 (date 字段), 优先级高于 result.bars。
   */
  klines?: Array<{ date: string; open: number; high: number; low: number; close: number; vol: number }>
  height?: number
}

export const CzscChart = forwardRef<CzscChartHandle, Props>(function CzscChart(
  { result, klines, height = 480 },
  ref,
) {
  // 优先用显式传入的 klines; 否则从 result.bars 推导 (date 字段 = dt)
  const resolvedKlines = klines && klines.length
    ? klines
    : (result.bars ?? []).map(b => ({ date: b.dt, open: b.open, high: b.high, low: b.low, close: b.close, vol: b.vol }))
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  // 暴露 getDataURL 给父组件, 供 HTML 报告导出嵌入 PNG
  useImperativeHandle(ref, () => ({
    getDataURL: () => {
      if (!chartRef.current) return null
      try {
        return chartRef.current.getDataURL({
          type: 'png',
          pixelRatio: 2,
          backgroundColor: '#ffffff',
        })
      } catch (e) {
        console.error('CzscChart getDataURL failed:', e)
        return null
      }
    },
  }), [])

  useEffect(() => {
    if (!chartRef.current) return

    // K 线数据 (优先用显式 klines, 否则从 result.bars 推导)
    const candleData = resolvedKlines.length
      ? resolvedKlines.map(k => [k.open, k.close, k.low, k.high])
      : []

    // 分型标记
    const fxMarks = result.fx_list.map(fx => ({
      name: fx.dt,
      coord: [fx.dt, isTopMark(fx.mark) ? fx.high : fx.low],
      symbol: isTopMark(fx.mark) ? 'triangle' : 'pin',
      symbolSize: 12,
      itemStyle: {
        color: isTopMark(fx.mark) ? '#ef4444' : '#22c55e',
      },
      label: {
        show: false,
      },
    }))

    // 笔连线 (series: lines)
    const biLines = result.bi_list.map(bi => ({
      coords: [
        [bi.sdt, isUpDirection(bi.direction) ? bi.low : bi.high],
        [bi.edt, isUpDirection(bi.direction) ? bi.high : bi.low],
      ],
      lineStyle: {
        color: isUpDirection(bi.direction) ? '#ef4444' : '#22c55e',
        width: 1.5,
        type: 'solid' as const,
      },
    }))

    // 中枢矩形 (markArea) — czsc 中枢 = 至少 3 笔重叠的价格区间 [zd, zg]
    // markArea[[{xAxis,yAxis},{xAxis,yAxis}], ...] 每个矩形由对角线两点定义 (左下 + 右上)
    // itemStyle 必须写在 markArea 顶层 (对所有矩形生效), 写在点对象里会被 echarts 忽略
    const zsAreas = result.zs_list.map(zs => ([
      { xAxis: zs.start_dt, yAxis: zs.zs_range[0] },
      { xAxis: zs.end_dt,   yAxis: zs.zs_range[1] },
    ]))

    // 中枢上下沿水平虚线 (markLine) — 仅在中枢时间范围内绘制, 标注 zd/zg 数值
    // 用两点连线格式 [[startCoord, endCoord], ...], 避免单点水平线横跨整个图表
    const zsMarkLines = result.zs_list.flatMap(zs => ([
      [
        { coord: [zs.start_dt, zs.zs_range[0]] },
        { coord: [zs.end_dt,   zs.zs_range[0]], label: { formatter: `zd ${zs.zs_range[0].toFixed(2)}`, color: '#2563eb', fontSize: 10, position: 'insideEndTop' } },
      ],
      [
        { coord: [zs.start_dt, zs.zs_range[1]] },
        { coord: [zs.end_dt,   zs.zs_range[1]], label: { formatter: `zg ${zs.zs_range[1].toFixed(2)}`, color: '#2563eb', fontSize: 10, position: 'insideEndTop' } },
      ],
    ]))

    const option = {
      // 强制白底, 保证 K 线红绿 / 中枢蓝 / 分型标记在暗色主题下也清晰可辨
      backgroundColor: '#ffffff',
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: { data: ['K线', '分型', '笔', '中枢'], top: 0, textStyle: { color: '#1e293b' } },
      grid: { left: '6%', right: '6%', top: 40, bottom: 60 },
      xAxis: {
        type: 'category',
        data: resolvedKlines.map(k => k.date),
        axisLabel: { color: '#475569', fontSize: 11 },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
      },
      yAxis: {
        scale: true,
        splitLine: { show: true, lineStyle: { color: '#e2e8f0', type: 'dashed' } },
        axisLabel: { color: '#475569', fontSize: 11 },
        axisLine: { lineStyle: { color: '#cbd5e1' } },
      },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { show: true, type: 'slider', top: '90%', start: 0, end: 100, textStyle: { color: '#475569' } },
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
              color: 'rgba(59, 130, 246, 0.35)',
              borderColor: 'rgba(59, 130, 246, 0.9)',
              borderWidth: 1.5,
            },
            data: zsAreas,
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: zsMarkLines,
          },
        },
      ],
    } as echarts.EChartsOption

    chartRef.current.setOption(option, true)
  }, [result, resolvedKlines])

  return <div ref={containerRef} style={{ width: '100%', height }} />
})
