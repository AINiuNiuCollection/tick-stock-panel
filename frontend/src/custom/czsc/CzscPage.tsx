/**
 * 缠论分析独立页 (/czsc 路由)
 *
 * 布局: 参数面板 + ECharts 图表 + 结果 Tab 列表
 * 数据流: 调主工程后端 /api/czsc/analyze (optional-dependency 直接集成, 非 czsc-serve)
 */
import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import { fetchCzscAnalyze, fetchCzscHealth, type CzscAnalyzeResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { CzscParamsPanel, type CzscParams } from './CzscParamsPanel'
import { CzscChart, type CzscChartHandle } from './CzscChart'
import { CzscResultTabs } from './CzscResultTabs'
import { buildCzscHtml, buildCzscHtmlFilename, downloadCzscHtml } from './exportCzscHtml'

export function CzscPage() {
  const [params, setParams] = useState<CzscParams | null>(null)
  const chartRef = useRef<CzscChartHandle>(null)

  const health = useQuery({
    queryKey: QK.czscHealth,
    queryFn: fetchCzscHealth,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const analyze = useQuery<CzscAnalyzeResult>({
    queryKey: params
      ? QK.czscAnalyze(params.symbol, params.freq, params.start_date, params.end_date)
      : ['czsc-analyze', 'idle'],
    queryFn: () => fetchCzscAnalyze({
      symbol: params!.symbol,
      freq: params!.freq,
      start_date: params!.start_date,
      end_date: params!.end_date,
      max_bi_num: params!.max_bi_num,
      min_bi_len: params!.min_bi_len,
      features: params!.features.join(','),
      force_refresh: params!.force_refresh,
    }),
    enabled: !!params,
    staleTime: 5 * 60_000,
  })

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

      <CzscParamsPanel
        onAnalyze={setParams}
        loading={analyze.isFetching}
      />

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-3 min-h-0">
        <div className="lg:col-span-2 bg-elevated rounded-btn p-2 min-h-0">
          {analyze.data ? (
            <CzscChart ref={chartRef} result={analyze.data} height={520} />
          ) : analyze.isFetching ? (
            <EmptyState title="分析中…" />
          ) : analyze.isError ? (
            <EmptyState title="分析失败" hint="请检查服务状态或参数" />
          ) : (
            <EmptyState title="输入标的代码并点击「分析」" />
          )}
        </div>

        <div className="bg-elevated rounded-btn p-2 min-h-0">
          {analyze.data ? (
            <CzscResultTabs result={analyze.data} />
          ) : (
            <EmptyState title="等待分析结果" />
          )}
        </div>
      </div>

      {analyze.data && (
        <div className="flex items-center justify-between gap-3">
          <div className="text-xs text-muted">
            共 {analyze.data.bar_count} 根 K 线 · 数据源: {analyze.data.source}
            {analyze.data.cached ? ' · 缓存' : ' · 实时'}
          </div>
          <button
            type="button"
            onClick={() => {
              const data = analyze.data
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
