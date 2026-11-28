"""回测引擎 — 大盘信号 × 目标标的 (设计 §8 裁定口径)。

执行铁律:
    - T 日大盘收盘出信号 → T+1 目标标的开盘成交;
    - 停牌/无K线自动顺延至下一交易日开盘;
    - 一字板不追: open==high (一字涨停) 不追买顺延, open==low (一字跌停) 不杀卖顺延;
    - 成交价口径 (逐笔自洽, 可手工核算):
        入场成交价 = 开盘价 × (1 + slippage)
        出场成交价 = 原始成交价 × (1 − slippage)   (止盈/止损触发价同样过滑点)
        pnl = shares×(出场成交价 − 入场成交价) − 双边佣金(含印花税)
    - 只做多; 持仓中不重复开仓; 初始资金默认 10 万; 仓位比例可配。
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from datetime import date

import polars as pl

from .stats.base import Signal


@dataclass(frozen=True)
class ExitSpec:
    """出场规则 (三参数化, 设计 §8 裁定 2)。"""

    mode: str = "time"  # "time" | "reverse" | "profit_stop"
    hold_days: int = 5             # mode=time 的持有交易日数 / profit_stop 的兜底时限
    take_profit_pct: float = 5.0   # mode=profit_stop 止盈 %
    stop_loss_pct: float = 3.0     # mode=profit_stop 止损 %


@dataclass(frozen=True)
class CostSpec:
    commission_rate: float = 0.00025  # 佣金 万2.5 双边
    stamp_tax_rate: float = 0.0       # ETF 免印花税 (股票回测时可改)
    slippage_rate: float = 0.001      # 滑点 0.1% (不利方向)


@dataclass
class Trade:
    entry_signal_dt: date
    entry_dt: date          # 实际成交日 (可能因停牌/一字板顺延)
    entry_price: float      # 含滑点成交价
    exit_dt: date | None
    exit_price: float | None  # 含滑点成交价
    exit_reason: str = ""   # time / reverse / take_profit / stop_loss / end_of_data
    shares: float = 0.0
    pnl: float = 0.0
    return_pct: float = 0.0   # 单笔收益率 = pnl / 入场总成本 (含佣金)


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    initial_capital: float = 100000.0
    final_equity: float = 0.0
    total_return_pct: float = 0.0
    annual_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    avg_hold_days: float = 0.0
    equity_curve: list[tuple[date, float]] = field(default_factory=list)


def _next_tradeable_idx(after: date, dts: list[date]) -> int | None:
    """首个 > after 的目标K线下标 (二分)。"""
    lo = bisect.bisect_right(dts, after)
    return lo if lo < len(dts) else None


def _try_buy(start: int, dts, opens, highs) -> tuple[int, float] | None:
    """从 start 起逐日尝试买入; 一字涨停 (open==high) 不追, 顺延。"""
    i = start
    while i < len(dts):
        if opens[i] < highs[i]:
            return i, opens[i]
        i += 1
    return None


def _try_sell(start: int, dts, opens, lows) -> tuple[int, float] | None:
    """从 start 起逐日尝试卖出; 一字跌停 (open==low) 顺延。"""
    i = start
    while i < len(dts):
        if opens[i] > lows[i]:
            return i, opens[i]
        i += 1
    return None


def run_backtest(
    target: pl.DataFrame,
    signals: list[Signal],
    exit_spec: ExitSpec | None = None,
    cost: CostSpec | None = None,
    initial_capital: float = 100000.0,
    position_ratio: float = 1.0,
) -> BacktestResult:
    """单参数组回测。target: 目标标的日K (date/open/high/low/close 升序)。"""
    exit_spec = exit_spec or ExitSpec()
    cost = cost or CostSpec()
    result = BacktestResult(initial_capital=initial_capital)
    if target.is_empty():
        result.final_equity = initial_capital
        result.equity_curve = []
        return result

    dts = target["date"].to_list()
    opens = target["open"].to_list()
    highs = target["high"].to_list()
    lows = target["low"].to_list()

    buys = [s for s in signals if s.direction > 0 and _next_tradeable_idx(s.dt, dts) is not None]
    sell_dts = [s.dt for s in signals if s.direction < 0]

    slip = cost.slippage_rate
    fee_rate = cost.commission_rate + cost.stamp_tax_rate
    equity = initial_capital
    trades: list[Trade] = []
    busy_until = -1  # 上一笔出场K线下标, 持仓中不重复开仓

    for sig in buys:
        start_idx = _next_tradeable_idx(sig.dt, dts)
        if start_idx is None:
            continue
        filled = _try_buy(max(start_idx, busy_until + 1), dts, opens, highs)
        if filled is None:
            break  # 尾部再无可买日, 后续信号同样买不进
        e_idx, raw_entry = filled
        entry_exec = raw_entry * (1.0 + slip)
        n_shares = math.floor(equity * position_ratio / entry_exec)
        if n_shares <= 0:
            busy_until = e_idx  # 钱不够也占用, 防止同日多信号刷单
            continue
        entry_cost = n_shares * entry_exec
        fee_in = entry_cost * fee_rate

        # ---- 逐笔确定出场 -------------------------------------------------
        exit_idx = len(dts) - 1
        exit_exec = opens[-1] * (1.0 - slip)
        exit_reason = "end_of_data"

        if exit_spec.mode == "time":
            sold = _try_sell(e_idx + exit_spec.hold_days, dts, opens, lows)
            if sold:
                exit_idx, raw_exit = sold
                exit_exec = raw_exit * (1.0 - slip)
                exit_reason = "time"
        elif exit_spec.mode == "reverse":
            k = bisect.bisect_right(sell_dts, sig.dt)
            if k < len(sell_dts):
                cand = _next_tradeable_idx(sell_dts[k], dts)
                if cand is not None and cand > e_idx:
                    sold = _try_sell(cand, dts, opens, lows)
                    if sold:
                        exit_idx, raw_exit = sold
                        exit_exec = raw_exit * (1.0 - slip)
                        exit_reason = "reverse"
        elif exit_spec.mode == "profit_stop":
            tp = entry_exec * (1.0 + exit_spec.take_profit_pct / 100.0)
            sl = entry_exec * (1.0 - exit_spec.stop_loss_pct / 100.0)
            last_j = min(e_idx + exit_spec.hold_days, len(dts) - 1)
            hit = False
            j = e_idx  # 入场当日开盘建仓后即参与当日盘中判定
            while j <= last_j and not hit:
                if opens[j] <= sl:      # 跳空低开穿越止损: 以开盘价成交
                    exit_idx, exit_exec, exit_reason, hit = j, opens[j] * (1.0 - slip), "stop_loss", True
                elif opens[j] >= tp:    # 跳空高开穿越止盈: 以开盘价成交
                    exit_idx, exit_exec, exit_reason, hit = j, opens[j] * (1.0 - slip), "take_profit", True
                elif lows[j] <= sl:     # 同日双触按止损优先 (保守)
                    exit_idx, exit_exec, exit_reason, hit = j, sl * (1.0 - slip), "stop_loss", True
                elif highs[j] >= tp:
                    exit_idx, exit_exec, exit_reason, hit = j, tp * (1.0 - slip), "take_profit", True
                j += 1
            if not hit:
                sold = _try_sell(e_idx + exit_spec.hold_days, dts, opens, lows)
                if sold:
                    exit_idx, raw_exit = sold
                    exit_exec = raw_exit * (1.0 - slip)
                    exit_reason = "time"
        else:
            raise ValueError(f"unknown exit mode: {exit_spec.mode!r}")

        proceeds = n_shares * exit_exec
        fee_out = proceeds * fee_rate
        pnl = proceeds - entry_cost - fee_in - fee_out
        equity += pnl
        trades.append(
            Trade(
                entry_signal_dt=sig.dt,
                entry_dt=dts[e_idx],
                entry_price=round(entry_exec, 4),
                exit_dt=dts[exit_idx],
                exit_price=round(exit_exec, 4),
                exit_reason=exit_reason,
                shares=float(n_shares),
                pnl=round(pnl, 2),
                return_pct=round(pnl / (entry_cost + fee_in) * 100.0, 4),
            )
        )
        busy_until = exit_idx

    _fill_metrics(result, trades, dts)
    return result


def _fill_metrics(result: BacktestResult, trades: list[Trade], dts: list[date]) -> None:
    result.trades = trades
    if not trades:
        result.final_equity = result.initial_capital
        result.equity_curve = [(dts[0], result.initial_capital)]
        return
    result.final_equity = round(result.initial_capital + sum(t.pnl for t in trades), 2)
    result.total_return_pct = (result.final_equity / result.initial_capital - 1.0) * 100.0
    days = (trades[-1].exit_dt - dts[0]).days if trades[-1].exit_dt else (dts[-1] - dts[0]).days
    if days > 0:
        years = days / 365.0
        result.annual_return_pct = (
            ((result.final_equity / result.initial_capital) ** (1.0 / years) - 1.0) * 100.0
        )
    # 资金曲线 (逐笔口径) + 最大回撤
    eq = result.initial_capital
    curve = [(dts[0], round(eq, 2))]
    peak = eq
    mdd = 0.0
    for t in trades:
        eq += t.pnl
        curve.append((t.exit_dt, round(eq, 2)))
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak if peak > 0 else 0.0)
    result.equity_curve = curve
    result.max_drawdown_pct = mdd * 100.0
    # 胜率 / 盈亏比 / 平均持仓
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    result.win_rate = len(wins) / len(trades) * 100.0
    aw = sum(t.pnl for t in wins) / len(wins) if wins else 0.0
    al = abs(sum(t.pnl for t in losses) / len(losses)) if losses else 0.0
    result.profit_loss_ratio = (aw / al) if al > 0 else (float("inf") if aw > 0 else 0.0)
    result.avg_hold_days = (
        sum((t.exit_dt - t.entry_dt).days for t in trades if t.exit_dt) / len(trades)
    )
    # 夏普 (按笔年化: 年化收益 / 年化波动)
    rets = [t.return_pct / 100.0 for t in trades]
    if len(rets) > 1 and days > 0:
        years = days / 365.0
        n = len(rets)
        mean = sum(rets) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1))
        if sd > 0:
            per_year = n / years
            result.sharpe = mean / sd * math.sqrt(per_year)
