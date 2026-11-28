"""/api/market 路由层测试 — 注册表发现 / 单组回测 / 网格寻优。"""
from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import market as market_api


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(market_api.router)
    return TestClient(app)


def _index_df() -> pl.DataFrame:
    d = [date(2024, 1, i) for i in range(1, 16)]
    closes = [10.0, 10, 10, 10, 9.0, 10, 10, 10, 9.0, 10, 10, 10, 10, 10, 10]
    return pl.DataFrame(
        {
            "date": d,
            "open": [10.0] * 15,
            "high": [10.0] * 15,
            "low": [10.0] * 15,
            "close": closes,
            "volume": [1000.0] * 15,
            "amount": [10000.0] * 15,
        }
    )


def _target_df() -> pl.DataFrame:
    d = [date(2024, 1, i) for i in range(1, 16)]
    opens = [10.0 + i * 0.1 for i in range(15)]
    return pl.DataFrame(
        {
            "date": d,
            "open": opens,
            "high": [o + 0.2 for o in opens],
            "low": [o - 0.2 for o in opens],
            "close": [10.5 + i * 0.1 for i in range(15)],
            "volume": [100.0] * 15,
            "amount": [1000.0] * 15,
        }
    )


@pytest.fixture()
def patched_data(monkeypatch):
    monkeypatch.setattr(market_api, "load_index_daily", lambda *a, **k: _index_df())
    monkeypatch.setattr(market_api, "load_etf_daily", lambda *a, **k: _target_df())


def test_stats_modules(patched_data):
    res = _client().get("/api/market/stats/modules")
    assert res.status_code == 200
    modules = res.json()["modules"]
    ids = {m["id"] for m in modules}
    assert {"ma_state", "crash_speed", "volume_price"} <= ids
    crash = next(m for m in modules if m["id"] == "crash_speed")
    assert crash["label"] == "急跌急涨"
    names = {p["name"] for p in crash["params"]}
    assert "threshold_pct" in names


def test_backtest(patched_data):
    payload = {
        "index_symbol": "000001.SH",
        "target_symbol": "510300.SH",
        "module_id": "crash_speed",
        "entry_params": {"threshold_pct": 5.0},
        "exit": {"mode": "time", "hold_days": 2},
    }
    res = _client().post("/api/market/backtest", json=payload)
    assert res.status_code == 200
    body = res.json()
    # 两次急跌 (+1) 与两次急涨 (−1) → 4 条信号, 其中做多信号 2 条 = 2 笔交易
    assert len(body["signals"]) == 4
    assert len(body["buy_signals"]) == 2
    assert body["metrics"]["n_trades"] == 2
    t0 = body["trades"][0]
    assert t0["entry_signal_dt"] == "2024-01-05"
    assert t0["entry_dt"] == "2024-01-06"  # T+1 开盘
    assert t0["exit_reason"] == "time"
    assert body["equity_curve"][0]["dt"] == "2024-01-01"
    # 双K线内嵌 OHLCV (raw 深历史, 供前端联动图)
    assert body["target_bars"][0]["date"] == "2024-01-01"
    assert body["index_bars"][0]["date"] == "2024-01-01"
    assert {"open", "high", "low", "close", "volume"} <= set(body["index_bars"][0])


def test_backtest_unknown_module(patched_data):
    res = _client().post(
        "/api/market/backtest",
        json={"module_id": "nope"},
    )
    assert res.status_code == 400


def test_backtest_missing_symbol(monkeypatch):
    monkeypatch.setattr(
        market_api, "load_index_daily", lambda *a, **k: pl.DataFrame()
    )
    res = _client().post(
        "/api/market/backtest",
        json={"module_id": "crash_speed"},
    )
    assert res.status_code == 404


def test_optimize(patched_data):
    payload = {
        "index_symbol": "000001.SH",
        "target_symbol": "510300.SH",
        "module_id": "crash_speed",
        "entry_grid": {"threshold_pct": [5.0, 10.0]},
        "exit_grid": {"mode": ["time"], "hold_days": [1, 3]},
        "train_ratio": 0.7,
    }
    res = _client().post("/api/market/optimize", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["n_combos"] == 4
    assert {"entry_params", "exit", "full", "train", "validation", "overfit_flag"} <= set(
        body["rows"][0]
    )
    # 默认按 validation 收益降序
    vals = [r["validation"]["total_return_pct"] for r in body["rows"]]
    assert vals == sorted(vals, reverse=True)
    assert "window" in body


def test_optimize_requires_grid(patched_data):
    res = _client().post(
        "/api/market/optimize",
        json={"module_id": "crash_speed"},
    )
    assert res.status_code == 400
