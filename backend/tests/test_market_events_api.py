"""/api/market/events* 端点测试 (P3-T5) — 列表/统计/聚合 + 迷你路径序列。"""
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


def _kline() -> pl.DataFrame:
    """30 根单调 +1% — 手工好核算; 事件日=第 6 根 (2024-01-08)。"""
    d = [date(2024, 1, i) for i in range(1, 31)]
    closes = [100.0 * 1.01 ** i for i in range(30)]
    return pl.DataFrame(
        {
            "date": d,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000.0] * 30,
            "amount": [10000.0] * 30,
        }
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """事件库 + 日历落 tmp, data_dir 与指数日K均打桩。"""
    (tmp_path / "policy").mkdir(parents=True)
    (tmp_path / "policy" / "policy_events.json").write_text(
        json.dumps(
            {
                "events": [
                    {
                        "id": "ev-approved",
                        "date": "2024-01-08",
                        "title": "已确认重大事件",
                        "category": "货币政策",
                        "importance": "major",
                        "direction": "positive",
                        "source": "https://example.com/a",
                        "status": "approved",
                    },
                    {
                        "id": "ev-draft",
                        "date": "2024-01-09",
                        "title": "抓取候选",
                        "category": "监管政策",
                        "importance": "minor",
                        "direction": "neutral",
                        "source": "https://example.com/b",
                        "status": "draft",
                        "fetch_code": "X1",
                    },
                    {
                        "id": "ev-nosource",
                        "date": "2024-01-10",
                        "title": "无来源事件",
                        "category": "外部事件",
                        "importance": "major",
                        "direction": "negative",
                        "source": "",
                        "status": "approved",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "policy" / "fixed_calendar.json").write_text(
        json.dumps({"entries": [{"date": "2026-03-05", "title": "两会", "kind": "两会"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_api, "load_index_daily", lambda *a, **k: _kline())
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))


def test_list_events(env):
    res = _client().get("/api/market/events")
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {"total": 3, "countable": 1, "draft": 1}
    evs = {e["id"]: e for e in body["events"]}
    # 铁律: 只有 approved+major+source 进统计
    assert evs["ev-approved"]["countable"] is True
    # 全历史指数 bars 内嵌 (raw 分区, 事件 Tab 主图数据源)
    assert body["index_bars"][0]["date"] == "2024-01-01"
    assert len(body["index_bars"]) == 30
    assert evs["ev-draft"]["countable"] is False
    assert evs["ev-nosource"]["countable"] is False
    # countable 事件带统计 (T+1 = +1%: 事件日第6根 close[5]/close[4]-1 = 1%)
    assert evs["ev-approved"]["stats"]["t1"] == pytest.approx(1.0)
    # 非 countable 不带统计
    assert evs["ev-draft"]["stats"] is None
    # 聚合: n=1 < 5 只显示样本数
    assert body["aggregate"] == [{"direction": "positive", "ma20_position": None, "n": 1}]
    # 固定日历透出
    assert body["calendar"][0]["kind"] == "两会"


def test_events_stats_carry_bi_direction(env):
    """v2 事件技术背景: stats 必含缠论日线笔方向字段 (None=笔数据不足, 不虚构)。"""
    res = _client().get("/api/market/events")
    assert res.status_code == 200
    evs = {e["id"]: e for e in res.json()["events"]}
    assert "bi_direction" in evs["ev-approved"]["stats"]
    assert evs["ev-approved"]["stats"]["bi_direction"] in (None, "up", "down")


def test_list_events_filters(env):
    res = _client().get("/api/market/events", params={"status": "draft"})
    body = res.json()
    assert body["counts"]["total"] == 1
    assert body["events"][0]["id"] == "ev-draft"
    res2 = _client().get("/api/market/events", params={"category": "监管政策"})
    assert [e["id"] for e in res2.json()["events"]] == ["ev-draft"]


def test_list_events_empty_library(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(
        market_api, "load_index_daily", lambda *a, **k: pl.DataFrame()
    )
    res = _client().get("/api/market/events")
    assert res.status_code == 200
    body = res.json()
    assert body["counts"] == {"total": 0, "countable": 0, "draft": 0}
    assert body["events"] == [] and body["aggregate"] == []


def test_event_series_ok(env):
    res = _client().get("/api/market/events/series", params={"event_id": "ev-approved"})
    assert res.status_code == 200
    body = res.json()
    assert body["event"]["id"] == "ev-approved"
    # 序列与统计口径交叉一致: T+1 value/100-1 == t1
    t1 = next(p for p in body["points"] if p["offset"] == 0)
    assert t1["value"] / 100 == pytest.approx(1.01, abs=0.001)
    # 前置 5 根存在
    assert body["points"][0]["offset"] == -5


def test_event_series_not_found(env):
    res = _client().get("/api/market/events/series", params={"event_id": "nope"})
    assert res.status_code == 404


def test_event_series_out_of_kline_range(env, monkeypatch):
    # K 线过短 (前置不足 5 根) -> 404
    monkeypatch.setattr(
        market_api,
        "load_index_daily",
        lambda *a, **k: _kline().head(4),
    )
    res = _client().get("/api/market/events/series", params={"event_id": "ev-approved"})
    assert res.status_code == 404
