/**
 * 缠论分析参数面板 — 范围/级别/频率/特征全可配置 (Q8)
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { SymbolPicker } from '@/components/SymbolPicker'
import { api } from '@/lib/api'

export interface CzscParams {
  symbol: string
  symbol_name?: string | null  // 中文名 (前端透传, 不查库)
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
  const [symbolName, setSymbolName] = useState<string | null>(null)
  const [freq, setFreq] = useState('日线')
  const [startDate, setStartDate] = useState(defaultStart)
  const [endDate, setEndDate] = useState(today)
  const [maxBiNum, setMaxBiNum] = useState(100)
  const [minBiLen, setMinBiLen] = useState(7)
  const [features, setFeatures] = useState<string[]>(['fx', 'bi', 'zs', 'signals'])
  const [forceRefresh, setForceRefresh] = useState(false)

  // 变更点3: 自动查中文名 — 用户手动输入代码 (不选下拉) 时 onSelect 不触发,
  //          这里按 symbol 精确查 instrumentNames 补全 name。下拉选择时 onSelect
  //          已设 symbolName, 此查询命中缓存不会覆盖 (useEffect 内判空才 set)。
  const trimmedSymbol = symbol.trim()
  const namesQuery = useQuery({
    queryKey: ['czsc-symbol-name', trimmedSymbol],
    queryFn: () => api.instrumentNames([trimmedSymbol]),
    enabled: trimmedSymbol.length > 0,
    staleTime: 5 * 60_000,
  })
  useEffect(() => {
    // symbolName 已有值时不覆盖 (用户从下拉选的优先)
    if (symbolName) return
    const names = namesQuery.data?.names
    if (names && trimmedSymbol && names[trimmedSymbol]) {
      setSymbolName(names[trimmedSymbol])
    }
  }, [namesQuery.data, trimmedSymbol, symbolName])

  // symbol 改变时清空 symbolName, 让自动查询重新补全 (除非用户从下拉选了新的)
  // 用 SymbolPicker 的 onSelect 直接 setSymbolName, 这里只在 symbol 变且非下拉选择时清空
  const prevSymbolRef = useRef<string>(initialSymbol)
  useEffect(() => {
    if (prevSymbolRef.current !== symbol) {
      prevSymbolRef.current = symbol
      // symbol 变化时清空 name, 触发自动查询重新补全;
      // 若是下拉选择, onSelect 会紧接着 setSymbolName 覆盖。
      setSymbolName(null)
    }
  }, [symbol])

  const toggleFeature = (key: string) => {
    setFeatures(prev => prev.includes(key) ? prev.filter(f => f !== key) : [...prev, key])
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!symbol.trim()) return
    onAnalyze({
      symbol: symbol.trim(),
      symbol_name: symbolName,
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
        <SymbolPicker
          value={symbol}
          onChange={setSymbol}
          onSelect={(_sym, name) => setSymbolName(name)}
          assetTypes="stock,etf,index"
          size="sm"
          placeholder="代码 / 名称"
          className="w-56"
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
          // color-scheme 让浏览器原生日期选择器适配 light/dark 主题,
          // 否则 dark 主题下日历图标不可见且点击不弹日期方框。
          style={{ colorScheme: 'dark light' }}
          className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">结束日期</span>
        <input
          type="date"
          value={endDate}
          onChange={e => setEndDate(e.target.value)}
          style={{ colorScheme: 'dark light' }}
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
        // 几何参考 hAdmin .btn-primary (圆角 3px / padding 4px 12px / font-weight 400 / 白字)
        // 颜色按用户要求与本工程主题对齐: --accent 电光蓝 (非 hAdmin 紫)
        className="h-8 min-w-[80px] px-3 py-1 rounded-[3px] bg-accent text-white text-sm font-normal leading-[1.42857143] transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? '分析中…' : '分析'}
      </button>
    </form>
  )
}
