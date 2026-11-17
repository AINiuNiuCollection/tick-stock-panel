/**
 * 缠论分析参数面板 — 范围/级别/频率/特征全可配置 (Q8)
 */
import { useState } from 'react'

export interface CzscParams {
  symbol: string
  freq: string
  start_date?: string
  end_date?: string
  max_bi_num: number
  min_bi_len: number
  features: string[]
  force_refresh: boolean
}

interface Props {
  initialSymbol?: string
  onAnalyze: (params: CzscParams) => void
  loading?: boolean
}

const FREQ_OPTIONS = ['日线', '周线', '月线', '30分钟', '60分钟', '15分钟', '5分钟']
const FEATURE_OPTIONS = [
  { key: 'fx', label: '分型' },
  { key: 'bi', label: '笔' },
  { key: 'zs', label: '中枢' },
  { key: 'signals', label: '信号' },
]

export function CzscParamsPanel({ initialSymbol = '', onAnalyze, loading }: Props) {
  const today = new Date().toISOString().slice(0, 10)
  const defaultStart = new Date(Date.now() - 365 * 86400 * 1000).toISOString().slice(0, 10)
  const [symbol, setSymbol] = useState(initialSymbol)
  const [freq, setFreq] = useState('日线')
  const [startDate, setStartDate] = useState(defaultStart)
  const [endDate, setEndDate] = useState(today)
  const [maxBiNum, setMaxBiNum] = useState(100)
  const [minBiLen, setMinBiLen] = useState(7)
  const [features, setFeatures] = useState<string[]>(['fx', 'bi', 'zs', 'signals'])
  const [forceRefresh, setForceRefresh] = useState(false)

  const toggleFeature = (key: string) => {
    setFeatures(prev => prev.includes(key) ? prev.filter(f => f !== key) : [...prev, key])
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    onAnalyze({
      symbol: symbol.trim(),
      freq,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      max_bi_num: maxBiNum,
      min_bi_len: minBiLen,
      features: features.length ? features : ['fx', 'bi', 'zs'],
      force_refresh: forceRefresh,
    })
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 p-3 bg-elevated rounded-btn">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">标的代码</span>
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value)}
          placeholder="600519.SH"
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-32"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">频率</span>
        <select
          value={freq}
          onChange={e => setFreq(e.target.value)}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
        >
          {FREQ_OPTIONS.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">起始日期</span>
        <input
          type="date"
          value={startDate}
          onChange={e => setStartDate(e.target.value)}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">结束日期</span>
        <input
          type="date"
          value={endDate}
          onChange={e => setEndDate(e.target.value)}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">最大笔数</span>
        <input
          type="number"
          min={10}
          max={500}
          value={maxBiNum}
          onChange={e => setMaxBiNum(Number(e.target.value) || 100)}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">最小笔长</span>
        <input
          type="number"
          min={3}
          max={30}
          value={minBiLen}
          onChange={e => setMinBiLen(Number(e.target.value) || 7)}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm w-20"
        />
      </label>

      <fieldset className="flex flex-col gap-1">
        <span className="text-xs text-muted">特征</span>
        <div className="flex gap-2">
          {FEATURE_OPTIONS.map(opt => (
            <label key={opt.key} className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={features.includes(opt.key)}
                onChange={() => toggleFeature(opt.key)}
              />
              {opt.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="flex items-center gap-1 text-xs">
        <input
          type="checkbox"
          checked={forceRefresh}
          onChange={e => setForceRefresh(e.target.checked)}
        />
        强制刷新缓存
      </label>

      <button
        type="submit"
        disabled={loading || !symbol.trim()}
        className="h-8 px-4 rounded-btn bg-primary text-primary-fg text-sm disabled:opacity-50 hover:opacity-90"
      >
        {loading ? '分析中…' : '分析'}
      </button>
    </form>
  )
}
