/**
 * K线图手绘对话框
 *
 * 交互逻辑:
 *  - 工具栏: K线 / 趋势线 / 水平线 / 文字 / 橡皮擦
 *  - 画布: 鼠标点击/拖拽在逻辑坐标(idx, price)上绘制
 *  - K线工具: 点击画布 → 新增一根 K 线 (close=点击位置, open=上根close)
 *  - 趋势线: 拖拽两个端点
 *  - 水平线: 点击位置生成水平价格线
 *  - 文字: 点击后弹出 prompt 输入文字
 *  - 橡皮擦: 点击最近的元素删除
 *  - 拖拽调整: 鼠标靠近 K线/量能 分界线时上下拖拽调整区域比例;
 *              鼠标靠近 K 线影线顶端/底端时上下拖拽调整 high/low
 *  - 生成按钮: 将画布数据转 SVG 插入备忘录
 *
 * 坐标转换: 鼠标像素坐标 → 逻辑坐标(idx, price)
 *   idx = (x - 10) / (yAxisX - 10) * (count - 1)
 *   price = max - (y - areaTop) / areaHeight * (max - min)
 */
import { useState, useRef, useCallback, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  X,
  CandlestickChart,
  TrendingUp,
  Minus,
  Type as TypeIcon,
  Eraser,
  Trash2,
  Check,
  Undo2,
  HelpCircle,
} from 'lucide-react'
import { cn } from '@/lib/cn'
import { useTheme } from '@/lib/theme'
import {
  type KChartData,
  type TrendLine,
  type TextLabel,
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
  klineArea,
  volumeArea,
  resolveRatio,
  priceRange,
  idxToX,
  priceToY,
  createKLine,
  dedupKlines,
  removeKline,
  findNearestKline,
  findNearestTrendLine,
  generateKChartSvg,
  emptyKChartData,
  calcMA,
  calcVolumes,
  isBull,
  formatPrice,
  BULL_COLOR,
  BEAR_COLOR,
  MA5_COLOR,
  MA10_COLOR,
} from './kchart-svg'

export type KChartTool = 'kline' | 'trend' | 'horizontal' | 'text' | 'eraser'

/** 拖拽模式 */
type DragMode = 'none' | 'trend' | 'divider' | 'kline-high' | 'kline-low' | 'kline-body-top' | 'kline-body-bottom'

export interface KChartDialogProps {
  /** 初始数据 (编辑模式); 新建模式传 undefined */
  initialData?: KChartData
  /** 关闭对话框 */
  onClose: () => void
  /** 插入 SVG 到备忘录 */
  onInsert: (svg: string) => void
}

export type { KChartData } from './kchart-svg'

/** Y 轴标签区域宽度 (右侧) */
const Y_AXIS_WIDTH = 44
/** Y 轴标签 X 坐标 */
const Y_AXIS_X = CANVAS_WIDTH - Y_AXIS_WIDTH
/** K 线影线拖拽命中阈值 (px) */
const WICK_HIT_THRESHOLD = 6
/** 分界线拖拽命中阈值 (px) */
const DIVIDER_HIT_THRESHOLD = 6

export function KChartDialog({ initialData, onClose, onInsert }: KChartDialogProps) {
  const theme = useTheme()
  const [data, setData] = useState<KChartData>(
    initialData ?? emptyKChartData(theme),
  )
  const [tool, setTool] = useState<KChartTool>('kline')
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const [hoverPrice, setHoverPrice] = useState<number | null>(null)
  const [dragMode, setDragMode] = useState<DragMode>('none')
  const [dragStart, setDragStart] = useState<{ idx: number; price: number } | null>(null)
  const [dragKlineIdx, setDragKlineIdx] = useState<number | null>(null)
  const [cursor, setCursor] = useState<string>('crosshair')
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const historyRef = useRef<KChartData[]>([])
  const [canUndo, setCanUndo] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  // 当前区域比例
  const ratio = resolveRatio(data.klineAreaRatio)

  // 撤销栈
  const pushHistory = useCallback((prev: KChartData) => {
    historyRef.current.push(prev)
    if (historyRef.current.length > 50) historyRef.current.shift()
    setCanUndo(true)
  }, [])

  const undo = useCallback(() => {
    const prev = historyRef.current.pop()
    if (prev) {
      setData(prev)
      setCanUndo(historyRef.current.length > 0)
    }
  }, [])

  // 价格范围 (用于坐标转换)
  const { min, max } = useMemo(() => priceRange(data.klines), [data.klines])
  const kCount = Math.max(data.klines.length, 2)

  // 鼠标像素坐标 → 逻辑坐标
  const pixelToLogic = useCallback(
    (px: number, py: number): { idx: number; price: number } => {
      const area = klineArea(ratio)
      const usable = Y_AXIS_X - 10
      const idx = kCount <= 1 ? 0 : ((px - 10) / usable) * (kCount - 1)
      // 价格: y 越小价格越高
      const ratioY = (py - area.top) / area.height
      const price = max - ratioY * (max - min)
      return { idx: Math.round(idx * 10) / 10, price: Math.round(price * 100) / 100 }
    },
    [min, max, kCount, ratio],
  )

  // 画布渲染
  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // 清空
    const isDark = data.theme === 'dark'
    ctx.fillStyle = isDark ? '#18181B' : '#FAFAF9'
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)

    const area = klineArea(ratio)
    const volArea = volumeArea(ratio)
    const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)'
    const borderColor = isDark ? '#27272A' : '#E4E4E7'
    const textColor = isDark ? '#A1A1AA' : '#71717A'
    const axisBgColor = isDark ? 'rgba(24,24,27,0.9)' : 'rgba(250,250,249,0.9)'

    // --- 水平网格线 (K 线区) ---
    ctx.strokeStyle = gridColor
    ctx.lineWidth = 0.5
    const hGridCount = 4
    for (let i = 0; i <= hGridCount; i++) {
      const y = area.top + (area.height / hGridCount) * i
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(Y_AXIS_X, y)
      ctx.stroke()
    }
    // 水平网格线 (量能区)
    for (let i = 0; i <= 2; i++) {
      const y = volArea.top + (volArea.height / 2) * i
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(Y_AXIS_X, y)
      ctx.stroke()
    }
    // 垂直网格线
    const vGridCount = Math.min(kCount - 1, 6)
    if (vGridCount > 0) {
      for (let i = 0; i <= vGridCount; i++) {
        const x = idxToX((i / vGridCount) * (kCount - 1), kCount)
        ctx.beginPath()
        ctx.moveTo(x, area.top)
        ctx.lineTo(x, volArea.bottom)
        ctx.stroke()
      }
    }

    // --- 量能柱 ---
    const volumes = calcVolumes(data.klines)
    for (let i = 0; i < data.klines.length; i++) {
      const k = data.klines[i]
      const x = idxToX(k.idx, kCount)
      const h = volumes[i] * volArea.height
      ctx.fillStyle = isBull(k) ? BULL_COLOR : BEAR_COLOR
      ctx.globalAlpha = 0.6
      ctx.fillRect(x - 5, volArea.bottom - h, 10, h)
    }
    ctx.globalAlpha = 1

    // --- Vol 标签 ---
    ctx.fillStyle = textColor
    ctx.globalAlpha = 0.7
    ctx.font = '9px sans-serif'
    ctx.fillText('Vol', 6, volArea.top + 11)
    ctx.globalAlpha = 1

    // --- 量能区分隔线 ---
    ctx.strokeStyle = gridColor
    ctx.lineWidth = 0.5
    ctx.beginPath()
    ctx.moveTo(0, area.bottom + 5)
    ctx.lineTo(Y_AXIS_X, area.bottom + 5)
    ctx.stroke()

    // --- K 线 ---
    for (const k of data.klines) {
      const x = idxToX(k.idx, kCount)
      const yOpen = priceToY(k.open, min, max, area.top, area.height)
      const yClose = priceToY(k.close, min, max, area.top, area.height)
      const yHigh = priceToY(k.high, min, max, area.top, area.height)
      const yLow = priceToY(k.low, min, max, area.top, area.height)
      const color = isBull(k) ? BULL_COLOR : BEAR_COLOR
      const isHovered = hoverIdx === k.idx || dragKlineIdx === k.idx

      // 悬停高亮
      if (isHovered) {
        ctx.fillStyle = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
        ctx.fillRect(x - 8, area.top, 16, area.height)
      }

      // 影线
      ctx.strokeStyle = color
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(x, yHigh)
      ctx.lineTo(x, yLow)
      ctx.stroke()
      // 实体
      ctx.fillStyle = color
      const bodyTop = Math.min(yOpen, yClose)
      const bodyH = Math.max(Math.abs(yClose - yOpen), 1)
      ctx.fillRect(x - 5, bodyTop, 10, bodyH)

      // 拖拽手柄 (影线顶端/底端 + 实体顶端/底端)
      if (isHovered) {
        const yBodyTop = Math.min(yOpen, yClose)
        const yBodyBottom = Math.max(yOpen, yClose)
        // 影线手柄 (空心)
        ctx.strokeStyle = color
        ctx.lineWidth = 1.5
        ctx.strokeRect(x - 4, yHigh - 2, 8, 3)
        ctx.strokeRect(x - 4, yLow - 1, 8, 3)
        // 实体手柄 (实心, 稍宽)
        ctx.fillStyle = color
        ctx.fillRect(x - 7, yBodyTop - 2, 14, 3)
        ctx.fillRect(x - 7, yBodyBottom - 1, 14, 3)
      }
    }

    // --- MA5 / MA10 ---
    const drawMA = (ma: (number | null)[], color: string) => {
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.globalAlpha = 0.8
      ctx.beginPath()
      let started = false
      for (let i = 0; i < ma.length; i++) {
        const v = ma[i]
        if (v === null) {
          started = false
          continue
        }
        const x = idxToX(i, kCount)
        const y = priceToY(v, min, max, area.top, area.height)
        if (!started) {
          ctx.moveTo(x, y)
          started = true
        } else {
          ctx.lineTo(x, y)
        }
      }
      ctx.stroke()
      ctx.globalAlpha = 1
    }
    if (data.klines.length >= 5) drawMA(calcMA(data.klines, 5), MA5_COLOR)
    if (data.klines.length >= 10) drawMA(calcMA(data.klines, 10), MA10_COLOR)

    // --- 趋势线 ---
    for (const line of data.trendLines) {
      const x1 = idxToX(line.x1, kCount)
      const y1 = priceToY(line.y1, min, max, area.top, area.height)
      const x2 = idxToX(line.x2, kCount)
      const y2 = priceToY(line.y2, min, max, area.top, area.height)
      ctx.strokeStyle = '#71717A'
      ctx.lineWidth = 1.5
      ctx.setLineDash([4, 2])
      ctx.beginPath()
      ctx.moveTo(x1, y1)
      ctx.lineTo(x2, y2)
      ctx.stroke()
      ctx.setLineDash([])
    }

    // --- 水平线 ---
    for (const line of data.horizontalLines) {
      const y = priceToY(line.price, min, max, area.top, area.height)
      const x1 = idxToX(line.startIdx ?? 0, kCount)
      const x2 = idxToX(line.endIdx ?? kCount - 1, kCount)
      ctx.strokeStyle = '#71717A'
      ctx.lineWidth = 1
      ctx.setLineDash([2, 2])
      ctx.beginPath()
      ctx.moveTo(x1, y)
      ctx.lineTo(x2, y)
      ctx.stroke()
      ctx.setLineDash([])
    }

    // --- 文字标注 ---
    for (const label of data.labels) {
      const x = idxToX(label.idx, kCount)
      const y = priceToY(label.price, min, max, area.top, area.height)
      ctx.fillStyle = isDark ? 'rgba(39,39,42,0.8)' : 'rgba(244,244,245,0.9)'
      const w = label.text.length * 7 + 8
      ctx.fillRect(x + 4, y - 10, w, 18)
      ctx.fillStyle = textColor
      ctx.font = '11px sans-serif'
      ctx.fillText(label.text, x + 8, y + 3)
    }

    // --- 最新价水平线 + 标签 ---
    if (data.klines.length > 0) {
      const lastK = data.klines[data.klines.length - 1]
      const yLast = priceToY(lastK.close, min, max, area.top, area.height)
      const lastColor = isBull(lastK) ? BULL_COLOR : BEAR_COLOR
      ctx.strokeStyle = lastColor
      ctx.lineWidth = 0.5
      ctx.globalAlpha = 0.6
      ctx.setLineDash([3, 2])
      ctx.beginPath()
      ctx.moveTo(0, yLast)
      ctx.lineTo(Y_AXIS_X, yLast)
      ctx.stroke()
      ctx.setLineDash([])
      ctx.globalAlpha = 1
      // 价格标签
      ctx.fillStyle = lastColor
      ctx.fillRect(Y_AXIS_X, yLast - 7, Y_AXIS_WIDTH, 14)
      ctx.fillStyle = '#FFFFFF'
      ctx.font = '10px sans-serif'
      ctx.fillText(formatPrice(lastK.close), Y_AXIS_X + 4, yLast + 3)
    }

    // --- Y 轴价格标签 ---
    ctx.font = '10px sans-serif'
    for (let i = 0; i <= hGridCount; i++) {
      const y = area.top + (area.height / hGridCount) * i
      const price = max - (i / hGridCount) * (max - min)
      ctx.fillStyle = axisBgColor
      ctx.fillRect(Y_AXIS_X, y - 7, Y_AXIS_WIDTH, 14)
      ctx.fillStyle = textColor
      ctx.fillText(formatPrice(price), Y_AXIS_X + 4, y + 3)
    }

    // --- X 轴 idx 标签 ---
    if (kCount > 1) {
      ctx.fillStyle = textColor
      ctx.globalAlpha = 0.7
      ctx.font = '9px sans-serif'
      const xLabelCount = Math.min(kCount, 6)
      for (let i = 0; i < xLabelCount; i++) {
        const idx = Math.round((i / (xLabelCount - 1)) * (kCount - 1))
        const x = idxToX(idx, kCount)
        if (x < Y_AXIS_X - 10) {
          ctx.fillText(String(idx), x - 4, CANVAS_HEIGHT - 4)
        }
      }
      ctx.globalAlpha = 1
    }

    // --- 右侧轴线 ---
    ctx.strokeStyle = borderColor
    ctx.lineWidth = 0.5
    ctx.beginPath()
    ctx.moveTo(Y_AXIS_X, area.top)
    ctx.lineTo(Y_AXIS_X, volArea.bottom)
    ctx.stroke()

    // --- 图例 (左上角) ---
    ctx.font = '10px sans-serif'
    const ma5 = calcMA(data.klines, 5)
    const ma10 = calcMA(data.klines, 10)
    let legendX = 8
    if (data.klines.length >= 5) {
      const ma5Last = ma5[ma5.length - 1]
      ctx.fillStyle = MA5_COLOR
      ctx.fillRect(legendX, 7, 8, 2)
      ctx.fillStyle = textColor
      ctx.fillText(`MA5 ${ma5Last !== null ? formatPrice(ma5Last) : ''}`, legendX + 12, 14)
      legendX = 80
    }
    if (data.klines.length >= 10) {
      const ma10Last = ma10[ma10.length - 1]
      ctx.fillStyle = MA10_COLOR
      ctx.fillRect(legendX, 7, 8, 2)
      ctx.fillStyle = textColor
      ctx.fillText(`MA10 ${ma10Last !== null ? formatPrice(ma10Last) : ''}`, legendX + 12, 14)
    }

    // --- 十字光标 ---
    if (hoverIdx !== null && dragMode === 'none' && (tool === 'kline' || tool === 'eraser')) {
      const x = idxToX(hoverIdx, kCount)
      ctx.strokeStyle = isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.15)'
      ctx.lineWidth = 0.5
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(x, area.top)
      ctx.lineTo(x, volArea.bottom)
      ctx.stroke()
      if (hoverPrice !== null) {
        const y = priceToY(hoverPrice, min, max, area.top, area.height)
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(Y_AXIS_X, y)
        ctx.stroke()
        // 价格标签
        ctx.setLineDash([])
        ctx.fillStyle = isDark ? '#3B82F6' : '#3B82F6'
        ctx.fillRect(Y_AXIS_X, y - 7, Y_AXIS_WIDTH, 14)
        ctx.fillStyle = '#FFFFFF'
        ctx.font = '10px sans-serif'
        ctx.fillText(formatPrice(hoverPrice), Y_AXIS_X + 4, y + 3)
      }
      ctx.setLineDash([])
    }

    // --- 分界线拖拽指示 ---
    if (cursor === 'ns-resize' || dragMode === 'divider') {
      const dividerY = area.bottom + 5
      ctx.strokeStyle = isDark ? 'rgba(59,130,246,0.6)' : 'rgba(59,130,246,0.5)'
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, dividerY)
      ctx.lineTo(Y_AXIS_X, dividerY)
      ctx.stroke()
      // 拖拽手柄
      ctx.fillStyle = isDark ? 'rgba(59,130,246,0.8)' : 'rgba(59,130,246,0.6)'
      ctx.fillRect(Y_AXIS_X / 2 - 12, dividerY - 2, 24, 4)
    }

    // --- 趋势线拖拽预览 ---
    if (tool === 'trend' && dragStart && dragMode === 'trend') {
      ctx.fillStyle = '#3B82F6'
      ctx.beginPath()
      ctx.arc(idxToX(dragStart.idx, kCount), priceToY(dragStart.price, min, max, area.top, area.height), 3, 0, Math.PI * 2)
      ctx.fill()
    }

    // --- 边框 ---
    ctx.strokeStyle = borderColor
    ctx.lineWidth = 1
    ctx.strokeRect(0.5, 0.5, CANVAS_WIDTH - 1, CANVAS_HEIGHT - 1)
  }, [data, min, max, kCount, tool, hoverIdx, hoverPrice, dragMode, dragStart, dragKlineIdx, cursor, ratio])

  useEffect(() => {
    renderCanvas()
  }, [renderCanvas])

  // 鼠标事件处理
  const getMousePos = (e: React.MouseEvent): { x: number; y: number } => {
    const canvas = canvasRef.current
    if (!canvas) return { x: 0, y: 0 }
    const rect = canvas.getBoundingClientRect()
    const scaleX = CANVAS_WIDTH / rect.width
    const scaleY = CANVAS_HEIGHT / rect.height
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    }
  }

  // 检测鼠标是否靠近分界线
  const checkDividerProximity = (py: number): boolean => {
    const area = klineArea(ratio)
    return Math.abs(py - (area.bottom + 5)) < DIVIDER_HIT_THRESHOLD
  }

  // 检测鼠标是否靠近某根 K 线的可拖拽端点 (影线顶/底 + 实体顶/底)
  const checkKlineProximity = (
    px: number,
    py: number,
  ): { mode: 'kline-high' | 'kline-low' | 'kline-body-top' | 'kline-body-bottom'; idx: number } | null => {
    const area = klineArea(ratio)
    for (const k of data.klines) {
      const x = idxToX(k.idx, kCount)
      const yHigh = priceToY(k.high, min, max, area.top, area.height)
      const yLow = priceToY(k.low, min, max, area.top, area.height)
      const yOpen = priceToY(k.open, min, max, area.top, area.height)
      const yClose = priceToY(k.close, min, max, area.top, area.height)
      const yBodyTop = Math.min(yOpen, yClose)
      const yBodyBottom = Math.max(yOpen, yClose)
      if (Math.abs(px - x) < 8) {
        // 影线顶端 (优先级最高, 在实体上方)
        if (Math.abs(py - yHigh) < WICK_HIT_THRESHOLD) {
          return { mode: 'kline-high', idx: k.idx }
        }
        // 影线底端
        if (Math.abs(py - yLow) < WICK_HIT_THRESHOLD) {
          return { mode: 'kline-low', idx: k.idx }
        }
        // 实体顶端
        if (Math.abs(py - yBodyTop) < WICK_HIT_THRESHOLD) {
          return { mode: 'kline-body-top', idx: k.idx }
        }
        // 实体底端
        if (Math.abs(py - yBodyBottom) < WICK_HIT_THRESHOLD) {
          return { mode: 'kline-body-bottom', idx: k.idx }
        }
      }
    }
    return null
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    const { x, y } = getMousePos(e)

    // 优先: 拖拽分界线
    if (checkDividerProximity(y)) {
      pushHistory(data)
      setDragMode('divider')
      return
    }

    // 优先: 拖拽 K 线影线
    const wickHit = checkKlineProximity(x, y)
    if (wickHit) {
      pushHistory(data)
      setDragMode(wickHit.mode)
      setDragKlineIdx(wickHit.idx)
      return
    }

    const { idx, price } = pixelToLogic(x, y)

    if (tool === 'kline') {
      pushHistory(data)
      const prevClose = data.klines.length > 0
        ? data.klines[data.klines.length - 1].close
        : null
      const newK = createKLine(idx, price, prevClose)
      setData((d) => ({ ...d, klines: dedupKlines([...d.klines, newK]) }))
    } else if (tool === 'trend') {
      setDragStart({ idx, price })
      setDragMode('trend')
    } else if (tool === 'horizontal') {
      pushHistory(data)
      setData((d) => ({
        ...d,
        horizontalLines: [...d.horizontalLines, { price }],
      }))
    } else if (tool === 'text') {
      const text = window.prompt('输入标注文字:')
      if (text && text.trim()) {
        pushHistory(data)
        const label: TextLabel = { idx, price, text: text.trim() }
        setData((d) => ({ ...d, labels: [...d.labels, label] }))
      }
    } else if (tool === 'eraser') {
      pushHistory(data)
      // 优先删除最近的 K 线
      const nearestK = findNearestKline(data.klines, idx, 0.8)
      if (nearestK) {
        setData((d) => ({ ...d, klines: removeKline(d.klines, nearestK.idx) }))
        return
      }
      // 其次删除趋势线
      const nearestLine = findNearestTrendLine(data.trendLines, idx, price, 3)
      if (nearestLine) {
        setData((d) => ({
          ...d,
          trendLines: d.trendLines.filter(
            (l) => !(l.x1 === nearestLine.x1 && l.y1 === nearestLine.y1 && l.x2 === nearestLine.x2 && l.y2 === nearestLine.y2),
          ),
        }))
        return
      }
      // 其次删除水平线
      const nearestH = data.horizontalLines.find((l) => Math.abs(l.price - price) < (max - min) * 0.05)
      if (nearestH) {
        setData((d) => ({
          ...d,
          horizontalLines: d.horizontalLines.filter((l) => l !== nearestH),
        }))
        return
      }
      // 最后删除文字标注
      const nearestLabel = data.labels.find(
        (l) => Math.abs(l.idx - idx) < 1 && Math.abs(l.price - price) < (max - min) * 0.1,
      )
      if (nearestLabel) {
        setData((d) => ({ ...d, labels: d.labels.filter((l) => l !== nearestLabel) }))
      }
    }
  }

  const handleMouseMove = (e: React.MouseEvent) => {
    const { x, y } = getMousePos(e)

    // --- 拖拽中 ---
    if (dragMode === 'divider') {
      // 计算新的 klineAreaRatio
      const newRatio = (y - 20) / (CANVAS_HEIGHT - 40)
      const clamped = Math.max(0.3, Math.min(0.85, newRatio))
      setData((d) => ({ ...d, klineAreaRatio: clamped }))
      return
    }

    if (dragMode === 'kline-high' && dragKlineIdx !== null) {
      const { price } = pixelToLogic(x, y)
      setData((d) => ({
        ...d,
        klines: d.klines.map((k) => {
          if (k.idx !== dragKlineIdx) return k
          const maxBody = Math.max(k.open, k.close)
          return { ...k, high: Math.max(price, maxBody) }
        }),
      }))
      return
    }

    if (dragMode === 'kline-low' && dragKlineIdx !== null) {
      const { price } = pixelToLogic(x, y)
      setData((d) => ({
        ...d,
        klines: d.klines.map((k) => {
          if (k.idx !== dragKlineIdx) return k
          const minBody = Math.min(k.open, k.close)
          return { ...k, low: Math.min(price, minBody) }
        }),
      }))
      return
    }

    if (dragMode === 'kline-body-top' && dragKlineIdx !== null) {
      const { price } = pixelToLogic(x, y)
      setData((d) => ({
        ...d,
        klines: d.klines.map((k) => {
          if (k.idx !== dragKlineIdx) return k
          // 实体顶端 = max(open, close), 拖拽时调整较大的那个值
          if (k.close >= k.open) {
            const newClose = Math.max(price, k.open)
            return { ...k, close: newClose, high: Math.max(k.high, newClose) }
          } else {
            const newOpen = Math.max(price, k.close)
            return { ...k, open: newOpen, high: Math.max(k.high, newOpen) }
          }
        }),
      }))
      return
    }

    if (dragMode === 'kline-body-bottom' && dragKlineIdx !== null) {
      const { price } = pixelToLogic(x, y)
      setData((d) => ({
        ...d,
        klines: d.klines.map((k) => {
          if (k.idx !== dragKlineIdx) return k
          // 实体底端 = min(open, close), 拖拽时调整较小的那个值
          if (k.close <= k.open) {
            const newClose = Math.min(price, k.open)
            return { ...k, close: newClose, low: Math.min(k.low, newClose) }
          } else {
            const newOpen = Math.min(price, k.close)
            return { ...k, open: newOpen, low: Math.min(k.low, newOpen) }
          }
        }),
      }))
      return
    }

    if (dragMode === 'trend') {
      // 趋势线拖拽中, 更新悬停位置
      const { idx, price } = pixelToLogic(x, y)
      setHoverIdx(Math.round(idx))
      setHoverPrice(price)
      return
    }

    // --- 非拖拽: 检测光标和悬停 ---
    // 分界线检测
    if (checkDividerProximity(y)) {
      setCursor('ns-resize')
      setHoverIdx(null)
      setHoverPrice(null)
      return
    }

    // K 线端点检测 (影线 + 实体)
    const wickHit = checkKlineProximity(x, y)
    if (wickHit) {
      setCursor('ns-resize')
      setHoverIdx(wickHit.idx)
      setHoverPrice(null)
      return
    }

    // 正常悬停
    setCursor('crosshair')
    const { idx, price } = pixelToLogic(x, y)
    if (tool === 'kline' || tool === 'eraser') {
      setHoverIdx(Math.round(idx))
      setHoverPrice(price)
    } else {
      setHoverIdx(null)
      setHoverPrice(null)
    }
  }

  const handleMouseUp = (e: React.MouseEvent) => {
    if (dragMode === 'trend' && dragStart) {
      const { x, y } = getMousePos(e)
      const { idx, price } = pixelToLogic(x, y)
      // 只有当终点和起点不同时才添加
      if (Math.abs(idx - dragStart.idx) > 0.1 || Math.abs(price - dragStart.price) > 0.01) {
        pushHistory(data)
        const line: TrendLine = {
          x1: dragStart.idx,
          y1: dragStart.price,
          x2: idx,
          y2: price,
        }
        setData((d) => ({ ...d, trendLines: [...d.trendLines, line] }))
      }
      setDragStart(null)
    }
    if (dragMode !== 'none') {
      setDragMode('none')
      setDragKlineIdx(null)
    }
  }

  const handleMouseLeave = () => {
    if (dragMode === 'none') {
      setHoverIdx(null)
      setHoverPrice(null)
      setCursor('crosshair')
    }
  }

  // 清空
  const handleClear = () => {
    if (data.klines.length === 0 && data.trendLines.length === 0 && data.labels.length === 0 && data.horizontalLines.length === 0) {
      return
    }
    if (window.confirm('确定清空所有内容?')) {
      pushHistory(data)
      setData((d) => ({ ...d, klines: [], trendLines: [], horizontalLines: [], labels: [] }))
    }
  }

  // 生成并插入
  const handleGenerate = () => {
    if (data.klines.length === 0) {
      window.alert('请至少绘制一根 K 线')
      return
    }
    const svg = generateKChartSvg(data)
    onInsert(svg)
    onClose()
  }

  // 工具按钮配置
  const tools: { id: KChartTool; label: string; icon: typeof X }[] = [
    { id: 'kline', label: 'K线', icon: CandlestickChart },
    { id: 'trend', label: '趋势线', icon: TrendingUp },
    { id: 'horizontal', label: '水平线', icon: Minus },
    { id: 'text', label: '文字', icon: TypeIcon },
    { id: 'eraser', label: '橡皮擦', icon: Eraser },
  ]

  return (
    <>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        className="fixed inset-0 z-[100] bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <motion.div
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.96, opacity: 0 }}
        transition={{ duration: 0.18, ease: 'easeOut' }}
        className="fixed inset-0 z-[101] flex items-center justify-center p-4"
      >
        <div className="w-full max-w-3xl flex flex-col rounded-2xl border border-border bg-surface text-foreground shadow-2xl overflow-hidden">
          {/* 顶部标题栏 */}
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border shrink-0">
            <div className="flex items-center gap-2">
              <CandlestickChart className="h-4 w-4 text-accent" />
              <span className="text-sm font-medium">手绘 K 线图</span>
              <span className="text-xs text-muted">
                ({data.klines.length} 根 K 线)
              </span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowHelp(true)}
                className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors"
                title="使用说明"
              >
                <HelpCircle className="h-4 w-4" />
              </button>
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors"
                title="关闭"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* 工具栏 */}
          <div className="flex items-center gap-1 px-4 py-2 border-b border-border shrink-0 flex-wrap">
            {tools.map((t) => {
              const Icon = t.icon
              return (
                <button
                  key={t.id}
                  onClick={() => setTool(t.id)}
                  className={cn(
                    'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs transition-all',
                    tool === t.id
                      ? 'bg-accent text-white shadow-sm'
                      : 'text-muted hover:bg-elevated hover:text-foreground',
                  )}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span>{t.label}</span>
                </button>
              )
            })}
            <div className="w-px h-5 bg-border mx-1" />
            <button
              onClick={undo}
              disabled={!canUndo}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs transition-all disabled:opacity-40 disabled:cursor-not-allowed text-muted hover:bg-elevated hover:text-foreground"
              title="撤销"
            >
              <Undo2 className="h-3.5 w-3.5" />
              <span>撤销</span>
            </button>
            <button
              onClick={handleClear}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs transition-all text-muted hover:bg-elevated hover:text-foreground"
              title="清空"
            >
              <Trash2 className="h-3.5 w-3.5" />
              <span>清空</span>
            </button>
            <div className="flex-1" />
            <button
              onClick={handleGenerate}
              disabled={data.klines.length === 0}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-accent text-white hover:opacity-90 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Check className="h-3.5 w-3.5" />
              <span>插入备忘录</span>
            </button>
          </div>

          {/* 画布区域 */}
          <div className="flex-1 overflow-auto p-4 bg-elevated/30 flex items-center justify-center">
            <canvas
              ref={canvasRef}
              width={CANVAS_WIDTH}
              height={CANVAS_HEIGHT}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseLeave}
              onContextMenu={(e) => e.preventDefault()}
              className="max-w-full rounded-lg shadow-sm"
              style={{ aspectRatio: `${CANVAS_WIDTH} / ${CANVAS_HEIGHT}`, cursor }}
            />
          </div>

          {/* 底部提示 */}
          <div className="px-4 py-2 border-t border-border text-xs text-muted shrink-0">
            {tool === 'kline' && '点击画布添加 K 线 · 鼠标靠近影线/实体端点可拖拽调整高低 · 拖拽K线/量能分界线调整区域比例'}
            {tool === 'trend' && '拖拽绘制趋势线'}
            {tool === 'horizontal' && '点击添加水平价格线 (支撑/阻力位)'}
            {tool === 'text' && '点击位置添加文字标注'}
            {tool === 'eraser' && '点击最近的元素删除 (K线/线/文字) · 拖拽分界线调整区域比例'}
          </div>
        </div>
      </motion.div>

      {/* 使用说明弹窗 */}
      {showHelp && (
        <>
          <div
            className="fixed inset-0 z-[102] bg-black/30"
            onClick={() => setShowHelp(false)}
          />
          <motion.div
            initial={{ scale: 0.96, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-[103] flex items-center justify-center p-4 pointer-events-none"
          >
            <div className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-2xl border border-border bg-surface text-foreground shadow-2xl pointer-events-auto">
              <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-surface">
                <div className="flex items-center gap-2">
                  <HelpCircle className="h-4 w-4 text-accent" />
                  <span className="text-sm font-medium">使用说明</span>
                </div>
                <button
                  onClick={() => setShowHelp(false)}
                  className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-foreground transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="px-5 py-4 space-y-4 text-sm text-muted leading-relaxed">
                <section>
                  <h4 className="text-foreground font-medium mb-1.5 flex items-center gap-1.5">
                    <CandlestickChart className="h-3.5 w-3.5 text-accent" />
                    K 线工具
                  </h4>
                  <p>点击画布添加一根 K 线。<b className="text-foreground">收盘价 = 点击位置</b>，开盘价 = 上一根 K 线的收盘价（首根为平盘）。影线（上下引线）会自动生成一小段超出实体的部分。</p>
                  <p className="mt-1.5">鼠标靠近已有 K 线时，该列会高亮并出现 4 个拖拽手柄：</p>
                  <ul className="mt-1 ml-4 space-y-0.5 text-xs">
                    <li>· <b className="text-foreground">影线顶端</b>（空心手柄）— 拖拽调整最高价</li>
                    <li>· <b className="text-foreground">影线底端</b>（空心手柄）— 拖拽调整最低价</li>
                    <li>· <b className="text-foreground">实体顶端</b>（实心手柄）— 拖拽调整实体上边界</li>
                    <li>· <b className="text-foreground">实体底端</b>（实心手柄）— 拖拽调整实体下边界</li>
                  </ul>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5 flex items-center gap-1.5">
                    <TrendingUp className="h-3.5 w-3.5 text-accent" />
                    趋势线
                  </h4>
                  <p>按住鼠标拖拽，从起点拉到终点松开，绘制一条虚线趋势线。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5 flex items-center gap-1.5">
                    <Minus className="h-3.5 w-3.5 text-accent" />
                    水平线
                  </h4>
                  <p>点击画布某一价格位置，生成一条横贯全图的水平虚线，用于标注支撑/阻力位。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5 flex items-center gap-1.5">
                    <TypeIcon className="h-3.5 w-3.5 text-accent" />
                    文字标注
                  </h4>
                  <p>点击画布位置，在弹出框中输入文字，生成带背景的标注标签。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5 flex items-center gap-1.5">
                    <Eraser className="h-3.5 w-3.5 text-accent" />
                    橡皮擦
                  </h4>
                  <p>点击最近的元素删除（按优先级：K 线 → 趋势线 → 水平线 → 文字标注）。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5">
                    分界线拖拽
                  </h4>
                  <p>鼠标移到 <b className="text-foreground">K 线区与量能区的分界线</b>附近时，光标变为上下箭头，上下拖拽可调整两个区域的高度比例（30%~85%）。比例会保存到导出的 SVG 中。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5">
                    十字光标
                  </h4>
                  <p>使用 K 线或橡皮擦工具时，鼠标悬停会显示十字虚线和当前价格，便于精确定位。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5">
                    撤销 / 清空
                  </h4>
                  <p>点击「撤销」回退最近一步操作（最多 50 步）。点击「清空」清除所有内容（需确认）。</p>
                </section>
                <section>
                  <h4 className="text-foreground font-medium mb-1.5">
                    插入备忘录
                  </h4>
                  <p>至少绘制一根 K 线后，点击「插入备忘录」将图表转为 SVG 插入备忘录。双击已插入的 K 线图可重新编辑。</p>
                </section>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </>
  )
}
