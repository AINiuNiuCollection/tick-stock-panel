import type { StrategyBacktestResult } from '@/lib/api'
import type { BacktestData, EquityPoint, Trade, PerSymbolStat, SelectionLogEntry } from './types'

/**
 * Convert StrategyBacktestResult (API snake_case) to BacktestData (analysis camelCase).
 * This enables the Analysis page to work directly with live backtest results
 * without requiring a CSV export/upload round-trip.
 */
export function convertBacktestResult(result: StrategyBacktestResult): BacktestData {
  const stats = result.stats ?? {}

  // ── 基准收益: 从 benchmark_curve 首尾值计算 (与 StrategyBacktest.tsx 一致) ──
  const benchValues = (result.benchmark_curve ?? [])
    .map(r => Number(r.close ?? r.value))
    .filter(v => Number.isFinite(v) && v > 0)
  const benchmarkReturn = benchValues.length >= 2
    ? benchValues[benchValues.length - 1] / benchValues[0] - 1
    : null
  const totalReturn = stats.total_return != null ? Number(stats.total_return) : null
  const excessReturn = totalReturn != null && benchmarkReturn != null
    ? totalReturn - benchmarkReturn
    : null

  // Build summary from stats
  const summary: Record<string, string> = {
    '策略名称': result.strategy_info?.name ?? result.strategy_info?.id ?? '策略',
    '回测区间': `${result.config?.start ?? ''} ~ ${result.config?.end ?? ''}`,
    '净值曲线天数': String(result.equity_curve?.length ?? 0),
    '完成交易数': String(result.trades?.length ?? 0),
    '总收益': stats.total_return != null ? (stats.total_return * 100).toFixed(2) + '%' : '',
    '年化收益': stats.annual_return != null ? (stats.annual_return * 100).toFixed(2) + '%' : '',
    '最大回撤': stats.max_drawdown != null ? (stats.max_drawdown * 100).toFixed(2) + '%' : '',
    '夏普比率': stats.sharpe != null ? String(stats.sharpe) : '',
    '索提诺': stats.sortino != null ? Number(stats.sortino).toFixed(2) : '',
    '胜率': stats.win_rate != null ? (stats.win_rate * 100).toFixed(1) + '%' : '',
    '盈亏比': stats.profit_factor != null ? String(stats.profit_factor) : '',
    '同期基准': benchmarkReturn != null ? (benchmarkReturn * 100).toFixed(2) + '%' : '',
    '超额收益': excessReturn != null ? (excessReturn * 100).toFixed(2) + '%' : '',
    '最终权益': stats.final_equity != null ? Number(stats.final_equity).toLocaleString() : '',
    '起始资金': stats.initial_capital != null ? Number(stats.initial_capital).toLocaleString() : '',
  }

  // Build equity curve, merging drawdown and benchmark from separate curves
  const ddMap = new Map((result.drawdown_curve ?? []).map(r => [r.date, r.value]))
  const benchMap = new Map((result.benchmark_curve ?? []).map(r => [r.date, r.close ?? r.value]))

  const equityCurve: EquityPoint[] = (result.equity_curve ?? []).map(r => ({
    date: r.date,
    equity: r.value,
    cash: r.cash ?? 0,
    positions: r.positions ?? 0,
    exposure: r.exposure ?? 0,
    drawdown: ddMap.get(r.date) ?? 0,
    benchmark: benchMap.get(r.date) ?? 0,
  }))

  // Build trades
  let hasScore = false
  const trades: Trade[] = (result.trades ?? []).map(t => {
    if (t.entry_score != null && !isNaN(t.entry_score)) hasScore = true
    return {
      symbol: t.symbol,
      name: t.name ?? '',
      entryDate: t.entry_date,
      entryPrice: t.entry_price,
      exitDate: t.exit_date,
      exitPrice: t.exit_price,
      pnlPct: t.pnl_pct,
      duration: t.duration,
      exitReason: t.exit_reason ?? '',
      shares: t.shares ?? 0,
      entryValue: t.entry_value ?? 0,
      exitValue: t.exit_value ?? 0,
      pnlAmount: t.pnl_amount ?? 0,
      entryScore: t.entry_score ?? undefined,
    }
  })

  // Build per-symbol stats
  const perSymbol: PerSymbolStat[] = (result.per_symbol_stats ?? []).map(p => ({
    symbol: p.symbol,
    nTrades: p.n_trades,
    totalReturn: p.total_return,
    winRate: p.win_rate,
    best: p.best,
    worst: p.worst,
  }))

  // ── 选股过程日志 (从 stats.selection_log 提取) ──
  const selectionLog: SelectionLogEntry[] = (stats.selection_log as SelectionLogEntry[]) ?? []

  return { summary, equityCurve, trades, perSymbol, hasScore, selectionLog }
}
