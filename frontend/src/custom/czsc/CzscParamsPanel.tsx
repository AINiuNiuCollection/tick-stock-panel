/**
 * 缠论分析参数面板 — 范围/级别/频率/特征全可配置 (Q8)
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Check } from 'lucide-react'
import { SymbolPicker } from '@/components/SymbolPicker'
import { api } from '@/lib/api'

/**
 * 下拉多选组件 — 点击按钮弹出下拉框 (仿 hAdmin 下拉按钮风格),
 * 弹层内为 checkbox 列表, 选中打勾, 点击外部关闭。
 * 按钮只显示「label (已选N)」+ caret, 不平铺已选标签 (已选由图表图例展示);
 * option 可带 color 字段, 在选项右侧显示色块。
 */
interface MultiSelectOption {
  value: string
  label: string
  color?: string
}
function MultiSelectDropdown({
  label,
  options,
  selected,
  onChange,
  placeholder = '请选择',
}: {
  label: string
  options: MultiSelectOption[]
  selected: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  const toggle = (v: string) => {
    onChange(selected.includes(v) ? selected.filter(x => x !== v) : [...selected, v])
  }

  return (
    <div ref={ref} className="relative flex flex-col gap-1">
      <span className="text-xs text-muted">
        {label}{selected.length > 0 ? ` (已选${selected.length})` : ''}
      </span>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex items-center justify-between gap-1 h-8 px-2 rounded-btn border border-border bg-base text-sm min-w-[140px] hover:border-accent transition-colors"
      >
        <span className={`truncate ${selected.length > 0 ? 'text-foreground' : 'text-muted'}`}>
          {selected.length > 0 ? placeholder : placeholder}
        </span>
        <ChevronDown className={`h-3.5 w-3.5 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 min-w-full bg-elevated border border-border rounded-btn shadow-lg py-1 max-h-60 overflow-auto">
          {options.map(opt => {
            const checked = selected.includes(opt.value)
            return (
              <button
                key={opt.value}
                type="button"
                onClick={() => toggle(opt.value)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm text-left hover:bg-accent/10 transition-colors ${checked ? 'text-foreground' : 'text-muted'}`}
              >
                <span className={`w-4 h-4 flex items-center justify-center rounded border ${checked ? 'bg-accent border-accent' : 'border-border'}`}>
                  {checked && <Check className="w-3 h-3 text-white" />}
                </span>
                <span className="flex-1">{opt.label}</span>
                {opt.color && (
                  <span
                    className="w-4 h-2 rounded-sm shrink-0"
                    style={{ backgroundColor: opt.color }}
                    aria-hidden
                  />
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

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
  ma_periods?: number[]        // 均线周期列表 (最多 3 条, 参考同花顺)
  bs_macd_area_mode?: 'split' | 'total_abs' | 'dif_dea'  // 背驰 MACD 面积口径
  bs_use_dif?: boolean         // 背驰是否启用 DIF 极值条件
  bs_use_dea?: boolean         // 背驰是否启用 DEA 极值条件
  bs_use_macd_area?: boolean   // 背驰是否启用 MACD 面积条件
}

interface Props {
  initialSymbol?: string
  onAnalyze: (params: CzscParams) => void
  loading?: boolean
  /** 均线变化实时回调 (无需重新点分析即可更新图表) */
  onMaPeriodsChange?: (periods: number[]) => void
}

const FREQ_OPTIONS = ['日线', '周线', '月线', '30分钟', '60分钟', '15分钟', '5分钟']
const FEATURE_OPTIONS = [
  { key: 'fx', label: '分型' },
  { key: 'bi', label: '笔' },
  { key: 'zs', label: '中枢' },
  { key: 'signals', label: '信号' },
  { key: 'bs_points', label: '买卖点' },
]
// 均线周期可选值 (参考同花顺: 5/10/12/20/30/60/120/250 日)
const MA_PERIOD_OPTIONS = [5, 10, 12, 20, 30, 60, 120, 250]
// 均线配色 (与 CzscChart.MA_COLORS 同步; 下拉项右侧色块用此色, 选中即图表中该均线的颜色)
const MA_PERIOD_COLORS: Record<number, string> = {
  5: '#C78A2E',
  10: '#2D6A8C',
  12: '#9D6FD4',
  20: '#D94F70',
  30: '#3F8E58',
  60: '#B58A1F',
  120: '#5B6FA8',
  250: '#8C6BA8',
}
// 背驰 MACD 面积口径
const BS_MACD_AREA_MODES = [
  { value: 'split', label: '红绿柱分计' },
  { value: 'total_abs', label: 'Σ|hist|' },
  { value: 'dif_dea', label: 'Σ|DIF-DEA|' },
] as const

export function CzscParamsPanel({ initialSymbol = '', onAnalyze, loading, onMaPeriodsChange }: Props) {
  const today = new Date().toISOString().slice(0, 10)
  const defaultStart = new Date(Date.now() - 365 * 86400 * 1000).toISOString().slice(0, 10)
  const [symbol, setSymbol] = useState(initialSymbol)
  const [symbolName, setSymbolName] = useState<string | null>(null)
  const [freq, setFreq] = useState('日线')
  const [startDate, setStartDate] = useState(defaultStart)
  const [endDate, setEndDate] = useState(today)
  const [maxBiNum, setMaxBiNum] = useState(100)
  const [minBiLen, setMinBiLen] = useState(7)
  const [features, setFeatures] = useState<string[]>(['fx', 'bi', 'zs', 'signals', 'bs_points'])
  const [forceRefresh, setForceRefresh] = useState(false)
  // 均线周期: 默认 [5, 10, 20], 最多 3 条 (同花顺惯例)
  const [maPeriods, setMaPeriods] = useState<number[]>([5, 10, 20])
  // 背驰配置: 默认三条件全开, 面积口径 split (红绿柱分计)
  const [bsMacdAreaMode, setBsMacdAreaMode] = useState<'split' | 'total_abs' | 'dif_dea'>('split')
  const [bsUseDif, setBsUseDif] = useState(true)
  const [bsUseDea, setBsUseDea] = useState(true)
  const [bsUseMacdArea, setBsUseMacdArea] = useState(true)

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
      features: features.length ? features : ['fx', 'bi', 'zs', 'bs_points'],
      force_refresh: forceRefresh,
      ma_periods: maPeriods,
      bs_macd_area_mode: bsMacdAreaMode,
      bs_use_dif: bsUseDif,
      bs_use_dea: bsUseDea,
      bs_use_macd_area: bsUseMacdArea,
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
          displayName={symbolName}
          assetTypes="stock,etf,index"
          size="sm"
          placeholder="代码 / 名称"
          className="w-72"
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
          // 项3: 点击 input 任意位置 (含日期数字区) 都弹出原生日期选择框。
          //   原生 date input 默认只有点日历图标才弹; showPicker() 是 HTML Living Standard
          //   API, 现代浏览器 (Chrome 95+/Edge 95+/Firefox 101+) 支持。
          onClick={(e) => {
            const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void }
            try { el.showPicker?.() } catch { /* 用户手势已触发, 忽略 */ }
          }}
          // color-scheme 让浏览器原生日期选择器适配 light/dark 主题,
          // 'light dark' 顺序: 亮色优先渲染日历 popup (dark 模式下浏览器会自动反转)。
          style={{ colorScheme: 'light dark', position: 'relative', zIndex: 1 }}
          className="czsc-date-input h-8 px-2 rounded-btn border border-border bg-base text-sm cursor-pointer"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted">结束日期</span>
        <input
          type="date"
          value={endDate}
          onChange={e => setEndDate(e.target.value)}
          onClick={(e) => {
            const el = e.currentTarget as HTMLInputElement & { showPicker?: () => void }
            try { el.showPicker?.() } catch { /* 用户手势已触发, 忽略 */ }
          }}
          style={{ colorScheme: 'light dark', position: 'relative', zIndex: 1 }}
          className="czsc-date-input h-8 px-2 rounded-btn border border-border bg-base text-sm cursor-pointer"
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

      {/* 均线配置 (下拉按钮多选, 不限条数) */}
      <MultiSelectDropdown
        label="均线"
        options={MA_PERIOD_OPTIONS.map(p => ({
          value: String(p),
          label: `SMA${p}`,
          color: MA_PERIOD_COLORS[p] ?? MA_PERIOD_COLORS[5],
        }))}
        selected={maPeriods.map(String)}
        onChange={(next) => {
          const arr = next.map(Number).filter(n => Number.isFinite(n)).sort((a, b) => a - b)
          setMaPeriods(arr)
          onMaPeriodsChange?.(arr)
        }}
        placeholder="选择均线周期"
      />

      {/* 背驰配置 (买卖点识别判据) — 面积口径下拉 + 三条件下拉多选
          仅当勾选「买卖点」特征时生效; 后端 _identify_bs_points 据此过滤买卖点 */}
      {features.includes('bs_points') && (
        <fieldset className="flex flex-wrap items-end gap-3 border border-border rounded-btn p-2">
          <span className="w-full text-xs text-muted font-bold">背驰配置 (买卖点判据)</span>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted">面积口径</span>
            <select
              value={bsMacdAreaMode}
              onChange={e => setBsMacdAreaMode(e.target.value as typeof bsMacdAreaMode)}
              className="h-8 px-2 rounded-btn border border-border bg-base text-sm"
            >
              {BS_MACD_AREA_MODES.map(m => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </label>
          <MultiSelectDropdown
            label="背驰条件"
            options={[
              { value: 'macd_area', label: 'MACD面积' },
              { value: 'dif_peak', label: 'DIF极值' },
              { value: 'dea_peak', label: 'DEA极值' },
            ]}
            selected={[
              ...(bsUseMacdArea ? ['macd_area'] : []),
              ...(bsUseDif ? ['dif_peak'] : []),
              ...(bsUseDea ? ['dea_peak'] : []),
            ]}
            onChange={(next) => {
              setBsUseMacdArea(next.includes('macd_area'))
              setBsUseDif(next.includes('dif_peak'))
              setBsUseDea(next.includes('dea_peak'))
            }}
            placeholder="选择背驰条件"
          />
          <span className="w-full text-[10px] text-muted">
            所选条件 AND 全满足才算背驰; 减少条件可放宽识别 (信号增多)
          </span>
        </fieldset>
      )}

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
