export interface SummaryItem {
  key: string
  value: string
}

export interface EquityPoint {
  date: string
  equity: number
  cash: number
  positions: number
  exposure: number
  drawdown: number
  benchmark: number
}

export interface Trade {
  symbol: string
  name: string
  entryDate: string
  entryPrice: number
  exitDate: string
  exitPrice: number
  pnlPct: number
  duration: number
  exitReason: string
  shares: number
  entryValue: number
  exitValue: number
  pnlAmount: number
  entryScore?: number
}

export interface PerSymbolStat {
  symbol: string
  nTrades: number
  totalReturn: number
  winRate: number
  best: number
  worst: number
}

export interface SelectionCandidate {
  symbol: string
  name: string
  score: number | null
  rank: number | null
  status: 'selected' | 'rejected'
  reason: string | null
}

export interface SelectionLogEntry {
  date: string
  signal_count: number
  slots_available: number
  candidates: SelectionCandidate[]
}

export interface BacktestData {
  summary: Record<string, string>
  equityCurve: EquityPoint[]
  trades: Trade[]
  perSymbol: PerSymbolStat[]
  hasScore: boolean
  selectionLog: SelectionLogEntry[]
}
