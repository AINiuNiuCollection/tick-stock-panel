/**
 * Tab 4 市场结构 (v3-⑤) — 全市场宽度走势 + 当前快照。
 *
 * 数据: /api/market/breadth (data/research/breadth_daily.parquet, 指纹缓存)。
 * 缺失/过期时提供「重新计算」按钮 (POST /breadth/rebuild, 全历史扫描)。
 * 铁律: 零预测性文字 — 只呈现宽度事实。
 */
import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { api, type MarketBreadthRow } from '@/lib/api'

const RANGE_OPTIONS = [
  { label: '近250日', days: 250 },
  { label: '近2年', days: 480 },
  { label: '近5年', days: 1200 },
  { label: '全历史', days: 100000 },
]

function fmtPct(v: number | null | undefined): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`
}

function fmtAmount(v: number | null | undefined): string {
  if (v == null) return '—'
  if (v >= 1e12) return `${(v / 1e12).toFixed(2)} 万亿`
  if (v >= 1e8) return `${(v / 1e8).toFixed(0)} 亿`
  return v.toLocaleString('zh-CN')
}

function BreadthChart({ rows, height = 380 }: { rows: MarketBreadthRow[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) chartRef.current = echarts.init(ref.current)
    const chart = chartRef.current
    const option: echarts.EChartsCoreOption = {
      tooltip: { trigger: 'axis' },
      legend: { top: 0, data: ['站上MA20占比', '创60日新高占比'] },
      grid: { left: 8, right: 16, top: 26, bottom: 40, containLabel: true },
      xAxis: {
        type: 'category',
        data: rows.map((r) => r.date),
        axisLabel: { formatter: (v: string) => v.slice(0, 7) },
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: 1,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: '#eef0f3' } },
      },
      dataZoom: [{ type: 'inside' }, { type: 'slider', bottom: 2, height: 18 }],
      series: [
        {
          name: '站上MA20占比',
          type: 'line',
          data: rows.map((r) => r.pct_above_ma20),
          showSymbol: false,
          lineStyle: { width: 1.3, color: '#f59e0b' },
          itemStyle: { color: '#f59e0b' },
          areaStyle: { opacity: 0.06 },
        },
        {
          name: '创60日新高占比',
          type: 'line',
          data: rows.map((r) => r.pct_new_high_60d),
          showSymbol: false,
          lineStyle: { width: 1.3, color: '#8b5cf6' },
          itemStyle: { color: '#8b5cf6' },
        },
      ],
    }
    chart.setOption(option, { notMerge: true })
  }, [rows])
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !ref.current) return
    let ro: ResizeObserver | undefined
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => chart.resize())
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

export function MarketStructureTab() {
  const qc = useQueryClient()
  const [days, setDays] = useState(250)
  const [rebuilding, setRebuilding] = useState(false)
  const q = useQuery({
    queryKey: ['market-breadth', days],
    queryFn: () => api.marketBreadth(days),
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const rebuild = async () => {
    setRebuilding(true)
    try {
      await api.marketBreadthRebuild()
      await qc.invalidateQueries({ queryKey: ['market-breadth'] })
    } finally {
      setRebuilding(false)
    }
  }

  if (q.isLoading) {
    return (
      <div className="h-full grid place-items-center">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    )
  }
  if (q.isError) {
    // 404 = 未计算/过期; 其他错误直接透出
    return (
      <div className="h-full grid place-items-center px-8">
        <div className="text-center max-w-md">
          <p className="text-sm text-secondary">
            宽度序列未就绪 ({q.error instanceof Error ? q.error.message : '未知错误'})
          </p>
          <button
            onClick={rebuild}
            disabled={rebuilding}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-accent px-3 py-1.5 text-sm text-accent hover:bg-accent hover:text-white disabled:opacity-50"
          >
            {rebuilding ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {rebuilding ? '全历史扫描中…' : '重新计算 (全历史)'}
          </button>
        </div>
      </div>
    )
  }
  const data = q.data
  if (!data) return null
  const last = data.rows[data.rows.length - 1]

  return (
    <div className="h-full overflow-y-auto p-5">
      {/* 范围切换 + 重建 */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex gap-1">
          {RANGE_OPTIONS.map((o) => (
            <button
              key={o.days}
              onClick={() => setDays(o.days)}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                days === o.days ? 'bg-accent text-white' : 'border border-border text-muted hover:text-foreground'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
        <button
          onClick={rebuild}
          disabled={rebuilding}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1 text-xs text-muted hover:text-foreground disabled:opacity-50"
          title="enriched 分区更新后全量重算宽度序列"
        >
          {rebuilding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          {rebuilding ? '扫描中…' : '重算'}
        </button>
      </div>

      {/* 宽度走势图 */}
      <section className="rounded-lg border border-border bg-card p-4">
        <header className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-foreground">全市场宽度走势</h3>
          <span className="text-[10px] text-muted">
            样本 = 沪深北全市场个股 ({last?.sample_count} 只) · 数据截至 {data.as_of}
          </span>
        </header>
        <div className="mt-2">
          <BreadthChart rows={data.rows} />
        </div>
      </section>

      {/* 当前快照 */}
      <section className="mt-3 rounded-lg border border-border bg-card p-4">
        <h3 className="text-sm font-medium text-foreground">当前结构快照 · {data.as_of}</h3>
        {last && (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-x-8 gap-y-1.5 text-sm">
            <KV k="站上 MA20 占比" v={fmtPct(last.pct_above_ma20)} tone={last.pct_above_ma20 >= 0.5 ? 'up' : 'down'} />
            <KV k="创 60 日新高占比" v={fmtPct(last.pct_new_high_60d)} />
            <KV k="全市场成交额" v={fmtAmount(last.total_amount)} />
            <KV
              k="成交额 250 日分位"
              v={last.amount_pctile_250 == null ? '—' : fmtPct(last.amount_pctile_250)}
              tone={last.amount_level === 'extreme_high' ? 'up' : last.amount_level === 'extreme_low' ? 'down' : undefined}
            />
          </div>
        )}
        <p className="mt-2 text-xs text-muted">
          宽度 = 全市场个股口径 (不含指数); 序列共 {data.total_days} 个交易日, 缓存指纹随 enriched 分区更新自动过期。
        </p>
      </section>
    </div>
  )
}
