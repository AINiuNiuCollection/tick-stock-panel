"""参数网格寻优 — 全枚举 + train/validation 过拟合防护 (设计 §8.1)。

算法: 信号序列按出场参数共享 — 每组入场参数只跑一次 to_signals,
出场参数网格在共享信号上批量回测; 离散小空间网格全枚举即全局最优,
无局部最优陷阱, 结果可完整呈现复核。

分段: 按目标标的日历时序切 70%/30% 得 split 日期;
train 段 = 信号日 < split (交易可自然延续过边界, 归属按入场段);
validation 段 = 信号日 ≥ split。默认按 validation 收益排序 (先可信后好看)。
"""
from __future__ import annotations

import itertools
from datetime import date
from typing import Any

import polars as pl

from .backtest import BacktestResult, CostSpec, ExitSpec, run_backtest
from .stats.base import Signal
from .stats.registry import REGISTRY

_DEFAULT_HOLDS = (1, 3, 5, 10, 20)
_DEFAULT_MODES = ("time", "reverse", "profit_stop")
_DEFAULT_TPS = (3.0, 5.0, 8.0)
_DEFAULT_SLS = (2.0, 3.0, 5.0)


def default_exit_grid() -> dict[str, list[Any]]:
    """出场参数默认网格 (设计 §8.1: 持有 N × 出场模式 × 止盈止损档)。"""
    return {
        "mode": list(_DEFAULT_MODES),
        "hold_days": list(_DEFAULT_HOLDS),
        "take_profit_pct": list(_DEFAULT_TPS),
        "stop_loss_pct": list(_DEFAULT_SLS),
    }


def _build_exit_specs(exit_grid: dict[str, list[Any]] | None) -> list[ExitSpec]:
    """展开出场参数网格 → ExitSpec 列表。

    非本模式参数不参与笛卡尔积 (mode=time 不枚举止盈止损),
    控制组合数并让每组 ExitSpec 语义干净。
    """
    grid = exit_grid or default_exit_grid()
    modes: list[str] = list(grid.get("mode", _DEFAULT_MODES))
    holds: list[int] = [int(v) for v in grid.get("hold_days", _DEFAULT_HOLDS)]
    tps: list[float] = [float(v) for v in grid.get("take_profit_pct", _DEFAULT_TPS)]
    sls: list[float] = [float(v) for v in grid.get("stop_loss_pct", _DEFAULT_SLS)]
    specs: list[ExitSpec] = []
    for mode in modes:
        if mode == "time":
            specs.extend(ExitSpec(mode="time", hold_days=h) for h in holds)
        elif mode == "reverse":
            # 反向信号出场不吃时限/止盈损, 单 spec (hold_days 仅作占位)
            specs.append(ExitSpec(mode="reverse", hold_days=holds[0]))
        elif mode == "profit_stop":
            specs.extend(
                ExitSpec(mode="profit_stop", hold_days=h, take_profit_pct=tp, stop_loss_pct=sl)
                for h, tp, sl in itertools.product(holds, tps, sls)
            )
        else:
            raise ValueError(f"unknown exit mode in grid: {mode!r}")
    return specs


def optimize_grid(
    index_df: pl.DataFrame,
    target: pl.DataFrame,
    module_id: str,
    entry_grid: dict[str, list[Any]],
    exit_grid: dict[str, list[Any]] | None = None,
    cost: CostSpec | None = None,
    initial_capital: float = 100000.0,
    position_ratio: float = 1.0,
    train_ratio: float = 0.7,
    sort_by: str = "validation",
    signal_from: date | None = None,
) -> dict[str, Any]:
    """入场×出场参数网格全枚举寻优。

    返回: {
        split_date, rows: [
            {entry_params, exit: {mode,...}, full/train/validation 段指标, overfit_flag}
        ]
    }
    overfit_flag: train 段收益 > 0 且 train 收益排名前 25% 但 validation 收益 ≤ 0
                  → 样本外崩塌, 前端标红 (设计 §8 裁定 2)。
    """
    if module_id not in REGISTRY:
        raise ValueError(f"unknown stats module: {module_id!r}")
    module = REGISTRY[module_id]
    cost = cost or CostSpec()
    split = _split_date(target, train_ratio)

    # 入场参数网格展开 (键排序保证枚举稳定)
    names = sorted(entry_grid)
    combos = [dict(zip(names, vals)) for vals in itertools.product(*(entry_grid[n] for n in names))]

    exit_specs = _build_exit_specs(exit_grid)
    rows: list[dict[str, Any]] = []
    for entry_params in combos:
        signals = module.to_signals(index_df, entry_params)
        if signal_from is not None:
            # 暖机段 (指标尚未收敛) 产生的信号不参与回测, 只作为窗口前垫舱
            signals = [s for s in signals if s.dt >= signal_from]
        train_sigs = [s for s in signals if s.dt < split]
        valid_sigs = [s for s in signals if s.dt >= split]
        for spec in exit_specs:
            full = run_backtest(
                target, signals, spec, cost, initial_capital, position_ratio
            )
            train = run_backtest(
                target, train_sigs, spec, cost, initial_capital, position_ratio
            )
            valid = run_backtest(
                target, valid_sigs, spec, cost, initial_capital, position_ratio
            )
            rows.append(
                {
                    "entry_params": entry_params,
                    "exit": {
                        "mode": spec.mode,
                        "hold_days": spec.hold_days,
                        "take_profit_pct": spec.take_profit_pct,
                        "stop_loss_pct": spec.stop_loss_pct,
                    },
                    "full": _compact(full),
                    "train": _compact(train),
                    "validation": _compact(valid),
                    "trades_sample": None,  # 前端选中后走单参数组回测拿逐笔明细
                }
            )

    _flag_overfit(rows)
    key = {"validation": "validation", "train": "train", "full": "full"}.get(sort_by, "validation")
    rows.sort(key=lambda r: r[key]["total_return_pct"], reverse=True)
    return {
        "module_id": module_id,
        "split_date": split.isoformat(),
        "train_ratio": train_ratio,
        "n_combos": len(rows),
        "rows": rows,
    }


def _flag_overfit(rows: list[dict[str, Any]]) -> None:
    """样本外崩塌标注: train 排名前 25% 且 train>0 但 validation ≤ 0 → overfit。"""
    n = len(rows)
    if n == 0:
        return
    ranked = sorted(rows, key=lambda r: r["train"]["total_return_pct"], reverse=True)
    top = set(id(r) for r in ranked[: max(1, n // 4)])
    for r in rows:
        tr = r["train"]["total_return_pct"]
        va = r["validation"]["total_return_pct"]
        r["overfit_flag"] = bool(id(r) in top and tr > 0 and va <= 0)


def _split_date(target: pl.DataFrame, train_ratio: float) -> date:
    dates = target["date"].to_list()
    if not dates:
        raise ValueError("target 为空, 无法切分 train/validation")
    idx = int(len(dates) * train_ratio)
    idx = min(max(idx, 1), len(dates) - 1)
    return dates[idx]


def _compact(r: BacktestResult) -> dict[str, Any]:
    return {
        "n_trades": len(r.trades),
        "total_return_pct": round(r.total_return_pct, 2),
        "annual_return_pct": round(r.annual_return_pct, 2),
        "max_drawdown_pct": round(r.max_drawdown_pct, 2),
        "sharpe": None if r.sharpe in (float("inf"),) else round(r.sharpe, 3),
        "win_rate": round(r.win_rate, 1),
        "final_equity": round(r.final_equity, 2),
    }
