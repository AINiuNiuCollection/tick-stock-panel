/**
 * Tab 0 总览仪表盘 (设计 §1.1, v3-④ 图表化重构) — "现在是什么市, 处于什么位置?"
 *
 * 铁律: 零预测性文字 — 只呈现状态与统计事实, 判断留给交易员。
 * 图表为主: ①近250日价格走势 (K线+MA20/60+事件旗标+最新点标注)
 *          ②量能水位走势 (额+5日均额线)  ③MA20 偏离走势 (%)
 * 文字压缩为底部小卡: 当前状态 / 缠论快照 / 临近事件 / 信号模块。
 */
import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { useQuery } from '@tanstack/react-query'
import { CalendarDays, Gauge, Loader2, TrendingDown, TrendingUp } from 'lucide-react'
import { api, type MarketOverviewResponse } from '@/lib/api'

const UP_COLOR = '#e24b4a'
const DN_COLOR = '#1d9e75'
const MA20_COLOR = '#f59e0b'
const MA60_COLOR = '#8b5cf6'
const FLAG_POS = '#c0392b'
const FLAG_NEG = '#1d9e75'

function fmtNum(v: number | null | undefined, digits = 2): string {
  return v == null ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function fmtPct(v: number | null | undefined): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

function fmtAmount(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} 万亿`
  if (v >= 1e8) return `${(v / 1e8).toFixed(0)} 亿`
  return v.toLocaleString('zh-CN')
}

const VOLUME_LEVEL_LABEL: Record<string, string> = {
  extreme_high: '极端放量',
  extreme_low: '极端缩量',
  normal: '常态区间',
}

/** 通用 echarts 容器: init 一次 + ResizeObserver 兜底 resize */
function useChart(option: echarts.EChartsCoreOption, deps: unknown[], height: number | string) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) chartRef.current = echarts.init(ref.current)
    const chart = chartRef.current
    chart.setOption(option, { notMerge: true })
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !ref.current) return
    const onResize = () => chart.resize()
    let ro: ResizeObserver | undefined
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(onResize)
      ro.observe(ref.current)
    }
    return () => {
      ro?.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])
  return <div ref={ref} style={{ height, width: '100%' }} />
}

function PriceChart({ data, height = 360 }: { data: MarketOverviewResponse; height?: number }) {
  const c = data.chart
  const closes = c.ohlc.map((r) => r[1])
  const flags = c.event_flags
    .map((f) => {
      const idx = c.dates.indexOf(f.date)
      if (idx < 0) return null
      const bar = c.ohlc[idx]
      const color = f.category === 'trade' ? FLAG_POS : FLAG_NEG
      return {
        coord: [idx, bar[2] * 0.99],
        symbol: 'triangle',
        symbolSize: 10,
        itemStyle: { color },
        label: { show: true, formatter: '▌', fontSize: 10, color, position: 'bottom' },
        eventTitle: `${f.date} ${f.title}`,
      }
    })
    .filter((p): p is NonNullable<typeof p> => p !== null)
  const last = c.dates.length - 1
  const lastClose = closes[last]
  const option: echarts.EChartsCoreOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { top: 0, data: ['收盘', 'MA20', 'MA60'] },
    grid: { left: 8, right: 16, top: 26, bottom: 24, containLabel: true },
    xAxis: {
      type: 'category',
      data: c.dates,
      axisLabel: { formatter: (v: string) => v.slice(0, 7) },
    },
    yAxis: { type: 'value', scale: true, splitLine: { lineStyle: { color: '#eef0f3' } } },
    dataZoom: [{ type: 'inside' }],
    series: [
      {
        name: '收盘',
        type: 'candlestick',
        data: c.ohlc,
        itemStyle: { color: UP_COLOR, color0: DN_COLOR, borderColor: UP_COLOR, borderColor0: DN_COLOR },
        markPoint: {
          data: [
            ...flags,
            {
              coord: [last, lastClose],
              symbol: 'pin',
              symbolSize: 46,
              itemStyle: { color: UP_COLOR },
              label: { show: true, formatter: lastClose.toFixed(0), fontSize: 10, color: '#fff' },
            },
          ] as any[],
          animation: false,
        },
      },
      { name: 'MA20', type: 'line', data: c.ma20, showSymbol: false, lineStyle: { width: 1.2, color: MA20_COLOR }, itemStyle: { color: MA20_COLOR } },
      { name: 'MA60', type: 'line', data: c.ma60, showSymbol: false, lineStyle: { width: 1.2, color: MA60_COLOR }, itemStyle: { color: MA60_COLOR } },
    ],
  }
  return useChart(option, [data], height)
}

function VolumeChart({ data, height = 180 }: { data: MarketOverviewResponse; height?: number }) {
  const c = data.chart
  const option: echarts.EChartsCoreOption = {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: ['日成交额', '5日均额'] },
    grid: { left: 8, right: 16, top: 26, bottom: 24, containLabel: true },
    xAxis: { type: 'category', data: c.dates, axisLabel: { show: false } },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => (v >= 1e8 ? `${(v / 1e8).toFixed(0)}亿` : `${v}`) },
      splitLine: { lineStyle: { color: '#eef0f3' } },
    },
    series: [
      { name: '日成交额', type: 'bar', data: c.amounts, itemStyle: { color: '#93c5fd' } },
      { name: '5日均额', type: 'line', data: c.amt5, showSymbol: false, lineStyle: { width: 1.4, color: MA20_COLOR }, itemStyle: { color: MA20_COLOR } },
    ],
  }
  return useChart(option, [data], height)
}

function DevChart({ data, height = 180 }: { data: MarketOverviewResponse; height?: number }) {
  const c = data.chart
  // MA20 偏离% = (close-MA20)/MA20*100, 前端逐点计算 (与后端 price.ma20_dev_pct 同口径)
  const dev = c.ohlc.map((r, i) => {
    const ma = c.ma20[i]
    return ma == null || ma === 0 ? null : ((r[1] - ma) / ma) * 100
  })
  const option: echarts.EChartsCoreOption = {
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v: number) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`),
    },
    grid: { left: 8, right: 16, top: 14, bottom: 24, containLabel: true },
    xAxis: { type: 'category', data: c.dates, axisLabel: { show: false } },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (v: number) => `${v}%` },
      splitLine: { lineStyle: { color: '#eef0f3' } },
    },
    series: [
      {
        name: 'MA20偏离',
        type: 'line',
        data: dev,
        showSymbol: false,
        lineStyle: { width: 1.4, color: MA60_COLOR },
        itemStyle: { color: MA60_COLOR },
        areaStyle: { opacity: 0.08 },
        markLine: {
          silent: true,
          symbol: 'none',
          label: { show: false },
          data: [{ yAxis: 0 }],
          lineStyle: { color: '#94a3b8', type: 'dashed' },
        },
      },
    ],
  }
  return useChart(option, [data], height)
}

function Card({ title, asOf, icon, children, className = '' }: { title: string; asOf?: string; icon: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-border bg-card p-4 ${className}`}>
      <header className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          <span className="text-accent">{icon}</span>
          {title}
        </h3>
        {asOf && <span className="text-[10px] text-muted">数据截至 {asOf}</span>}
      </header>
      <div className="mt-3 text-sm leading-relaxed">{children}</div>
    </section>
  )
}

function KV({ k, v, tone }: { k: string; v: string; tone?: 'up' | 'down' }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted">{k}</span>
      <span
        className={`font-mono ${
          tone === 'up' ? 'text-red-600 dark:text-red-400' : tone === 'down' ? 'text-green-600 dark:text-green-400' : 'text-foreground'
        }`}
      >
        {v}
      </span>
    </div>
  )
}

function Body({ data }: { data: MarketOverviewResponse }) {
  const { price: p, ma20_streak: streak, volume: vol, czsc, upcoming, as_of, index_symbol } = data
  return (
    <div className="flex flex-col gap-3 p-5">
      {/* ① 近250日价格走势 — K线 + MA20/60 + 事件旗标 + 最新点标注 */}
      <section className="rounded-lg border border-border bg-card p-4">
        <header className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">
            近 250 日走势 · {index_symbol}
          </h3>
          <span className="text-[10px] text-muted">
            数据截至 {as_of} · 旗标 = 政策事件 (hover 见详情)
          </span>
        </header>
        <div className="mt-2">
          <PriceChart data={data} />
        </div>
      </section>

      {/* ②③ 量能水位 + MA20 偏离 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <section className="rounded-lg border border-border bg-card p-4">
          <header className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">量能水位</h3>
            {vol && (
              <span className="text-xs text-muted">
                250日分位 <span className="font-mono text-foreground">{(vol.percentile_250 * 100).toFixed(1)}%</span>
                <span
                  className={`ml-2 ${
                    vol.level === 'extreme_high'
                      ? 'text-red-600 dark:text-red-400'
                      : vol.level === 'extreme_low'
                        ? 'text-green-600 dark:text-green-400'
                        : 'text-foreground'
                  }`}
                >
                  {VOLUME_LEVEL_LABEL[vol.level] ?? vol.level}
                </span>
              </span>
            )}
          </header>
          <div className="mt-2">
            <VolumeChart data={data} />
          </div>
          {vol && (
            <p className="mt-1 text-xs text-muted">近 5 日日均成交额 {fmtAmount(vol.last_5d_amount)}</p>
          )}
        </section>

        <section className="rounded-lg border border-border bg-card p-4">
          <header className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">MA20 偏离走势</h3>
            <span className="text-xs text-muted">0 轴 = 20 日线</span>
          </header>
          <div className="mt-2">
            <DevChart data={data} />
          </div>
        </section>
      </div>

      {/* 文字态压缩为小卡 */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <Card title="当前状态" asOf={as_of} icon={<Gauge size={15} />}>
          <KV k="最新收盘" v={fmtNum(p.close)} />
          <KV k="当日涨跌" v={fmtPct(p.pct_change_pct)} tone={p.pct_change_pct == null ? undefined : p.pct_change_pct >= 0 ? 'up' : 'down'} />
          <KV k="距 20 日线" v={fmtPct(p.ma20_dev_pct)} tone={p.ma20_dev_pct == null ? undefined : p.ma20_dev_pct >= 0 ? 'up' : 'down'} />
          <KV k="距 60 日线" v={fmtPct(p.ma60_dev_pct)} tone={p.ma60_dev_pct == null ? undefined : p.ma60_dev_pct >= 0 ? 'up' : 'down'} />
          <KV k="距 250 日线" v={fmtPct(p.ma250_dev_pct)} tone={p.ma250_dev_pct == null ? undefined : p.ma250_dev_pct >= 0 ? 'up' : 'down'} />
        </Card>

        <Card title="均线状态" asOf={as_of} icon={streak?.above ? <TrendingUp size={15} /> : <TrendingDown size={15} />}>
          {streak ? (
            <>
              <KV k="收盘位置" v={streak.above ? '20 日线上方' : '20 日线下方'} tone={streak.above ? 'up' : 'down'} />
              <KV k="连续天数" v={`${streak.days} 个交易日`} />
            </>
          ) : (
            <p className="text-muted">均线暖机数据不足</p>
          )}
          <div className="my-2 border-t border-border/60" />
          <KV
            k="日线笔方向"
            v={czsc.daily_bi_direction === 'up' ? '向上' : czsc.daily_bi_direction === 'down' ? '向下' : '笔数据不足'}
            tone={czsc.daily_bi_direction === 'up' ? 'up' : czsc.daily_bi_direction === 'down' ? 'down' : undefined}
          />
        </Card>

        <Card title="临近事件 · 未来 7 天" asOf={as_of} icon={<CalendarDays size={15} />}>
          {upcoming.length ? (
            <ul className="space-y-1.5">
              {upcoming.map((u, i) => (
                <li key={`${u.date}-${i}`} className="flex justify-between gap-2">
                  <span className="text-foreground">{u.title}</span>
                  <span className="font-mono text-xs text-muted">{u.date}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">未来 7 天无已知固定政策日历</p>
          )}
        </Card>

        <Card title="信号模块" asOf={as_of} icon={<Gauge size={15} />}>
          <ul className="space-y-1">
            {data.modules.map((m) => (
              <li key={m.id} className="flex justify-between gap-2 text-xs">
                <span className="text-foreground">{m.label}</span>
                <span className="font-mono text-muted">{m.id}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}

export function MarketOverviewTab() {
  const q = useQuery({
    queryKey: ['market-overview'],
    queryFn: () => api.marketOverview(),
    staleTime: 5 * 60 * 1000,
  })

  if (q.isLoading) {
    return (
      <div className="h-full grid place-items-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }
  if (q.isError) {
    return (
      <div className="h-full grid place-items-center px-8">
        <p className="text-sm text-red-600 dark:text-red-400">
          总览快照加载失败 ({q.error instanceof Error ? q.error.message : '未知错误'})
          <button className="ml-2 text-accent underline" onClick={() => q.refetch()}>
            重试
          </button>
        </p>
      </div>
    )
  }
  return (
    <div className="h-full overflow-y-auto">
      {q.data && <Body data={q.data} />}
    </div>
  )
}
