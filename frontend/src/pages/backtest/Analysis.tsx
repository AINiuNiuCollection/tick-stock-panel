import { useState, useCallback, useRef, useEffect } from 'react'
import { parseBacktestCsv } from './analysis/parseCsv'
import { convertBacktestResult } from './analysis/convertResult'
import { getSharedResult } from './analysis/sharedData'
import type { BacktestData } from './analysis/types'
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
import { PageHeader } from '@/components/PageHeader'
import { Upload, FileText, Database } from 'lucide-react'
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
] as const

export function Analysis() {
  const [data, setData] = useState<BacktestData | null>(null)
  const [activeTab, setActiveTab] = useState<string>('overview')
  const [fileName, setFileName] = useState('')
  const [dataSource, setDataSource] = useState<'csv' | 'live'>('csv')
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Check for shared backtest result on mount (from StrategyBacktest page)
  useEffect(() => {
    const shared = getSharedResult()
    if (shared) {
      const converted = convertBacktestResult(shared)
      setData(converted)
      setFileName(shared.strategy_info?.name ?? shared.strategy_info?.id ?? '回测结果')
      setDataSource('live')
      // 不清除共享数据，用户切走再回来仍可查看
    }
  }, [])

  const handleFile = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const text = String(reader.result || '')
      const parsed = parseBacktestCsv(text)
      setData(parsed)
      setFileName(file.name)
      setDataSource('csv')
    }
    reader.readAsText(file, 'utf-8')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) handleFile(file)
  }, [handleFile])

  return (
    <div className="min-h-full">
      <PageHeader
        title="回测分析"
        subtitle="上传回测 CSV 文件，生成专业操盘手分析面板"
      />

      {!data ? (
        <div className="flex items-center justify-center py-20">
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
          {/* 文件信息 */}
          <div className="flex items-center gap-3 text-sm">
            {dataSource === 'live' ? (
              <Database className="h-4 w-4 text-green-500" />
            ) : (
              <FileText className="h-4 w-4 text-primary" />
            )}
            <span className="font-medium text-foreground">{fileName}</span>
            {dataSource === 'live' && (
              <span className="rounded bg-green-500/20 px-1.5 py-0.5 text-xs text-green-400">实时数据</span>
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
          </div>
        </div>
      )}
    </div>
  )
}
