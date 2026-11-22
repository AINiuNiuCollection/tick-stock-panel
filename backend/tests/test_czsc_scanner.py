"""B1/B2 选股扫描器单元测试 — 用 mock analyzer 隔离算法, 只测编排逻辑。"""
from __future__ import annotations

from datetime import date, timedelta

from app.custom.czsc.application.scanner import ScanService
from app.custom.czsc.config import (
    DEFAULT_SCAN_POOL,
    SCAN_SIGNAL_WHITELIST,
    ScanRequest,
)
from app.custom.czsc.schemas import BsPointItem, ZsItem


def _bp(dt: str, kind: str, direction: str = "买", passes: list[str] | None = None, zs_index: int = 0) -> BsPointItem:
    return BsPointItem(
        dt=dt, type=kind, direction=direction, price=10.0, bi_direction="向下",
        zs_index=zs_index, divergence_type="趋势背驰:macd_area+dif",
        divergence_pass=passes if passes is not None else ["macd_area", "dif"],
        definition_mode="practical", level="日线",
    )


class FakeAnalyzer:
    """按 symbol 返回预置 bs_points, 可注入异常。"""

    def __init__(self, mapping: dict[str, list[BsPointItem]], errors: dict[str, str] | None = None) -> None:
        self.mapping = mapping
        self.errors = errors or {}
        self.calls: list[str] = []

    def analyze(self, req) -> dict:
        self.calls.append(req.symbol)
        if req.symbol in self.errors:
            raise RuntimeError(self.errors[req.symbol])
        zs = [ZsItem(zs_range=[8.0, 9.0], start_dt="2026-01-01", end_dt="2026-02-01")]
        return {
            "symbol": req.symbol, "symbol_name": None, "freq": req.freq,
            "bs_points": list(self.mapping.get(req.symbol, [])),
            "zs_list": zs,
        }


def _req(**kwargs) -> ScanRequest:
    base = dict(
        symbols=("000001.SZ", "000002.SZ"),
        as_of=date(2026, 11, 20),
        freq="日线",
        max_workers=1,
        limit=50,
    )
    base.update(kwargs)
    return ScanRequest(**base).normalized()


def test_scan_request_normalization():
    req = ScanRequest(
        pool="invalid", symbols=("", " 600000.SH ", "600000.SH"),
        signal_types=("B1", "S1", "b2", "BAD"), order_by="bad",
        limit=9999, max_workers=999, lookback_days=1, max_signal_age=-3,
        min_divergence_hits=99,
    ).normalized()
    assert req.pool == DEFAULT_SCAN_POOL
    assert req.symbols == ("600000.SH",)
    assert req.signal_types == SCAN_SIGNAL_WHITELIST
    assert req.order_by == "dt_desc"
    assert req.limit == 500
    assert req.max_workers == 32
    assert req.lookback_days == 60
    assert req.max_signal_age == 0
    assert req.min_divergence_hits == 2


def test_scan_filters_only_b1_b2_and_buy_direction():
    as_of = date(2026, 11, 20)
    recent = (as_of - timedelta(days=1)).isoformat()
    fake = FakeAnalyzer({
        "000001.SZ": [
            _bp(recent, "B1", "买", ["macd_area", "dif"]),
            _bp(recent, "B3", "买"),
            _bp(recent, "B2", "买", ["dif"]),
            _bp(recent, "S1", "卖"),
            _bp(recent, "B1", "卖"),
        ],
        "000002.SZ": [],
    })
    svc = ScanService(analyzer=fake)
    result = svc.scan(_req())
    assert result.total == 2
    assert {h.type for h in result.hits} == {"B1", "B2"}
    assert all(h.direction == "买" for h in result.hits)
    assert all(h.symbol == "000001.SZ" for h in result.hits)


def test_scan_max_signal_age_filters_stale():
    as_of = date(2026, 11, 20)
    fake = FakeAnalyzer({
        "000001.SZ": [
            _bp((as_of - timedelta(days=2)).isoformat(), "B1"),
            _bp((as_of - timedelta(days=30)).isoformat(), "B2"),
        ],
    })
    svc = ScanService(analyzer=fake)
    result = svc.scan(_req(symbols=("000001.SZ",), max_signal_age=5))
    assert result.total == 1
    assert result.hits[0].signal_age_days == 2
    # 0 = 不限
    result_all = svc.scan(_req(symbols=("000001.SZ",), max_signal_age=0))
    assert result_all.total == 2


def test_scan_min_divergence_hits():
    as_of = date(2026, 11, 20)
    recent = (as_of - timedelta(days=1)).isoformat()
    fake = FakeAnalyzer({
        "000001.SZ": [
            _bp(recent, "B1", passes=["macd_area", "dif"]),
            _bp(recent, "B2", passes=["dif"]),
        ],
    })
    svc = ScanService(analyzer=fake)
    assert svc.scan(_req(symbols=("000001.SZ",), min_divergence_hits=2)).total == 1
    assert svc.scan(_req(symbols=("000001.SZ",), min_divergence_hits=1)).total == 2


def test_scan_order_and_limit():
    as_of = date(2026, 11, 20)
    fake = FakeAnalyzer({
        "000001.SZ": [
            _bp((as_of - timedelta(days=1)).isoformat(), "B1", passes=["dif"]),
            _bp((as_of - timedelta(days=2)).isoformat(), "B2", passes=["macd_area", "dif"]),
        ],
    })
    svc = ScanService(analyzer=fake)
    by_dt = svc.scan(_req(symbols=("000001.SZ",), order_by="dt_desc"))
    assert by_dt.hits[0].type == "B1"  # 更新在前
    by_div = svc.scan(_req(symbols=("000001.SZ",), order_by="divergence_desc"))
    assert by_div.hits[0].type == "B2"  # 命中数多在前
    limited = svc.scan(_req(symbols=("000001.SZ",), limit=1))
    assert limited.total == 1


def test_scan_error_isolation():
    as_of = date(2026, 11, 20)
    recent = (as_of - timedelta(days=1)).isoformat()
    fake = FakeAnalyzer(
        {"000002.SZ": [_bp(recent, "B1")]},
        errors={"000001.SZ": "NO_DATA"},
    )
    svc = ScanService(analyzer=fake)
    result = svc.scan(_req())
    assert result.total == 1
    assert "000001.SZ" in result.errors
    assert result.total_scanned == 2


def test_scan_rejects_full_market_minute_without_symbols(monkeypatch):
    # 注入假池, 避免测试触发真实 TickFlow 网络请求
    monkeypatch.setattr(
        "app.custom.czsc.application.scanner._get_pool",
        lambda pool_id: [f"{i:06d}.SZ" for i in range(300)],
    )
    svc = ScanService(analyzer=FakeAnalyzer({}))
    req = ScanRequest(symbols=(), freq="30分钟", max_symbols=None).normalized()
    result = svc.scan(req)
    assert result.total == 0
    assert "__params__" in result.errors
    assert "分钟级别" in result.errors["__params__"]


def test_scan_zs_range_and_definition_mode_propagated():
    as_of = date(2026, 11, 20)
    recent = (as_of - timedelta(days=1)).isoformat()
    fake = FakeAnalyzer({"000001.SZ": [_bp(recent, "B1")]})
    svc = ScanService(analyzer=fake)
    result = svc.scan(_req(symbols=("000001.SZ",)))
    hit = result.hits[0]
    assert hit.zs_range == [8.0, 9.0]
    assert hit.definition_mode == "practical"
    assert hit.divergence_pass == ["macd_area", "dif"]


def test_scan_params_summary_contains_divergence():
    fake = FakeAnalyzer({})
    svc = ScanService(analyzer=fake)
    result = svc.scan(_req())
    assert result.params["divergence"]["macd_area_mode"] == "split"
    assert result.params["signal_types"] == ["B1", "B2"]
