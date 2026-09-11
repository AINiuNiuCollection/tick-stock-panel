import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { parseBacktestCsv } from './analysis/parseCsv'
import { convertBacktestResult } from './analysis/convertResult'
import { getSharedResult } from './analysis/sharedData'
import type { BacktestData } from './analysis/types'
import type { BacktestHistoryMeta, BacktestHistoryRecord, StrategyBacktestResult } from '@/lib/api'
import { api } from '@/lib/api'
import { Overview } from './analysis/Overview'
import { EquityCurve } from './analysis/EquityCurve'
import { TradeTable } from './analysis/TradeTable'
import { ExitAnalysis } from './analysis/ExitAnalysis'
import { ReturnDist } from './analysis/ReturnDist'
import { DurationAnalysis } from './analysis/DurationAnalysis'
import { DrawdownAnalysis } from './analysis/DrawdownAnalysis'
import { StreakAnalysis } from './analysis/StreakAnalysis'
import { RollingMetrics } from './analysis/RollingMetrics'
import { PerSymbolContribution } from './analysis/PerSymbolContribution'
import { Heatmap } from './analysis/Heatmap'
import { ScatterMatrix } from './analysis/ScatterMatrix'
import { MarketComparison } from './analysis/MarketComparison'
import { ScoreAnalysis } from './analysis/ScoreAnalysis'
import { BacktestParams } from './analysis/BacktestParams'
import { PageHeader } from '@/components/PageHeader'
import { Upload, FileText, Database, Trash2, Pencil, Check, X } from 'lucide-react'
import { cn } from '@/lib/cn'

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'equity', label: '净值曲线' },
  { id: 'trades', label: '交易明细' },
  { id: 'exit', label: '退出分析' },
  { id: 'dist', label: '收益分布' },
  { id: 'duration', label: '持仓分析' },
  { id: 'drawdown', label: '回撤分析' },
  { id: 'streak', label: '连续盈亏' },
  { id: 'rolling', label: '滚动指标' },
  { id: 'contribution', label: '个股贡献' },
  { id: 'heatmap', label: '月度热力图' },
  { id: 'scatter', label: '散点矩阵' },
  { id: 'market', label: 'A股走势' },
  { id: 'score', label: '评分关联' },
  { id: 'params', label: '回测参数' },
] as const

export function Analysis() {
  const queryClient = useQueryClient()
  const [data, setData] = useState<BacktestData | null>(null)
  const [activeTab, setActiveTab] = useState<string>('overview')
  const [fileName, setFileName] = useState('')
  const [dataSource, setDataSource] = useState<'csv' | 'live' | 'history'>('csv')
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // ── 回测历史记录 ──
  const [selectedRecordId, setSelectedRecordId] = useState<string>('')
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')

  // 历史记录列表
  const historyListQ = useQuery({
    queryKey: ['backtest-history-list'],
    queryFn: () => api.backtestHistoryList(),
    staleTime: 10_000,
  })

  // 选中的历史记录详情(含完整 result)
  const historyDetailQ = useQuery({
    queryKey: ['backtest-history-detail', selectedRecordId],
    queryFn: () => api.backtestHistoryDetail(selectedRecordId),
    enabled: !!selectedRecordId,
    staleTime: 0,
  })

  // 重命名
  const renameMut = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.backtestHistoryRename(id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtest-history-list'] })
      setRenaming(false)
    },
  })

  // 删除
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.backtestHistoryDelete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['backtest-history-list'] })
      setSelectedRecordId('')
      setData(null)
    },
  })

  // Check for shared backtest result on mount (from StrategyBacktest page)
  useEffect(() => {
    const shared = getSharedResult()
    if (shared) {
      const converted = convertBacktestResult(shared)
      setData(converted)
      setFileName(shared.strategy_info?.name ?? shared.strategy_info?.id ?? '回测结果')
      setDataSource('live')
      // 不清除共享数据，用户切走再回来仍可查看
      // 刷新历史列表, 刚保存的记录会出现在列表中
      queryClient.invalidateQueries({ queryKey: ['backtest-history-list'] })
    }
  }, [])

  // 当历史记录列表加载完成, 如果没有选中记录且没有已加载数据, 自动选最新一条
  useEffect(() => {
    if (!historyListQ.data?.items?.length) return
    if (selectedRecordId) return
    if (data) return
    setSelectedRecordId(historyListQ.data.items[0].id)
  }, [historyListQ.data, selectedRecordId, data])

  // 当历史记录详情加载完成, 转换为 BacktestData 并渲染
  useEffect(() => {
    if (!historyDetailQ.data) return
    const record = historyDetailQ.data as BacktestHistoryRecord
    const result = record.result as StrategyBacktestResult
    if (!result) return
    const converted = convertBacktestResult(result)
    setData(converted)
    setFileName(record.name)
    setDataSource('history')
  }, [historyDetailQ.data])

  const handleFile = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result || '')
      const parsed = parseBacktestCsv(text)
      setData(parsed)
      setFileName(file.name)
      setDataSource('csv')
      setSelectedRecordId('')
    }
    reader.readAsText(file, 'utf-8')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }, [handleFile])

  // 从下拉框选择历史记录
  const handleSelectRecord = (id: string) => {
    if (!id) {
      setSelectedRecordId('')
      setData(null)
      return
    }
    setSelectedRecordId(id)
  }

  // 确认重命名
  const handleRenameConfirm = () => {
    if (!selectedRecordId || !renameValue.trim()) return
    renameMut.mutate({ id: selectedRecordId, name: renameValue.trim() })
  }

  const historyItems = historyListQ.data?.items ?? []
  const currentRecord = historyDetailQ.data as BacktestHistoryRecord | null

  return (
    <div className="min-h-full">
      <PageHeader
        title="回测分析"
        subtitle="上传回测 CSV 文件，生成专业操盘手分析面板"
      />

      {!data ? (
        <div className="flex flex-col items-center gap-6 py-20">
          {/* 历史记录选择(如果有记录) */}
          {historyItems.length > 0 && (
            <div className="w-full max-w-2xl rounded-xl border border-border bg-surface p-4">
              <h3 className="mb-2 text-sm font-semibold text-foreground">历史回测记录</h3>
              <select
                value=""
                onChange={(e) => e.target.value && handleSelectRecord(e.target.value)}
                className="w-full rounded-lg border border-border bg-base px-3 py-2 text-sm text-foreground [&>option]:bg-base [&>option]:text-foreground"
              >
                <option value="">选择一条记录查看...</option>
                {historyItems.map((item: BacktestHistoryMeta) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.strategy_name} · {item.start}~{item.end} · 收益:{item.total_return != null ? (item.total_return * 100).toFixed(1) + '%' : '—'}
                  </option>
                ))}
              </select>
            </div>
          )}
          {/* CSV 上传区域 */}
          <div
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onClick={() => inputRef.current?.click()}
            className={cn(
              'flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed p-16 cursor-pointer transition-colors',
              dragOver ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'
            )}
          >
            <Upload className="h-12 w-12 text-muted" />
            <div className="text-lg font-semibold text-foreground">拖拽 CSV 文件到此处</div>
            <div className="text-sm text-muted">或点击选择文件</div>
            <input
              ref={inputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFile(file)
              }}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {/* 历史记录选择栏 */}
          {historyItems.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface px-3 py-2">
              <span className="text-xs font-medium text-muted">历史记录:</span>
              <select
                value={selectedRecordId}
                onChange={(e) => handleSelectRecord(e.target.value)}
                className="min-w-[200px] max-w-[400px] rounded-lg border border-border bg-base px-2 py-1 text-xs text-foreground [&>option]:bg-base [&>option]:text-foreground"
              >
                <option value="">{dataSource === 'live' ? '当前运行结果(未选择历史)' : '选择历史记录...'}</option>
                {historyItems.map((item: BacktestHistoryMeta) => (
                  <option key={item.id} value={item.id}>
                    {item.name} · {item.strategy_name} · {item.start}~{item.end}
                  </option>
                ))}
              </select>
              {/* 重命名 */}
              {selectedRecordId && (
                renaming ? (
                  <>
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleRenameConfirm()}
                      className="rounded border border-border bg-base px-2 py-1 text-xs text-foreground"
                      autoFocus
                    />
                    <button onClick={handleRenameConfirm} className="rounded p-1 text-green-500 hover:bg-border/50" title="确认">
                      <Check className="h-3.5 w-3.5" />
                    </button>
                    <button onClick={() => setRenaming(false)} className="rounded p-1 text-muted hover:bg-border/50" title="取消">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => { setRenaming(true); setRenameValue(historyItems.find(i => i.id === selectedRecordId)?.name ?? '') }}
                    className="rounded p-1 text-muted hover:text-foreground hover:bg-border/50"
                    title="重命名"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )
              )}
              {/* 删除 */}
              {selectedRecordId && (
                <button
                  onClick={() => {
                    if (confirm('确认删除此记录？')) deleteMut.mutate(selectedRecordId)
                  }}
                  className="rounded p-1 text-muted hover:text-red-500 hover:bg-border/50"
                  title="删除"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}

          {/* 文件信息 */}
          <div className="flex items-center gap-3 text-sm">
            {dataSource === 'live' ? (
              <Database className="h-4 w-4 text-green-500" />
            ) : dataSource === 'history' ? (
              <Database className="h-4 w-4 text-blue-500" />
            ) : (
              <FileText className="h-4 w-4 text-primary" />
            )}
            <span className="font-medium text-foreground">{fileName}</span>
            {dataSource === 'live' && (
              <span className="rounded bg-green-500/20 px-1.5 py-0.5 text-xs text-green-400">实时数据</span>
            )}
            {dataSource === 'history' && (
              <span className="rounded bg-blue-500/20 px-1.5 py-0.5 text-xs text-blue-400">历史记录</span>
            )}
            <span className="text-muted">
              {data.trades.length} 笔交易 · {data.equityCurve.length} 天净值
            </span>
            <button
              onClick={() => inputRef.current?.click()}
              className="ml-auto rounded-lg border border-border px-3 py-1 text-xs text-muted hover:text-foreground hover:border-primary/50 transition-colors"
            >
              重新上传
            </button>
            <input
              ref={inputRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFile(file)
              }}
            />
          </div>

          {/* Tab 导航 */}
          <div className="flex flex-wrap gap-1 rounded-xl border border-border bg-surface p-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                  activeTab === tab.id
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted hover:text-foreground hover:bg-border/50'
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* 内容区 */}
          <div className="min-h-[600px]">
            {activeTab === 'overview' && <Overview data={data} />}
            {activeTab === 'equity' && <EquityCurve data={data} />}
            {activeTab === 'trades' && <TradeTable data={data} />}
            {activeTab === 'exit' && <ExitAnalysis data={data} />}
            {activeTab === 'dist' && <ReturnDist data={data} />}
            {activeTab === 'duration' && <DurationAnalysis data={data} />}
            {activeTab === 'drawdown' && <DrawdownAnalysis data={data} />}
            {activeTab === 'streak' && <StreakAnalysis data={data} />}
            {activeTab === 'rolling' && <RollingMetrics data={data} />}
            {activeTab === 'contribution' && <PerSymbolContribution data={data} />}
            {activeTab === 'heatmap' && <Heatmap data={data} />}
            {activeTab === 'scatter' && <ScatterMatrix data={data} />}
            {activeTab === 'market' && <MarketComparison data={data} />}
            {activeTab === 'score' && <ScoreAnalysis data={data} />}
            {activeTab === 'params' && <BacktestParams record={currentRecord} />}
          </div>
        </div>
      )}
    </div>
  )
}
