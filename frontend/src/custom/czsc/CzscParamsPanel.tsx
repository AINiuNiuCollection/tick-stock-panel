/**
 * 缠论分析参数面板 — 范围/级别/频率/特征全可配置 (Q8)
 */
import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Settings2, X, HelpCircle, LineChart, Target, SlidersHorizontal } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { SymbolPicker } from '@/components/SymbolPicker'
import { api } from '@/lib/api'

/**
 * 帮助提示 — ? 图标, 鼠标悬停显示详细解释气泡。
 * 用于设置项的说明, 不占用横向空间。
 */
function HelpTip({ text }: { text: string }) {
  return (
    <span className="relative inline-flex group/tip align-middle ml-1">
      <HelpCircle className="h-3.5 w-3.5 text-muted cursor-help" />
      <span
        className="pointer-events-none absolute left-1/2 bottom-full mb-1 -translate-x-1/2 z-50
                   w-56 rounded-btn border border-border bg-elevated shadow-lg p-2 text-[11px] text-foreground
                   opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-opacity"
      >
        {text}
      </span>
    </span>
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
  /** @deprecated 缠师原文未要求 DEA, 保留字段兼容后端, 恒 false */
  bs_use_dea?: boolean
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
  // 背驰配置: 默认两条件 (MACD面积 + DIF) 全开, 面积口径 split (红绿柱分计)
  // DEA 已废弃 (缠师原文未要求), 不再暴露 UI; 提交时恒传 false 兼容后端
  const [bsMacdAreaMode, setBsMacdAreaMode] = useState<'split' | 'total_abs' | 'dif_dea'>('split')
  const [bsUseDif, setBsUseDif] = useState(true)
  const [bsUseMacdArea, setBsUseMacdArea] = useState(true)
  // 设置抽屉开关
  const [settingsOpen, setSettingsOpen] = useState(false)

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
      bs_use_dea: false,  // 已废弃, 恒 false 兼容后端
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

      {/* 齿轮设置按钮 — 点击弹出右侧抽屉 (均线/背驰/高级设置) */}
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        title="均线 / 背驰 / 高级设置"
        className="h-8 w-8 flex items-center justify-center rounded-btn border border-border bg-base text-muted hover:text-foreground hover:border-accent transition-colors"
      >
        <Settings2 className="h-4 w-4" />
      </button>

      <button
        type="submit"
        disabled={loading || !symbol.trim()}
        // 几何参考 hAdmin .btn-primary (圆角 3px / padding 4px 12px / font-weight 400 / 白字)
        // 颜色按用户要求与本工程主题对齐: --accent 电光蓝 (非 hAdmin 紫)
        className="h-8 min-w-[80px] px-3 py-1 rounded-[3px] bg-accent text-white text-sm font-normal leading-[1.42857143] transition-colors hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? '分析中…' : '分析'}
      </button>

      {/* ===== 设置抽屉 (右侧滑入, 仿 Settings 页分块卡片风格) =====
          均线实时应用 (onChange 立即触发 onMaPeriodsChange 更新图表);
          背驰/高级参数需手动点「分析」才生效 (后端计算)。 */}
      <AnimatePresence>
        {settingsOpen && (
          <>
            {/* 遮罩 */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 bg-black/30 z-40"
              onClick={() => setSettingsOpen(false)}
            />
            {/* 抽屉 */}
            <motion.aside
              initial={{ x: '100%' }}
              animate={{ x: 0 }}
              exit={{ x: '100%' }}
              transition={{ type: 'tween', duration: 0.2, ease: 'easeOut' }}
              className="fixed top-0 right-0 h-full w-[480px] max-w-[90vw] z-50 bg-surface border-l border-border shadow-2xl flex flex-col"
            >
              {/* 抽屉标题栏 */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-border">
                <div className="flex items-center gap-2">
                  <Settings2 className="h-4 w-4 text-accent" />
                  <h2 className="text-base font-medium text-foreground">缠论分析设置</h2>
                </div>
                <button
                  type="button"
                  onClick={() => setSettingsOpen(false)}
                  className="p-1 rounded-btn text-muted hover:text-foreground hover:bg-elevated transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* 抽屉内容 (可滚动) */}
              <div className="flex-1 overflow-auto px-5 py-4">

                {/* ===== 均线设置 ===== */}
                <section className="rounded-card border border-border bg-base p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <LineChart className="h-4 w-4 text-accent" />
                    <h3 className="text-sm font-medium text-foreground">
                      均线设置<HelpTip text="SMA 简单移动平均线。勾选即在K线图上叠加该周期均线, 不限条数。均线变化实时生效, 无需重新分析。每条均线颜色固定, 与下方色块一致。" />
                    </h3>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {MA_PERIOD_OPTIONS.map(p => {
                      const checked = maPeriods.includes(p)
                      const color = MA_PERIOD_COLORS[p] ?? MA_PERIOD_COLORS[5]
                      return (
                        <label
                          key={p}
                          className={`flex items-center justify-between gap-2 px-3 py-2 rounded-btn border text-sm cursor-pointer transition-colors ${checked ? 'border-accent bg-accent/10 text-foreground' : 'border-border text-muted hover:text-foreground'}`}
                        >
                          <span className="flex items-center gap-2 min-w-0">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                const next = checked
                                  ? maPeriods.filter(x => x !== p)
                                  : [...maPeriods, p].sort((a, b) => a - b)
                                setMaPeriods(next)
                                onMaPeriodsChange?.(next)
                              }}
                              className="accent-accent shrink-0"
                            />
                            <span className="truncate">SMA{p}</span>
                          </span>
                          <span className="w-5 h-2.5 rounded-sm shrink-0" style={{ backgroundColor: color }} />
                        </label>
                      )
                    })}
                  </div>
                  <div className="mt-2 text-[11px] text-muted">
                    当前已选 {maPeriods.length} 条: {maPeriods.length ? maPeriods.map(p => `SMA${p}`).join(' / ') : '无'}
                  </div>
                </section>

                {/* ===== 背驰判据设置 ===== */}
                <section className="rounded-card border border-border bg-base p-5 mt-5">
                  <div className="flex items-center gap-2 mb-3">
                    <Target className="h-4 w-4 text-accent" />
                    <h3 className="text-sm font-medium text-foreground">
                      背驰判据设置<HelpTip text="背驰是缠论买卖点识别的核心判据。仅当「特征」勾选了「买卖点」时生效。修改后需重新点「分析」才应用 (后端计算)。" />
                    </h3>
                  </div>

                  {/* 面积口径 */}
                  <div className="flex items-center justify-between gap-4 py-2">
                    <div className="min-w-0">
                      <div className="text-sm text-foreground flex items-center">
                        MACD 面积口径
                        <HelpTip text="计算一笔的 MACD 面积时采用的口径:&#10;• 红绿柱分计: 按笔方向取同向柱面积 (下跌笔取绿柱, 上涨笔取红柱)&#10;• Σ|hist|: 该笔区间内所有 MACD 柱绝对值之和&#10;• Σ|DIF-DEA|: 该笔区间内 |DIF-DEA| 之和 (与柱高同源)" />
                      </div>
                      <div className="text-[11px] text-muted truncate">对比两段同向笔的 MACD 面积, 递减则背驰</div>
                    </div>
                    <select
                      value={bsMacdAreaMode}
                      onChange={e => setBsMacdAreaMode(e.target.value as typeof bsMacdAreaMode)}
                      className="h-8 px-2 rounded-btn border border-border bg-surface text-sm shrink-0"
                    >
                      {BS_MACD_AREA_MODES.map(m => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                      ))}
                    </select>
                  </div>

                  {/* 两条件 (缠师原文: MACD面积 + DIF, 无 DEA) */}
                  <div className="text-sm text-foreground mt-3 mb-2 flex items-center">
                    背驰条件 (AND 全满足)
                    <HelpTip text="两个条件全部满足才算背驰 (AND 关系), 严格对齐缠师原文第 24 课。取消勾选任一条件可放宽识别, 买卖点信号会增多但准确度下降。&#10;• MACD面积: c 段面积 < a 段面积 (a 段=趋势起始/中枢进入, c 段=末笔/离开段)&#10;• DIF极值: c 段 DIF 高点 < a 段 DIF 高点 (上涨取 max, 下跌取 min)&#10;注: DEA 条件已移除 (缠师原文未要求)" />
                  </div>
                  <div className="flex flex-col gap-2">
                    <label className={`flex items-center gap-2 px-3 py-2 rounded-btn border text-sm cursor-pointer transition-colors ${bsUseMacdArea ? 'border-accent bg-accent/10 text-foreground' : 'border-border text-muted hover:text-foreground'}`}>
                      <input
                        type="checkbox"
                        checked={bsUseMacdArea}
                        onChange={e => setBsUseMacdArea(e.target.checked)}
                        className="accent-accent"
                      />
                      MACD 面积递减
                    </label>
                    <label className={`flex items-center gap-2 px-3 py-2 rounded-btn border text-sm cursor-pointer transition-colors ${bsUseDif ? 'border-accent bg-accent/10 text-foreground' : 'border-border text-muted hover:text-foreground'}`}>
                      <input
                        type="checkbox"
                        checked={bsUseDif}
                        onChange={e => setBsUseDif(e.target.checked)}
                        className="accent-accent"
                      />
                      DIF 极值弱化
                    </label>
                  </div>
                  <div className="mt-2 text-[11px] text-muted">
                    所选条件 AND 全满足才算背驰; 减少条件可放宽识别 (信号增多)
                  </div>
                </section>

                {/* ===== 高级设置 ===== */}
                <section className="rounded-card border border-border bg-base p-5 mt-5">
                  <div className="flex items-center gap-2 mb-3">
                    <SlidersHorizontal className="h-4 w-4 text-accent" />
                    <h3 className="text-sm font-medium text-foreground">
                      高级设置<HelpTip text="影响分析行为的全局开关。" />
                    </h3>
                  </div>
                  <label className="flex items-center justify-between gap-4 py-2 cursor-pointer">
                    <div className="min-w-0">
                      <div className="text-sm text-foreground flex items-center">
                        强制刷新缓存
                        <HelpTip text="勾选后本次分析忽略后端缓存, 强制重新取数并计算。当前版本后端无缓存层, 此项暂为预留。" />
                      </div>
                      <div className="text-[11px] text-muted truncate">忽略缓存, 强制重新取数</div>
                    </div>
                    <input
                      type="checkbox"
                      checked={forceRefresh}
                      onChange={e => setForceRefresh(e.target.checked)}
                      className="accent-accent h-4 w-4"
                    />
                  </label>
                </section>

              </div>

              {/* 抽屉底部按钮 */}
              <div className="flex justify-end gap-2 px-5 py-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => setSettingsOpen(false)}
                  className="h-8 px-4 rounded-btn border border-border bg-surface text-sm text-foreground hover:bg-elevated transition-colors"
                >
                  关闭
                </button>
              </div>
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </form>
  )
}
