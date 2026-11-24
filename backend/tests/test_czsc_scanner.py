"""B1/B2 选股扫描器单元测试 — 用 mock analyzer 隔离算法, 只测编排逻辑。"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from app.custom.czsc.application.scanner import ScanService, get_scan_progress
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


class _Bar:
    """年龄计数只读 .dt。"""
    __slots__ = ("dt",)

    def __init__(self, dt: datetime) -> None:
        self.dt = dt


def _daily_bars(end: date, days: int = 45) -> list[_Bar]:
    """[end-days, end] 逐日 K 线 (年龄按根数计, 供 _extract_hits 真实路径)。"""
    end_dt = end if isinstance(end, datetime) else datetime(end.year, end.month, end.day)
    return [_Bar(end_dt - timedelta(days=i)) for i in range(days, -1, -1)]


class FakeAnalyzer:
    """按 symbol 返回预置 bs_points, 可注入异常; bars 默认逐日生成可覆盖。"""

    def __init__(
        self,
        mapping: dict[str, list[BsPointItem]],
        errors: dict[str, str] | None = None,
        bars: list[_Bar] | None = None,
    ) -> None:
        self.mapping = mapping
        self.errors = errors or {}
        self.bars = bars
        self.calls: list[str] = []

    def analyze(self, req) -> dict:
        self.calls.append(req.symbol)
        if req.symbol in self.errors:
            raise RuntimeError(self.errors[req.symbol])
        zs = [ZsItem(zs_range=[8.0, 9.0], start_dt="2026-01-01", end_dt="2026-02-01")]
        end = getattr(req, "end", None) or date(2026, 11, 20)
        bars = self.bars if self.bars is not None else _daily_bars(end)
        return {
            "symbol": req.symbol, "symbol_name": None, "freq": req.freq,
            "bs_points": list(self.mapping.get(req.symbol, [])),
            "zs_list": zs,
            "bars": bars,
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


def test_scan_signal_age_counts_weekly_bars():
    """周线: 年龄按周K线根数 — 信号在 10-30 那根周K, 之后 11-06/11-13/11-20 共 3 根。"""
    fridays = [
        datetime(2026, 10, 30, 15, 0), datetime(2026, 11, 6, 15, 0),
        datetime(2026, 11, 13, 15, 0), datetime(2026, 11, 20, 15, 0),
    ]
    fake = FakeAnalyzer(
        {"000001.SZ": [_bp("2026-10-30 15:00:00", "B1")]},
        bars=[_Bar(d) for d in fridays],
    )
    svc = ScanService(analyzer=fake)
    r = svc.scan(_req(symbols=("000001.SZ",), freq="周线", max_signal_age=3))
    assert r.total == 1
    assert r.hits[0].signal_age_days == 3
    # 阈值 2 根周K → 3 根已超龄, 过滤
    r2 = svc.scan(_req(symbols=("000001.SZ",), freq="周线", max_signal_age=2))
    assert r2.total == 0


def test_scan_signal_age_skips_non_trading_days():
    """日线: 信号 11-13(周五), 交易日 11-16..11-20 → 年龄 5 根 (周末 2 个自然日不计)。"""
    trading = [datetime(2026, 11, d, 15, 0) for d in (12, 13, 16, 17, 18, 19, 20)]
    fake = FakeAnalyzer(
        {"000001.SZ": [_bp("2026-11-13 15:00:00", "B1")]},
        bars=[_Bar(d) for d in trading],
    )
    svc = ScanService(analyzer=fake)
    r = svc.scan(_req(symbols=("000001.SZ",), max_signal_age=5))
    assert r.total == 1
    assert r.hits[0].signal_age_days == 5
    r2 = svc.scan(_req(symbols=("000001.SZ",), max_signal_age=4))
    assert r2.total == 0


def test_scan_signal_age_falls_back_to_calendar_days_without_bars():
    """防御: analyze 结果无 bars 时回退自然日口径 (2026-11-23 之前的旧行为)。"""
    as_of = date(2026, 11, 20)

    class NoBarsAnalyzer:
        def analyze(self, req) -> dict:
            return {
                "symbol": req.symbol, "symbol_name": None, "freq": req.freq,
                "bs_points": [_bp((as_of - timedelta(days=2)).isoformat(), "B1")],
                "zs_list": [], "bars": None,
            }

    svc = ScanService(analyzer=NoBarsAnalyzer())
    r = svc.scan(_req(symbols=("000001.SZ",), max_signal_age=2))
    assert r.total == 1
    assert r.hits[0].signal_age_days == 2


def test_scan_min_divergence_hits():
    """P1-1 (2026-11-24) 语义: B1 恒参与过滤; structural 模式下 B2 的盘整背驰
    只是置信度标注 (divergence_pass 可为空), 不参与过滤; strict 模式维持过滤。"""
    as_of = date(2026, 11, 20)
    recent = (as_of - timedelta(days=1)).isoformat()
    fake = FakeAnalyzer({
        "000001.SZ": [
            _bp(recent, "B1", passes=["macd_area", "dif"]),
            _bp(recent, "B2", passes=["dif"]),
        ],
    })
    svc = ScanService(analyzer=fake)
    # structural (默认): B2 仅 1 命中仍保留 — 过滤只作用于 B1
    assert svc.scan(_req(symbols=("000001.SZ",), min_divergence_hits=2)).total == 2
    # strict: B2 盘整背驰是必要条件, 1 命中 < 2 被过滤
    strict_req = replace(
        _req(symbols=("000001.SZ",), min_divergence_hits=2),
        divergence=replace(
            _req(symbols=("000001.SZ",), min_divergence_hits=2).divergence,
            bs_output_mode="strict",
        ),
    )
    assert svc.scan(strict_req).total == 1
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


def test_scan_publishes_total_before_first_symbol_and_marks_done():
    """前端依赖 0/total 立即出现来估算等待窗口。"""
    seen: list[dict] = []

    class ProbeAnalyzer(FakeAnalyzer):
        def analyze(self, req) -> dict:
            seen.append(get_scan_progress())
            return super().analyze(req)

    svc = ScanService(analyzer=ProbeAnalyzer({}))
    svc.scan(_req())
    assert seen[0]["active"] is True
    assert seen[0]["done"] == 0
    assert seen[0]["total"] == 2
    assert get_scan_progress()["active"] is False


def test_scan_clears_progress_on_unexpected_error(monkeypatch):
    svc = ScanService(analyzer=FakeAnalyzer({}))

    def boom(_hits):
        raise RuntimeError("boom")

    monkeypatch.setattr(svc, "_annotate_sub_dt", boom)
    with pytest.raises(RuntimeError, match="boom"):
        svc.scan(_req())
    assert get_scan_progress()["active"] is False
