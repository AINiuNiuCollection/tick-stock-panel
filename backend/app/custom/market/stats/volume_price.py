"""M3 量价组合 — 地量做多 ('地量见地价'实证) / 极端放量离场。"""
from __future__ import annotations

from typing import Any

import polars as pl

from .base import ParamSpec, Signal, StatsModule
from .registry import register


@register
class VolumePriceModule(StatsModule):
    id = "volume_price"
    label = "量价组合"
    description = (
        "成交额落入滚动 window 日分位 ≤low_q 时做多 (地量口径); "
        "≥high_q 时视为极端放量反向信号。"
    )
    params = (
        ParamSpec(
            name="window",
            label="分位窗口",
            type="int",
            default=250,
            min=60,
            max=500,
            description="滚动分位窗口 (日)。",
        ),
        ParamSpec(
            name="low_q",
            label="地量分位",
            type="float",
            default=0.05,
            min=0.0,
            max=0.5,
            description="成交额分位 ≤ 该值视为地量。",
        ),
        ParamSpec(
            name="high_q",
            label="放量分位",
            type="float",
            default=0.95,
            min=0.5,
            max=1.0,
            description="成交额分位 ≥ 该值视为极端放量。",
        ),
    )

    def to_signals(self, df: pl.DataFrame, params: dict[str, Any]) -> list[Signal]:
        p = self.resolve_params(params)
        if len(df) < int(p["window"]) + 1:
            return []
        out = (
            df.with_columns(
                pl.col("amount").rolling_map(
                    lambda s: float(s.rank(method="average")[-1] - 1) / (len(s) - 1),
                    window_size=int(p["window"]),
                ).alias("amount_q")
            )
            .drop_nulls("amount_q")
        )
        dates = out["date"].to_list()
        qs = out["amount_q"].to_list()
        amounts = out["amount"].to_list()
        signals: list[Signal] = []
        for i in range(len(out)):
            if qs[i] <= p["low_q"]:
                signals.append(Signal(dt=dates[i], direction=1, note=f"地量分位{qs[i]:.2f}"))
            elif qs[i] >= p["high_q"]:
                signals.append(Signal(dt=dates[i], direction=-1, note=f"放量分位{qs[i]:.2f}"))
        return signals
