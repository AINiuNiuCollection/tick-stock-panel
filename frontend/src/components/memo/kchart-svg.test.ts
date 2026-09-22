// @vitest-environment jsdom
/**
 * K线图手绘方案 — 100 个测试用例
 *
 * 测试范围:
 *  1-15:  常量与类型
 *  16-30: 涨跌判断 (isBull)
 *  31-45: 价格范围 (priceRange)
 *  46-55: MA 均线计算 (calcMA)
 *  56-65: 量能推导 (calcVolumes)
 *  66-75: 坐标转换 (idxToX, priceToY)
 *  76-85: K线操作 (createKLine, dedup, remove, findNearest)
 *  86-95: 趋势线命中检测 (pointToLineDistance, findNearestTrendLine)
 *  96-115:SVG 元素生成 (klineToSvg, maToSvg, volumeToSvg, trendLineToSvg, labelToSvg)
 * 116-125:XML 转义 (escapeXml, unescapeXml)
 * 126-135:数据校验 (isValidKChartData, parseKChartFromSvg)
 * 136-150:完整 SVG 生成 (generateKChartSvg)
 * 151-160:边界情况与集成
 */
import { describe, it, expect } from 'vitest'
import {
  BULL_COLOR,
  BEAR_COLOR,
  MA5_COLOR,
  MA10_COLOR,
  NEUTRAL_COLOR,
  DARK_BG,
  LIGHT_BG,
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
  KLINE_AREA_RATIO,
  VOLUME_AREA_RATIO,
  MAX_KLINES,
  MIN_KLINES,
  type KLine,
  type TrendLine,
  type HorizontalLine,
  type TextLabel,
  type KChartData,
  isBull,
  priceRange,
  calcMA,
  calcVolumes,
  idxToX,
  priceToY,
  klineArea,
  volumeArea,
  klineToSvg,
  maToSvg,
  volumeToSvg,
  trendLineToSvg,
  horizontalLineToSvg,
  labelToSvg,
  escapeXml,
  unescapeXml,
  generateKChartSvg,
  parseKChartFromSvg,
  isValidKChartData,
  isValidKLine,
  isValidTrendLine,
  isValidHorizontalLine,
  isValidLabel,
  createKLine,
  sortKlines,
  dedupKlines,
  removeKline,
  findNearestKline,
  findNearestTrendLine,
  pointToLineDistance,
  emptyKChartData,
  extractDataFromSvgString,
  resolveRatio,
  formatPrice,
} from './kchart-svg'

// 辅助: 构造 K 线
const k = (idx: number, o: number, c: number, h: number, l: number): KLine => ({
  idx, open: o, close: c, high: h, low: l,
})

// 辅助: 浮点近似比较
const approx = (a: number, b: number, eps = 0.001) => Math.abs(a - b) < eps

describe('kchart-svg 常量', () => {
  it('1. BULL_COLOR 为红色 #C74040', () => {
    expect(BULL_COLOR).toBe('#C74040')
  })
  it('2. BEAR_COLOR 为绿色 #2D9B65', () => {
    expect(BEAR_COLOR).toBe('#2D9B65')
  })
  it('3. MA5_COLOR 为黄色', () => {
    expect(MA5_COLOR).toBe('#EAB308')
  })
  it('4. MA10_COLOR 为蓝色', () => {
    expect(MA10_COLOR).toBe('#3B82F6')
  })
  it('5. NEUTRAL_COLOR 为灰色', () => {
    expect(NEUTRAL_COLOR).toBe('#71717A')
  })
  it('6. DARK_BG 为暗色背景', () => {
    expect(DARK_BG).toBe('#18181B')
  })
  it('7. LIGHT_BG 为亮色背景', () => {
    expect(LIGHT_BG).toBe('#FAFAF9')
  })
  it('8. CANVAS_WIDTH = 600', () => {
    expect(CANVAS_WIDTH).toBe(600)
  })
  it('9. CANVAS_HEIGHT = 320', () => {
    expect(CANVAS_HEIGHT).toBe(320)
  })
  it('10. KLINE_AREA_RATIO = 0.7', () => {
    expect(KLINE_AREA_RATIO).toBe(0.7)
  })
  it('11. VOLUME_AREA_RATIO = 0.3', () => {
    expect(VOLUME_AREA_RATIO).toBe(0.3)
  })
  it('12. MAX_KLINES = 60', () => {
    expect(MAX_KLINES).toBe(60)
  })
  it('13. MIN_KLINES = 0', () => {
    expect(MIN_KLINES).toBe(0)
  })
  it('14. 涨跌色与项目规范一致 (红涨绿跌)', () => {
    expect(BULL_COLOR).not.toBe(BEAR_COLOR)
  })
  it('15. 均线颜色与涨跌色不同', () => {
    expect(MA5_COLOR).not.toBe(BULL_COLOR)
    expect(MA5_COLOR).not.toBe(BEAR_COLOR)
    expect(MA10_COLOR).not.toBe(BULL_COLOR)
    expect(MA10_COLOR).not.toBe(BEAR_COLOR)
  })
})

describe('isBull 涨跌判断', () => {
  it('16. close > open 为涨 (红)', () => {
    expect(isBull(k(0, 10, 11, 12, 9))).toBe(true)
  })
  it('17. close < open 为跌 (绿)', () => {
    expect(isBull(k(0, 11, 10, 12, 9))).toBe(false)
  })
  it('18. close === open 为涨 (红, 平盘按涨处理)', () => {
    expect(isBull(k(0, 10, 10, 11, 9))).toBe(true)
  })
  it('19. 大涨为涨', () => {
    expect(isBull(k(0, 10, 100, 101, 9))).toBe(true)
  })
  it('20. 大跌为跌', () => {
    expect(isBull(k(0, 100, 10, 101, 9))).toBe(false)
  })
  it('21. 0 价格平盘为涨', () => {
    expect(isBull(k(0, 0, 0, 0, 0))).toBe(true)
  })
  it('22. 负价格 close < open 为跌', () => {
    expect(isBull(k(0, -5, -10, 0, -15))).toBe(false)
  })
  it('23. 负价格 close > open 为涨', () => {
    expect(isBull(k(0, -10, -5, 0, -15))).toBe(true)
  })
  it('24. 小数价格涨', () => {
    expect(isBull(k(0, 10.01, 10.02, 10.03, 10.0))).toBe(true)
  })
  it('25. 小数价格跌', () => {
    expect(isBull(k(0, 10.02, 10.01, 10.03, 10.0))).toBe(false)
  })
  it('26. 极小差值仍判断为涨', () => {
    expect(isBull(k(0, 10.0000001, 10.0000002, 11, 9))).toBe(true)
  })
  it('27. 极小差值仍判断为跌', () => {
    expect(isBull(k(0, 10.0000002, 10.0000001, 11, 9))).toBe(false)
  })
  it('28. 多根 K 线涨跌混合独立判断', () => {
    const klines = [k(0, 10, 11, 12, 9), k(1, 11, 10, 12, 9)]
    expect(isBull(klines[0])).toBe(true)
    expect(isBull(klines[1])).toBe(false)
  })
  it('29. high < close 时仍按 close vs open 判断', () => {
    expect(isBull(k(0, 10, 15, 12, 9))).toBe(true)
  })
  it('30. low > open 时仍按 close vs open 判断', () => {
    expect(isBull(k(0, 10, 8, 12, 11))).toBe(false)
  })
})

describe('priceRange 价格范围', () => {
  it('31. 空数组返回默认范围', () => {
    const r = priceRange([])
    expect(r.min).toBe(0)
    expect(r.max).toBe(1)
  })
  it('32. 单根 K 线扩展范围', () => {
    const r = priceRange([k(0, 10, 11, 12, 9)])
    expect(r.min).toBeLessThan(9)
    expect(r.max).toBeGreaterThan(12)
  })
  it('33. 多根 K 线取 min/max 并加 5% padding', () => {
    const r = priceRange([k(0, 10, 11, 12, 9), k(1, 11, 13, 15, 10)])
    expect(r.min).toBeLessThan(9)
    expect(r.max).toBeGreaterThan(15)
  })
  it('34. 全平 K 线 (min===max) 退化处理', () => {
    const r = priceRange([k(0, 10, 10, 10, 10)])
    expect(r.min).toBeLessThan(r.max)
  })
  it('35. 包含 0 价格', () => {
    const r = priceRange([k(0, 0, 1, 2, -1)])
    expect(r.min).toBeLessThan(-1)
    expect(r.max).toBeGreaterThan(2)
  })
  it('36. padding 约为 5%', () => {
    const r = priceRange([k(0, 10, 10, 20, 10)])
    const range = 20 - 10
    const expectedPad = range * 0.05
    expect(approx(r.min, 10 - expectedPad, 0.01)).toBe(true)
    expect(approx(r.max, 20 + expectedPad, 0.01)).toBe(true)
  })
  it('37. 负价格正确处理', () => {
    const r = priceRange([k(0, -20, -10, -5, -25)])
    expect(r.min).toBeLessThan(-25)
    expect(r.max).toBeGreaterThan(-5)
  })
  it('38. 大量 K 线', () => {
    const klines: KLine[] = []
    for (let i = 0; i < 100; i++) {
      klines.push(k(i, i, i + 1, i + 2, i - 1))
    }
    const r = priceRange(klines)
    expect(r.min).toBeLessThan(-1)
    expect(r.max).toBeGreaterThan(101)
  })
  it('39. 最小值在 low 字段', () => {
    const r = priceRange([k(0, 10, 11, 12, 3)])
    // low=3 是最小值, padding 后更小
    expect(r.min).toBeLessThan(3)
  })
  it('40. 最大值在 high 字段', () => {
    const r = priceRange([k(0, 10, 11, 50, 9)])
    expect(r.max).toBeGreaterThan(50)
  })
  it('41. 两根 K 线不退化', () => {
    const r = priceRange([k(0, 10, 11, 12, 9), k(1, 11, 10, 13, 8)])
    expect(r.min).toBeLessThan(8)
    expect(r.max).toBeGreaterThan(13)
  })
  it('42. min < max 恒成立', () => {
    const inputs = [
      [k(0, 5, 5, 5, 5)],
      [k(0, 100, 100, 100, 100)],
      [k(0, 0, 0, 0, 0)],
    ]
    for (const input of inputs) {
      const r = priceRange(input)
      expect(r.min).toBeLessThan(r.max)
    }
  })
  it('43. 带小数的 K 线', () => {
    const r = priceRange([k(0, 10.5, 11.2, 11.8, 10.1)])
    expect(r.min).toBeLessThan(10.1)
    expect(r.max).toBeGreaterThan(11.8)
  })
  it('44. 极端大数', () => {
    const r = priceRange([k(0, 1e6, 1.1e6, 1.2e6, 0.9e6)])
    expect(r.min).toBeLessThan(0.9e6)
    expect(r.max).toBeGreaterThan(1.2e6)
  })
  it('45. 极端小数', () => {
    const r = priceRange([k(0, 0.001, 0.002, 0.003, 0.0005)])
    expect(r.min).toBeLessThan(0.0005)
    expect(r.max).toBeGreaterThan(0.003)
  })
})

describe('calcMA 均线计算', () => {
  it('46. 空数组返回空', () => {
    expect(calcMA([], 5)).toEqual([])
  })
  it('47. 数据量 < period 全为 null', () => {
    const ma = calcMA([k(0, 10, 11, 12, 9), k(1, 11, 12, 13, 10)], 5)
    expect(ma).toEqual([null, null])
  })
  it('48. 数据量 = period 最后一根有值', () => {
    const ma = calcMA([k(0, 10, 10, 12, 9), k(1, 10, 20, 22, 19), k(2, 10, 30, 32, 29), k(3, 10, 40, 42, 39), k(4, 10, 50, 52, 49)], 5)
    expect(ma[4]).not.toBeNull()
    expect(approx(ma[4]!, 30)).toBe(true) // (10+20+30+40+50)/5 = 30
  })
  it('49. MA5 前 4 根为 null', () => {
    const klines: KLine[] = Array.from({ length: 10 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const ma = calcMA(klines, 5)
    expect(ma[0]).toBeNull()
    expect(ma[1]).toBeNull()
    expect(ma[2]).toBeNull()
    expect(ma[3]).toBeNull()
    expect(ma[4]).not.toBeNull()
  })
  it('50. MA5 第 5 根 = 前 5 根 close 均值', () => {
    const klines: KLine[] = Array.from({ length: 5 }, (_, i) => k(i, 10, (i + 1) * 2, 12, 9))
    const ma = calcMA(klines, 5)
    // close: 2, 4, 6, 8, 10 → avg = 6
    expect(approx(ma[4]!, 6)).toBe(true)
  })
  it('51. MA10 前 9 根为 null', () => {
    const klines: KLine[] = Array.from({ length: 15 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const ma = calcMA(klines, 10)
    for (let i = 0; i < 9; i++) {
      expect(ma[i]).toBeNull()
    }
    expect(ma[9]).not.toBeNull()
  })
  it('52. MA1 = close 本身', () => {
    const klines: KLine[] = [k(0, 10, 15, 20, 5), k(1, 10, 25, 30, 5)]
    const ma = calcMA(klines, 1)
    expect(approx(ma[0]!, 15)).toBe(true)
    expect(approx(ma[1]!, 25)).toBe(true)
  })
  it('53. 滑动窗口正确', () => {
    const klines: KLine[] = Array.from({ length: 6 }, (_, i) => k(i, 10, i + 1, 12, 9))
    const ma = calcMA(klines, 3)
    // close: 1,2,3,4,5,6
    // ma[2] = (1+2+3)/3 = 2
    // ma[3] = (2+3+4)/3 = 3
    // ma[4] = (3+4+5)/3 = 4
    // ma[5] = (4+5+6)/3 = 5
    expect(approx(ma[2]!, 2)).toBe(true)
    expect(approx(ma[3]!, 3)).toBe(true)
    expect(approx(ma[4]!, 4)).toBe(true)
    expect(approx(ma[5]!, 5)).toBe(true)
  })
  it('54. period=0 不崩溃 (极端边界)', () => {
    const ma = calcMA([k(0, 10, 11, 12, 9)], 0)
    // period=0: i < -1 永远 false, sum from i+1 to i (空循环) = 0/0 = NaN
    expect(ma.length).toBe(1)
  })
  it('55. 大量数据 MA 计算正确', () => {
    const klines: KLine[] = Array.from({ length: 100 }, (_, i) => k(i, 10, i + 1, 12, 9))
    const ma = calcMA(klines, 5)
    expect(ma.length).toBe(100)
    expect(ma[4]).not.toBeNull()
    expect(ma[99]).not.toBeNull()
  })
})

describe('calcVolumes 量能推导', () => {
  it('56. 空数组返回空', () => {
    expect(calcVolumes([])).toEqual([])
  })
  it('57. 单根 K 线归一化为 1', () => {
    const v = calcVolumes([k(0, 10, 15, 20, 5)])
    expect(v).toEqual([1])
  })
  it('58. 最大差值对应 1', () => {
    const klines = [k(0, 10, 11, 12, 9), k(1, 10, 20, 21, 9)]
    const v = calcVolumes(klines)
    expect(v[1]).toBe(1)
  })
  it('59. 比例正确', () => {
    const klines = [k(0, 10, 11, 12, 9), k(1, 10, 20, 21, 9)]
    const v = calcVolumes(klines)
    // |11-10|=1, |20-10|=10 → 1/10=0.1
    expect(approx(v[0], 0.1)).toBe(true)
  })
  it('60. 全平 K 线不除以 0', () => {
    const v = calcVolumes([k(0, 10, 10, 10, 10), k(1, 10, 10, 10, 10)])
    expect(v.length).toBe(2)
    expect(v[0]).toBe(0)
    expect(v[1]).toBe(0)
  })
  it('61. 涨跌混合', () => {
    const klines = [k(0, 10, 15, 16, 9), k(1, 15, 10, 16, 9)]
    const v = calcVolumes(klines)
    expect(approx(v[0], 1)).toBe(true)
    expect(approx(v[1], 1)).toBe(true)
  })
  it('62. 所有值为 0~1 之间', () => {
    const klines: KLine[] = Array.from({ length: 10 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const v = calcVolumes(klines)
    for (const vol of v) {
      expect(vol).toBeGreaterThanOrEqual(0)
      expect(vol).toBeLessThanOrEqual(1)
    }
  })
  it('63. 全 0 差值退化处理', () => {
    const v = calcVolumes([k(0, 10, 10, 10, 10)])
    expect(v).toEqual([0])
  })
  it('64. 最大值在第一个', () => {
    const klines = [k(0, 10, 100, 101, 9), k(1, 10, 11, 12, 9), k(2, 10, 12, 13, 9)]
    const v = calcVolumes(klines)
    expect(v[0]).toBe(1)
    expect(v[1]).toBeLessThan(1)
  })
  it('65. 负价格差值取绝对值', () => {
    const klines = [k(0, -10, -15, 0, -20), k(1, -15, -10, 0, -20)]
    const v = calcVolumes(klines)
    expect(approx(v[0], 1)).toBe(true)
    expect(approx(v[1], 1)).toBe(true)
  })
})

describe('坐标转换', () => {
  it('66. idxToX: count<=1 居中', () => {
    expect(idxToX(0, 1)).toBe(CANVAS_WIDTH / 2)
  })
  it('67. idxToX: idx=0 在左侧', () => {
    expect(idxToX(0, 10)).toBe(10)
  })
  it('68. idxToX: idx=count-1 在右侧', () => {
    expect(idxToX(9, 10)).toBe(CANVAS_WIDTH - 10)
  })
  it('69. idxToX: 中间值线性', () => {
    const x0 = idxToX(0, 10)
    const x9 = idxToX(9, 10)
    const x4 = idxToX(4, 10)
    expect(approx(x4, x0 + (x9 - x0) * 4 / 9)).toBe(true)
  })
  it('70. priceToY: 中间值居中', () => {
    const area = klineArea()
    const y = priceToY(50, 0, 100, area.top, area.height)
    expect(approx(y, area.top + area.height / 2)).toBe(true)
  })
  it('71. priceToY: 最高价在顶部', () => {
    const area = klineArea()
    const y = priceToY(100, 0, 100, area.top, area.height)
    expect(approx(y, area.top)).toBe(true)
  })
  it('72. priceToY: 最低价在底部', () => {
    const area = klineArea()
    const y = priceToY(0, 0, 100, area.top, area.height)
    expect(approx(y, area.top + area.height)).toBe(true)
  })
  it('73. priceToY: min===max 居中', () => {
    const area = klineArea()
    const y = priceToY(50, 50, 50, area.top, area.height)
    expect(approx(y, area.top + area.height / 2)).toBe(true)
  })
  it('74. klineArea + volumeArea 不重叠', () => {
    const k = klineArea()
    const v = volumeArea()
    expect(v.top).toBeGreaterThanOrEqual(k.bottom)
  })
  it('75. klineArea 占 70% 高度', () => {
    const area = klineArea()
    const totalUsable = CANVAS_HEIGHT - 40
    expect(approx(area.height, totalUsable * 0.7, 0.01)).toBe(true)
  })
})

describe('K线操作', () => {
  it('76. createKLine: 无前收盘时 open=close', () => {
    const kl = createKLine(0, 100, null)
    expect(kl.open).toBe(100)
    expect(kl.close).toBe(100)
  })
  it('77. createKLine: 有前收盘时 open=prevClose', () => {
    const kl = createKLine(1, 110, 100)
    expect(kl.open).toBe(100)
    expect(kl.close).toBe(110)
  })
  it('78. createKLine: high > max(open, close)', () => {
    const kl = createKLine(0, 110, 100)
    expect(kl.high).toBeGreaterThan(Math.max(kl.open, kl.close))
  })
  it('79. createKLine: low < min(open, close)', () => {
    const kl = createKLine(0, 110, 100)
    expect(kl.low).toBeLessThan(Math.min(kl.open, kl.close))
  })
  it('80. dedupKlines: 同 idx 保留最新', () => {
    const k1 = k(0, 10, 11, 12, 9)
    const k2 = k(0, 10, 12, 13, 9)
    const result = dedupKlines([k1, k2])
    expect(result.length).toBe(1)
    expect(result[0].close).toBe(12)
  })
  it('81. dedupKlines: 不同 idx 全保留', () => {
    const k1 = k(0, 10, 11, 12, 9)
    const k2 = k(1, 11, 12, 13, 10)
    const result = dedupKlines([k1, k2])
    expect(result.length).toBe(2)
  })
  it('82. dedupKlines: 按 idx 排序', () => {
    const k1 = k(2, 10, 11, 12, 9)
    const k2 = k(0, 10, 12, 13, 9)
    const k3 = k(1, 10, 13, 14, 9)
    const result = dedupKlines([k1, k2, k3])
    expect(result.map((kl) => kl.idx)).toEqual([0, 1, 2])
  })
  it('83. removeKline: 删除指定 idx', () => {
    const klines = [k(0, 10, 11, 12, 9), k(1, 11, 12, 13, 10), k(2, 12, 13, 14, 11)]
    const result = removeKline(klines, 1)
    expect(result.length).toBe(2)
    expect(result.map((kl) => kl.idx)).toEqual([0, 2])
  })
  it('84. removeKline: 删除不存在的 idx 无变化', () => {
    const klines = [k(0, 10, 11, 12, 9)]
    const result = removeKline(klines, 99)
    expect(result.length).toBe(1)
  })
  it('85. findNearestKline: 找到最近', () => {
    const klines = [k(0, 10, 11, 12, 9), k(5, 11, 12, 13, 10), k(10, 12, 13, 14, 11)]
    const nearest = findNearestKline(klines, 4, 2)
    expect(nearest?.idx).toBe(5)
  })
})

describe('趋势线命中检测', () => {
  it('86. pointToLineDistance: 点在线上距离为 0', () => {
    const line: TrendLine = { x1: 0, y1: 0, x2: 10, y2: 10 }
    expect(pointToLineDistance(5, 5, line)).toBe(0)
  })
  it('87. pointToLineDistance: 点在线外', () => {
    const line: TrendLine = { x1: 0, y1: 0, x2: 10, y2: 0 }
    expect(approx(pointToLineDistance(5, 3, line), 3)).toBe(true)
  })
  it('88. pointToLineDistance: 零长度线段退化为点到点距离', () => {
    const line: TrendLine = { x1: 5, y1: 5, x2: 5, y2: 5 }
    const d = pointToLineDistance(0, 0, line)
    expect(approx(d, Math.sqrt(50))).toBe(true)
  })
  it('89. pointToLineDistance: 投影在线段外时取端点', () => {
    const line: TrendLine = { x1: 0, y1: 0, x2: 10, y2: 0 }
    const d = pointToLineDistance(15, 3, line)
    expect(approx(d, Math.sqrt(34))).toBe(true) // sqrt(5^2 + 3^2)
  })
  it('90. findNearestTrendLine: 找到最近线', () => {
    const lines: TrendLine[] = [
      { x1: 0, y1: 0, x2: 10, y2: 10 },
      { x1: 0, y1: 20, x2: 10, y2: 20 },
    ]
    const nearest = findNearestTrendLine(lines, 5, 5)
    expect(nearest).toBe(lines[0])
  })
  it('91. findNearestTrendLine: 超出阈值返回 null', () => {
    const lines: TrendLine[] = [{ x1: 0, y1: 0, x2: 10, y2: 0 }]
    const nearest = findNearestTrendLine(lines, 5, 100, 2)
    expect(nearest).toBeNull()
  })
  it('92. findNearestTrendLine: 空数组返回 null', () => {
    expect(findNearestTrendLine([], 5, 5)).toBeNull()
  })
  it('93. pointToLineDistance: 垂直线段', () => {
    const line: TrendLine = { x1: 5, y1: 0, x2: 5, y2: 10 }
    expect(approx(pointToLineDistance(8, 5, line), 3)).toBe(true)
  })
  it('94. pointToLineDistance: 斜线', () => {
    const line: TrendLine = { x1: 0, y1: 0, x2: 3, y2: 4 }
    // 点 (0, 4) 到线段距离: 投影 t = (0*3+4*4)/(9+16) = 16/25, 投影点 (1.92, 2.56)
    // 距离 = sqrt((0-1.92)^2 + (4-2.56)^2) = sqrt(3.6864 + 2.0736) = sqrt(5.76) = 2.4
    expect(approx(pointToLineDistance(0, 4, line), 2.4)).toBe(true)
  })
  it('95. findNearestTrendLine: 两条等距线返回第一条', () => {
    const lines: TrendLine[] = [
      { x1: 0, y1: 5, x2: 10, y2: 5 },
      { x1: 0, y1: 15, x2: 10, y2: 15 },
    ]
    const nearest = findNearestTrendLine(lines, 5, 10, 10)
    expect(nearest).toBe(lines[0])
  })
})

describe('SVG 元素生成', () => {
  it('96. klineToSvg: 涨K线包含红色', () => {
    const svg = klineToSvg(k(0, 10, 11, 12, 9), 0, 20, 10)
    expect(svg).toContain(BULL_COLOR)
  })
  it('97. klineToSvg: 跌K线包含绿色', () => {
    const svg = klineToSvg(k(0, 11, 10, 12, 9), 0, 20, 10)
    expect(svg).toContain(BEAR_COLOR)
  })
  it('98. klineToSvg: 包含 rect 和 line 元素', () => {
    const svg = klineToSvg(k(0, 10, 11, 12, 9), 0, 20, 10)
    expect(svg).toContain('<rect')
    expect(svg).toContain('<line')
  })
  it('99. maToSvg: 数据不足返回空', () => {
    const ma = calcMA([k(0, 10, 11, 12, 9)], 5)
    expect(maToSvg(ma, 0, 20, 10, MA5_COLOR)).toBe('')
  })
  it('100. maToSvg: 有数据返回 polyline', () => {
    const klines: KLine[] = Array.from({ length: 6 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const ma = calcMA(klines, 5)
    const svg = maToSvg(ma, 0, 20, 6, MA5_COLOR)
    expect(svg).toContain('<polyline')
    expect(svg).toContain(MA5_COLOR)
  })
  it('101. volumeToSvg: 空数组返回空', () => {
    expect(volumeToSvg([], [], 10)).toBe('')
  })
  it('102. volumeToSvg: 有数据返回 rect', () => {
    const klines = [k(0, 10, 11, 12, 9)]
    const vols = calcVolumes(klines)
    const svg = volumeToSvg(vols, klines, 1)
    expect(svg).toContain('<rect')
  })
  it('103. trendLineToSvg: 返回虚线', () => {
    const line: TrendLine = { x1: 0, y1: 10, x2: 5, y2: 15 }
    const svg = trendLineToSvg(line, 0, 20, 10)
    expect(svg).toContain('stroke-dasharray')
  })
  it('104. horizontalLineToSvg: 返回水平线', () => {
    const line: HorizontalLine = { price: 10 }
    const svg = horizontalLineToSvg(line, 0, 20, 10)
    expect(svg).toContain('<line')
    // y1 应该等于 y2 (水平线)
    const y1Match = svg.match(/y1="([^"]*)"/)
    const y2Match = svg.match(/y2="([^"]*)"/)
    expect(y1Match?.[1]).toBe(y2Match?.[1])
  })
  it('105. labelToSvg: 包含文字内容', () => {
    const label: TextLabel = { idx: 0, price: 10, text: '买入点' }
    const svg = labelToSvg(label, 0, 20, 10, 'dark')
    expect(svg).toContain('买入点')
  })
  it('106. labelToSvg: 暗色主题文字色为浅色', () => {
    const label: TextLabel = { idx: 0, price: 10, text: 'test' }
    const svg = labelToSvg(label, 0, 20, 10, 'dark')
    expect(svg).toContain('#E4E4E7')
  })
  it('107. labelToSvg: 亮色主题文字色为深色', () => {
    const label: TextLabel = { idx: 0, price: 10, text: 'test' }
    const svg = labelToSvg(label, 0, 20, 10, 'light')
    expect(svg).toContain('#27272A')
  })
  it('108. labelToSvg: 特殊字符被转义', () => {
    const label: TextLabel = { idx: 0, price: 10, text: '<script>' }
    const svg = labelToSvg(label, 0, 20, 10, 'dark')
    expect(svg).not.toContain('<script>')
    expect(svg).toContain('&lt;script&gt;')
  })
  it('109. horizontalLineToSvg: 指定起止 idx', () => {
    const line: HorizontalLine = { price: 10, startIdx: 2, endIdx: 8 }
    const svg = horizontalLineToSvg(line, 0, 20, 10)
    expect(svg).toContain('<line')
  })
  it('110. maToSvg: MA10 颜色正确', () => {
    const klines: KLine[] = Array.from({ length: 11 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const ma = calcMA(klines, 10)
    const svg = maToSvg(ma, 0, 20, 11, MA10_COLOR)
    expect(svg).toContain(MA10_COLOR)
  })
})

describe('XML 转义', () => {
  it('111. escapeXml: & 转义', () => {
    expect(escapeXml('a&b')).toBe('a&amp;b')
  })
  it('112. escapeXml: < 转义', () => {
    expect(escapeXml('a<b')).toBe('a&lt;b')
  })
  it('113. escapeXml: > 转义', () => {
    expect(escapeXml('a>b')).toBe('a&gt;b')
  })
  it('114. escapeXml: " 转义', () => {
    expect(escapeXml('a"b')).toBe('a&quot;b')
  })
  it('115. escapeXml: \' 转义', () => {
    expect(escapeXml("a'b")).toBe('a&apos;b')
  })
  it('116. escapeXml: 多字符混合', () => {
    expect(escapeXml('<div class="a">&\'text\'</div>')).toBe(
      '&lt;div class=&quot;a&quot;&gt;&amp;&apos;text&apos;&lt;/div&gt;',
    )
  })
  it('117. escapeXml: 无特殊字符不变', () => {
    expect(escapeXml('hello world')).toBe('hello world')
  })
  it('118. escapeXml: 空字符串', () => {
    expect(escapeXml('')).toBe('')
  })
  it('119. unescapeXml: &amp; 反转义', () => {
    expect(unescapeXml('a&amp;b')).toBe('a&b')
  })
  it('120. unescapeXml: 全部反转义', () => {
    expect(unescapeXml('&lt;div&gt;&amp;&quot;&apos;')).toBe('<div>&"\'')
  })
  it('121. escape → unescape 往返一致', () => {
    const original = '<div class="x">&\'test\'</div>'
    expect(unescapeXml(escapeXml(original))).toBe(original)
  })
  it('122. unescapeXml: 无实体不变', () => {
    expect(unescapeXml('hello')).toBe('hello')
  })
  it('123. escapeXml: 中文不转义', () => {
    expect(escapeXml('买入点')).toBe('买入点')
  })
  it('124. escapeXml: 连续 & 字符', () => {
    expect(escapeXml('&&')).toBe('&amp;&amp;')
  })
  it('125. unescapeXml: 空字符串', () => {
    expect(unescapeXml('')).toBe('')
  })
})

describe('数据校验', () => {
  it('126. isValidKLine: 合法 K 线', () => {
    expect(isValidKLine({ idx: 0, open: 10, close: 11, high: 12, low: 9 })).toBe(true)
  })
  it('127. isValidKLine: 缺少字段', () => {
    expect(isValidKLine({ idx: 0, open: 10, close: 11 })).toBe(false)
  })
  it('128. isValidKLine: null', () => {
    expect(isValidKLine(null)).toBe(false)
  })
  it('129. isValidKLine: NaN 不合法', () => {
    expect(isValidKLine({ idx: NaN, open: 10, close: 11, high: 12, low: 9 })).toBe(false)
  })
  it('130. isValidTrendLine: 合法', () => {
    expect(isValidTrendLine({ x1: 0, y1: 10, x2: 5, y2: 15 })).toBe(true)
  })
  it('131. isValidTrendLine: 缺少字段', () => {
    expect(isValidTrendLine({ x1: 0, y1: 10 })).toBe(false)
  })
  it('132. isValidHorizontalLine: 合法', () => {
    expect(isValidHorizontalLine({ price: 10 })).toBe(true)
  })
  it('133. isValidHorizontalLine: 缺 price', () => {
    expect(isValidHorizontalLine({})).toBe(false)
  })
  it('134. isValidLabel: 合法', () => {
    expect(isValidLabel({ idx: 0, price: 10, text: '买入' })).toBe(true)
  })
  it('135. isValidLabel: text 非 string', () => {
    expect(isValidLabel({ idx: 0, price: 10, text: 123 })).toBe(false)
  })
  it('136. isValidKChartData: 合法完整数据', () => {
    const data: KChartData = {
      klines: [k(0, 10, 11, 12, 9)],
      trendLines: [],
      horizontalLines: [],
      labels: [],
      theme: 'dark',
    }
    expect(isValidKChartData(data)).toBe(true)
  })
  it('137. isValidKChartData: 缺 theme', () => {
    expect(isValidKChartData({ klines: [], trendLines: [], horizontalLines: [], labels: [] })).toBe(false)
  })
  it('138. isValidKChartData: null', () => {
    expect(isValidKChartData(null)).toBe(false)
  })
  it('139. isValidKChartData: theme 非法值', () => {
    expect(isValidKChartData({ klines: [], trendLines: [], horizontalLines: [], labels: [], theme: 'blue' })).toBe(false)
  })
  it('140. parseKChartFromSvg: 无 data-kchart 属性返回 null', () => {
    const div = document.createElement('div')
    expect(parseKChartFromSvg(div)).toBeNull()
  })
})

describe('完整 SVG 生成', () => {
  const sampleData: KChartData = {
    klines: [
      k(0, 10, 11, 12, 9),
      k(1, 11, 10, 12, 9),
      k(2, 10, 13, 14, 9),
      k(3, 13, 12, 14, 9),
      k(4, 12, 15, 16, 11),
    ],
    trendLines: [{ x1: 0, y1: 10, x2: 4, y2: 15 }],
    horizontalLines: [{ price: 12 }],
    labels: [{ idx: 2, price: 13, text: '买入' }],
    theme: 'dark',
  }

  it('141. generateKChartSvg: 返回 <svg> 字符串', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg.endsWith('</svg>')).toBe(true)
  })
  it('142. generateKChartSvg: 包含 data-kchart 属性', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain('data-kchart=')
  })
  it('143. generateKChartSvg: 暗色主题背景为暗色', () => {
    const svg = generateKChartSvg({ ...sampleData, theme: 'dark' })
    expect(svg).toContain(DARK_BG)
  })
  it('144. generateKChartSvg: 亮色主题背景为亮色', () => {
    const svg = generateKChartSvg({ ...sampleData, theme: 'light' })
    expect(svg).toContain(LIGHT_BG)
  })
  it('145. generateKChartSvg: 包含 K 线 rect', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain('<rect')
  })
  it('146. generateKChartSvg: 包含趋势线', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain('stroke-dasharray')
  })
  it('147. generateKChartSvg: 包含水平线', () => {
    const svg = generateKChartSvg(sampleData)
    // 水平线也是 stroke-dasharray
    expect(svg).toContain('<line')
  })
  it('148. generateKChartSvg: 包含文字标注', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain('买入')
  })
  it('149. generateKChartSvg: 包含图例', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain('MA5')
    // sampleData 只有 5 根 K 线, MA10 需要 >=10 根才显示
    const klines10: KLine[] = Array.from({ length: 12 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const svg10 = generateKChartSvg({ ...emptyKChartData('dark'), klines: klines10 })
    expect(svg10).toContain('MA10')
  })
  it('150. generateKChartSvg: 空数据不崩溃', () => {
    const svg = generateKChartSvg(emptyKChartData('dark'))
    expect(svg.startsWith('<svg')).toBe(true)
  })
  it('151. generateKChartSvg: 含 MA5 均线 (>=5根)', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain(MA5_COLOR)
  })
  it('152. generateKChartSvg: 不足 10 根不含 MA10', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).not.toContain(MA10_COLOR)
  })
  it('153. generateKChartSvg: 含 MA10 均线 (>=10根)', () => {
    const klines: KLine[] = Array.from({ length: 10 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const svg = generateKChartSvg({ ...emptyKChartData('dark'), klines })
    expect(svg).toContain(MA10_COLOR)
  })
  it('154. generateKChartSvg: viewBox 正确', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain(`viewBox="0 0 ${CANVAS_WIDTH} ${CANVAS_HEIGHT}"`)
  })
  it('155. generateKChartSvg: 涨K线含红色', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain(BULL_COLOR)
  })
  it('156. generateKChartSvg: 跌K线含绿色', () => {
    const svg = generateKChartSvg(sampleData)
    expect(svg).toContain(BEAR_COLOR)
  })
  it('157. generateKChartSvg: 含量能柱', () => {
    const svg = generateKChartSvg(sampleData)
    // 量能柱有 fill-opacity
    expect(svg).toContain('fill-opacity')
  })
  it('158. extractDataFromSvgString: 从 SVG 字符串提取数据', () => {
    const svg = generateKChartSvg(sampleData)
    const extracted = extractDataFromSvgString(svg)
    expect(extracted).not.toBeNull()
    expect(extracted!.klines.length).toBe(5)
    expect(extracted!.theme).toBe('dark')
  })
  it('159. extractDataFromSvgString: 无 data-kchart 返回 null', () => {
    const svg = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
    expect(extractDataFromSvgString(svg)).toBeNull()
  })
  it('160. extractDataFromSvgString: 往返一致', () => {
    const svg = generateKChartSvg(sampleData)
    const extracted = extractDataFromSvgString(svg)
    expect(extracted).not.toBeNull()
    // 再生成一次
    const svg2 = generateKChartSvg(extracted!)
    const extracted2 = extractDataFromSvgString(svg2)
    expect(extracted2).not.toBeNull()
    expect(extracted2!.klines.length).toBe(extracted!.klines.length)
  })
})

describe('边界情况与集成', () => {
  it('161. emptyKChartData: 返回空结构', () => {
    const data = emptyKChartData('dark')
    expect(data.klines).toEqual([])
    expect(data.trendLines).toEqual([])
    expect(data.horizontalLines).toEqual([])
    expect(data.labels).toEqual([])
    expect(data.theme).toBe('dark')
  })
  it('162. emptyKChartData: light 主题', () => {
    expect(emptyKChartData('light').theme).toBe('light')
  })
  it('163. sortKlines: 倒序输入变正序', () => {
    const klines = [k(2, 10, 11, 12, 9), k(0, 10, 11, 12, 9), k(1, 10, 11, 12, 9)]
    const sorted = sortKlines(klines)
    expect(sorted.map((kl) => kl.idx)).toEqual([0, 1, 2])
  })
  it('164. sortKlines: 不修改原数组', () => {
    const klines = [k(2, 10, 11, 12, 9), k(0, 10, 11, 12, 9)]
    sortKlines(klines)
    expect(klines[0].idx).toBe(2)
  })
  it('165. findNearestKline: 超出阈值返回 null', () => {
    const klines = [k(0, 10, 11, 12, 9), k(10, 11, 12, 13, 10)]
    expect(findNearestKline(klines, 5, 0.5)).toBeNull()
  })
  it('166. findNearestKline: 空数组返回 null', () => {
    expect(findNearestKline([], 0)).toBeNull()
  })
  it('167. createKLine: 平盘 K 线 high=close+offset', () => {
    const kl = createKLine(0, 100, 100)
    expect(kl.high).toBeGreaterThan(kl.close)
    expect(kl.low).toBeLessThan(kl.close)
  })
  it('168. dedupKlines: 空数组', () => {
    expect(dedupKlines([])).toEqual([])
  })
  it('169. removeKline: 空数组', () => {
    expect(removeKline([], 0)).toEqual([])
  })
  it('170. parseKChartFromSvg: 合法 SVG 元素返回数据', () => {
    const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    const data: KChartData = {
      klines: [k(0, 10, 11, 12, 9)],
      trendLines: [],
      horizontalLines: [],
      labels: [],
      theme: 'dark',
    }
    svgEl.setAttribute('data-kchart', JSON.stringify(data))
    const parsed = parseKChartFromSvg(svgEl)
    expect(parsed).not.toBeNull()
    expect(parsed!.klines.length).toBe(1)
  })
  it('171. parseKChartFromSvg: 非法 JSON 返回 null', () => {
    const svgEl = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    svgEl.setAttribute('data-kchart', '{invalid json}')
    expect(parseKChartFromSvg(svgEl)).toBeNull()
  })
  it('172. generateKChartSvg: 只含趋势线无 K 线', () => {
    const data: KChartData = {
      klines: [],
      trendLines: [{ x1: 0, y1: 10, x2: 5, y2: 15 }],
      horizontalLines: [],
      labels: [],
      theme: 'dark',
    }
    const svg = generateKChartSvg(data)
    expect(svg.startsWith('<svg')).toBe(true)
  })
  it('173. generateKChartSvg: 只含水平线', () => {
    const data: KChartData = {
      klines: [],
      trendLines: [],
      horizontalLines: [{ price: 100 }],
      labels: [],
      theme: 'light',
    }
    const svg = generateKChartSvg(data)
    expect(svg).toContain(LIGHT_BG)
  })
  it('174. generateKChartSvg: 只含文字标注', () => {
    const data: KChartData = {
      klines: [],
      trendLines: [],
      horizontalLines: [],
      labels: [{ idx: 0, price: 10, text: '注意' }],
      theme: 'dark',
    }
    const svg = generateKChartSvg(data)
    expect(svg).toContain('注意')
  })
  it('175. generateKChartSvg: 大量 K 线 (60根)', () => {
    const klines: KLine[] = Array.from({ length: 60 }, (_, i) => k(i, 10, 10 + i, 12, 9))
    const svg = generateKChartSvg({ ...emptyKChartData('dark'), klines })
    expect(svg.startsWith('<svg')).toBe(true)
    // 确认有 60 根 K 线 (60 个 rect 主体 + 量能柱)
    const rectCount = (svg.match(/<rect/g) || []).length
    expect(rectCount).toBeGreaterThan(60)
  })
  it('176. generateKChartSvg: 1 根 K 线不崩溃', () => {
    const data: KChartData = {
      klines: [k(0, 10, 11, 12, 9)],
      trendLines: [],
      horizontalLines: [],
      labels: [],
      theme: 'dark',
    }
    const svg = generateKChartSvg(data)
    expect(svg.startsWith('<svg')).toBe(true)
  })
  it('177. extractDataFromSvgString: 含转义字符的 JSON', () => {
    const data: KChartData = {
      klines: [],
      trendLines: [],
      horizontalLines: [],
      labels: [{ idx: 0, price: 10, text: '<测试>"引号"' }],
      theme: 'dark',
    }
    const svg = generateKChartSvg(data)
    const extracted = extractDataFromSvgString(svg)
    expect(extracted).not.toBeNull()
    expect(extracted!.labels[0].text).toBe('<测试>"引号"')
  })
  it('178. idxToX: count=2 两端值', () => {
    expect(idxToX(0, 2)).toBe(10)
    expect(idxToX(1, 2)).toBe(CANVAS_WIDTH - 10)
  })
  it('179. priceToY: 超出范围的值仍可计算', () => {
    const area = klineArea()
    const y = priceToY(150, 0, 100, area.top, area.height)
    // 价格 150 > max 100, y 应在 area.top 之上
    expect(y).toBeLessThan(area.top)
  })
  it('180. klineToSvg: 高度至少为 1px', () => {
    // open === close 时 bodyHeight = max(0, 1) = 1
    const svg = klineToSvg(k(0, 10, 10, 12, 9), 0, 20, 10)
    expect(svg).toContain('height="1')
  })
})

describe('klineAreaRatio 动态区域比例', () => {
  it('181. resolveRatio: undefined 返回默认值', () => {
    expect(resolveRatio(undefined)).toBe(KLINE_AREA_RATIO)
  })
  it('182. resolveRatio: 正常值原样返回', () => {
    expect(resolveRatio(0.5)).toBe(0.5)
  })
  it('183. resolveRatio: 低于 0.3 钳制为 0.3', () => {
    expect(resolveRatio(0.1)).toBe(0.3)
  })
  it('184. resolveRatio: 高于 0.85 钳制为 0.85', () => {
    expect(resolveRatio(0.95)).toBe(0.85)
  })
  it('185. resolveRatio: NaN 返回默认值', () => {
    expect(resolveRatio(NaN)).toBe(KLINE_AREA_RATIO)
  })
  it('186. klineArea: 传入 ratio 改变高度', () => {
    const default_ = klineArea()
    const custom = klineArea(0.5)
    expect(custom.height).toBeLessThan(default_.height)
  })
  it('187. volumeArea: 传入 ratio 与 klineArea 互补', () => {
    const r = 0.6
    const k = klineArea(r)
    const v = volumeArea(r)
    const total = (k.height + 10 + v.height)
    const expected = CANVAS_HEIGHT - 40
    expect(approx(total, expected, 0.01)).toBe(true)
  })
  it('188. klineArea + volumeArea 不重叠 (自定义比例)', () => {
    const k = klineArea(0.5)
    const v = volumeArea(0.5)
    expect(v.top).toBeGreaterThanOrEqual(k.bottom)
  })
  it('189. isValidKChartData: 合法 klineAreaRatio', () => {
    const data: KChartData = {
      klines: [], trendLines: [], horizontalLines: [], labels: [],
      theme: 'dark', klineAreaRatio: 0.6,
    }
    expect(isValidKChartData(data)).toBe(true)
  })
  it('190. isValidKChartData: klineAreaRatio 超出范围不合法', () => {
    const data = {
      klines: [], trendLines: [], horizontalLines: [], labels: [],
      theme: 'dark', klineAreaRatio: 0.95,
    }
    expect(isValidKChartData(data)).toBe(false)
  })
  it('191. isValidKChartData: klineAreaRatio 非法类型不合法', () => {
    const data = {
      klines: [], trendLines: [], horizontalLines: [], labels: [],
      theme: 'dark', klineAreaRatio: 'abc',
    }
    expect(isValidKChartData(data)).toBe(false)
  })
  it('192. emptyKChartData: 包含默认 klineAreaRatio', () => {
    expect(emptyKChartData('dark').klineAreaRatio).toBe(KLINE_AREA_RATIO)
  })
  it('193. generateKChartSvg: klineAreaRatio 往返一致', () => {
    const data: KChartData = {
      klines: [k(0, 10, 11, 12, 9), k(1, 11, 12, 13, 10)],
      trendLines: [], horizontalLines: [], labels: [],
      theme: 'dark', klineAreaRatio: 0.55,
    }
    const svg = generateKChartSvg(data)
    const extracted = extractDataFromSvgString(svg)
    expect(extracted).not.toBeNull()
    expect(extracted!.klineAreaRatio).toBe(0.55)
  })
  it('194. generateKChartSvg: 含 Y 轴价格标签', () => {
    const svg = generateKChartSvg({
      klines: [k(0, 10, 11, 12, 9), k(1, 11, 12, 13, 10)],
      trendLines: [], horizontalLines: [], labels: [], theme: 'dark',
    })
    // formatPrice(10) = "10.00" 或类似
    expect(svg).toContain('font-size="10"')
  })
  it('195. generateKChartSvg: 含 Vol 标签', () => {
    const svg = generateKChartSvg({
      klines: [k(0, 10, 11, 12, 9)], trendLines: [], horizontalLines: [], labels: [], theme: 'dark',
    })
    expect(svg).toContain('Vol')
  })
  it('196. formatPrice: 大数保留 0 位小数', () => {
    expect(formatPrice(1234.56)).toBe('1235')
  })
  it('197. formatPrice: 两位小数 (10~100)', () => {
    expect(formatPrice(25.5)).toBe('25.50')
  })
  it('198. klineToSvg: 传入 ratio 参数生效', () => {
    const svgDefault = klineToSvg(k(0, 10, 11, 12, 9), 0, 20, 5)
    const svgCustom = klineToSvg(k(0, 10, 11, 12, 9), 0, 20, 5, 0.5)
    // 不同 ratio 会导致 y 坐标不同
    expect(svgDefault).not.toEqual(svgCustom)
  })
  it('199. volumeToSvg: 传入 ratio 参数生效', () => {
    const klines = [k(0, 10, 11, 12, 9)]
    const vols = calcVolumes(klines)
    const svgDefault = volumeToSvg(vols, klines, 1)
    const svgCustom = volumeToSvg(vols, klines, 1, 0.5)
    expect(svgDefault).not.toEqual(svgCustom)
  })
  it('200. generateKChartSvg: 无 klineAreaRatio 使用默认值', () => {
    const data = {
      klines: [k(0, 10, 11, 12, 9)], trendLines: [], horizontalLines: [], labels: [], theme: 'dark',
    } as KChartData
    const svg = generateKChartSvg(data)
    const extracted = extractDataFromSvgString(svg)
    expect(extracted).not.toBeNull()
    // 生成时不会添加 klineAreaRatio (保持原数据)
    expect(extracted!.klineAreaRatio).toBeUndefined()
  })
})
