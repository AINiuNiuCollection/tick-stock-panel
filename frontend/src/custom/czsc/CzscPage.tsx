/**
 * 缠论分析独立页 (/czsc 路由)
 *
 * 布局: 参数面板 + ECharts 图表 (上) + 结果 Tab 列表 (下, 可滚动)
 * 数据流: 调主工程后端 /api/czsc/analyze (optional-dependency 直接集成, 非 czsc-serve)
 *
 * 触发策略: 进入页面【不自动分析】。用户点「分析」才提交请求。
 *   上次的参数持久化到 sessionStorage, 仅用于恢复表单显示, 不触发分析;
 *   已提交的分析结果从 react-query 缓存取出展示 (离开再返回仍可见上次图表),
 *   但要发起新分析必须再次点击。
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, GripHorizontal, Maximize2, Minimize2 } from 'lucide-react'
import { fetchCzscAnalyze, fetchCzscHealth, ApiError, type CzscAnalyzeResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { CzscParamsPanel, type CzscParams } from './CzscParamsPanel'
import { CzscChart, type CzscChartHandle } from './CzscChart'
import { CzscResultTabs } from './CzscResultTabs'
import { buildCzscHtml, buildCzscHtmlFilename, downloadCzscHtml } from './exportCzscHtml'

const PARAMS_STORAGE_KEY = 'czsc:last-params'

/** 从 react-query 缓存中取出最后一次成功的 czsc-analyze 结果 (按 dataUpdatedAt 降序取最新)。 */
function pickLastAnalyzeFromCache(
  qc: ReturnType<typeof useQueryClient>,
): CzscAnalyzeResult | undefined {
  const cache = qc.getQueryCache()
  const all = cache.getAll()
  let best: CzscAnalyzeResult | undefined
  let bestTs = -1
  for (const q of all) {
    const key = q.queryKey
    if (!Array.isArray(key) || key[0] !== 'czsc-analyze') continue
    if (key[1] === 'idle') continue
    const data = q.state.data as CzscAnalyzeResult | undefined
    if (!data || !data.ok) continue
    if (q.state.dataUpdatedAt > bestTs) {
      bestTs = q.state.dataUpdatedAt
      best = data
    }
  }
  return best
}

/** 从 sessionStorage 取出最后一次分析的参数 (让返回后可继续 refetch 同一查询)。 */
function loadLastParams(): CzscParams | null {
  try {
    const raw = sessionStorage.getItem(PARAMS_STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as CzscParams
  } catch {
    return null
  }
}

export function CzscPage() {
  const qc = useQueryClient()
  // 上次参数仅用于恢复【表单显示】; 进入页面不自动分析, 必须点击「分析」才提交。
  const [savedParams, setSavedParams] = useState<CzscParams | null>(() => loadLastParams())
  const [submittedParams, setSubmittedParams] = useState<CzscParams | null>(null)
  // 均线实时状态 — 下拉变更立即更新图表, 无需重新点分析;
  // 初始值取 savedParams.ma_periods (恢复上次会话) 或默认 [5,10,20]
  const [liveMaPeriods, setLiveMaPeriods] = useState<number[]>(
    () => savedParams?.ma_periods ?? [5, 10, 20],
  )
  // 图表显示选项 (实时生效, 无需重新分析): 中枢高低数据默认关, 分型标记默认开
  const [liveZsPriceVisible, setLiveZsPriceVisible] = useState(false)
  const [liveFxMarksVisible, setLiveFxMarksVisible] = useState(true)
  // 全屏切换 — 对图表面板元素用 Fullscreen API; ECharts 由 ResizeObserver 自动跟随尺寸
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
  const chartRef = useRef<CzscChartHandle>(null)
  // 整体可拉伸容器高度 (px), 由 ResizeObserver 实时跟踪
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerHeight, setContainerHeight] = useState<number>(0)
  // 图表区占比 (0.1 ~ 0.9), 默认 0.7 (70%)
  const [chartRatio, setChartRatio] = useState<number>(() => {
    const saved = typeof window !== 'undefined' ? sessionStorage.getItem('czsc:chart-ratio') : null
    const n = saved ? Number(saved) : 0.7
    return Number.isFinite(n) && n >= 0.1 && n <= 0.9 ? n : 0.7
  })
  const dragStateRef = useRef<{ startY: number; startRatio: number } | null>(null)

  // 监听整体容器高度变化 (窗口 resize / 父布局变化都会触发)
  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const h = e.contentRect.height
        if (h > 0) setContainerHeight(h)
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 拖动开始: 记录起始 Y 与起始占比
  const onResizeStart = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragStateRef.current = { startY: e.clientY, startRatio: chartRatio }
    ;(e.target as HTMLDivElement).setPointerCapture(e.pointerId)
  }, [chartRatio])

  // 拖动中: 按整体高度换算 delta 为占比增量
  const onResizeMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const st = dragStateRef.current
    if (!st || containerHeight <= 0) return
    const delta = e.clientY - st.startY
    const deltaRatio = delta / containerHeight
    // 限制 10% ~ 90% (用户可让任一侧缩到很小)
    const next = Math.min(0.9, Math.max(0.1, st.startRatio + deltaRatio))
    setChartRatio(next)
  }, [containerHeight])

  // 拖动结束: 持久化占比 + 清理
  const onResizeEnd = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    if (dragStateRef.current) {
      try {
        sessionStorage.setItem('czsc:chart-ratio', String(chartRatio))
      } catch {
        // sessionStorage 满或禁用时忽略
      }
    }
    dragStateRef.current = null
    try {
      ;(e.target as HTMLDivElement).releasePointerCapture(e.pointerId)
    } catch {
      // 已释放时忽略
    }
  }, [chartRatio])

  // 点击「分析」才提交: 记录本次参数(触发查询) + 持久化表单初值 + 同步均线。
  // 与旧行为的区别: 恢复的 savedParams 不再自动触发查询, 必须显式点击。
  const handleAnalyze = useCallback((next: CzscParams) => {
    setSubmittedParams(next)
    setSavedParams(next)
    try {
      sessionStorage.setItem(PARAMS_STORAGE_KEY, JSON.stringify(next))
    } catch {
      // sessionStorage 满或禁用时忽略
    }
    if (next.ma_periods && next.ma_periods.length > 0) {
      setLiveMaPeriods(next.ma_periods)
    }
  }, [])

  const health = useQuery({
    queryKey: QK.czscHealth,
    queryFn: fetchCzscHealth,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const analyze = useQuery<CzscAnalyzeResult>({
    queryKey: submittedParams
      ? QK.czscAnalyze(
          submittedParams.symbol, submittedParams.freq,
          submittedParams.start_date, submittedParams.end_date,
          submittedParams.max_bi_num, submittedParams.min_bi_len,
          submittedParams.features.join(','),
          submittedParams.bs_macd_area_mode, submittedParams.bs_use_dif,
          submittedParams.bs_use_macd_area, submittedParams.ma_periods,
          submittedParams.force_refresh, submittedParams.bs_trend_overlap_mode,
        )
      : ['czsc-analyze', 'idle'],
    queryFn: () => fetchCzscAnalyze({
      symbol: submittedParams!.symbol,
      symbol_name: submittedParams!.symbol_name,
      freq: submittedParams!.freq,
      start_date: submittedParams!.start_date,
      end_date: submittedParams!.end_date,
      max_bi_num: submittedParams!.max_bi_num,
      min_bi_len: submittedParams!.min_bi_len,
      features: submittedParams!.features.join(','),
      force_refresh: submittedParams!.force_refresh,
      bs_macd_area_mode: submittedParams!.bs_macd_area_mode,
      bs_use_dif: submittedParams!.bs_use_dif,
      bs_use_dea: submittedParams!.bs_use_dea,
      bs_use_macd_area: submittedParams!.bs_use_macd_area,
      bs_trend_overlap_mode: submittedParams!.bs_trend_overlap_mode,
      // 透传【提交时】勾选的均线周期 — 后端取数自动扩展暖机并计算 SMA 后下发。
      // 注意: 用提交值而非 liveMaPeriods, 避免仅改图表均线就触发重新请求。
      ma_periods: submittedParams!.ma_periods,
    }),
    // 只有点击提交后才发起; 进入页面 submittedParams=null → 不自动分析
    enabled: !!submittedParams,
    staleTime: 5 * 60_000,
    // gcTime 默认 5min; 提高到 30min 让用户离开再返回更可能命中缓存
    gcTime: 30 * 60_000,
  })

  // 当前展示数据: 优先本次 analyze.data, 否则回退到 react-query 缓存中最后一次成功的分析结果
  // 这样离开页面再返回 (params 已从 sessionStorage 恢复, 但查询可能还在 stale/refetching 中)
  // 也能立即显示上次的图表, 不会出现空白。
  const lastFromCache = pickLastAnalyzeFromCache(qc)
  const displayData = analyze.data ?? lastFromCache

  // 分析失败时, 提取后端结构化错误 (NO_DATA/CZSC_NOT_INSTALLED 等) 用于顶部 banner 提示。
  // 没有 displayData 时走 EmptyState, 不显示 banner (避免与"分析失败"空状态重复)。
  const analyzeError = analyze.error
  const errCode = analyzeError instanceof ApiError ? analyzeError.code : ''
  const errMsg = analyzeError instanceof ApiError ? analyzeError.message : (analyzeError instanceof Error ? analyzeError.message : '')
  const errHint = analyzeError instanceof ApiError ? analyzeError.hint : ''
  const showErrorBanner = !!analyzeError && !!displayData && !analyze.isFetching

  const serveOk = health.data?.ok === true

  return (
    <div className="flex flex-col gap-3 h-full">
      <PageHeader
        title="缠论分析"
        subtitle="分型 · 笔 · 中枢 · 信号 (基于 czsc 库 optional-dependency 集成)"
        right={
          <span className={`inline-flex items-center gap-1.5 text-xs ${serveOk ? 'text-green-500' : 'text-red-500'}`}>
            <span className={`w-2 h-2 rounded-full ${serveOk ? 'bg-green-500' : 'bg-red-500'}`} />
            {serveOk ? `可用 v${health.data?.version ?? ''}` : 'czsc 未就绪'}
          </span>
        }
      />

      {!serveOk && (
        <div className="text-xs text-amber-500 bg-amber-500/10 rounded-btn px-3 py-2">
          ⚠ czsc 扩展未就绪。请在后端执行:
          <code className="mx-1 px-1 bg-base rounded">cd backend && uv sync --extra czsc</code>
        </div>
      )}

      {showErrorBanner && (
        <div className="text-xs text-red-500 bg-red-500/10 rounded-btn px-3 py-2 flex items-start gap-2">
          <span className="shrink-0">⚠</span>
          <div className="min-w-0 flex-1">
            <div className="font-medium">
              数据源暂不可用 — 以下为上次缓存结果{errCode ? ` [${errCode}]` : ''}
            </div>
            <div className="text-red-500/80 mt-0.5 break-words">
              {errMsg}{errHint ? ` (hint: ${errHint})` : ''}
            </div>
            <div className="text-red-500/60 mt-0.5">
              请稍后重试, 或检查网络/代理是否拦截了 TickFlow/eastmoney 数据源
            </div>
          </div>
          <button
            type="button"
            onClick={() => analyze.refetch()}
            className="shrink-0 px-2 py-1 rounded-btn bg-red-500/10 hover:bg-red-500/20 text-red-500 transition-colors"
          >
            重试
          </button>
        </div>
      )}

      <CzscParamsPanel
        initialSymbol={savedParams?.symbol ?? ''}
        initialParams={savedParams}
        onAnalyze={handleAnalyze}
        loading={analyze.isFetching}
        onMaPeriodsChange={setLiveMaPeriods}
        zsPriceVisible={liveZsPriceVisible}
        onZsPriceVisibleChange={setLiveZsPriceVisible}
        fxMarksVisible={liveFxMarksVisible}
        onFxMarksVisibleChange={setLiveFxMarksVisible}
      />

      {/* 上下布局: 图表在上, 可拖动分割条, 结果数据在下 (可滚动显示全部 fx/bi/zs 行)。
          chartRatio 控制图表占比 (默认 0.7), 拖动范围 0.1 ~ 0.9, 持久化 sessionStorage。
          变更点1: 始终用 flex-grow 按占比分配, 不再用固定 px height, 确保占满整个页面高度。
                   containerHeight 仅用于拖动增量计算, 不参与布局。 */}
      <div ref={containerRef} className="flex-1 flex flex-col gap-1 min-h-0">
        <div
          ref={fsPanelRef}
          className="bg-elevated rounded-btn p-2 min-h-0 flex flex-col relative"
          style={{ flex: isFullscreen ? undefined : `${chartRatio} 1 0` }}
        >
          {/* 全屏切换按钮 — 悬浮在图表区右上角 (让开 ECharts 悬浮面板, 贴右上角内边) */}
          <button
            type="button"
            onClick={toggleFullscreen}
            title={isFullscreen ? '退出全屏 (Esc)' : '全屏显示'}
            className="absolute top-2 right-14 z-20 h-7 w-7 flex items-center justify-center rounded-btn
                       border border-border bg-base text-muted hover:text-foreground hover:border-accent transition-colors"
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
          {displayData ? (
            <CzscChart
              ref={chartRef}
              result={displayData}
              height="100%"
              maPeriods={liveMaPeriods}
              showZsPriceLabels={liveZsPriceVisible}
              showFxMarks={liveFxMarksVisible}
            />
          ) : analyze.isFetching ? (
            <EmptyState title="分析中…" />
          ) : analyze.isError ? (
            <EmptyState title="分析失败" hint="请检查服务状态或参数" />
          ) : (
            <EmptyState title="输入标的代码并点击「分析」" />
          )}
        </div>

        {/* 可拖动分割条 — 鼠标上下拖动调节图表与数据区高度比例
            虚线上下边框 + 中间抓手图标, 让分割条明显可见 */}
        <div
          onPointerDown={onResizeStart}
          onPointerMove={onResizeMove}
          onPointerUp={onResizeEnd}
          onPointerCancel={onResizeEnd}
          className="shrink-0 flex items-center justify-center h-3 cursor-row-resize border-y border-dashed border-border hover:border-accent hover:bg-accent/10 transition-colors"
          title="拖动调节上下区域高度"
        >
          <GripHorizontal className="h-3.5 w-3.5 text-muted" />
        </div>

        <div
          className="bg-elevated rounded-btn p-2 min-h-0 overflow-hidden flex flex-col"
          style={{ flex: `${1 - chartRatio} 1 0` }}
        >
          {displayData ? (
            <CzscResultTabs result={displayData} />
          ) : (
            <EmptyState title="等待分析结果" />
          )}
        </div>
      </div>

      {displayData && (
        <div className="flex items-center justify-between gap-3 shrink-0">
          <div className="text-xs text-muted">
            共 {displayData.bar_count} 根 K 线 · 数据源: {displayData.source}
            {displayData.cached ? ' · 缓存' : ' · 实时'}
            {!analyze.data && lastFromCache ? ' · 显示上次缓存结果' : ''}
            <span className="ml-2 opacity-70">· 点击图表后 ↑↓ 缩放、←→ 平移</span>
          </div>
          <button
            type="button"
            onClick={() => {
              const data = displayData
              if (!data) return
              // 从 CzscChart 实例取当前图表 PNG; 若 chart 未渲染则 chartDataURL=null (导出表格-only 报告)
              const chartDataURL = chartRef.current?.getDataURL() ?? null
              const html = buildCzscHtml(data, chartDataURL)
              const filename = buildCzscHtmlFilename(data.symbol, data.freq)
              downloadCzscHtml(html, filename)
            }}
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn bg-elevated border border-border text-sm hover:bg-base transition-colors"
          >
            <Download className="h-3.5 w-3.5" />
            导出 HTML
          </button>
        </div>
      )}
    </div>
  )
}
