/**
 * 通用标的搜索选择器 — 代码 / 名称 / 拼音首字母模糊匹配。
 *
 * 复用 instrumentSearch 后端 (frontend/src/lib/api.ts: instrumentSearch)。
 * 模式对齐 Watchlist.StockSearchBox / StockFinancialSearch:
 *   - useQuery + staleTime 30s
 *   - 外部点击关闭 + Esc 关闭 + 上/下键导航 + Enter 选中
 *
 * 支持两种使用方式:
 *   1. 受控 (value/onChange): 适合表单内嵌, 如缠论分析参数面板。
 *      选中后 value 被设置为 symbol (如 "600519.SH"), 显示输入框可继续编辑。
 *   2. 非受控 (onSelect): 适合独立搜索入口, 如财务页主搜索框。
 *      选中后清空输入并触发 onSelect(symbol, name)。
 *
 * 通过 size="sm" | "md" 切换紧凑/标准两种尺寸。
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { boardTag } from '@/components/stock-table/primitives'

export interface SymbolPickerResult {
  symbol: string
  name: string
  code?: string
  asset_type?: string
}

interface CommonProps {
  /** 搜索资产类型, 逗号分隔 (默认 'stock,etf,index') */
  assetTypes?: string
  /** 占位提示 */
  placeholder?: string
  /** 尺寸: sm = 紧凑 (表单内嵌), md = 标准 (主搜索入口) */
  size?: 'sm' | 'md'
  /** 容器自定义 className */
  className?: string
  /** 是否禁用 */
  disabled?: boolean
}

interface ControlledProps extends CommonProps {
  /** 受控模式: 表单内嵌时使用 */
  value: string
  onChange: (symbol: string) => void
  onSelect?: never
}

interface UncontrolledProps extends CommonProps {
  /** 非受控模式: 独立搜索入口时使用 */
  onSelect: (symbol: string, name: string) => void
  value?: never
  onChange?: never
}

type Props = ControlledProps | UncontrolledProps

export function SymbolPicker(props: Props) {
  const {
    assetTypes = 'stock,etf,index',
    placeholder = '输入代码 / 名称',
    size = 'md',
    className = '',
    disabled = false,
  } = props
  const isControlled = props.value !== undefined

  // 受控模式下, query 既跟踪用户输入搜索, 也会回显当前 value; 输入框始终显示用户输入
  const [query, setQuery] = useState(isControlled ? (props.value as string) : '')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // 受控模式: 外部 value 变化时同步显示 (例如清空/重置)
  useEffect(() => {
    if (isControlled && document.activeElement !== inputRef.current) {
      setQuery(props.value as string)
    }
  }, [props.value, isControlled])

  const search = useQuery({
    queryKey: QK.instrumentSearch(query, assetTypes),
    queryFn: () => api.instrumentSearch(query, 20, assetTypes),
    enabled: query.trim().length > 0,
    staleTime: 30_000,
  })

  const results: SymbolPickerResult[] = search.data?.results ?? []

  // 外部点击关闭下拉
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  function handleSelect(r: SymbolPickerResult) {
    if (isControlled) {
      (props as ControlledProps).onChange(r.symbol)
      setQuery(r.symbol)
    } else {
      (props as UncontrolledProps).onSelect(r.symbol, r.name)
      setQuery('')
    }
    setOpen(false)
    setActiveIdx(-1)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') { setOpen(false); return }
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx(i => Math.max(i - 1, -1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (activeIdx >= 0) handleSelect(results[activeIdx])
      else if (results.length > 0) handleSelect(results[0])
    }
  }

  const trimmed = query.trim()

  // 尺寸变体
  const inputCls = size === 'sm'
    ? 'w-full h-8 pl-9 pr-9 rounded-btn bg-base border border-border text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-accent/50 transition-colors'
    : 'w-full h-11 pl-11 pr-10 rounded-card bg-surface border border-border text-sm text-foreground placeholder:text-muted focus:outline-none focus:border-accent/50 focus:bg-base transition-colors'
  const iconCls = size === 'sm'
    ? 'absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none'
    : 'absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none'
  const loaderCls = size === 'sm'
    ? 'absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted animate-spin'
    : 'absolute right-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted animate-spin'

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <div className="relative flex items-center">
        <Search className={iconCls} />
        <input
          ref={inputRef}
          type="text"
          placeholder={placeholder}
          value={query}
          disabled={disabled}
          onChange={(e) => {
            setQuery(e.target.value)
            setOpen(true)
            setActiveIdx(-1)
            // 受控模式下, 用户手动输入也同步到父组件 (允许直接键入完整 symbol 不选下拉)
            if (isControlled) (props as ControlledProps).onChange(e.target.value)
          }}
          onFocus={() => { if (trimmed) setOpen(true) }}
          onKeyDown={handleKeyDown}
          className={inputCls}
        />
        {search.isFetching && (
          <Loader2 className={loaderCls} />
        )}
      </div>

      <AnimatePresence>
        {open && trimmed && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12, ease: [0.16, 1, 0.3, 1] }}
            className="absolute left-0 right-0 top-full mt-1.5 z-50 max-h-[360px] overflow-y-auto rounded-card border border-border bg-base shadow-xl"
          >
            {search.isLoading ? (
              <div className="px-4 py-6 flex items-center justify-center gap-2 text-xs text-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                搜索中…
              </div>
            ) : results.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-muted">
                未找到匹配的股票
              </div>
            ) : (
              results.map((r, i) => (
                <button
                  key={r.symbol}
                  type="button"
                  onClick={() => handleSelect(r)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors duration-100 ${
                    i === activeIdx ? 'bg-accent/10 text-accent' : 'hover:bg-elevated text-foreground'
                  }`}
                >
                  <span className="font-mono shrink-0 text-xs w-[88px]">{r.symbol}</span>
                  <span className="truncate text-sm flex-1">{r.name}</span>
                  {(() => {
                    const b = boardTag(r.symbol)
                    return b && (
                      <span className={`shrink-0 px-1 py-0.5 rounded text-[10px] leading-none border ${b.color}`}>{b.label}</span>
                    )
                  })()}
                  {r.asset_type === 'index' && (
                    <span className="shrink-0 px-1 py-0.5 rounded text-[10px] leading-none bg-sky-500/10 text-sky-400">指数</span>
                  )}
                  {r.asset_type === 'etf' && (
                    <span className="shrink-0 px-1 py-0.5 rounded text-[10px] leading-none bg-violet-500/10 text-violet-400">ETF</span>
                  )}
                  {r.code && <span className="text-[10px] text-muted font-mono shrink-0">{r.code}</span>}
                </button>
              ))
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
