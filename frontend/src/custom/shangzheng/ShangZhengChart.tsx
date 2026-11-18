/**
 * 上证策略图表 — 净值曲线 + 买卖点标记 + K 线模式
 *
 * mode='nav': 策略净值 vs 基准净值 (对齐 HTML chartNav)
 * mode='signals': 净值曲线上标记 B/S 买卖点 (对齐 HTML chartMain 的简化)
 * mode='kline': K 线 + 买卖点标记 (对齐 HTML chartMain, 需传入 klineRows)
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { StrategyBacktestTrade, KlineRow } from '@/lib/api'

interface EquityPoint {
  date: string
  value: number
  cash?: number
  positions?: number
  exposure?: number
}

interface BenchmarkPoint {
  date: string
  value: number
  close?: number
  name?: string
  symbol?: string
}

interface Props {
  equityCurve: EquityPoint[]
  benchmarkCurve: BenchmarkPoint[]
  trades: StrategyBacktestTrade[]
  height: number
  mode: 'nav' | 'signals' | 'kline'
  klineRows?: KlineRow[]
}

const BUY_COLOR = '#2563eb'
const SELL_COLOR = '#f59e0b'
const UP_COLOR = '#e24b4a'
const DN_COLOR = '#1d9e75'

export function ShangZhengChart({ equityCurve, benchmarkCurve, trades, height, mode, klineRows }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
    }
    const chart = chartRef.current

    // K 线模式: 用 klineRows 绘制 candlestick + 买卖点
    if (mode === 'kline' && klineRows && klineRows.length > 0) {
      const dates = klineRows.map((r) => r.date)
      const ohlc = klineRows.map((r) => [r.open, r.close, r.low, r.high])
      const vols = klineRows.map((r) => r.volume ?? 0)

      const buyPoints = trades
        .map((t) => {
          const idx = dates.indexOf(t.entry_date)
          if (idx < 0) return null
          const row = klineRows[idx]
          return {
            coord: [idx, row.low * 0.995],
            symbol: 'triangle',
            symbolSize: 12,
            symbolRotate: 0,
            itemStyle: { color: BUY_COLOR },
            label: { show: true, formatter: 'B', fontSize: 9, color: BUY_COLOR, offset: [0, 12] },
          }
        })
        .filter(Boolean) as any[]

      const sellPoints = trades
        .map((t) => {
          const idx = dates.indexOf(t.exit_date)
          if (idx < 0) return null
          const row = klineRows[idx]
          return {
            coord: [idx, row.high * 1.005],
            symbol: 'triangle',
            symbolSize: 12,
            symbolRotate: 180,
            itemStyle: { color: SELL_COLOR },
            label: { show: true, formatter: 'S', fontSize: 9, color: SELL_COLOR, offset: [0, -12] },
          }
        })
        .filter(Boolean) as any[]

      const option: echarts.EChartsCoreOption = {
        grid: [
          { left: 8, right: 16, top: 16, height: '70%', containLabel: true },
          { left: 8, right: 16, top: '78%', height: '18%', containLabel: true },
        ],
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
        },
        xAxis: [
          {
            type: 'category',
            data: dates,
            axisLabel: {
              formatter: (val: string) => {
                const m = val.slice(5, 7)
                return `${parseInt(m, 10)}月`
              },
              width: 56,
              overflow: 'truncate',
            },
            axisLine: { lineStyle: { color: '#e5e7eb' } },
          },
          {
            type: 'category',
            gridIndex: 1,
            data: dates,
            axisLabel: { show: false },
            axisLine: { lineStyle: { color: '#e5e7eb' } },
          },
        ],
        yAxis: [
          {
            type: 'value',
            scale: true,
            axisLabel: { formatter: (v: number) => v.toFixed(0), width: 56 },
            splitLine: { lineStyle: { color: '#eef0f3' } },
          },
          {
            type: 'value',
            gridIndex: 1,
            axisLabel: { show: false },
            splitLine: { show: false },
          },
        ],
        series: [
          {
            name: 'K线',
            type: 'candlestick',
            data: ohlc,
            itemStyle: {
              color: UP_COLOR,
              color0: DN_COLOR,
              borderColor: UP_COLOR,
              borderColor0: DN_COLOR,
            },
            markPoint: {
              data: [...buyPoints, ...sellPoints],
              animation: false,
            },
          },
          {
            name: '成交量',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: klineRows.map((r, i) => ({
              value: vols[i],
              itemStyle: { color: r.close >= r.open ? UP_COLOR : DN_COLOR, opacity: 0.5 },
            })),
          },
        ],
      }
      chart.setOption(option, { notMerge: true })
      return
    }

    // 默认: 净值曲线模式 (nav / signals)
    const dates = equityCurve.map((p) => p.date)
    const navValues = equityCurve.map((p) => p.value)
    const benchValues = benchmarkCurve.length
      ? benchmarkCurve.map((p) => p.value)
      : []

    const buyPoints = trades
      .map((t) => {
        const idx = dates.indexOf(t.entry_date)
        if (idx < 0) return null
        return {
          coord: [idx, navValues[idx]],
          symbol: 'triangle',
          symbolSize: 10,
          itemStyle: { color: BUY_COLOR },
          label: { show: false },
        }
      })
      .filter(Boolean) as any[]

    const sellPoints = trades
      .map((t) => {
        const idx = dates.indexOf(t.exit_date)
        if (idx < 0) return null
        return {
          coord: [idx, navValues[idx]],
          symbol: 'pin',
          symbolSize: 10,
          itemStyle: { color: SELL_COLOR },
          label: { show: false },
        }
      })
      .filter(Boolean) as any[]

    const series: echarts.SeriesOption[] = [
      {
        name: '策略净值',
        type: 'line',
        data: navValues,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: BUY_COLOR, width: 1.5 },
        areaStyle: mode === 'nav' ? { opacity: 0.08 } : undefined,
        markPoint: {
          data: [...buyPoints, ...sellPoints],
          animation: false,
        },
      },
    ]

    if (mode === 'nav' && benchValues.length) {
      series.push({
        name: '基准',
        type: 'line',
        data: benchValues,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#9aa4b0', width: 1, type: 'dashed' },
      })
    }

    const option: echarts.EChartsCoreOption = {
      grid: { left: 8, right: 16, top: 16, bottom: 24, containLabel: true },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        valueFormatter: (v: any) => (typeof v === 'number' ? v.toFixed(4) : String(v)),
      },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: {
          formatter: (val: string) => {
            const m = val.slice(5, 7)
            return `${parseInt(m, 10)}月`
          },
          width: 56,
          overflow: 'truncate',
        },
        axisLine: { lineStyle: { color: '#e5e7eb' } },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: {
          formatter: (v: number) => v.toFixed(2),
          width: 56,
        },
        splitLine: { lineStyle: { color: '#eef0f3' } },
      },
      series,
    }

    chart.setOption(option, { notMerge: true })
  }, [equityCurve, benchmarkCurve, trades, mode, klineRows])

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
