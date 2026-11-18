/**
 * 统计卡片 — 对齐 HTML 的 .stats 5列 grid 布局
 */
interface Props {
  stats: Record<string, any>
  strategyInfo: {
    id: string
    name: string
    description: string
    entry_signals: string[]
    exit_signals: string[]
    stop_loss: number | null
    max_hold_days: number | null
  }
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}

export function PanYangStats({ stats, strategyInfo }: Props) {
  const nTrades = stats.n_trades ?? stats.total_trades ?? 0
  const winRate = stats.win_rate
  const totalReturn = stats.total_return ?? stats.total
  const cagr = stats.cagr ?? stats.annual_return
  const mdd = stats.max_drawdown ?? stats.mdd
  const avgRet = stats.avg_return ?? stats.avg_ret
  const plRatio = stats.profit_loss_ratio ?? stats.pl_ratio
  const calmar = stats.calmar
  const benchTotal = stats.bench_total ?? stats.benchmark_return

  const cards = [
    { k: '交易笔数', v: String(nTrades), n: `平均收益 ${fmtPct(avgRet)}` },
    { k: '胜率', v: fmtPct(winRate), n: `盈亏比 ${fmtNum(plRatio)}` },
    { k: '累计收益', v: fmtPct(totalReturn), n: `基准 ${fmtPct(benchTotal)}` },
    { k: '年化收益', v: fmtPct(cagr), n: `Calmar ${fmtNum(calmar)}` },
    { k: '最大回撤', v: fmtPct(mdd), n: `最大持仓 ${strategyInfo.max_hold_days ?? '—'} 天` },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2.5">
      {cards.map((c) => (
        <div
          key={c.k}
          className="bg-elevated border border-border rounded-btn px-3 py-2.5"
        >
          <div className="text-[11.5px] text-muted mb-0.5">{c.k}</div>
          <div className="text-lg font-semibold tabular-nums">{c.v}</div>
          <div className="text-[11px] text-muted mt-0.5">{c.n}</div>
        </div>
      ))}
    </div>
  )
}
