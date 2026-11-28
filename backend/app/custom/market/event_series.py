"""事件序列 (迷你路径) — 事件前5日→后60日归一化走势 (设计 §2.3 第二/三层, P3-T4)。

口径:
    - 窗口 = 事件前 5 个交易日 + 事件日起 60 个交易日 (共 65 点);
    - 归一化基期 = 事件前收盘 (= 窗口第 1 点的基准, 该点值 100);
    - 每点值 = close / base * 100;
    - 同期指数基线: 上证指数同窗口归一化 (供 ETF 事件对比; 指数事件时两者同源)。

与 T3 统计口径交叉一致: 序列第 6 点 (T+1) / 100 - 1 == stats.t1。
"""
from __future__ import annotations

from datetime import date

import polars as pl

from app.custom.market.events import PolicyEvent

_PRE_DAYS = 5
_POST_DAYS = 60


def build_event_series(
    event: PolicyEvent, dates: list[date], closes: list[float]
) -> dict | None:
    """单事件迷你路径 + 指数基线; 事件不在范围内返回 None。

    返回 {"event_id", "points": [{"offset", "date", "value"}...],
          "index_points": [...] (dates/closes 即指数时与 points 相同)}。
    offset: -5..-1 事件前, 0=T+1 (事件日起第一个交易日), 1..59 后续 T+2..T+60。
    前向/后向不足时窗口截断 (不补 NaN)。
    """
    lo, t_idx = 0, len(dates)
    while lo < len(dates):
        if dates[lo] >= event.date:
            t_idx = lo
            break
        lo += 1
    start = t_idx - _PRE_DAYS
    end = t_idx + _POST_DAYS  # exclusive
    if t_idx <= 0 or start < 0 or t_idx >= len(dates):
        return None  # 前置不足 5 根 / 事件在范围外
    closes_l = [float(c) for c in closes[start:end]]
    dates_l = dates[start:end]
    if not closes_l:
        return None
    base = float(closes[t_idx - 1])  # 事件前收盘

    def norm(series: list[float], dts: list[date]) -> list[dict]:
        return [
            {"offset": i - _PRE_DAYS, "date": d.isoformat(), "value": round(v / base * 100, 2)}
            for i, (v, d) in enumerate(zip(series, dts))
        ]

    points = norm(closes_l, dates_l)
    return {
        "event_id": event.id,
        "base": base,
        "points": points,
        # dates/closes 即指数日K: index_points == points (ETF 事件场景由调用方传指数序列)
        "index_points": points,
    }


def build_event_series_with_benchmark(
    event: PolicyEvent,
    asset_dates: list[date],
    asset_closes: list[float],
    index_dates: list[date],
    index_closes: list[float],
) -> dict | None:
    """事件标的序列 + 同期指数基线 (各自以事件前收盘归一化到 100)。"""
    base_res = build_event_series(event, asset_dates, asset_closes)
    if base_res is None:
        return None
    # 指数基线: 同一事件日, 在指数序列中定位
    lo, idx_t = 0, len(index_dates)
    while lo < len(index_dates):
        if index_dates[lo] >= event.date:
            idx_t = lo
            break
        lo += 1
    i_start = idx_t - _PRE_DAYS
    if idx_t <= 0 or i_start < 0 or idx_t >= len(index_dates):
        base_res["index_points"] = []
        return base_res
    i_base = float(index_closes[idx_t - 1])
    i_dates = index_dates[i_start : idx_t + _POST_DAYS]
    i_closes = [float(c) for c in index_closes[i_start : idx_t + _POST_DAYS]]
    base_res["index_points"] = [
        {"offset": i - _PRE_DAYS, "date": d.isoformat(), "value": round(v / i_base * 100, 2)}
        for i, (v, d) in enumerate(zip(i_closes, i_dates))
    ]
    return base_res


def series_from_dfs(
    event: PolicyEvent, asset_kline: pl.DataFrame, index_kline: pl.DataFrame | None = None
) -> dict | None:
    """polars 入口; index_kline 为 None 时直接用 asset_kline 作基线。"""
    if asset_kline.is_empty():
        return None
    a_dates = [d.date() if hasattr(d, "date") else d for d in asset_kline["date"].to_list()]
    a_closes = asset_kline["close"].to_list()
    if index_kline is None or index_kline.is_empty():
        return build_event_series(event, a_dates, a_closes)
    i_dates = [d.date() if hasattr(d, "date") else d for d in index_kline["date"].to_list()]
    i_closes = index_kline["close"].to_list()
    return build_event_series_with_benchmark(event, a_dates, a_closes, i_dates, i_closes)
