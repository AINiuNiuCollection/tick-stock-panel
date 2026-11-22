from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.custom.czsc import routes as czsc_routes
from app.custom.czsc.errors import AnalyzerError
from app.custom.czsc.schemas import AnalyzeResult

pytest.importorskip("czsc")


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(czsc_routes.build_router())
    return TestClient(app)


def test_health_and_capabilities():
    client = _client()
    health = client.get("/api/czsc/health")
    assert health.status_code == 200
    assert health.headers["X-Czsc-Api-Version"] == "1"
    assert health.json()["czsc_native_available"] is True

    capabilities = client.get("/api/czsc/capabilities")
    assert capabilities.json()["available"] is True


def test_analyze_serializes(monkeypatch):
    async def fake_analyze(request):
        return {
            "symbol": request.symbol,
            "symbol_name": None,
            "freq": request.freq,
            "bar_count": 0,
            "fx_list": [],
            "bi_list": [],
            "zs_list": [],
            "bars": [],
            "macd": [],
            "mas": [],
            "bs_points": [],
            "signals": {},
            "warnings": None,
            "source": "fake",
            "cached": False,
        }

    monkeypatch.setattr(czsc_routes, "analyze_async", fake_analyze)
    response = _client().get(
        "/api/czsc/analyze",
        params={"symbol": "600000.SH", "features": "fx,bi", "ma_periods": "5,20"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["bar_count"] == 0
    assert body["mas"] == []


def test_analyze_error_maps_to_503(monkeypatch):
    async def boom(request):
        raise AnalyzerError("NO_DATA", "no data")

    monkeypatch.setattr(czsc_routes, "analyze_async", boom)
    response = _client().get("/api/czsc/analyze", params={"symbol": "600000.SH"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "NO_DATA"


def test_disabled_router(monkeypatch):
    monkeypatch.setattr(settings, "czsc_enabled", False)
    response = _client().get("/api/czsc/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CZSC_DISABLED"


def test_refresh_clears_analysis_cache(monkeypatch):
    import polars as pl

    from app.custom.czsc.application.cache import AnalysisCache
    from app.custom.czsc.application.service import AnalyzeService, set_default_service

    cache = AnalysisCache()
    cache.put(("stale",), {"bar_count": 1})
    set_default_service(AnalyzeService(chain=None, cache=cache))  # type: ignore[arg-type]
    df = pl.DataFrame(
        {
            "dt": [datetime(2024, 1, 2)],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "vol": [1.0],
            "amount": [1.0],
        }
    )
    monkeypatch.setattr(czsc_routes, "_fetch_kline", lambda *args: (df, "fake"))
    try:
        response = _client().post("/api/czsc/data/refresh", json={"symbol": "600000.SH"})
        assert response.status_code == 200
        assert response.json()["cached_bars"] == 1
        assert len(cache) == 0
    finally:
        set_default_service(None)


def test_contract_fields_match_frontend():
    expected = set(AnalyzeResult.model_fields)
    api_ts = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "api.ts"
    text = api_ts.read_text(encoding="utf-8")
    block = text.split("export interface CzscAnalyzeResult {", 1)[1].split("}", 1)[0]
    for field in expected:
        assert field in block, f"frontend CzscAnalyzeResult missing field: {field}"
