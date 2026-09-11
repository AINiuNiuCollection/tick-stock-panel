import type { StrategyBacktestResult } from '@/lib/api'

/**
 * Shared store for passing backtest result data between pages.
 * Uses sessionStorage for persistence so the data survives SPA navigation
 * (sidebar nav, route changes) without being lost to code-splitting.
 *
 * Flow:
 *   1. StrategyBacktest page auto-saves result via setSharedResult() when backtest completes
 *   2. User navigates to Analysis page (via sidebar or "分析" button)
 *   3. Analysis page reads via getSharedResult() on mount
 *
 * sessionStorage (~5MB) is preferred over localStorage because backtest results
 * are ephemeral — no need to persist across browser restarts.
 * If data is too large for sessionStorage, trades are truncated to the most recent 2000.
 */

const STORAGE_KEY = '__backtest_shared_result__'

export function setSharedResult(result: StrategyBacktestResult | null) {
  if (result) {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(result))
    } catch (e) {
      // Data too large — try truncating trades to reduce size
      try {
        const trimmed: StrategyBacktestResult = {
          ...result,
          trades: (result.trades ?? []).slice(-2000),
        }
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed))
        console.warn('[sharedData] Truncated trades to 2000 to fit sessionStorage')
      } catch (e2) {
        console.warn('[sharedData] Failed to persist even after truncation:', e2)
      }
    }
  } else {
    sessionStorage.removeItem(STORAGE_KEY)
  }
}

export function getSharedResult(): StrategyBacktestResult | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as StrategyBacktestResult
  } catch {
    return null
  }
}

export function clearSharedResult() {
  sessionStorage.removeItem(STORAGE_KEY)
}
