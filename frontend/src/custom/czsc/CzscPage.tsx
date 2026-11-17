/**
 * 缠论分析独立页 (/czsc 路由)
 *
 * 布局: 参数面板 + ECharts 图表 + 结果 Tab 列表
 * 数据流: 调主工程后端代理 /api/czsc/analyze → 透传到 czsc-serve
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchCzscAnalyze, fetchCzscHealth, type CzscAnalyzeResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { CzscParamsPanel, type CzscParams } from './CzscParamsPanel'
import { CzscChart } from './CzscChart'
import { CzscResultTabs } from './CzscResultTabs'

export function CzscPage() {
  const [params, setParams] = useState<CzscParams | null>(null)

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
        subtitle="分型 · 笔 · 中枢 · 信号 (基于 czsc-serve 独立服务)"
        right={
          <span className={`inline-flex items-center gap-1.5 text-xs ${serveOk ? 'text-green-500' : 'text-red-500'}`}>
            <span className={`w-2 h-2 rounded-full ${serveOk ? 'bg-green-500' : 'bg-red-500'}`} />
            {serveOk ? `服务在线 v${health.data?.version ?? ''}` : '服务未启动'}
          </span>
        }
      />

      {!serveOk && (
        <div className="text-xs text-amber-500 bg-amber-500/10 rounded-btn px-3 py-2">
          ⚠ czsc-serve 未启动。请执行:
          <code className="mx-1 px-1 bg-base rounded">cd D:/Code/githubProject/czsc && uv sync --extra serve && python -m czsc.serve</code>
        </div>
      )}

      <CzscParamsPanel
        onAnalyze={setParams}
        loading={analyze.isFetching}
      />

      <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-3 min-h-0">
        <div className="lg:col-span-2 bg-elevated rounded-btn p-2 min-h-0">
          {analyze.data ? (
            <CzscChart result={analyze.data} height={520} />
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
        <div className="text-xs text-muted">
          共 {analyze.data.bar_count} 根 K 线 · 数据源: {analyze.data.source}
          {analyze.data.cached ? ' · 缓存' : ' · 实时'}
        </div>
      )}
    </div>
  )
}
