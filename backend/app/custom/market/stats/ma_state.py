"""M1 均线状态机 (潘扬口径) — 指数收盘上穿/跌破均线产生带方向信号。"""
from __future__ import annotations

from typing import Any

import polars as pl

from .base import ParamSpec, Signal, StatsModule
from .registry import register


@register
class MaStateModule(StatsModule):
    id = "ma_state"
    label = "均线状态机"
    description = "收盘价上穿均线做多、跌破均线离场 (潘扬 20 日线口径的信号化)。"
    params = (
        ParamSpec(
            name="ma_period",
            label="均线周期",
            type="int",
            default=20,
            min=5,
            max=250,
            description="均线计算天数 (收盘价简单均值)。",
        ),
    )

    def to_signals(self, df: pl.DataFrame, params: dict[str, Any]) -> list[Signal]:
        p = self.resolve_params(params)
        n = int(p["ma_period"])
        if len(df) < n + 1:
            return []
        out = df.with_columns(pl.col("close").rolling_mean(n).alias("ma")).drop_nulls("ma")
        dates = out["date"].to_list()
        closes = out["close"].to_list()
        mas = out["ma"].to_list()
        signals: list[Signal] = []
        for i in range(1, len(out)):
            if closes[i - 1] <= mas[i - 1] and closes[i] > mas[i]:
                signals.append(Signal(dt=dates[i], direction=1, note=f"上穿MA{n}"))
            elif closes[i - 1] >= mas[i - 1] and closes[i] < mas[i]:
                signals.append(Signal(dt=dates[i], direction=-1, note=f"跌破MA{n}"))
        return signals
