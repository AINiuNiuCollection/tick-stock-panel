"""M4 均线异动波段 — 潘扬「日线级别-异动波段策略」的信号化复刻。

规则 (同 data/strategies/custom/custom_shang_zheng_anomaly_wave.py 的反推口径):
- 异动动量: mom_pct = (close - EMA{mom_period}) / EMA{mom_period} * 100
  (EMA 首值种子, 与主工程 czsc 约定一致)。
- 入场 (+1): mom_pct > buy_mom_thr (指数异动突破)。
- 反向 (-1): mom_pct < 0 或 收盘跌破 MA{ma_period}。
- 冷却: 上一条 +1 信号后 cooldown_days 个交易日内的 +1 信号被抑制。
"""
from __future__ import annotations

from typing import Any

import polars as pl

from .base import ParamSpec, Signal, StatsModule
from .registry import register


@register
class AnomalyWaveModule(StatsModule):
    id = "ma_anomaly_wave"
    label = "均线异动波段(潘扬)"
    description = (
        "收盘价对 EMA 的乖离率 (异动动量) 超阈值时做多; "
        "乖离转负或收盘跌破均线产生反向 (离场) 信号; 冷却期内抑制连续做多。"
    )
    params = (
        ParamSpec(
            name="mom_period",
            label="动量EMA周期",
            type="int",
            default=5,
            min=3,
            max=20,
            description="异动动量的 EMA 周期 (乖离率基准线)。",
        ),
        ParamSpec(
            name="buy_mom_thr",
            label="买入动量阈值(%)",
            type="float",
            default=2.0,
            min=0.5,
            max=10.0,
            description="乖离率超过该百分比即触发做多 (均线涨幅买入阈值)。",
        ),
        ParamSpec(
            name="ma_period",
            label="卖出均线天数",
            type="int",
            default=5,
            min=3,
            max=60,
            description="收盘跌破该均线触发反向信号; 「涨到多少卖出」由出场规则的止盈止损承担。",
        ),
        ParamSpec(
            name="cooldown_days",
            label="冷却期天数",
            type="int",
            default=5,
            min=0,
            max=30,
            description="上一条做多信号后 N 个交易日内不再重复做多。",
        ),
    )

    def to_signals(self, df: pl.DataFrame, params: dict[str, Any]) -> list[Signal]:
        p = self.resolve_params(params)
        period = int(p["mom_period"])
        buy_thr = float(p["buy_mom_thr"])
        ma_period = int(p["ma_period"])
        cooldown = int(p["cooldown_days"])
        if len(df) < max(period, ma_period) + 1:
            return []
        out = df.with_columns(
            pl.col("close").ewm_mean(span=period, adjust=False).alias("ema"),
            pl.col("close").rolling_mean(ma_period).alias("ma"),
        )
        dates = out["date"].to_list()
        closes = out["close"].to_list()
        emas = out["ema"].to_list()
        mas = out["ma"].to_list()
        signals: list[Signal] = []
        last_entry_i = -(cooldown + 1)
        for i in range(len(out)):
            ema = emas[i]
            ma = mas[i]
            close = closes[i]
            if ema and ema > 0:
                mom_pct = (close - ema) / ema * 100.0
                if mom_pct < 0:
                    signals.append(
                        Signal(dt=dates[i], direction=-1, note=f"动量转负 {mom_pct:.2f}%")
                    )
                if mom_pct > buy_thr and i - last_entry_i > cooldown:
                    signals.append(
                        Signal(dt=dates[i], direction=1, note=f"异动动量 {mom_pct:.2f}%>{buy_thr}%")
                    )
                    last_entry_i = i
            if ma is not None and close < ma:
                signals.append(
                    Signal(dt=dates[i], direction=-1, note=f"跌破MA{ma_period}")
                )
        return signals
