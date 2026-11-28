"""事件统计引擎单测 (P3-T3) — 确定性合成K线手工核算。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.custom.market.events import PolicyEvent
from app.custom.market.event_stats import aggregate, compute_event_stats, compute_events_stats


def _kline(closes: list[float], start: date = date(2024, 1, 1)) -> pl.DataFrame:
    """合成日K: 从 start 起每个交易日(跳过周末)一根, 全部收盘价给定。"""
    ds, d = [], start
    while len(ds) < len(closes):
        if d.weekday() < 5:
            ds.append(d)
        d += timedelta(days=1)
    return pl.DataFrame({"date": ds, "close": closes})


def _ev(day: date, **kw) -> PolicyEvent:
    base = dict(
        id=f"ev-{day.isoformat()}",
        date=day,
        title="测试事件",
        category="货币政策",
        importance="major",
        direction="positive",
        source="https://example.com",
    )
    base.update(kw)
    return PolicyEvent(**base)


# ---------- compute_event_stats 手工核算 ----------
# 合成: 100 → 110 (T+1, +10%) → 105 (T+5, +5%) → ... 事件日 = 第2根 (index 1)


def test_event_stats_basic_horizons():
    closes = [100.0, 110.0, 108.0, 112.0, 109.0, 105.0] + [104.0] * 14 + [120.0] + [100.0] * 30
    kl = _kline(closes)
    # 事件生效日 = 第2个交易日 (kline 第 index 1 那天)
    ev_day = kl["date"][1]
    ev = _ev(ev_day)
    st = compute_event_stats(ev, kl["date"].to_list(), closes)
    assert st is not None
    assert st.base_close == 100.0  # 前收盘 = 第1根
    assert st.t1 == pytest.approx(10.0)  # 110/100
    # T+5 = index 1+4 = 5 -> 105.0 (+5%)
    assert st.t5 == pytest.approx(5.0)
    # T+20 = index 1+19 = 20 -> 120.0 (+20%)
    assert st.t20 == pytest.approx(20.0)
    # T+60 越界 -> None
    assert st.t60 is None
    # 20日窗口 (index 1..20): max=120 (+20%), min=104 (+4%)
    assert st.max_up_20 == pytest.approx(20.0)
    # 合成线单调段无真正回撤, 窗口最低 104 vs base 100 -> +4% (口径: 窗口收盘极值 vs 前收盘)
    assert st.max_dd_20 == pytest.approx(4.0)


def test_event_stats_event_date_non_trading():
    closes = [100.0, 110.0, 108.0, 112.0, 109.0, 105.0] + [104.0] * 60
    kl = _kline(closes)
    dates = kl["date"].to_list()
    # 事件日 = 第5与第6个交易日之间的周六 (非交易日):
    # 生效日起第一个交易日 = index 5, 前收盘 = index 4 (109)
    ev_day = dates[4] + timedelta(days=1)
    assert ev_day not in set(dates)
    st = compute_event_stats(_ev(ev_day), dates, closes)
    assert st is not None
    assert st.base_close == 109.0  # 前收盘 = 事件前最后一个交易日
    assert st.t1 == pytest.approx(-3.67)  # T+1 = 次一交易日收盘 105 vs 109


def test_event_stats_out_of_range():
    closes = [100.0, 101.0, 102.0]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    # 早于全部K线 (t_idx=0 无前收盘)
    assert compute_event_stats(_ev(dates[0]), dates, closes) is None
    # 晚于全部K线
    assert compute_event_stats(_ev(dates[-1] + timedelta(days=10)), dates, closes) is None


def test_event_stats_ma20_context():
    # 前20根缓慢下跌 (事件时在20日线下), 第21根暴跌触发事件日
    closes = [200.0 - i for i in range(21)]  # 200..180, 事件日 index 20, close=180
    kl = _kline(closes)
    st = compute_event_stats(_ev(kl["date"][20]), kl["date"].to_list(), closes)
    assert st is not None
    assert st.above_ma20 is False  # 180 < MA20(前20根均值约190)
    # 上涨型: 事件日收盘 > 前20根均值
    closes2 = [100.0 + i for i in range(21)]
    kl2 = _kline(closes2)
    st2 = compute_event_stats(_ev(kl2["date"][20]), kl2["date"].to_list(), closes2)
    assert st2.above_ma20 is True
    # 不足20根 -> None
    closes3 = [100.0, 101.0, 102.0]
    kl3 = _kline(closes3)
    st3 = compute_event_stats(_ev(kl3["date"][1]), kl3["date"].to_list(), closes3)
    assert st3.above_ma20 is None


def test_compute_events_stats_batch():
    closes = [100.0 * 1.01 ** i for i in range(80)]  # 每根 +1%, 手工核算
    kl = _kline(closes)
    dates = kl["date"].to_list()
    evs = [_ev(dates[10]), _ev(dates[25]), _ev(dates[60])]
    results = compute_events_stats(evs, kl)
    assert len(results) == 3
    # 每条: base=前收盘, T+k = 1.01**k - 1 (实现 round(2))
    # T+60 需 t_idx+59 < 80: 仅第 1 条 (t_idx=10) 前向充足
    for st, ev in zip(results, evs):
        assert st.t1 == pytest.approx(1.0)
        assert st.t20 == pytest.approx(round((1.01 ** 20 - 1) * 100, 2))
    by_id = {s.event_id: s for s in results}
    assert by_id[evs[0].id].t60 == pytest.approx(round((1.01 ** 60 - 1) * 100, 2))
    assert by_id[evs[1].id].t60 is None  # t_idx=25, +59 越界
    assert by_id[evs[2].id].t60 is None  # 前向数据不足, 不算 0
    # 空 kline
    assert compute_events_stats(evs, pl.DataFrame(schema={"date": pl.Date, "close": pl.Float64})) == []


# ---------- aggregate (n<5 规则) ----------


def test_aggregate_n_lt_5_hides_medians():
    closes = [100.0 + i for i in range(80)]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    evs = [_ev(dates[10 + i], direction="positive") for i in range(3)]
    stats = compute_events_stats(evs, kl)
    rows = aggregate(evs, stats)
    assert len(rows) == 1
    assert rows[0]["n"] == 3
    assert rows[0]["direction"] == "positive"
    assert "median_t1" not in rows[0]  # n<5 只显示样本数


def test_aggregate_groups_and_median():
    closes = [100.0 * 1.01 ** i for i in range(90)]
    kl = _kline(closes)
    dates = kl["date"].to_list()
    # positive 5 条 + negative 5 条 — 位置均离数据头 >=20 根 (MA20 可判), 分两组
    evs = [_ev(dates[25 + i], direction="positive") for i in range(5)]
    evs += [_ev(dates[50 + i], direction="negative") for i in range(5)]
    stats = compute_events_stats(evs, kl)
    rows = aggregate(evs, stats)
    assert len(rows) == 2
    pos = next(r for r in rows if r["direction"] == "positive")
    neg = next(r for r in rows if r["direction"] == "negative")
    assert pos["n"] == 5
    assert neg["n"] == 5
    # 合成线斜率一致: t1 全部 +1% -> 中位数 1.0
    assert pos["median_t1"] == pytest.approx(1.0)
    assert neg["median_t1"] == pytest.approx(1.0)
    assert pos["ma20_position"] == "above"
