import type { BacktestData, EquityPoint, Trade, PerSymbolStat } from './types'

function num(v: string | undefined): number {
  if (!v) return 0
  const n = parseFloat(v.replace(/,/g, ''))
  return isNaN(n) ? 0 : n
}

export function parseBacktestCsv(text: string): BacktestData {
  const lines = text.split(/\r?\n/)
  let i = 0
  const summary: Record<string, string> = {}
  let equityCurve: EquityPoint[] = []
  let trades: Trade[] = []
  let perSymbol: PerSymbolStat[] = []
  let hasScore = false

  while (i < lines.length) {
    const line = lines[i].trim()
    if (line === '# 概要') {
      i++
      if (i < lines.length && lines[i].includes('指标')) i++ // header
      while (i < lines.length && lines[i].trim() && !lines[i].startsWith('#')) {
        const parts = lines[i].split(',')
        if (parts.length >= 2) summary[parts[0].trim()] = parts[1].trim()
        i++
      }
    } else if (line === '# 净值曲线') {
      i++
      if (i < lines.length && lines[i].includes('date')) i++ // header
      const rows: EquityPoint[] = []
      while (i < lines.length && lines[i].trim() && !lines[i].startsWith('#')) {
        const p = lines[i].split(',')
        if (p.length >= 7) {
          rows.push({
            date: p[0].trim(),
            equity: num(p[1]),
            cash: num(p[2]),
            positions: parseInt(p[3]) || 0,
            exposure: num(p[4]),
            drawdown: num(p[5]),
            benchmark: num(p[6]),
          })
        }
        i++
      }
      equityCurve = rows
    } else if (line === '# 交易明细') {
      i++
      const header = lines[i] || ''
      if (header.includes('entry_score')) {
        hasScore = true
        i++
      } else if (header.includes('symbol')) {
        i++
      }
      const rows: Trade[] = []
      while (i < lines.length && lines[i].trim() && !lines[i].startsWith('#')) {
        const p = lines[i].split(',')
        if (p.length >= 13) {
          rows.push({
            symbol: p[0].trim(),
            name: p[1].trim(),
            entryDate: p[2].trim(),
            entryPrice: num(p[3]),
            exitDate: p[4].trim(),
            exitPrice: num(p[5]),
            pnlPct: num(p[6]),
            duration: parseInt(p[7]) || 0,
            exitReason: p[8].trim(),
            shares: num(p[9]),
            entryValue: num(p[10]),
            exitValue: num(p[11]),
            pnlAmount: num(p[12]),
            entryScore: p.length >= 14 ? num(p[13]) : undefined,
          })
        }
        i++
      }
      trades = rows
    } else if (line === '# 分标的统计') {
      i++
      if (i < lines.length && lines[i].includes('symbol')) i++ // header
      const rows: PerSymbolStat[] = []
      while (i < lines.length && lines[i].trim() && !lines[i].startsWith('#')) {
        const p = lines[i].split(',')
        if (p.length >= 6) {
          rows.push({
            symbol: p[0].trim(),
            nTrades: parseInt(p[1]) || 0,
            totalReturn: num(p[2]),
            winRate: num(p[3]),
            best: num(p[4]),
            worst: num(p[5]),
          })
        }
        i++
      }
      perSymbol = rows
    } else {
      i++
    }
  }

  return { summary, equityCurve, trades, perSymbol, hasScore }
}
