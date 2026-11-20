/**
 * 缠论分析 ECharts 可视化 — K 线叠加 SMA / FX 虚线 / BI 实线 / 中枢紫框
 *
 * 复用 echarts 依赖, 不引入新前端库。
 * 对齐 czsc 库原生 lightweight-charts 主题 (czsc/utils/plotting/lightweight/_theme.py),
 * 图表元素语义:
 *   - K 线: 红涨绿跌 (czsc 原生 up/down 色)
 *   - SMA5: 古铜色实线 (czsc 原生 sma5)
 *   - SMA20: 钢蓝色实线 (czsc 原生 sma20)
 *   - FX 分型: 卡其色虚线折线, 连接分型高/低点 (czsc 原生 fx_dashed)
 *   - BI 笔: 深靛蓝实线, 连接笔端点 (czsc 原生 bi)
 *   - 中枢: 紫色虚线边框矩形 + ZS 序号标签 (czsc 原生不画中枢, 本工程自定义)
 */
import { useEffect, useRef, useImperativeHandle, forwardRef, useState } from 'react'
import * as echarts from 'echarts'
import type { CzscAnalyzeResult, CzscMa } from '@/lib/api'

/**
 * 监听 html.dark 类变化, 触发图表重渲染以切换 light/dark 主题。
 * 返回当前是否为 dark; 仅用于触发依赖, 实际配色在 getChartTheme() 内读取 DOM。
 */
function useDarkMode(): boolean {
  const [isDark, setIsDark] = useState(
    typeof document !== 'undefined'
      && document.documentElement.classList.contains('dark')
  )
  useEffect(() => {
    if (typeof document === 'undefined') return
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'))
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])
  return isDark
}

/** 判断顶分型: czsc 1.0.2 返回 mark='顶分型' (旧版 'Mark.G') */
function isTopMark(mark: string): boolean {
  return mark === 'Mark.G' || mark === '顶分型' || mark.includes('顶')
}

/** 判断向上笔: czsc 1.0.2 返回 direction='向上' (旧版 'Direction.Up') */
function isUpDirection(direction: string): boolean {
  return direction === 'Direction.Up' || direction === '向上' || direction.includes('上')
}

/**
 * 主题配色 — 对齐 czsc 库原生 lightweight-charts 主题
 * (czsc/utils/plotting/lightweight/_theme.py:29-60 THEMES 字典)。
 * light "量化年鉴" 暖纸色调 / dark "Deep Cosmos" 深空配色,
 * 与本工程 html.dark 切换联动。
 *
 * 字段命名严格对齐 czsc _theme.py: background/text/grid/up/down/
 * sma5/sma20/fx_dashed/bi。中枢矩形 czsc 原生不画, 本工程自定义
 * 紫色虚线边框 + ZS 序号 (zsBorder), 与 czsc 信号调色板第 5 色
 * (#7B4FA8 light / #C29CF2 dark) 同系, 不与 K 线红绿或笔色冲突。
 */
interface ChartTheme {
  background: string
  text: string
  grid: string
  up: string         // K 线涨色 (阳线) — czsc _theme.py:36/50
  down: string       // K 线跌色 (阴线) — czsc _theme.py:37/51
  sma5: string       // SMA5 古铜色 — czsc _theme.py:38/52
  sma20: string      // SMA20 钢蓝色 — czsc _theme.py:39/53
  fx_dashed: string  // 分型虚线色 (卡其) — czsc _theme.py:40/54
  bi: string         // 笔色 (深靛蓝) — czsc _theme.py:41/55
  zsBorder: string   // 中枢矩形紫色虚线边框 (本工程自定义)
  zsLabel: string    // 中枢 ZS 序号标签色 (本工程自定义)
  zsFill: string     // 中枢浅粉色透明底色 (项5: rgba(255,182,193,0.18))
}

function getChartTheme(): ChartTheme {
  const isDark = typeof document !== 'undefined'
    && document.documentElement.classList.contains('dark')
  if (isDark) {
    // czsc dark "Deep Cosmos" — 变更点3: 虚线/中枢边框加深
    return {
      background: '#0E1116',
      text: '#EFEBE0',
      grid: '#1F242E',
      up: '#E94B3C',
      down: '#5BB85B',
      sma5: '#E6A93B',
      sma20: '#6EB6E4',
      fx_dashed: '#B5AE9A',     // 加深: #8B8678 → #B5AE9A (虚线对比度提升)
      bi: '#A8B8E8',
      zsBorder: '#9D6FD4',      // 加深: #C29CF2 → #9D6FD4 (中枢边框更醒目)
      zsLabel: '#9D6FD4',
      zsFill: 'rgba(255,182,193,0.18)',  // 项5: 浅粉色透明底色, dark/light 同色
    }
  }
  // czsc light "量化年鉴" 暖纸色 — 变更点3: 虚线/中枢边框加深
  return {
    background: '#F5F4EF',
    text: '#1A1A17',
    grid: '#E8E2D4',
    up: '#C03A2B',
    down: '#2E7D32',
    sma5: '#C78A2E',
    sma20: '#2D6A8C',
    fx_dashed: '#6B5A3E',     // 加深: #8B7E5E → #6B5A3E
    bi: '#1F3C6E',
    zsBorder: '#5B3A88',      // 加深: #7B4FA8 → #5B3A88
    zsLabel: '#5B3A88',
    zsFill: 'rgba(255,182,193,0.18)',  // 项5: 浅粉色透明底色
  }
}

/**
 * 计算 SMA(N) 简单移动平均线。
 * @param closes 收盘价序列 (按时间升序)
 * @param period 周期 (SMA5 → 5, SMA20 → 20)
 * @returns 与 closes 等长的数组, 前 period-1 个为 null
 */
function calcSMA(closes: number[], period: number): Array<number | null> {
  const out: Array<number | null> = []
  let sum = 0
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i]
    if (i >= period) sum -= closes[i - period]
    out.push(i >= period - 1 ? sum / period : null)
  }
  return out
}

/**
 * 格式化成交量: >=1e9 → "X.XXB", >=1e6 → "X.XXM", >=1e3 → "X.XXK", 否则原值。
 * 对齐示例图右侧面板 "VOL 1.61M" 风格。
 */
function formatVol(vol: number): string {
  if (!isFinite(vol)) return '—'
  if (vol >= 1e9) return (vol / 1e9).toFixed(2) + 'B'
  if (vol >= 1e6) return (vol / 1e6).toFixed(2) + 'M'
  if (vol >= 1e3) return (vol / 1e3).toFixed(2) + 'K'
  return vol.toFixed(0)
}

/**
 * xAxis 标签格式化 — 对齐示例图底部时间轴:
 *   - 同年内显示 "M月" (如 "4月" "11月")
 *   - 1月或跨年首月显示 "YYYY年" (如 "2026年")
 * 通过比较当前 index 与前一 index 的年份判断跨年。
 */
function formatXAxisLabel(
  categories: string[],
  _value: string,
  index: number,
): string {
  const dt = categories[index]
  if (!dt) return ''
  // dt 形如 "2026-11-09 00:00:00" 或 "2026-11-09"
  const m = dt.match(/^(\d{4})-(\d{2})/)
  if (!m) return dt
  const year = m[1]
  const month = Number(m[2])
  // 跨年: 前一个不同年 或 index=0 (首月显示年份)
  if (index === 0) return `${year}年`
  const prev = categories[index - 1]
  const prevM = prev ? prev.match(/^(\d{4})-(\d{2})/) : null
  if (!prevM || prevM[1] !== year) return `${year}年`
  return `${month}月`
}

export interface CzscChartHandle {
  /** 导出当前图表为 base64 PNG dataURL (供 HTML 报告嵌入) */
  getDataURL: () => string | null
}

interface Props {
  result: CzscAnalyzeResult
  /**
   * K 线数据 (OHLCV), 由调用方提供。
   * 若不传, 自动从 result.bars 推导 (后端 analyze 响应已含 bars 字段)。
   * 兼容旧调用方传 {date, open, ...} 格式 (date 字段), 优先级高于 result.bars。
   */
  klines?: Array<{ date: string; open: number; high: number; low: number; close: number; vol: number }>
  /**
   * 图表高度。传 number 为固定 px; 传 "100%" 则撑满父容器 (父容器需有确定高度)。
   * 变更点1: 支持 "100%" 让图表区随父级 flex 占比动态伸缩, 不再需要外层传固定 px。
   */
  height?: number | string
  /**
   * 均线周期列表 (不限条数)。
   * 默认 [5, 10, 20]; 每个数字为 SMA 周期 (5/10/12/20/30/60/120/250 日)。
   * 空数组表示不画均线。
   */
  maPeriods?: number[]
}

// 均线配色表 — 按周期映射 (与 CzscParamsPanel.MA_PERIOD_COLORS 同步,
// 确保下拉项色块与图表中该均线颜色完全一致)
const MA_COLORS: Record<number, string> = {
  5: '#C78A2E',
  10: '#2D6A8C',
  12: '#9D6FD4',
  20: '#D94F70',
  30: '#3F8E58',
  60: '#B58A1F',
  120: '#5B6FA8',
  250: '#8C6BA8',
}
// 兜底色 (未知周期按序循环)
const MA_COLOR_FALLBACK = ['#C78A2E', '#2D6A8C', '#9D6FD4', '#D94F70', '#3F8E58', '#B58A1F', '#5B6FA8', '#8C6BA8']

export const CzscChart = forwardRef<CzscChartHandle, Props>(function CzscChart(
  { result, klines, height = 480, maPeriods },
  ref,
) {
  // 均线周期: 默认 [5, 10, 20], 不限条数
  const maPeriodsNorm = (maPeriods && maPeriods.length > 0)
    ? maPeriods.filter(p => p > 0)
    : [5, 10, 20]
  // 优先用显式传入的 klines; 否则从 result.bars 推导 (date 字段 = dt)
  const resolvedKlines = klines && klines.length
    ? klines
    : (result.bars ?? []).map(b => ({ date: b.dt, open: b.open, high: b.high, low: b.low, close: b.close, vol: b.vol }))
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  // 右上角数据面板拖动后的位置 (像素坐标, 相对画布); null 表示用默认右上角定位
  const panelPosRef = useRef<{ left: number; top: number } | null>(null)
  // 主题切换时触发图表重渲染
  const isDark = useDarkMode()

  useEffect(() => {
    if (!containerRef.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(containerRef.current)
    }
    return () => {
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  // 暴露 getDataURL 给父组件, 供 HTML 报告导出嵌入 PNG
  useImperativeHandle(ref, () => ({
    getDataURL: () => {
      if (!chartRef.current) return null
      try {
        return chartRef.current.getDataURL({
          type: 'png',
          pixelRatio: 2,
          backgroundColor: getChartTheme().background,
        })
      } catch (e) {
        console.error('CzscChart getDataURL failed:', e)
        return null
      }
    },
  }), [])

  useEffect(() => {
    if (!chartRef.current) return
    const theme = getChartTheme()

    // K 线数据 (优先用显式 klines, 否则从 result.bars 推导)
    const candleData = resolvedKlines.length
      ? resolvedKlines.map(k => [k.open, k.close, k.low, k.high])
      : []

    // 动态均线 SMA(N) — 优先用后端下发的 result.mas (含 120/250, 已扩展暖机);
    // 兜底: result.mas 为空 / 长度不匹配 / 该周期字段缺失时, 前端基于 close 自算。
    // maPeriodsNorm 由 props 传入 (默认 [5,10,20], 最多 3 条, 参考同花顺)。
    // 每条均线独立颜色 (MA_COLORS), 与顶部 legend 联动。
    const closes = resolvedKlines.map(k => k.close)
    const dateCategories = resolvedKlines.map(k => k.date)
    // 后端 mas 按 dt 与 bars 对齐; 旧缓存可能无 mas 字段, 用空数组兜底
    const masData: CzscMa[] = result.mas ?? []
    // 按 dateCategories 顺序取 ma{p} 值; 逐周期判断是否走后端数据:
    //   1. masData 长度与 dateCategories 完全对齐
    //   2. 该周期字段在 masData 首行中存在 (用户改均线但未重新分析时, 旧 mas 缺新周期字段)
    // 不满足任一条件则该周期回退到前端 calcSMA 自算 (无暖机, 但至少能显示)
    const masAligned = masData.length === dateCategories.length && masData.length > 0
    const maDataList = maPeriodsNorm.map((p, i) => {
      const color = MA_COLORS[p] ?? MA_COLOR_FALLBACK[i % MA_COLOR_FALLBACK.length]
      // 检查该周期是否在后端 mas 中存在 (取首行 sample 判断字段是否定义)
      const hasBackendField = masAligned && masData[0] && (`ma${p}` in masData[0])
      const data = hasBackendField
        ? masData.map(m => m[`ma${p}`] ?? null)
        : calcSMA(closes, p)
      return { period: p, color, data }
    })

    // 成交量副图数据 — 红绿柱: close>=open 用 theme.up, 否则 theme.down (对齐示例图与 czsc colorizeVol)
    const volData = resolvedKlines.map(k => ({
      value: k.vol,
      itemStyle: { color: k.close >= k.open ? theme.up : theme.down },
    }))

    // MACD 副图数据 (后端计算 EMA12/26/9, 前端仅消费)
    // - 柱状 hist: 红 (>=0) 绿 (<0)
    // - DIFF / DEA 两条折线, 对齐示例图 "MACD · 12/26/9"
    //
    // 变更点4: 前慢速 EMA 暖机段 (前 25 根 DIF/DEA 可能为 null) 视为 0, 让副图从首根显示,
    //          不再出现"左侧忍让没有数据"的空白。这与 czsc/通达信惯例一致 (前段补 0 而非留空)。
    const macdList = result.macd ?? []
    const macdHistData = macdList.map(m => ({
      value: m.macd ?? 0,
      itemStyle: { color: (m.macd ?? 0) >= 0 ? theme.up : theme.down },
    }))
    const macdDiffData = macdList.map(m => m.dif ?? 0)
    const macdDeaData = macdList.map(m => m.dea ?? 0)

    // 最后一根 bar 的 OHLC/CHG/VOL/MACD 数据, 用于右上角悬浮面板 (graphic 元素)
    const lastBar = resolvedKlines[resolvedKlines.length - 1]
    const lastMacd = macdList[macdList.length - 1]
    const prevClose = resolvedKlines.length >= 2 ? resolvedKlines[resolvedKlines.length - 2].close : lastBar?.close
    const chgPct = lastBar && prevClose != null
      ? ((lastBar.close - prevClose) / prevClose) * 100
      : null

    // FX 分型虚线折线 — 对齐示例图与 czsc 原生 fx_dashed:
    // 依次连接 fx_list 中每个分型的极值 (顶分型取 high, 底分型取 low),
    // 用 lines series 渲染整条折线, type='dashed', color=theme.fx_dashed。
    // 不再使用三角箭头 markPoint (示例图无箭头)。
    //
    // 变更点2: 只在顶底分型交替时画虚线 (跳过连续同向孤立分型),
    //          避免出现"没有顶底分型也有虚线连接"的伪分型段。
    //          连续同向: 同是顶或同是底时, 跳过当前点不画, 不推进 prev。
    const fxSorted = [...result.fx_list].sort((a, b) =>
      a.dt < b.dt ? -1 : a.dt > b.dt ? 1 : 0,
    )
    const fxSegments: Array<{ coords: [[string, number], [string, number]]; lineStyle: object }> = []
    let prevFx = fxSorted[0]
    for (let i = 1; i < fxSorted.length; i++) {
      const curr = fxSorted[i]
      const prevIsTop = isTopMark(prevFx.mark)
      const currIsTop = isTopMark(curr.mark)
      // 同向分型: 跳过, 不画虚线也不推进 prev (保留前一个作锚点)
      if (prevIsTop === currIsTop) continue
      const prevY = prevIsTop ? prevFx.high : prevFx.low
      const currY = currIsTop ? curr.high : curr.low
      fxSegments.push({
        coords: [[prevFx.dt, prevY], [curr.dt, currY]],
        lineStyle: {
          color: theme.fx_dashed,
          width: 1.6,  // 变更点3: 加粗 1.2 → 1.6, 提升虚线可见度
          type: 'dashed' as const,
        },
      })
      // 交替成功才推进 prev, 下一段从这里开始
      prevFx = curr
    }

    // BI 笔实线 — 对齐示例图与 czsc 原生 bi: 连接每笔起止端点 (sdt→edt),
    // 上笔取 low→high, 下笔取 high→low, type='solid', color=theme.bi
    const biLines = result.bi_list.map(bi => ({
      coords: [
        [bi.sdt, isUpDirection(bi.direction) ? bi.low : bi.high],
        [bi.edt, isUpDirection(bi.direction) ? bi.high : bi.low],
      ],
      lineStyle: {
        color: theme.bi,
        width: 1.8,
        type: 'solid' as const,
      },
    }))

    // 项4: 顶底分型红绿三角标识 — 仅标成笔 (bi_list) 的两端端点
    //   缠论: 笔的两端必须是分型。fx_list 包含所有分型 (含未成笔的孤立分型),
    //   全标会过密; 这里只标 bi_list 中每笔的起止端点, 与缠理「成笔才有意义」对齐。
    //
    //   提取规则 (与通达信/同花顺惯例一致):
    //     - 向上笔: 起点=底分型 (绿▼ at [sdt, low]), 终点=顶分型 (红▲ at [edt, high])
    //     - 向下笔: 起点=顶分型 (红▲ at [sdt, high]), 终点=底分型 (绿▼ at [edt, low])
    //   相邻笔共享端点 (笔1终点=笔2起点), 用 Map<dt, point> 去重避免同位置叠三角。
    //
    //   FX 虚线折线仍按 fx_list 全分型绘制 (展示分型演变), 与三角职责分离。
    const fxMarkPoints: Array<{
      coord: [string, number]
      symbol: 'triangle'
      symbolSize: number
      symbolRotate: number
      itemStyle: { color: string }
      label: { show: boolean }
    }> = []
    const biEndpointMap = new Map<string, typeof fxMarkPoints[number]>()
    for (const bi of result.bi_list) {
      const isUp = isUpDirection(bi.direction)
      // 起点
      const startPt = {
        coord: [bi.sdt, isUp ? bi.low : bi.high] as [string, number],
        symbol: 'triangle' as const,
        symbolSize: 10,
        symbolRotate: isUp ? 180 : 0,   // 向上笔起点是底分型▼ / 向下笔起点是顶分型▲
        itemStyle: { color: isUp ? theme.down : theme.up },
        label: { show: false },
      }
      // 终点
      const endPt = {
        coord: [bi.edt, isUp ? bi.high : bi.low] as [string, number],
        symbol: 'triangle' as const,
        symbolSize: 10,
        symbolRotate: isUp ? 0 : 180,   // 向上笔终点是顶分型▲ / 向下笔终点是底分型▼
        itemStyle: { color: isUp ? theme.up : theme.down },
        label: { show: false },
      }
      // 用 dt 去重: 同一 dt 上的端点只保留一个 (相邻笔共享端点)
      if (!biEndpointMap.has(bi.sdt)) biEndpointMap.set(bi.sdt, startPt)
      if (!biEndpointMap.has(bi.edt)) biEndpointMap.set(bi.edt, endPt)
    }
    fxMarkPoints.push(...biEndpointMap.values())

    // 中枢矩形 (markArea) — czsc 中枢 = 至少 3 笔重叠的价格区间 [zd, zg]
    // 对齐示例图: 紫色虚线边框, 浅粉底色 (项5), 不画 zd/zg 数值标签 (项4 单独标)
    // itemStyle 必须写在 markArea 顶层 (对所有矩形生效), 写在点对象里会被 echarts 忽略
    //
    // 变更点1: 只渲染 valid 中枢 (zs.valid !== false), 序号重新编号。
    //          czsc 库 get_zs_seq 原始算法每笔必归某中枢 (含 is_valid=False 的重叠不足中枢),
    //          此处按用户确认的 C 方案仅做渲染过滤, 不改算法。
    //
    // 中枢起止优化: czsc 原生 start_dt/end_dt 是「构成中枢的第一笔起点 / 最后一笔终点」,
    //   相邻中枢首尾相接时方框紧贴无间隔。改为在 [start_dt, end_dt] 范围内找
    //   第一根与最后一根「K 线区间与中枢价格区间有交集」的 K 线 (low<=zg && high>=zd),
    //   让方框收缩到真正与中枢交互的 K 线段, 相邻中枢之间露出空白。
    //   范围内无相交 K 线时回退原始边界 (兜底)。
    const validZsList = result.zs_list.filter(zs => zs.valid !== false)
    const zsRanges = validZsList.map(zs => {
      const [zd, zg] = zs.zs_range
      // 在 result.bars 中按 dt 限定到 [zs.start_dt, zs.end_dt] 范围
      // bars 是后端返回的 K 线列表 (与 resolvedKlines 同源), dt 字段为 ISO 字符串
      const barsAll = result.bars ?? []
      const inRange = barsAll.filter(b =>
        b.dt >= zs.start_dt && b.dt <= zs.end_dt,
      )
      // 找第一根与最后一根与中枢区间相交的 K 线
      // 相交判定: K 线 [low, high] 与中枢 [zd, zg] 有交集 ⇔ low<=zg && high>=zd
      let firstDt: string | null = null
      let lastDt: string | null = null
      for (const b of inRange) {
        if (b.low <= zg && b.high >= zd) {
          if (firstDt === null) firstDt = b.dt
          lastDt = b.dt
        }
      }
      const finalStart = firstDt ?? zs.start_dt
      const finalEnd = lastDt ?? zs.end_dt
      return { zs, start_dt: finalStart, end_dt: finalEnd }
    })
    const zsAreas = zsRanges.map(({ zs, start_dt, end_dt }) => ([
      { xAxis: start_dt, yAxis: zs.zs_range[0] },
      { xAxis: end_dt,   yAxis: zs.zs_range[1] },
    ]))

    // 缠论买卖点 (B1/B2/B3/S1/S2/S3) — 标在笔端点 K 线 (后端已计算背驰详细信息)
    //   买点 (B1/B2/B3): 红色加粗 12px (与 K 线涨色同系, 突出买点信号)
    //   卖点 (S1/S2/S3): 绿色加粗 12px (与 K 线跌色同系, 突出卖点信号)
    //   用 scatter series + label.formatter 渲染文字, 标在 price 上方 (买) / 下方 (卖)。
    //   tooltip 显示背驰详情: 前段面积/当前面积/前段DIF高点/当前DIF高点/DEA/背驰类型。
    const bsPoints = result.bs_points ?? []
    const bsScatterData = bsPoints.map(bp => ({
      value: [bp.dt, bp.price],
      // 给 tooltip formatter 用: 把背驰信息附在 data 上
      bsInfo: bp,
    }))

    // 中枢 ZS 序号标签 — markPoint 标在每个矩形顶部 (zg 价位) 位置, 显示 ZS1/ZS2/...
    // 对齐示例图右上角的 ZS1/ZS2/ZS3 灰色文字标注
    // 序号基于过滤后的 validZsList 重新编号 (避免跳号)
    //
    // 项4: 同时标 zg (上沿) / zd (下沿) 两个价位数值。
    //   - ZS 序号: 顶部 (zg 上方), 紫色
    //   - zg 价位: 矩形右上角内侧, 紫色小字
    //   - zd 价位: 矩形右下角内侧, 紫色小字
    const zsLabels = zsRanges.map(({ zs, start_dt }, idx) => ({
      name: `ZS${idx + 1}`,
      coord: [start_dt, zs.zs_range[1]],
      symbol: 'circle',
      symbolSize: 0,
      itemStyle: { color: 'transparent' },
      label: {
        show: true,
        formatter: `ZS${idx + 1}`,
        color: theme.zsLabel,
        fontSize: 11,
        fontWeight: 'bold',
        position: 'top',
      },
    }))
    // zg / zd 价位标签 (项4): 用 markPoint coord + label 显示价位数值
    // 用优化后的 end_dt (最后一根与中枢区间相交的 K 线) 让标签贴在新方框右边缘
    const zsPriceLabels: Array<{
      coord: [string, number]
      label: { show: boolean; formatter: string; color: string; fontSize: number; position: string; backgroundColor: string; padding: number[] }
    }> = []
    zsRanges.forEach(({ zs, end_dt }) => {
      const [zd, zg] = zs.zs_range
      zsPriceLabels.push({
        coord: [end_dt, zg],
        label: {
          show: true,
          formatter: zg.toFixed(2),
          color: theme.zsLabel,
          fontSize: 10,
          position: 'insideTopRight',
          backgroundColor: theme.background,
          padding: [1, 3],
        },
      })
      zsPriceLabels.push({
        coord: [end_dt, zd],
        label: {
          show: true,
          formatter: zd.toFixed(2),
          color: theme.zsLabel,
          fontSize: 10,
          position: 'insideBottomRight',
          backgroundColor: theme.background,
          padding: [1, 3],
        },
      })
    })

    // 三栏布局: 主图 60% / 成交量 15% / MACD 20% (剩余 5% 留给 dataZoom 与边距)
    // 三个 grid 共享 category xAxis, 各自独立 yAxis。axisIndex 将 series 绑定到对应 grid。
    // containLabel: true 让 echarts 把 y 轴标签宽度算进 grid 区域, 避免 MACD 负数标签 (-0.50) 被裁切。
    //
    // 变更点8: y 轴刻度改到右侧 (position:'right'), gridRight 加宽到 56 容纳刻度宽度,
    //          gridLeft 减到 4 (左侧不再需要容纳刻度)。主图与 VOL/MACD 都改右侧, 三栏右侧对齐。
    const gridLeft = 4
    const gridRight = 56
    const mainGrid = { left: gridLeft, right: gridRight, top: 64, height: '52%', containLabel: true }
    const volGrid = { left: gridLeft, right: gridRight, top: '66%', height: '11%', containLabel: true }
    const macdGrid = { left: gridLeft, right: gridRight, top: '80%', height: '14%', containLabel: true }

    // 右上角悬浮数据面板 (graphic 元素), 显示最后一根 bar 的 OHLC/CHG/VOL/MACD
    // 对齐示例图右侧黑色文字面板
    const graphicElements: echarts.EChartsOption['graphic'] = []
    // ===== 左上角股票标题 (仅标题, 图例统一由顶部 legend 承载, 避免重复) =====
    // 变更点7: 加中文标识 — 主标题显示 "代码 中文名" (中文名来自前端透传 symbol_name);
    //          副标题同样含中文, 让左上角 tag 不仅有编号也有中文标识。
    const symbolDisplayName = result.symbol_name ? `${result.symbol} ${result.symbol_name}` : result.symbol
    graphicElements.push({
      type: 'group',
      left: gridLeft,
      top: 8,
      children: [
        {
          type: 'text',
          style: {
            text: symbolDisplayName,
            x: 0, y: 0,
            fill: theme.text,
            font: 'bold 18px Inter, "HarmonyOS Sans SC", sans-serif',
          },
        },
        {
          type: 'text',
          style: {
            text: `${symbolDisplayName} 缠论结构 (${result.freq})`,
            x: 0, y: 22,
            fill: theme.text,
            opacity: 0.5,
            font: '11px Inter, "HarmonyOS Sans SC", sans-serif',
          },
        },
      ],
    })

    if (lastBar) {
      const chgColor = (chgPct ?? 0) >= 0 ? theme.up : theme.down
      const closeColor = lastBar.close >= lastBar.open ? theme.up : theme.down
      // 项2: 日K/周K/月K 只显示日期 (YYYY-MM-DD), 分钟K 显示完整 datetime
      const isDailyFreq = ['日线', '周线', '月线'].includes(result.freq)
      const panelDateLabel = isDailyFreq
        ? (lastBar.date.slice(0, 10))
        : lastBar.date
      const lines = [
        { label: panelDateLabel, color: theme.text, bold: true },
        { label: `OPEN ${lastBar.open.toFixed(2)}`, color: theme.text },
        { label: `HIGH ${lastBar.high.toFixed(2)}`, color: theme.text },
        { label: `LOW  ${lastBar.low.toFixed(2)}`, color: theme.text },
        { label: `CLOSE ${lastBar.close.toFixed(2)}`, color: closeColor },
        { label: `CHG % ${chgPct != null ? (chgPct >= 0 ? '+' : '') + chgPct.toFixed(2) : '—'}`, color: chgColor },
        { label: `VOL  ${formatVol(lastBar.vol)}`, color: theme.text },
        { label: 'MACD · 12/26/9', color: theme.text, bold: true },
        { label: `DIFF ${lastMacd?.dif != null ? lastMacd.dif.toFixed(2) : '—'}`, color: (lastMacd?.dif ?? 0) >= 0 ? theme.up : theme.down },
        { label: `DEA  ${lastMacd?.dea != null ? lastMacd.dea.toFixed(2) : '—'}`, color: theme.text },
        { label: `MACD ${lastMacd?.macd != null ? lastMacd.macd.toFixed(2) : '—'}`, color: (lastMacd?.macd ?? 0) >= 0 ? theme.up : theme.down },
      ]
      // 面板尺寸: 11 行 × 14px 行高 + padding 8px = ~162px 高, 宽度 ~150px
      const lineH = 14
      const padX = 8
      const padY = 6
      const panelW = 150
      const panelH = lines.length * lineH + padY * 2
      // 面板可拖动: 用 echarts graphic group 的 draggable + ondrag, 位置存 panelPosRef
      // 初始位置: 右上角 (用 right/top 表达; 拖动后切换为 left/top 像素坐标)
      const panelGroup: echarts.EChartsOption['graphic'] extends infer G
        ? G extends (infer Item)[]
          ? Item
          : never
        : never = {
        type: 'group',
        right: gridRight + 4,
        top: 8,
        draggable: true,
        // 拖动时 echarts 自动更新 group 位置, 这里仅记录到 ref 供下次重渲染复用
        ondrag: (e: { offsetX?: number; offsetY?: number }) => {
          if (e && typeof e.offsetX === 'number' && typeof e.offsetY === 'number') {
            panelPosRef.current = { left: e.offsetX, top: e.offsetY }
          }
        },
        children: [
          // 半透明边框背景矩形 (对齐示例图右侧方框)
          {
            type: 'rect',
            shape: { x: 0, y: 0, width: panelW, height: panelH, r: 4 },
            style: {
              fill: theme.background,
              opacity: 0.85,
              stroke: theme.grid,
              lineWidth: 1,
            },
          },
          ...lines.map((ln, i) => ({
            type: 'text' as const,
            style: {
              text: ln.label,
              x: padX,
              y: padY + i * lineH,
              fill: ln.color,
              font: `${ln.bold ? 'bold ' : ''}12px 'JetBrains Mono', monospace`,
            },
          })),
        ],
      }
      // 若用户已拖动过, 用记录的像素位置覆盖初始 right/top
      if (panelPosRef.current) {
        delete (panelGroup as { right?: number }).right
        ;(panelGroup as { left?: number }).left = panelPosRef.current.left
        ;(panelGroup as { top?: number }).top = panelPosRef.current.top
      }
      graphicElements.push(panelGroup)

      // ===== 右下角时间戳 (对齐示例图: "08 11月 '26 16:00") =====
      // 项2: 日K/周K/月K 只显示日期 (dd 月 'yy), 分钟K 追加 HH:mm
      const lastDate = lastBar.date.slice(0, 10) // YYYY-MM-DD
      const [yy, mm, dd] = lastDate.split('-')
      const monthZh = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'][Number(mm) - 1]
      const yy2 = yy.slice(2)
      // 从 lastBar.date 提取 HH:mm (分钟K的 dt 形如 "2026-11-09 14:30:00")
      const timePart = lastBar.date.slice(11, 16) // HH:mm, 日K为空
      const stampText = isDailyFreq
        ? `${dd} ${monthZh} '${yy2}`
        : `${dd} ${monthZh} '${yy2} ${timePart || '16:00'}`
      graphicElements.push({
        type: 'text',
        right: gridRight + 4,
        bottom: 24,
        style: {
          text: stampText,
          fill: '#fff',
          backgroundColor: theme.text,
          padding: [2, 6],
          font: "11px 'JetBrains Mono', monospace",
        },
      })
    }

    const option = {
      // 背景与文字色随 czsc 主题切换 (light #F5F4EF / dark 深空)
      backgroundColor: theme.background,
      // 变更点6/2: tooltip formatter — 中文分行展示 + 涨跌幅% + SMA 两位小数 + dt 仅日期。
      //   日期
      //   开 xxxx.xx
      //   收 xxxx.xx
      //   高 xxxx.xx
      //   低 xxxx.xx
      //   涨跌 +x.xx%
      //   SMA5 / SMA20 / VOL / MACD / DIFF / DEA
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: (params: unknown) => {
          if (!Array.isArray(params) || params.length === 0) return ''
          const arr = params as Array<{ axisValue?: string; seriesName?: string; value?: unknown; color?: string; dataIndex?: number; axisIndex?: number; data?: { bsInfo?: import('@/lib/api').CzscBsPoint } }>
          const dt = arr[0]?.axisValue ?? ''
          const dateStr = dt.slice(0, 10)  // 仅日期 YYYY-MM-DD
          // 关键修复: 鼠标在 VOL/MACD 副图时 arr 里无 'K线' series, 之前 kIdx=-1 导致
          //          OHLC 全部丢失。这里改用 arr[0].dataIndex 直接从 resolvedKlines 取
          //          当前 K 线 (三个 grid 共享同一 category xAxis, dataIndex 一致)。
          const idx = arr[0]?.dataIndex ?? -1
          const curK = idx >= 0 && idx < resolvedKlines.length ? resolvedKlines[idx] : undefined
          const prevK = idx >= 1 ? resolvedKlines[idx - 1] : undefined
          const chgPct = curK && prevK
            ? ((curK.close - prevK.close) / prevK.close) * 100
            : null
          const lines: string[] = [dateStr]
          // OHLC 始终从 resolvedKlines 直接取, 不依赖 K线 series 是否在 params 中
          if (curK) {
            lines.push(`开 ${curK.open.toFixed(2)}`)
            lines.push(`收 ${curK.close.toFixed(2)}`)
            lines.push(`高 ${curK.high.toFixed(2)}`)
            lines.push(`低 ${curK.low.toFixed(2)}`)
            if (chgPct != null) {
              const sign = chgPct >= 0 ? '+' : ''
              lines.push(`涨跌 ${sign}${chgPct.toFixed(2)}%`)
            }
          }
          // 买卖点背驰详细信息 — 当鼠标悬停的 K 线上有买卖点标注时, 展示背驰计算细节
          // (MACD面积对比 / DIF/DEA 高点对比 / 背驰类型)
          const bsOnThisBar = bsPoints.filter(bp => bp.dt.slice(0, 10) === dateStr)
          for (const bp of bsOnThisBar) {
            const color = bp.direction === '买' ? theme.up : theme.down
            lines.push(`<span style="color:${color};font-weight:bold">━━ ${bp.type} (${bp.direction}) ${bp.price.toFixed(2)} ━━</span>`)
            lines.push(`背驰类型: ${bp.divergence_type ?? '—'}`)
            lines.push(`命中条件: ${bp.divergence_pass.length ? bp.divergence_pass.join(' + ') : '—'}`)
            lines.push(`MACD面积 (a→c): ${bp.macd_area_prev != null ? bp.macd_area_prev.toFixed(4) : '—'} → ${bp.macd_area_cur != null ? bp.macd_area_cur.toFixed(4) : '—'}`)
            lines.push(`DIF极值 (a→c): ${bp.dif_peak_prev != null ? bp.dif_peak_prev.toFixed(4) : '—'} → ${bp.dif_peak_cur != null ? bp.dif_peak_cur.toFixed(4) : '—'}`)
            lines.push(`面积口径: ${bp.macd_area_mode}`)
            if (bp.zs_index >= 0) lines.push(`关联中枢: ZS${bp.zs_index + 1}`)
          }
          for (const p of arr) {
            const nm = p.seriesName ?? ''
            const v = p.value
            if (nm === 'K线') {
              // OHLC 已在上方从 resolvedKlines 取, 跳过避免重复
              continue
            } else if (nm.startsWith('SMA')) {
              // 动态均线 SMA5/SMA10/SMA20/... — 显示两位小数
              const n = typeof v === 'number' ? v : null
              lines.push(`${nm} ${n != null ? n.toFixed(2) : '—'}`)
            } else if (nm === 'VOL') {
              const n = typeof v === 'number' ? v : null
              lines.push(`${nm} ${n != null ? n.toFixed(2) : '—'}`)
            } else if (nm === 'MACD' || nm === 'DIFF' || nm === 'DEA') {
              const n = typeof v === 'number' ? v : null
              lines.push(`${nm} ${n != null ? n.toFixed(2) : '—'}`)
            } else if (nm === 'FX' || nm === 'BI' || nm === 'FX标记' || nm === '买卖点') {
              // lines / markPoint scatter 不展示数值 (坐标已可视化)
              continue
            } else if (nm === '中枢') {
              continue
            } else {
              lines.push(`${nm} ${v != null ? String(v) : '—'}`)
            }
          }
          return lines.join('<br/>')
        },
      },
      // 图例顺序与示例图对齐: 动态 SMA + FX (DASHED) + BI (SOLID) + 中枢 + 买卖点 + VOL + MACD
      // 均线名称随 maPeriodsNorm 动态生成 (SMA5/SMA10/SMA20/...)
      legend: {
        data: ['K线', ...maDataList.map(ma => `SMA${ma.period}`), 'FX', 'BI', '中枢', '买卖点', 'VOL', 'MACD'],
        top: 0,
        textStyle: { color: theme.text, fontSize: 11 },
      },
      grid: [mainGrid, volGrid, macdGrid],
      xAxis: [
        // 主图 xAxis (index 0) — 显示月份标签 (格式: "4月" / 跨年显示 "2026年")
        {
          type: 'category',
          data: dateCategories,
          axisLabel: {
            color: theme.text,
            fontSize: 11,
            // 对齐示例图: 同年内显示 "M月", 1月或跨年首月显示 "YYYY年"
            formatter: (value: string, index: number) => formatXAxisLabel(dateCategories, value, index),
          },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
          boundaryGap: true,
        },
        // VOL xAxis (index 1) — 不显示标签
        {
          type: 'category',
          gridIndex: 1,
          data: dateCategories,
          axisLabel: { show: false },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
        },
        // MACD xAxis (index 2) — 显示月份标签 (格式: "4月" / 跨年显示 "2026年")
        {
          type: 'category',
          gridIndex: 2,
          data: dateCategories,
          axisLabel: {
            color: theme.text,
            fontSize: 11,
            formatter: (value: string, index: number) => formatXAxisLabel(dateCategories, value, index),
          },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
        },
      ],
      yAxis: [
        // 主图 yAxis (index 0) — 价格, scale 自适应
        // 变更点8: 刻度改右侧 (position:'right') + 显示轴线 (axisLine.show:true)
        //          + 刻度值 toFixed(2) 只保留两位小数。
        //          axisLabel.width 固定 56px 让三栏右侧对齐。
        {
          scale: true,
          position: 'right',
          splitLine: { show: true, lineStyle: { color: theme.grid, type: 'dashed' } },
          axisLabel: {
            color: theme.text, fontSize: 11, width: 56,
            formatter: (v: number) => isFinite(v) ? v.toFixed(2) : '',
          },
          axisLine: { show: true, lineStyle: { color: theme.grid } },
        },
        // VOL yAxis (index 1) — 变更点8: 同样改右侧 + 两位小数
        {
          gridIndex: 1,
          position: 'right',
          splitNumber: 2,
          splitLine: { show: false },
          axisLabel: {
            color: theme.text, fontSize: 10, width: 56,
            formatter: (v: number) => isFinite(v) ? v.toFixed(2) : '',
          },
          axisLine: { show: true, lineStyle: { color: theme.grid } },
        },
        // MACD yAxis (index 2) — 含 0 轴, 变更点8: 同样改右侧 + 两位小数
        {
          gridIndex: 2,
          position: 'right',
          splitNumber: 3,
          splitLine: { show: true, lineStyle: { color: theme.grid, type: 'dashed' } },
          axisLabel: {
            color: theme.text, fontSize: 10, width: 56,
            formatter: (v: number) => isFinite(v) ? v.toFixed(2) : '',
          },
          axisLine: { show: true, lineStyle: { color: theme.grid } },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 0, end: 100 },
        { show: true, type: 'slider', xAxisIndex: [0, 1, 2], top: '94%', start: 0, end: 100, textStyle: { color: theme.text } },
      ],
      graphic: graphicElements,
      series: [
        // ===== 主图 (gridIndex 0) =====
        // K 线 (candlestick) — 涨红跌绿, czsc _theme.py up/down
        ...(candleData.length ? [{
          name: 'K线',
          type: 'candlestick' as const,
          data: candleData,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: {
            color: theme.up,         // 阳线实体
            color0: theme.down,      // 阴线实体
            borderColor: theme.up,   // 阳线边框
            borderColor0: theme.down,
          },
        }] : []),
        // 动态均线 SMA(N) — 由 maPeriodsNorm 决定 (默认 [5,10,20], 最多 3 条)
        // 每条均线独立颜色, 名称 SMA5/SMA10/SMA20/..., 与顶部 legend 联动
        ...maDataList.map(ma => ({
          name: `SMA${ma.period}`,
          type: 'line' as const,
          data: ma.data,
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: false,
          symbol: 'none',
          lineStyle: { color: ma.color, width: 1.4 },
          z: 2,
        })),
        // FX 分型 — 卡其色虚线折线, 连接相邻分型极值, czsc _theme.py fx_dashed
        //   注: echarts lines series 不支持 markPoint (官方限制), 顶底分型红绿三角
        //   标识挂到下方独立的 'FX标记' scatter series 上 (项1 修复)。
        {
          name: 'FX',
          type: 'lines' as const,
          coordinateSystem: 'cartesian2d',
          polyline: false,
          data: fxSegments,
          xAxisIndex: 0,
          yAxisIndex: 0,
          z: 3,
        },
        // 项1: FX 顶底分型红绿三角 — 用独立 scatter series 承载 markPoint
        //   data 为空 (本身不画散点), 仅用 markPoint 渲染三角
        {
          name: 'FX标记',
          type: 'scatter' as const,
          data: [],
          xAxisIndex: 0,
          yAxisIndex: 0,
          z: 6,
          markPoint: {
            silent: true,
            symbol: 'triangle',
            symbolSize: 10,
            data: fxMarkPoints,
          },
        },
        // 买卖点 (B1/B2/B3/S1/S2/S3) — scatter series + label.formatter 渲染文字
        //   买点红色 (theme.up), 卖点绿色 (theme.down), 加粗 12px
        //   标在 price 上方 (买点 position='top') / 下方 (卖点 position='bottom')
        //   label formatter: 直接显示 bp.type (B1/B2/..), 鼠标悬浮时 tooltip 展示背驰详情
        ...(bsScatterData.length ? [{
          name: '买卖点',
          type: 'scatter' as const,
          data: bsScatterData.map(d => ({
            value: d.value,
            // 透传 bsInfo 给 tooltip: echarts 把整个 data 对象传到 formatter 的 data 字段
            // 这里直接把 bp 信息挂到 data 上, formatter 通过 arr[i].data.bsInfo 取
            bsInfo: d.bsInfo,
            itemStyle: {
              color: d.bsInfo.direction === '买' ? theme.up : theme.down,
            },
            label: {
              show: true,
              formatter: () => d.bsInfo.type,
              color: d.bsInfo.direction === '买' ? theme.up : theme.down,
              fontSize: 12,
              fontWeight: 'bold' as const,
              position: d.bsInfo.direction === '买' ? 'bottom' : 'top',
              backgroundColor: theme.background,
              padding: [1, 3],
              borderColor: d.bsInfo.direction === '买' ? theme.up : theme.down,
              borderWidth: 1,
            },
          })),
          xAxisIndex: 0,
          yAxisIndex: 0,
          symbolSize: 1,    // 散点本身极小 (只显示 label 文字)
          z: 8,
        }] : []),
        // BI 笔 — 深靛蓝实线, 连接笔端点, czsc _theme.py bi
        {
          name: 'BI',
          type: 'lines' as const,
          coordinateSystem: 'cartesian2d',
          polyline: false,
          data: biLines,
          xAxisIndex: 0,
          yAxisIndex: 0,
          z: 4,
        },
        // 中枢 — 紫色虚线边框矩形 + ZS 序号标签 + 浅粉底色 (czsc 原生不画, 本工程自定义)
        // markArea itemStyle 必须写在顶层 (对所有矩形生效)
        //   项5: color 从 transparent 改为浅粉色透明 (zsFill rgba(255,182,193,0.18))
        //   项4: markPoint 加 zg/zd 价位数值标签 (在矩形右上下角)
        {
          name: '中枢',
          type: 'scatter' as const,
          data: [],
          xAxisIndex: 0,
          yAxisIndex: 0,
          markArea: {
            silent: true,
            itemStyle: {
              color: theme.zsFill,              // 项5: 浅粉色透明底色
              borderColor: theme.zsBorder,
              borderWidth: 1.6,                  // 变更点3: 加粗 1.2 → 1.6
              borderType: 'dashed',
            },
            data: zsAreas,
          },
          markPoint: {
            silent: true,
            symbol: 'circle',
            symbolSize: 0,
            data: [...zsLabels, ...zsPriceLabels],
          },
        },
        // ===== 成交量副图 (gridIndex 1) =====
        {
          name: 'VOL',
          type: 'bar' as const,
          data: volData,
          xAxisIndex: 1,
          yAxisIndex: 1,
        },
        // ===== MACD 副图 (gridIndex 2) =====
        // MACD 柱 (hist)
        {
          name: 'MACD',
          type: 'bar' as const,
          data: macdHistData,
          xAxisIndex: 2,
          yAxisIndex: 2,
        },
        // DIFF 线 — 深靛蓝 (与 BI 同色, czsc _theme.py macd_diff)
        {
          name: 'DIFF',
          type: 'line' as const,
          data: macdDiffData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          symbol: 'none',
          lineStyle: { color: theme.bi, width: 1.2 },
        },
        // DEA 线 — 古铜色 (与 SMA5 同色, czsc _theme.py macd_dea)
        {
          name: 'DEA',
          type: 'line' as const,
          data: macdDeaData,
          xAxisIndex: 2,
          yAxisIndex: 2,
          symbol: 'none',
          lineStyle: { color: theme.sma5, width: 1.2 },
        },
      ],
    } as echarts.EChartsOption

    chartRef.current.setOption(option, true)
  }, [result, resolvedKlines, isDark, maPeriodsNorm])

  // 高度变化时 (拖动分割条 / 父容器 resize) 同步 echarts 实例尺寸。
  // 变更点1: height="100%" 时父容器尺寸变化由 ResizeObserver 捕获, 自动 resize echarts。
  useEffect(() => {
    chartRef.current?.resize()
  }, [height])

  // 监听容器自身尺寸变化 (父级 flex 占比变动 / 窗口缩放), 自动 resize echarts。
  // 覆盖 height="100%" 场景, 此时 height prop 不变但容器实际尺寸在变。
  useEffect(() => {
    const el = containerRef.current
    if (!el || !chartRef.current || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => {
      chartRef.current?.resize()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return <div ref={containerRef} style={{ width: '100%', height }} />
})
