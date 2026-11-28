/**
 * 政策事件 Tab — 三层联动 (设计 §2.3):
 *   恒在层: 指数K线事件旗标 (利好▲红/利空▼绿/中性◆灰, 大小=importance), 筛选器实时过滤;
 *   检视层: 单击旗标/列表 → [T,T+20] 区间带 + 右侧抽屉 (迷你路径 vs 大盘基线 + 技术背景 + source);
 *   叠加层: 同类事件扇形图 (spaghetti + 均值粗线) + T+1/T+5/T+20 倍数直方图 + 统计表 (n<5 规则)。
 * 数据: /api/market/events (P3 §2.2 统计) + /api/market/events/series (迷你路径)。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, GripHorizontal, Loader2, Maximize2, Minimize2 } from 'lucide-react'
import {
  api,
  type MarketEventAggregateRow,
  type MarketPolicyEvent,
} from '@/lib/api'
import { MarketEventsChart } from './MarketEventsChart'
import { MiniPathChart, type SeriesLine } from './MiniPathChart'

const CATEGORIES = ['货币政策', '财政政策', '产业政策', '监管政策', '会议定调', '外部事件'] as const

function fmtPct(v: number | null | undefined): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}

/** n<5 规则: 小样本不显示百分比 (返回 null 由调用方显示 n) */
function fmtMed(row: MarketEventAggregateRow, key: 'median_t1' | 'median_t5' | 'median_t20' | 'median_t60'): string {
  const v = row[key]
  return v == null ? '—' : fmtPct(v)
}

// Esc 清除区间带 (设计 §2.3 联动规则)
function useEscHandler(onEsc: () => void) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onEsc()
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onEsc])
}

export function MarketEventsTab() {
  const [category, setCategory] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('') // ''=全部含draft
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // ---- 图表面板全屏 (Fullscreen API, 与缠论页同模式) ----
  const fsPanelRef = useRef<HTMLDivElement>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const toggleFullscreen = useCallback(() => {
    const el = fsPanelRef.current
    if (!el) return
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      void el.requestFullscreen?.()
    }
  }, [])
  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFsChange)
    return () => document.removeEventListener('fullscreenchange', onFsChange)
  }, [])

  // ---- 图表/下方内容 可拖动分割条 (占比 0.2~0.9, sessionStorage 持久化) ----
  const splitWrapRef = useRef<HTMLDivElement>(null)
  const [wrapHeight, setWrapHeight] = useState(0)
  const [chartRatio, setChartRatio] = useState<number>(() => {
    const saved = typeof window !== 'undefined' ? sessionStorage.getItem('market:events-chart-ratio') : null
    const n = saved ? Number(saved) : 0.62
    return Number.isFinite(n) && n >= 0.2 && n <= 0.9 ? n : 0.62
  })
  const dragRef = useRef<{ startY: number; startRatio: number } | null>(null)
  const chartRatioRef = useRef(chartRatio)
  chartRatioRef.current = chartRatio
  useEffect(() => {
    const el = splitWrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      const h = entries[0]?.contentRect.height
      if (h && h > 0) setWrapHeight(h)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const onSplitDown = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      e.preventDefault()
      dragRef.current = { startY: e.clientY, startRatio: chartRatio }
      ;(e.target as HTMLDivElement).setPointerCapture(e.pointerId)
    },
    [chartRatio],
  )
  const onSplitMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      const st = dragRef.current
      if (!st || wrapHeight <= 0) return
      const next = Math.min(0.9, Math.max(0.2, st.startRatio + (e.clientY - st.startY) / wrapHeight))
      setChartRatio(next)
    },
    [wrapHeight],
  )
  const onSplitUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragRef.current) {
      try {
        sessionStorage.setItem('market:events-chart-ratio', String(chartRatioRef.current))
      } catch {
        /* ignore */
      }
    }
    dragRef.current = null
    try {
      ;(e.target as HTMLDivElement).releasePointerCapture(e.pointerId)
    } catch {
      /* ignore */
    }
  }, [])

  const eventsQ = useQuery({
    queryKey: ['market-events'],
    queryFn: () => api.marketEvents(),
    staleTime: 5 * 60 * 1000,
  })
  const data = eventsQ.data

  const filtered = useMemo(() => {
    const evs = data?.events ?? []
    return evs.filter(
      (e) =>
        (!category || e.category === category) &&
        (!statusFilter || e.status === statusFilter),
    )
  }, [data, category, statusFilter])

  const onChart = useMemo(
    // 图上旗标: approved 事件 (draft 不上图, 只在列表标灰待审核)
    () => filtered.filter((e) => e.status === 'approved'),
    [filtered],
  )

  const selected = useMemo(
    () => filtered.find((e) => e.id === selectedId) ?? null,
    [filtered, selectedId],
  )

  // 列表↔图双向定位: 选中事件时图滚动到旗标 (chart 内部 dataZoom 由选中驱动, 此处只同步列表高亮)
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!selectedId || !listRef.current) return
    const el = listRef.current.querySelector(`[data-ev-id="${selectedId}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedId])

  useEscHandler(() => setSelectedId(null))

  return (
    <div className="flex h-full min-h-0">
      {/* 左: 主区 — 筛选器 + K线旗标图(可全屏/可拖占比) + 叠加层(滚动) */}
      <div ref={splitWrapRef} className="flex-1 min-w-0 flex flex-col gap-2 p-4 min-h-0">
        {/* 筛选器 (实时过滤, 不重载) */}
        <div className="shrink-0 flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted">类别</span>
          <FilterChip active={category === ''} onClick={() => setCategory('')}>
            全部
          </FilterChip>
          {CATEGORIES.map((c) => (
            <FilterChip key={c} active={category === c} onClick={() => setCategory(c)}>
              {c}
            </FilterChip>
          ))}
          <span className="ml-3 text-xs text-muted">状态</span>
          {[
            ['', '全部'],
            ['approved', '已确认'],
            ['draft', '待审核'],
          ].map(([v, label]) => (
            <FilterChip key={v} active={statusFilter === v} onClick={() => setStatusFilter(v)}>
              {label}
            </FilterChip>
          ))}
          {data && (
            <span className="ml-auto text-xs text-muted">
              共 {data.counts.total} 条 · 进统计 {data.counts.countable} · 待审核{' '}
              {data.counts.draft} (draft 不进统计)
            </span>
          )}
        </div>

        {eventsQ.isPending && (
          <div className="flex-1 grid place-items-center text-muted text-sm">
            <Loader2 className="animate-spin h-5 w-5" />
          </div>
        )}
        {eventsQ.isError && (
          <div className="h-[200px] grid place-items-center text-destructive text-sm">
            事件库加载失败: {(eventsQ.error as Error).message}
          </div>
        )}

        {data && (
          <>
            {/* 恒在层: K线 + 旗标 — 可全屏面板, 高度按 chartRatio 占比 */}
            {data.index_bars.length > 0 && (
              <div
                ref={fsPanelRef}
                className="relative rounded-btn border border-border bg-card min-h-0 flex flex-col"
                style={{ flex: `${chartRatio} 1 0` }}
              >
                <button
                  type="button"
                  onClick={toggleFullscreen}
                  title={isFullscreen ? '退出全屏 (Esc)' : 'K线图全屏'}
                  className="absolute right-2 top-2 z-10 p-1.5 rounded bg-base/80 border border-border text-muted hover:text-foreground hover:border-accent transition-colors"
                >
                  {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
                </button>
                <MarketEventsChart
                  height="100%"
                  bars={data.index_bars}
                  events={onChart}
                  selectedEvent={selected}
                  onSelect={(ev) => setSelectedId(ev.id === selectedId ? null : ev.id)}
                />
                {!isFullscreen && (
                  <p className="shrink-0 px-2 pb-1.5 text-[11px] text-muted">
                    ▲ 利好 (红) / ▼ 利空 (绿) / ◆ 中性 (灰), 大小=重要性; 点击旗标或列表 →
                    显示 [T, T+20] 区间带与右侧详情; Esc 或再次点击清除; 右上角可全屏。
                  </p>
                )}
              </div>
            )}

            {/* 可拖动分割条 — 调节K线图与下方内容高度占比 */}
            {data.index_bars.length > 0 && (
              <div
                onPointerDown={onSplitDown}
                onPointerMove={onSplitMove}
                onPointerUp={onSplitUp}
                onPointerCancel={onSplitUp}
                className="shrink-0 flex items-center justify-center h-3 cursor-row-resize border-y border-dashed border-border hover:border-accent hover:bg-accent/10 transition-colors"
                title="拖动调节K线图与下方区域高度"
              >
                <GripHorizontal className="h-3.5 w-3.5 text-muted" />
              </div>
            )}

            {/* 下半区: 叠加层 + 统计表 (滚动) */}
            <div
              className="min-h-0 overflow-y-auto flex flex-col gap-4 pr-1"
              style={{ flex: `${1 - chartRatio} 1 0` }}
            >
              <SpaghettiSection category={category} events={onChart} />

              {/* 统计表: direction × 技术背景 (n<5 规则) */}
              {data.aggregate.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">聚合统计 — direction × 技术背景 (中位数)</h3>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-muted border-b border-border">
                        <th className="text-left py-1.5 font-normal">方向</th>
                        <th className="text-left font-normal">{data.group_by === 'bi' ? '日线笔方向' : '20日线位置'}</th>
                        <th className="text-right font-normal">n</th>
                        <th className="text-right font-normal">T+1</th>
                        <th className="text-right font-normal">T+5</th>
                        <th className="text-right font-normal">T+20</th>
                        <th className="text-right font-normal">T+60</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.aggregate.map((r, i) => (
                        <tr key={i} className="border-b border-border/50">
                          <td className="py-1.5">
                            {r.direction === 'positive' ? '利好' : r.direction === 'negative' ? '利空' : '中性'}
                          </td>
                          <td>
                            {data.group_by === 'bi'
                              ? r.bi_direction === 'up'
                                ? '向上'
                                : r.bi_direction === 'down'
                                  ? '向下'
                                  : '—'
                              : r.ma20_position === 'above'
                                ? '20日线上'
                                : r.ma20_position === 'below'
                                  ? '20日线下'
                                  : '—'}
                          </td>
                          <td className="text-right">{r.n}</td>
                          <td className={`text-right ${r.n < 5 ? 'text-muted' : ''}`}>
                            {r.n < 5 ? '样本<5' : fmtMed(r, 'median_t1')}
                          </td>
                          <td className={`text-right ${r.n < 5 ? 'text-muted' : ''}`}>
                            {r.n < 5 ? '样本<5' : fmtMed(r, 'median_t5')}
                          </td>
                          <td className={`text-right ${r.n < 5 ? 'text-muted' : ''}`}>
                            {r.n < 5 ? '样本<5' : fmtMed(r, 'median_t20')}
                          </td>
                          <td className={`text-right ${r.n < 5 ? 'text-muted' : ''}`}>
                            {r.n < 5 ? '样本<5' : fmtMed(r, 'median_t60')}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="mt-1.5 text-[11px] text-muted">
                    铁律: 只统计 approved + major + 有 source 的事件; n&lt;5 分组不显示中位数。
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* 右: 事件列表 + 选中详情抽屉 (检视层) */}
      <div className="w-[380px] shrink-0 border-l border-border flex flex-col min-h-0">
        <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto">
          {filtered.map((ev) => (
            <EventRow
              key={ev.id}
              ev={ev}
              selected={ev.id === selectedId}
              onClick={() => setSelectedId(ev.id === selectedId ? null : ev.id)}
            />
          ))}
          {filtered.length === 0 && (
            <div className="p-6 text-center text-sm text-muted">无匹配事件</div>
          )}
        </div>
        {selected && <EventDrawer ev={selected} />}
      </div>
    </div>
  )
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-0.5 rounded text-xs border transition-colors ${
        active
          ? 'bg-accent text-white border-accent'
          : 'border-border text-secondary hover:text-foreground hover:border-accent'
      }`}
    >
      {children}
    </button>
  )
}

function EventRow({ ev, selected, onClick }: { ev: MarketPolicyEvent; selected: boolean; onClick: () => void }) {
  const grey = ev.status === 'draft' || !ev.source
  return (
    <button
      data-ev-id={ev.id}
      onClick={onClick}
      className={`w-full text-left px-3 py-2 border-b border-border/50 transition-colors ${
        selected ? 'bg-accent/10 border-l-2 border-l-accent' : 'hover:bg-muted/40 border-l-2 border-l-transparent'
      } ${grey ? 'opacity-55' : ''}`}
    >
      <div className="flex items-center gap-1.5">
        <span
          className={`text-[10px] ${
            ev.direction === 'positive' ? 'text-danger' : ev.direction === 'negative' ? 'text-bear' : 'text-muted'
          }`}
        >
          {ev.direction === 'positive' ? '▲' : ev.direction === 'negative' ? '▼' : '◆'}
        </span>
        <span className="text-xs font-medium text-foreground truncate">{ev.title}</span>
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
        <span>{ev.date}</span>
        <span>{ev.category}</span>
        <span>{ev.importance}</span>
        {ev.status === 'draft' && <span className="text-yellow-600">draft 待审核</span>}
        {!ev.source && <span className="text-yellow-600">无 source (不进统计)</span>}
        {ev.stats && (
          <span className={`ml-auto ${ev.stats.t1 != null && ev.stats.t1 >= 0 ? 'text-danger' : 'text-bear'}`}>
            T+1 {fmtPct(ev.stats.t1)}
          </span>
        )}
      </div>
    </button>
  )
}

/** 检视层抽屉: 迷你路径 (vs 大盘基线) + 技术背景 + source */
function EventDrawer({ ev }: { ev: MarketPolicyEvent }) {
  const seriesQ = useQuery({
    queryKey: ['market-event-series', ev.id],
    queryFn: () => api.marketEventSeries(ev.id),
    staleTime: 5 * 60 * 1000,
  })
  const st = ev.stats
  return (
    <div className="border-t border-border p-3 max-h-[65%] overflow-y-auto shrink-0">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium leading-snug">{ev.title}</h3>
          <p className="mt-0.5 text-[11px] text-muted">
            {ev.date} · {ev.category} ·{' '}
            {ev.direction === 'positive' ? '利好' : ev.direction === 'negative' ? '利空' : '中性'} ·{' '}
            {ev.importance} · {ev.status === 'approved' ? '已确认' : ev.status}
          </p>
        </div>
      </div>
      {ev.note && <p className="mt-1.5 text-xs text-secondary">{ev.note}</p>}

      {st && (
        <div className="mt-2 grid grid-cols-4 gap-1.5 text-center text-xs">
          {(
            [
              ['T+1', st.t1],
              ['T+5', st.t5],
              ['T+20', st.t20],
              ['T+60', st.t60],
            ] as const
          ).map(([label, v]) => (
            <div key={label} className="rounded border border-border py-1">
              <div className="text-[10px] text-muted">{label}</div>
              <div className={(v ?? 0) >= 0 ? 'text-danger' : 'text-bear'}>{fmtPct(v)}</div>
            </div>
          ))}
        </div>
      )}
      {st && (
        <p className="mt-1.5 text-[11px] text-muted">
          前收盘 {st.base_close?.toFixed(2)} · 事件后20日最大有利偏移{' '}
          <span className="text-danger">{fmtPct(st.max_up_20)}</span> · 最大不利偏移{' '}
          <span className="text-bear">{fmtPct(st.max_dd_20)}</span> (相对事件前收盘, 非峰谷回撤) · 事件时{' '}
          {st.above_ma20 == null ? 'MA20 数据不足' : st.above_ma20 ? '在20日线上' : '在20日线下'}
          {' · 缠论日线笔 '}
          {st.bi_direction == null
            ? '数据不足'
            : st.bi_direction === 'up'
              ? '向上'
              : st.bi_direction === 'down'
                ? '向下'
                : st.bi_direction}
        </p>
      )}

      {seriesQ.isPending && (
        <div className="h-[180px] grid place-items-center text-muted">
          <Loader2 className="animate-spin h-4 w-4" />
        </div>
      )}
      {seriesQ.data && (
        <div className="mt-2">
          <p className="text-[11px] text-muted mb-1">
            迷你路径 (前5日→后60日, 基期=事件前收盘=100)
          </p>
          <MiniPathChart
            height={180}
            lines={[
              {
                name: '事件路径',
                points: seriesQ.data.points.map((p) => ({ x: p.offset, y: p.value })),
                bold: true,
              },
              ...(seriesQ.data.index_points.length &&
              seriesQ.data.index_points !== seriesQ.data.points
                ? [
                    {
                      name: '大盘基线',
                      points: seriesQ.data.index_points.map((p) => ({ x: p.offset, y: p.value })),
                      dashed: true,
                    },
                  ]
                : []),
            ]}
          />
        </div>
      )}

      {ev.source && (
        <a
          href={ev.source}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline"
        >
          <ExternalLink className="h-3 w-3" />
          事件溯源
        </a>
      )}
      {!ev.source && <p className="mt-2 text-xs text-yellow-600">无 source — 页面标灰, 排除出统计</p>}
    </div>
  )
}

/** 叠加层: 同类事件扇形图 (spaghetti) + 均值粗线 */
function SpaghettiSection({ category, events }: { category: string; events: MarketPolicyEvent[] }) {
  const targets = useMemo(
    () => events.filter((e) => e.countable && (!category || e.category === category)),
    [events, category],
  )
  const [seriesList, setSeriesList] = useState<
    { id: string; label: string; points: { offset: number; value: number }[] }[]
  >([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    if (targets.length < 2) {
      setSeriesList([])
      return
    }
    setLoading(true)
    Promise.all(
      targets.map((ev) =>
        api
          .marketEventSeries(ev.id)
          .then((r) => ({
            id: ev.id,
            label: ev.date,
            points: r.points.map((p) => ({ offset: p.offset, value: p.value })),
          }))
          .catch(() => ({ id: ev.id, label: ev.date, points: [] as { offset: number; value: number }[] })),
      ),
    ).then((rs) => {
      if (!cancelled) {
        setSeriesList(rs.filter((r) => r.points.length > 0))
        setLoading(false)
      }
    })
    return () => {
      cancelled = true
    }
  }, [targets])

  if (targets.length < 2) return null

  // 均值粗线: 逐 offset 求均值
  const meanLine: SeriesLine | null = seriesList.length
    ? {
        name: '均值',
        bold: true,
        points: (() => {
          const byOffset = new Map<number, number[]>()
          seriesList.forEach((s) =>
            s.points.forEach((p) => {
              const arr = byOffset.get(p.offset) ?? []
              arr.push(p.value)
              byOffset.set(p.offset, arr)
            }),
          )
          return Array.from(byOffset.entries())
            .sort((a, b) => a[0] - b[0])
            .map(([offset, vals]) => ({ x: offset, y: vals.reduce((a, b) => a + b, 0) / vals.length }))
        })(),
      }
    : null

  // 倍数分布: T+1 / T+5 / T+20 各事件的值
  const horizons: { label: string; offset: number }[] = [
    { label: 'T+1', offset: 0 },
    { label: 'T+5', offset: 4 },
    { label: 'T+20', offset: 19 },
  ]

  return (
    <div>
      <h3 className="text-sm font-medium mb-2">
        同类事件叠加 (event study) — {category || '全部'} · n={targets.length}
      </h3>
      {loading ? (
        <div className="h-[200px] grid place-items-center text-muted">
          <Loader2 className="animate-spin h-4 w-4" />
        </div>
      ) : (
        <>
          <MiniPathChart
            height={240}
            showLegend={false}
            lines={[
              ...seriesList.map((s) => ({
                name: s.label,
                faint: true,
                points: s.points.map((p) => ({ x: p.offset, y: p.value })),
              })),
              ...(meanLine ? [meanLine] : []),
            ]}
          />
          <div className="mt-2 grid grid-cols-3 gap-2">
            {horizons.map((h) => {
              const vals = seriesList
                .map((s) => s.points.find((p) => p.offset === h.offset)?.value)
                .filter((v): v is number => v != null)
                .map((v) => v - 100)
              return (
                <div key={h.label} className="rounded border border-border p-2">
                  <div className="text-[11px] text-muted">
                    {h.label} 收益分布 (n={vals.length})
                  </div>
                  <div className="mt-1 flex items-baseline gap-1.5">
                    <span className={`text-sm font-medium ${vals.length && vals.reduce((a, b) => a + b, 0) / vals.length >= 0 ? 'text-danger' : 'text-bear'}`}>
                      {vals.length ? fmtPct(vals.reduce((a, b) => a + b, 0) / vals.length) : '—'}
                    </span>
                    <span className="text-[10px] text-muted">均值</span>
                  </div>
                  <div className="mt-1 space-y-0.5 max-h-24 overflow-y-auto">
                    {vals.map((v, i) => (
                      <div key={i} className="flex items-center gap-1.5 text-[11px]">
                        <div className="flex-1 h-1 rounded bg-muted overflow-hidden">
                          <div
                            className={`h-full ${v >= 0 ? 'bg-danger' : 'bg-bear'}`}
                            style={{ width: `${Math.min(100, Math.abs(v) * 4)}%` }}
                          />
                        </div>
                        <span className={v >= 0 ? 'text-danger' : 'text-bear'}>{fmtPct(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
