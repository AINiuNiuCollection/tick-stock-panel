/**
 * K线图手绘方案 — SVG 生成纯函数模块
 *
 * 所有函数均为纯函数, 无副作用, 可独立单测。
 * 颜色硬编码 (不用 CSS 变量), 确保导出 Markdown 时仍可见。
 *
 * 涨跌色对齐项目规范 (EChartsCandlestick.tsx):
 *   bull = #C74040 (红涨)
 *   bear = #2D9B65 (绿跌)
 */

// ============================================================
// 常量
// ============================================================

export const BULL_COLOR = '#C74040'
export const BEAR_COLOR = '#2D9B65'
export const MA5_COLOR = '#EAB308'
export const MA10_COLOR = '#3B82F6'
export const NEUTRAL_COLOR = '#71717A'

/** 暗色背景 (zinc-900) */
export const DARK_BG = '#18181B'
/** 亮色背景 (zinc-50) */
export const LIGHT_BG = '#FAFAF9'

/** 画布逻辑尺寸 (SVG viewBox) */
export const CANVAS_WIDTH = 600
export const CANVAS_HEIGHT = 320
/** K线区域高度占比 (上 70%) */
export const KLINE_AREA_RATIO = 0.7
/** 量能区域高度占比 (下 30%) */
export const VOLUME_AREA_RATIO = 0.3
/** K线最大数量 */
export const MAX_KLINES = 60
/** K线最小数量 */
export const MIN_KLINES = 0

// ============================================================
// 类型
// ============================================================

/** 单根手绘 K 线 */
export interface KLine {
  /** 序号 (0-based, X 轴位置) */
  idx: number
  /** 开盘价 */
  open: number
  /** 收盘价 */
  close: number
  /** 最高价 */
  high: number
  /** 最低价 */
  low: number
}

/** 趋势线标注 */
export interface TrendLine {
  /** 起点序号 (可为小数, 表示两根 K 线之间) */
  x1: number
  /** 起点价格 */
  y1: number
  /** 终点序号 */
  x2: number
  /** 终点价格 */
  y2: number
}

/** 水平线标注 */
export interface HorizontalLine {
  /** 价格水平 */
  price: number
  /** 起点序号 (默认 0) */
  startIdx?: number
  /** 终点序号 (默认最末) */
  endIdx?: number
}

/** 文字标注 */
export interface TextLabel {
  /** 序号位置 */
  idx: number
  /** 价格位置 */
  price: number
  /** 文本内容 */
  text: string
}

/** 画布数据 (存入 data-kchart JSON) */
export interface KChartData {
  /** K线数组 (按 idx 排序) */
  klines: KLine[]
  /** 趋势线数组 */
  trendLines: TrendLine[]
  /** 水平线数组 */
  horizontalLines: HorizontalLine[]
  /** 文字标注数组 */
  labels: TextLabel[]
  /** 主题: dark | light (生成时锁定) */
  theme: 'dark' | 'light'
  /** K线区域高度占比 (0.3~0.85, 默认 0.7; 可拖拽分界线调整) */
  klineAreaRatio?: number
}

// ============================================================
// 工具函数
// ============================================================

/** 涨跌判断: close >= open 为涨 (红) */
export function isBull(k: KLine): boolean {
  return k.close >= k.open
}

/** 获取所有 K 线的价格范围 [min, max] */
export function priceRange(klines: KLine[]): { min: number; max: number } {
  if (klines.length === 0) {
    return { min: 0, max: 1 }
  }
  let min = Infinity
  let max = -Infinity
  for (const k of klines) {
    if (k.low < min) min = k.low
    if (k.high > max) max = k.high
  }
  if (min === max) {
    // 全平退化: 上下留 1 单位
    min -= 1
    max += 1
  }
  // 留 5% 边距
  const pad = (max - min) * 0.05
  return { min: min - pad, max: max + pad }
}

/** MA(n) 均线计算: 返回每根 K 线处的 MA 值 (前 n-1 根为 null) */
export function calcMA(klines: KLine[], period: number): (number | null)[] {
  const result: (number | null)[] = []
  for (let i = 0; i < klines.length; i++) {
    if (i < period - 1) {
      result.push(null)
    } else {
      let sum = 0
      for (let j = i - period + 1; j <= i; j++) {
        sum += klines[j].close
      }
      result.push(sum / period)
    }
  }
  return result
}

/** 量能推导: 用 |close - open| 映射到量能高度 (0~1 归一化) */
export function calcVolumes(klines: KLine[]): number[] {
  if (klines.length === 0) return []
  const diffs = klines.map((k) => Math.abs(k.close - k.open))
  const maxDiff = Math.max(...diffs, 0.001)
  return diffs.map((d) => d / maxDiff)
}

// ============================================================
// 坐标转换
// ============================================================

/** 逻辑坐标 → 像素坐标 */
export function idxToX(idx: number, count: number): number {
  if (count <= 1) return CANVAS_WIDTH / 2
  const usable = CANVAS_WIDTH - 20 // 左右各留 10px
  return 10 + (idx / (count - 1)) * usable
}

export function priceToY(
  price: number,
  min: number,
  max: number,
  areaTop: number,
  areaHeight: number,
): number {
  if (max === min) return areaTop + areaHeight / 2
  const ratio = (price - min) / (max - min)
  // Y 轴翻转: 价格越高 Y 越小
  return areaTop + (1 - ratio) * areaHeight
}

/** 解析 klineAreaRatio (带范围钳制和默认值) */
export function resolveRatio(ratio: number | undefined): number {
  if (ratio === undefined || !Number.isFinite(ratio)) return KLINE_AREA_RATIO
  return Math.max(0.3, Math.min(0.85, ratio))
}

/** K线区域参数 */
export function klineArea(ratio?: number) {
  const r = resolveRatio(ratio)
  const top = 20
  const height = (CANVAS_HEIGHT - 40) * r
  return { top, height, bottom: top + height }
}

/** 量能区域参数 */
export function volumeArea(ratio?: number) {
  const r = resolveRatio(ratio)
  const k = klineArea(r)
  const top = k.bottom + 10
  const height = (CANVAS_HEIGHT - 40) * (1 - r) - 10
  return { top, height, bottom: top + height }
}

// ============================================================
// SVG 元素生成
// ============================================================

/** 单根 K 线 → SVG 元素字符串 */
export function klineToSvg(
  k: KLine,
  min: number,
  max: number,
  count: number,
  ratio?: number,
): string {
  const area = klineArea(ratio)
  const x = idxToX(k.idx, count)
  const yOpen = priceToY(k.open, min, max, area.top, area.height)
  const yClose = priceToY(k.close, min, max, area.top, area.height)
  const yHigh = priceToY(k.high, min, max, area.top, area.height)
  const yLow = priceToY(k.low, min, max, area.top, area.height)

  const color = isBull(k) ? BULL_COLOR : BEAR_COLOR
  const bodyTop = Math.min(yOpen, yClose)
  const bodyHeight = Math.max(Math.abs(yClose - yOpen), 1)
  const halfWidth = 5

  // 影线
  const wick = `<line x1="${x.toFixed(1)}" y1="${yHigh.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yLow.toFixed(1)}" stroke="${color}" stroke-width="1"/>`
  // 实体
  const body = `<rect x="${(x - halfWidth).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${(halfWidth * 2).toFixed(1)}" height="${bodyHeight.toFixed(1)}" fill="${color}"/>`

  return wick + body
}

/** MA 均线 → SVG polyline */
export function maToSvg(
  ma: (number | null)[],
  min: number,
  max: number,
  count: number,
  color: string,
  ratio?: number,
): string {
  const area = klineArea(ratio)
  const points: string[] = []
  for (let i = 0; i < ma.length; i++) {
    const v = ma[i]
    if (v === null) continue
    const x = idxToX(i, count)
    const y = priceToY(v, min, max, area.top, area.height)
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`)
  }
  if (points.length < 2) return ''
  return `<polyline points="${points.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-opacity="0.8"/>`
}

/** 量能柱 → SVG */
export function volumeToSvg(
  volumes: number[],
  klines: KLine[],
  count: number,
  ratio?: number,
): string {
  const area = volumeArea(ratio)
  const elements: string[] = []
  for (let i = 0; i < volumes.length; i++) {
    const x = idxToX(i, count)
    const h = volumes[i] * area.height
    const color = isBull(klines[i]) ? BULL_COLOR : BEAR_COLOR
    const halfWidth = 5
    elements.push(
      `<rect x="${(x - halfWidth).toFixed(1)}" y="${(area.bottom - h).toFixed(1)}" width="${(halfWidth * 2).toFixed(1)}" height="${h.toFixed(1)}" fill="${color}" fill-opacity="0.6"/>`,
    )
  }
  return elements.join('')
}

/** 趋势线 → SVG */
export function trendLineToSvg(
  line: TrendLine,
  min: number,
  max: number,
  count: number,
  ratio?: number,
): string {
  const area = klineArea(ratio)
  const x1 = idxToX(line.x1, count)
  const y1 = priceToY(line.y1, min, max, area.top, area.height)
  const x2 = idxToX(line.x2, count)
  const y2 = priceToY(line.y2, min, max, area.top, area.height)
  return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${NEUTRAL_COLOR}" stroke-width="1.5" stroke-dasharray="4,2"/>`
}

/** 水平线 → SVG */
export function horizontalLineToSvg(
  line: HorizontalLine,
  min: number,
  max: number,
  count: number,
  ratio?: number,
): string {
  const area = klineArea(ratio)
  const y = priceToY(line.price, min, max, area.top, area.height)
  const x1 = idxToX(line.startIdx ?? 0, count)
  const x2 = idxToX(line.endIdx ?? count - 1, count)
  return `<line x1="${x1.toFixed(1)}" y1="${y.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${NEUTRAL_COLOR}" stroke-width="1" stroke-dasharray="2,2"/>`
}

/** 文字标注 → SVG */
export function labelToSvg(
  label: TextLabel,
  min: number,
  max: number,
  count: number,
  theme: 'dark' | 'light',
  ratio?: number,
): string {
  const area = klineArea(ratio)
  const x = idxToX(label.idx, count)
  const y = priceToY(label.price, min, max, area.top, area.height)
  const textColor = theme === 'dark' ? '#E4E4E7' : '#27272A'
  const bgColor = theme === 'dark' ? 'rgba(39,39,42,0.8)' : 'rgba(244,244,245,0.9)'
  // 转义 XML 特殊字符
  const safeText = escapeXml(label.text)
  return `<g><rect x="${(x + 4).toFixed(1)}" y="${(y - 10).toFixed(1)}" width="${(safeText.length * 7 + 8).toFixed(1)}" height="18" fill="${bgColor}" rx="2"/><text x="${(x + 8).toFixed(1)}" y="${(y + 3).toFixed(1)}" fill="${textColor}" font-size="11" font-family="sans-serif">${safeText}</text></g>`
}

/** XML 特殊字符转义 */
export function escapeXml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

// ============================================================
// 主函数: KChartData → SVG 字符串
// ============================================================

/** 格式化价格标签 (保留合适小数位) */
export function formatPrice(price: number): string {
  if (Math.abs(price) >= 1000) return price.toFixed(0)
  if (Math.abs(price) >= 100) return price.toFixed(1)
  if (Math.abs(price) >= 10) return price.toFixed(2)
  return price.toFixed(2)
}

/** 生成完整 SVG 字符串 */
export function generateKChartSvg(data: KChartData): string {
  const { klines, trendLines, horizontalLines, labels, theme } = data
  const ratio = resolveRatio(data.klineAreaRatio)
  const bg = theme === 'dark' ? DARK_BG : LIGHT_BG
  const gridColor = theme === 'dark' ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
  const borderColor = theme === 'dark' ? '#27272A' : '#E4E4E7'
  const textColor = theme === 'dark' ? '#A1A1AA' : '#71717A'
  const axisBgColor = theme === 'dark' ? 'rgba(24,24,27,0.9)' : 'rgba(250,250,249,0.9)'

  const count = Math.max(klines.length, 2)
  const { min, max } = priceRange(klines)

  const area = klineArea(ratio)
  const volArea = volumeArea(ratio)
  const yAxisX = CANVAS_WIDTH - 44 // Y 轴标签区域左边界
  const labelW = 42 // Y 轴标签背景宽度

  const parts: string[] = []

  // --- 网格线 (水平, K 线区) ---
  const hGridCount = 4
  for (let i = 0; i <= hGridCount; i++) {
    const y = area.top + (area.height / hGridCount) * i
    parts.push(`<line x1="0" y1="${y.toFixed(1)}" x2="${yAxisX.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${gridColor}" stroke-width="0.5"/>`)
  }
  // 网格线 (水平, 量能区)
  for (let i = 0; i <= 2; i++) {
    const y = volArea.top + (volArea.height / 2) * i
    parts.push(`<line x1="0" y1="${y.toFixed(1)}" x2="${yAxisX.toFixed(1)}" y2="${y.toFixed(1)}" stroke="${gridColor}" stroke-width="0.5"/>`)
  }
  // 网格线 (垂直)
  const vGridCount = Math.min(count - 1, 6)
  if (vGridCount > 0) {
    for (let i = 0; i <= vGridCount; i++) {
      const x = idxToX((i / vGridCount) * (count - 1), count)
      parts.push(`<line x1="${x.toFixed(1)}" y1="${area.top}" x2="${x.toFixed(1)}" y2="${volArea.bottom.toFixed(1)}" stroke="${gridColor}" stroke-width="0.5"/>`)
    }
  }

  // --- 量能柱 ---
  const volumes = calcVolumes(klines)
  parts.push(volumeToSvg(volumes, klines, count, ratio))

  // --- 量能区标签 ---
  parts.push(`<text x="6" y="${(volArea.top + 11).toFixed(1)}" fill="${textColor}" font-size="9" font-family="sans-serif" opacity="0.7">Vol</text>`)

  // --- 量能区分隔线 ---
  parts.push(`<line x1="0" y1="${(area.bottom + 5).toFixed(1)}" x2="${yAxisX.toFixed(1)}" y2="${(area.bottom + 5).toFixed(1)}" stroke="${gridColor}" stroke-width="0.5"/>`)

  // --- K 线 ---
  parts.push(klines.map((k) => klineToSvg(k, min, max, count, ratio)).join(''))

  // --- MA5 / MA10 ---
  const ma5 = calcMA(klines, 5)
  const ma10 = calcMA(klines, 10)
  const ma5Svg = maToSvg(ma5, min, max, count, MA5_COLOR, ratio)
  const ma10Svg = maToSvg(ma10, min, max, count, MA10_COLOR, ratio)
  if (ma5Svg) parts.push(ma5Svg)
  if (ma10Svg) parts.push(ma10Svg)

  // --- 趋势线 ---
  parts.push(trendLines.map((l) => trendLineToSvg(l, min, max, count, ratio)).join(''))

  // --- 水平线 ---
  parts.push(horizontalLines.map((l) => horizontalLineToSvg(l, min, max, count, ratio)).join(''))

  // --- 文字标注 ---
  parts.push(labels.map((l) => labelToSvg(l, min, max, count, theme, ratio)).join(''))

  // --- 最新价水平线 + 标签 ---
  if (klines.length > 0) {
    const lastK = klines[klines.length - 1]
    const yLast = priceToY(lastK.close, min, max, area.top, area.height)
    const lastColor = isBull(lastK) ? BULL_COLOR : BEAR_COLOR
    parts.push(`<line x1="0" y1="${yLast.toFixed(1)}" x2="${yAxisX.toFixed(1)}" y2="${yLast.toFixed(1)}" stroke="${lastColor}" stroke-width="0.5" stroke-dasharray="3,2" opacity="0.6"/>`)
    parts.push(`<rect x="${yAxisX.toFixed(1)}" y="${(yLast - 7).toFixed(1)}" width="${labelW}" height="14" fill="${lastColor}"/>`)
    parts.push(`<text x="${(yAxisX + 4).toFixed(1)}" y="${(yLast + 3).toFixed(1)}" fill="#FFFFFF" font-size="10" font-family="sans-serif">${formatPrice(lastK.close)}</text>`)
  }

  // --- Y 轴价格标签 (右侧) ---
  for (let i = 0; i <= hGridCount; i++) {
    const y = area.top + (area.height / hGridCount) * i
    const price = max - (i / hGridCount) * (max - min)
    parts.push(`<rect x="${yAxisX.toFixed(1)}" y="${(y - 7).toFixed(1)}" width="${labelW}" height="14" fill="${axisBgColor}"/>`)
    parts.push(`<text x="${(yAxisX + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" fill="${textColor}" font-size="10" font-family="sans-serif">${formatPrice(price)}</text>`)
  }

  // --- X 轴 idx 标签 (底部) ---
  if (count > 1) {
    const xLabelCount = Math.min(count, 6)
    for (let i = 0; i < xLabelCount; i++) {
      const idx = Math.round((i / (xLabelCount - 1)) * (count - 1))
      const x = idxToX(idx, count)
      if (x < yAxisX - 10) {
        parts.push(`<text x="${(x - 4).toFixed(1)}" y="${(CANVAS_HEIGHT - 4).toFixed(1)}" fill="${textColor}" font-size="9" font-family="sans-serif" opacity="0.7">${idx}</text>`)
      }
    }
  }

  // --- 右侧轴线 ---
  parts.push(`<line x1="${yAxisX.toFixed(1)}" y1="${area.top}" x2="${yAxisX.toFixed(1)}" y2="${volArea.bottom.toFixed(1)}" stroke="${borderColor}" stroke-width="0.5"/>`)

  // --- 图例 (左上角, 只显示有足够数据的均线) ---
  const legendY = 14
  const showMA5 = klines.length >= 5
  const showMA10 = klines.length >= 10
  const legendParts: string[] = []
  if (showMA5) {
    const ma5Last = ma5[ma5.length - 1]
    legendParts.push(`<rect x="8" y="${legendY - 7}" width="8" height="2" fill="${MA5_COLOR}"/><text x="20" y="${legendY}" fill="${textColor}" font-size="10" font-family="sans-serif">MA5 ${ma5Last !== null ? formatPrice(ma5Last) : ''}</text>`)
  }
  if (showMA10) {
    const ma10Last = ma10[ma10.length - 1]
    const ma10X = showMA5 ? 80 : 8
    legendParts.push(`<rect x="${ma10X}" y="${legendY - 7}" width="8" height="2" fill="${MA10_COLOR}"/><text x="${ma10X + 12}" y="${legendY}" fill="${textColor}" font-size="10" font-family="sans-serif">MA10 ${ma10Last !== null ? formatPrice(ma10Last) : ''}</text>`)
  }
  parts.push(legendParts.join(''))

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}" width="${CANVAS_WIDTH}" height="${CANVAS_HEIGHT}" data-kchart="${escapeXml(JSON.stringify(data))}" style="background:${bg};border:1px solid ${borderColor};border-radius:4px;display:block;max-width:100%;">${parts.join('')}</svg>`
}

// ============================================================
// data-kchart JSON 序列化/反序列化
// ============================================================

/** 从 SVG 元素提取 KChartData (用于双击编辑) */
export function parseKChartFromSvg(svgElement: HTMLElement): KChartData | null {
  const raw = svgElement.getAttribute('data-kchart')
  if (!raw) return null
  try {
    const data = JSON.parse(raw) as KChartData
    if (!isValidKChartData(data)) return null
    return data
  } catch {
    return null
  }
}

/** 校验 KChartData 合法性 */
export function isValidKChartData(data: unknown): data is KChartData {
  if (typeof data !== 'object' || data === null) return false
  const d = data as Record<string, unknown>
  if (!Array.isArray(d.klines)) return false
  if (!Array.isArray(d.trendLines)) return false
  if (!Array.isArray(d.horizontalLines)) return false
  if (!Array.isArray(d.labels)) return false
  if (d.theme !== 'dark' && d.theme !== 'light') return false
  // klineAreaRatio 可选, 若存在须为 [0.3, 0.85] 范围内的有限数
  if (d.klineAreaRatio !== undefined) {
    if (typeof d.klineAreaRatio !== 'number' || !Number.isFinite(d.klineAreaRatio)) return false
    if (d.klineAreaRatio < 0.3 || d.klineAreaRatio > 0.85) return false
  }
  for (const k of d.klines) {
    if (!isValidKLine(k)) return false
  }
  for (const l of d.trendLines) {
    if (!isValidTrendLine(l)) return false
  }
  for (const l of d.horizontalLines) {
    if (!isValidHorizontalLine(l)) return false
  }
  for (const l of d.labels) {
    if (!isValidLabel(l)) return false
  }
  return true
}

export function isValidKLine(k: unknown): k is KLine {
  if (typeof k !== 'object' || k === null) return false
  const kObj = k as Record<string, unknown>
  return (
    typeof kObj.idx === 'number' &&
    typeof kObj.open === 'number' &&
    typeof kObj.close === 'number' &&
    typeof kObj.high === 'number' &&
    typeof kObj.low === 'number' &&
    Number.isFinite(kObj.idx) &&
    Number.isFinite(kObj.open) &&
    Number.isFinite(kObj.close) &&
    Number.isFinite(kObj.high) &&
    Number.isFinite(kObj.low)
  )
}

export function isValidTrendLine(l: unknown): l is TrendLine {
  if (typeof l !== 'object' || l === null) return false
  const lObj = l as Record<string, unknown>
  return (
    typeof lObj.x1 === 'number' &&
    typeof lObj.y1 === 'number' &&
    typeof lObj.x2 === 'number' &&
    typeof lObj.y2 === 'number'
  )
}

export function isValidHorizontalLine(l: unknown): l is HorizontalLine {
  if (typeof l !== 'object' || l === null) return false
  const lObj = l as Record<string, unknown>
  return typeof lObj.price === 'number'
}

export function isValidLabel(l: unknown): l is TextLabel {
  if (typeof l !== 'object' || l === null) return false
  const lObj = l as Record<string, unknown>
  return (
    typeof lObj.idx === 'number' &&
    typeof lObj.price === 'number' &&
    typeof lObj.text === 'string'
  )
}

// ============================================================
// K 线操作辅助
// ============================================================

/** 根据鼠标位置创建一根新 K 线 */
export function createKLine(
  idx: number,
  closePrice: number,
  prevClose: number | null,
): KLine {
  const open = prevClose ?? closePrice
  // 影线偏移: 固定小值 (不随 body 线性增长, 避免长引线)
  // body=0 时给 0.3 的最小影线; body>0 时追加 10% 的实体高度
  const body = Math.abs(closePrice - open)
  const wickOffset = 0.3 + body * 0.1
  const high = Math.max(open, closePrice) + wickOffset
  const low = Math.min(open, closePrice) - wickOffset
  return { idx, open, close: closePrice, high, low }
}

/** 按 idx 排序 K 线数组 */
export function sortKlines(klines: KLine[]): KLine[] {
  return [...klines].sort((a, b) => a.idx - b.idx)
}

/** 按 idx 去重: 同一 idx 保留最新 */
export function dedupKlines(klines: KLine[]): KLine[] {
  const map = new Map<number, KLine>()
  for (const k of klines) {
    map.set(k.idx, k)
  }
  return sortKlines(Array.from(map.values()))
}

/** 删除指定 idx 的 K 线 */
export function removeKline(klines: KLine[], idx: number): KLine[] {
  return klines.filter((k) => k.idx !== idx)
}

/** 查找最接近某个 idx 的已存在 K 线 (用于橡皮擦命中检测) */
export function findNearestKline(
  klines: KLine[],
  targetIdx: number,
  threshold: number = 0.5,
): KLine | null {
  let nearest: KLine | null = null
  let minDist = Infinity
  for (const k of klines) {
    const dist = Math.abs(k.idx - targetIdx)
    if (dist < minDist) {
      minDist = dist
      nearest = k
    }
  }
  return minDist <= threshold ? nearest : null
}

/** 查找最接近某点的趋势线 (用于橡皮擦命中检测) */
export function findNearestTrendLine(
  lines: TrendLine[],
  idx: number,
  price: number,
  threshold: number = 2,
): TrendLine | null {
  let nearest: TrendLine | null = null
  let minDist = Infinity
  for (const line of lines) {
    const dist = pointToLineDistance(idx, price, line)
    if (dist < minDist) {
      minDist = dist
      nearest = line
    }
  }
  return minDist <= threshold ? nearest : null
}

/** 点到线段的距离 (用于命中检测) */
export function pointToLineDistance(
  px: number,
  py: number,
  line: TrendLine,
): number {
  const { x1, y1, x2, y2 } = line
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) {
    return Math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
  }
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  const projX = x1 + t * dx
  const projY = y1 + t * dy
  return Math.sqrt((px - projX) ** 2 + (py - projY) ** 2)
}

/** 创建空画布数据 */
export function emptyKChartData(theme: 'dark' | 'light' = 'dark'): KChartData {
  return {
    klines: [],
    trendLines: [],
    horizontalLines: [],
    labels: [],
    theme,
    klineAreaRatio: KLINE_AREA_RATIO,
  }
}

/** 从 SVG 字符串中提取 data-kchart JSON (不依赖 DOM) */
export function extractDataFromSvgString(svg: string): KChartData | null {
  const match = svg.match(/data-kchart="([^"]*)"/)
  if (!match) return null
  try {
    const raw = unescapeXml(match[1])
    const data = JSON.parse(raw)
    if (!isValidKChartData(data)) return null
    return data
  } catch {
    return null
  }
}

/** 反转义 XML 实体 */
export function unescapeXml(text: string): string {
  return text
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
}
