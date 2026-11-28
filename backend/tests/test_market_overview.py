"""/api/market/overview 端点测试 (v2-4, 设计 §1.1) — 总览快照数值与合成K线手工核算对账。"""
from __future__ import annotations

import json
from datetime import date

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import market as market_api
from app.config import settings


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(market_api.router)
    return TestClient(app)


def _kline(n: int = 300) -> pl.DataFrame:
    """n 根单调 +1% — close[i] = 100 * 1.01^i, amount 恒定, 手工可核算。"""
    base = date(2023, 1, 2)
    d = [base.fromordinal(base.toordinal() + i) for i in range(n)]
    closes = [100.0 * 1.01 ** i for i in range(n)]
    return pl.DataFrame(
        {
            "date": d,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000.0] * n,
            "amount": [10000.0] * n,
        }
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(market_api, "load_index_daily", lambda *a, **k: _kline())
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


def test_overview_snapshot(env):
    res = _client().get("/api/market/overview")
    assert res.status_code == 200
    body = res.json()
    k = _kline()

    assert body["index_symbol"] == "000001.SH"
    assert body["as_of"] == k["date"].max().isoformat()

    # --- 价格状态手工核算 ---
    p = body["price"]
    latest = 100.0 * 1.01 ** 299
    prev = 100.0 * 1.01 ** 298
    assert p["close"] == pytest.approx(latest, rel=1e-9)
    assert p["prev_close"] == pytest.approx(prev, rel=1e-9)
    assert p["pct_change_pct"] == pytest.approx(1.0, abs=0.01)
    ma20 = 100.0 * sum(1.01 ** i for i in range(280, 300)) / 20
    assert p["ma20_dev_pct"] == pytest.approx((latest - ma20) / ma20 * 100, abs=0.05)
    ma250 = 100.0 * sum(1.01 ** i for i in range(50, 300)) / 250
    assert p["ma250_dev_pct"] == pytest.approx((latest - ma250) / ma250 * 100, abs=0.05)

    # --- MA20 上方连续天数: 单调上行全在 MA20 之上 ---
    assert body["ma20_streak"] == {"above": True, "days": 281}  # MA20 从第20根起有值

    # --- 量能水位: amount 恒定 -> 5日均值全相等 -> 分位 = 0/249 ≈ 0 -> extreme_low ---
    v = body["volume"]
    assert v["last_5d_amount"] == pytest.approx(10000.0)
    assert v["percentile_250"] == pytest.approx(0.0, abs=1e-6)
    assert v["level"] == "extreme_low"

    # --- 缠论快照: 字段存在, 合成单调数据笔方向可缺 (None = 不虚构) ---
    assert body["czsc"]["daily_bi_direction"] in (None, "up", "down")

    # --- 未来 7 天固定日历 / 信号模块注册表 ---
    assert body["upcoming"] == []
    assert isinstance(body["modules"], list) and body["modules"]

    # --- 近250日图表序列 (v3-④) ---
    c = body["chart"]
    assert len(c["dates"]) == 250
    assert len(c["ohlc"]) == 250 and len(c["ohlc"][0]) == 4
    assert len(c["amounts"]) == 250
    assert c["dates"][0] == date(2023, 1, 2).fromordinal(date(2023, 1, 2).toordinal() + 50).isoformat()
    assert c["dates"][-1] == body["as_of"]
    # ma20 尾值与 price.ma20_dev 同口径
    assert c["ma20"][-1] == pytest.approx(ma20, rel=1e-6)
    # amt5 恒定, 事件旗标合成数据下为空
    assert c["amt5"][-1] == pytest.approx(10000.0)
    assert c["event_flags"] == []


def test_overview_upcoming_calendar(tmp_path, monkeypatch):
    """固定日历落今天+3天 -> upcoming 命中; 超出 7 天 -> 不出现。"""
    today = date.today()
    (tmp_path / "policy").mkdir(parents=True)
    entries = [
        {"date": today.isoformat(), "title": "今日测试日历", "kind": "测试"},
        {"date": date.fromordinal(today.toordinal() + 3).isoformat(), "title": "三天后", "kind": "测试"},
        {"date": date.fromordinal(today.toordinal() + 10).isoformat(), "title": "十天外", "kind": "测试"},
    ]
    (tmp_path / "policy" / "fixed_calendar.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(market_api, "load_index_daily", lambda *a, **k: _kline())
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))

    body = _client().get("/api/market/overview").json()
    titles = [u["title"] for u in body["upcoming"]]
    assert titles == ["今日测试日历", "三天后"]


def test_overview_no_kline_404(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(market_api, "load_index_daily", lambda *a, **k: pl.DataFrame())
    res = _client().get("/api/market/overview")
    assert res.status_code == 404
