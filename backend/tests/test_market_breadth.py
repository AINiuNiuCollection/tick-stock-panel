"""市场结构 breadth (v3-⑤) — compute_breadth 数值手工核算 + 指纹缓存 + API。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import market as market_api
from app.config import settings
from app.custom.market.breadth import (
    breadth_path,
    compute_breadth,
    load_breadth,
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """合成 enriched 分区: 22 日 × 2 标的 (一个单调涨、一个恒定), 手工可核算。"""
    n = 22
    base = date(2026, 1, 5)
    days = [base + timedelta(days=i) for i in range(n)]
    up = [100.0 * 1.01 ** i for i in range(n)]
    flat = [50.0] * n
    rows = []
    for i, d in enumerate(days):
        for sym, closes in (("000001.SZ", up), ("000002.SZ", flat)):
            rows.append(
                {
                    "symbol": sym,
                    "date": d,
                    "open": closes[i],
                    "high": closes[i],
                    "low": closes[i],
                    "close": closes[i],
                    "volume": 1000.0,
                    "amount": 10000.0,
                }
            )
    raw = pl.DataFrame(rows)
    edir = tmp_path / "kline_daily_enriched"
    for d in days:
        part = edir / f"date={d.isoformat()}"
        part.mkdir(parents=True)
        raw.filter(pl.col("date") == d).write_parquet(part / "part.parquet")
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    return tmp_path


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(market_api.router)
    return TestClient(app)


def test_compute_breadth_handchecked(env):
    df = compute_breadth(env)
    # MA20 需 20 根暖机 -> 仅第 20/21/22 根 (2026-01-24/25/26) 有值
    assert df.height == 3
    assert df["date"].min() == date(2026, 1, 24)
    last = df.tail(1).to_dicts()[0]
    # 尾日: up 标的 close > MA20 且创 60 日新高; flat 标的 close == MA20 (>= 成立), 未创新高被 up 掩盖? 各自口径:
    # above_ma20: up=True, flat=True (50>=50) -> 1.0
    assert last["pct_above_ma20"] == pytest.approx(1.0)
    # new_high_60d: up=True; flat: 50 >= rolling_max(60)=50 -> True -> 1.0
    # 故改用更强断言前先核 flat: rolling_max 含当前根, 50>=50 为真
    assert last["pct_new_high_60d"] == pytest.approx(1.0)
    assert last["sample_count"] == 2
    assert last["total_amount"] == pytest.approx(20000.0)


def test_fingerprint_cache_roundtrip(env):
    compute_breadth(env)
    assert breadth_path(env).is_file()
    df = load_breadth(env)
    assert df is not None and df.height == 3
    # 新增一个分区 -> 指纹过期 -> None (需重建)
    nxt = date(2026, 1, 28)
    part = env / "kline_daily_enriched" / f"date={nxt.isoformat()}"
    part.mkdir(parents=True)
    pl.DataFrame({"symbol": ["000001.SZ"], "open": [120.0], "high": [120.0], "low": [120.0],
                  "close": [120.0], "volume": [1000.0], "amount": [10000.0]}
                 ).write_parquet(part / "part.parquet")
    assert load_breadth(env) is None


def test_breadth_api_rebuild_and_get(env):
    c = _client()
    # 未计算 -> 404
    r = c.get("/api/market/breadth")
    assert r.status_code == 404
    # 显式重建 -> 成功
    r = c.post("/api/market/breadth/rebuild")
    assert r.status_code == 200
    assert r.json()["total_days"] == 3
    # 读取: 默认 250 上限
    r = c.get("/api/market/breadth")
    assert r.status_code == 200
    body = r.json()
    assert body["total_days"] == 3
    assert len(body["rows"]) == 3
    assert body["as_of"] == body["rows"][-1]["date"]
    row = body["rows"][-1]
    assert row["pct_above_ma20"] == pytest.approx(1.0)
    assert row["sample_count"] == 2
    # limit
    r = c.get("/api/market/breadth?limit=2")
    assert len(r.json()["rows"]) == 2
