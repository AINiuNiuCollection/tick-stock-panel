"""M2 急跌急涨 — 单日/累计跌幅分档做多 (V 反), 急涨离场。"""
from __future__ import annotations

from typing import Any

import polars as pl

from .base import ParamSpec, Signal, StatsModule
from .registry import register


@register
class CrashSpeedModule(StatsModule):
    id = "crash_speed"
    label = "急跌急涨"
    description = (
        "单日跌幅 ≥X% 或连续 N 日累计跌幅 ≥X% 时做多 (急杀 V 反口径); "
        "单日涨幅 ≥X% 视为反向信号 (防一日游)。"
    )
    params = (
        ParamSpec(
            name="threshold_pct",
            label="跌幅阈值 %",
            type="float",
            default=3.0,
            min=0.5,
            max=10.0,
            description="触发做多的跌幅分档阈值。",
        ),
        ParamSpec(
            name="kind",
            label="跌幅口径",
            type="select",
            default="single",
            options=("single", "cumulative"),
            description="single=单日急跌; cumulative=N 日累计跌幅。",
        ),
        ParamSpec(
            name="cum_days",
            label="累计天数",
            type="int",
            default=5,
            min=2,
            max=20,
            description="kind=cumulative 时的滚动窗口 (自然跌速口径)。",
        ),
    )

    def to_signals(self, df: pl.DataFrame, params: dict[str, Any]) -> list[Signal]:
        p = self.resolve_params(params)
        threshold = float(p["threshold_pct"]) / 100.0
        dates = df["date"].to_list()
        closes = df["close"].to_list()
        signals: list[Signal] = []
        if p["kind"] == "cumulative":
            n = int(p["cum_days"])
            for i in range(n, len(df)):
                ret = closes[i] / closes[i - n] - 1.0
                if ret <= -threshold:
                    signals.append(
                        Signal(dt=dates[i], direction=1, note=f"{n}日累计{ret:.2%}≤-{threshold:.2%}")
                    )
                elif ret >= threshold:
                    signals.append(Signal(dt=dates[i], direction=-1, note=f"{n}日累计涨{ret:.2%}"))
        else:
            for i in range(1, len(df)):
                ret = closes[i] / closes[i - 1] - 1.0
                if ret <= -threshold:
                    signals.append(Signal(dt=dates[i], direction=1, note=f"单日跌{ret:.2%}"))
                elif ret >= threshold:
                    signals.append(Signal(dt=dates[i], direction=-1, note=f"单日涨{ret:.2%}"))
        return signals
