"""事件序列 (迷你路径) 单测 (P3-T4) — 含与 T3 统计口径交叉一致校验。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.custom.market.event_series import (
    build_event_series,
    build_event_series_with_benchmark,
    series_from_dfs,
)
from app.custom.market.event_stats import compute_event_stats
from app.custom.market.events import PolicyEvent


def _kline(closes: list[float], start: date = date(2024, 1, 1)) -> pl.DataFrame:
    ds, d = [], start
    while len(ds) < len(closes):
        if d.weekday() < 5:
            ds.append(d)
        d += timedelta(days=1)
    return pl.DataFrame({"date": ds, "close": closes})


def _ev(day: date) -> PolicyEvent:
    return PolicyEvent(
        id="ev",
        date=day,
        title="t",
        category="货币政策",
        importance="major",
        direction="positive",
        source="https://x",
    )


def test_series_basic_shape_and_base100():
    closes = [100.0] * 10 + [100.0 * 1.01 ** i for i in range(65)]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    ev = _ev(dates[10])  # t_idx=10, 前5根 + 后60根
    res = build_event_series(ev, dates, closes)
    assert res is not None
    pts = res["points"]
    assert len(pts) == 65  # 5 + 60
    assert pts[0]["offset"] == -5 and pts[-1]["offset"] == 59
    # 基期 = 事件前收盘 (idx9=100): 全部前5点 = 100
    assert pts[0]["value"] == 100.0
    # 事件前收盘点: offset -1 (idx9) = 100
    assert next(p for p in pts if p["offset"] == -1)["value"] == 100.0
    # 基线与序列相同 (指数事件)
    assert res["index_points"] == pts


def test_series_cross_check_with_t3_stats():
    closes = [100.0 * 1.01 ** i for i in range(80)]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    ev = _ev(dates[10])
    st = compute_event_stats(ev, dates, closes)
    res = build_event_series(ev, dates, closes)
    assert st is not None and res is not None
    # 交叉一致: 序列 T+1 点值/100-1 == stats.t1
    t1_pt = next(p for p in res["points"] if p["offset"] == 0)
    assert (t1_pt["value"] / 100 - 1) * 100 == pytest.approx(st.t1, abs=0.02)
    t20_pt = next(p for p in res["points"] if p["offset"] == 19)
    assert (t20_pt["value"] / 100 - 1) * 100 == pytest.approx(st.t20, abs=0.02)


def test_series_insufficient_pre_or_out_of_range():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    # 前置不足 5 根 (t_idx - 5 < 0)
    assert build_event_series(_ev(dates[3]), dates, closes) is None
    # 事件晚于全部K线
    assert build_event_series(_ev(dates[-1] + timedelta(days=5)), dates, closes) is None


def test_series_truncated_post_window():
    # 后窗不足 60 根: 截断不报错不补 NaN
    closes = [100.0] * 10 + [110.0, 111.0, 112.0]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    res = build_event_series(_ev(dates[10]), dates, closes)
    assert res is not None
    assert len(res["points"]) == 5 + 3  # 前5 + 事件日起3根
    assert all(isinstance(p["value"], float) for p in res["points"])


def test_series_with_benchmark_separate_baseline():
    asset = [100.0] * 10 + [120.0, 121.0, 122.0]
    index = [3000.0] * 10 + [3030.0, 3031.0, 3032.0]
    ak, ik = _kline(asset), _kline(index)
    a_dates = ak["date"].to_list()
    ev = _ev(a_dates[10])
    res = build_event_series_with_benchmark(
        ev, a_dates, asset, ik["date"].to_list(), index
    )
    assert res is not None
    # 标的: 事件前收盘 100 → T+1 = 120 (+20%)
    a_t1 = next(p for p in res["points"] if p["offset"] == 0)
    assert a_t1["value"] == pytest.approx(120.0)
    # 指数基线: 事件前收盘 3000 → T+1 = 3030 (+1%)
    i_t1 = next(p for p in res["index_points"] if p["offset"] == 0)
    assert i_t1["value"] == pytest.approx(101.0)


def test_series_from_dfs_entry():
    closes = [100.0] * 10 + [100.0 * 1.01 ** i for i in range(65)]
    kl = _kline(closes)
    ev = _ev(kl["date"][10])
    # index_kline=None: 直接用标的作基线
    res = series_from_dfs(ev, kl, None)
    assert res is not None
    assert res["index_points"] == res["points"]
    # 空 kline
    empty = pl.DataFrame(schema={"date": pl.Date, "close": pl.Float64})
    assert series_from_dfs(ev, empty, None) is None
    # 指数基线截断场景 (指数数据短): index_points 置空不炸
    short = _kline([3000.0] * 8)
    res2 = series_from_dfs(ev, kl, short)
    assert res2 is not None
    assert len(res2["points"]) == 65
