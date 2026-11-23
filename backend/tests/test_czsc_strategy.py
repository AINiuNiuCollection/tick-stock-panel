"""缠论 B1/B2 自定义策略测试 — mock czsc 扫描, 验证策略桥接逻辑。"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import polars as pl

from app.strategy.ai_generator import AIStrategyGenerator
from app.strategy.config import load_override
from app.strategy.engine import StrategyEngine

STRATEGY_PATH = Path(__file__).resolve().parents[2] / "data" / "strategies" / "custom" / "custom_czsc_b1b2.py"


def _load_strategy_module():
    spec = importlib.util.spec_from_file_location("custom_czsc_b1b2_test", STRATEGY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _history(symbols: list[str], as_of: date = date(2026, 11, 20)) -> pl.DataFrame:
    rows = []
    for s in symbols:
        for d in (date(2026, 11, 19), as_of):
            rows.append({
                "symbol": s, "date": d, "open": 10.0, "high": 10.5, "low": 9.5,
                "close": 10.0, "volume": 1e8, "amount": 5e8, "change_pct": 0.0,
                "name": s, "total_shares": 1e10, "float_shares": 8e9,
            })
    return pl.DataFrame(rows)


def test_strategy_passes_ast_safety():
    """策略文件必须通过 AST 安全校验 (含 app.custom.czsc 白名单子模块)。"""
    AIStrategyGenerator._validate_safety(STRATEGY_PATH.read_text(encoding="utf-8"))


def test_strategy_registered_with_correct_backend():
    engine = StrategyEngine(
        strategy_dirs=[STRATEGY_PATH.parent],
        override_loader=lambda sid: load_override(STRATEGY_PATH.parents[2], sid),
    )
    ids = [s["id"] for s in engine.list_strategies()]
    assert "custom_czsc_b1b2" in ids
    d = engine._strategies["custom_czsc_b1b2"]
    assert d.execution_backend == "python_history_legacy"
    assert d.filter_history_fn is not None
    param_ids = [p["id"] for p in d.meta["params"]]
    for required in (
        "freq", "signal_types", "max_signal_age", "bs_zs_pullback_base",
        "max_symbols", "bs_b1_sub_confirm",
    ):
        assert required in param_ids
    # B1 次级别确认默认开启 (2026-11-23 需求)
    b1_param = next(p for p in d.meta["params"] if p["id"] == "bs_b1_sub_confirm")
    assert b1_param["default"] is True


def test_filter_history_returns_only_hit_symbols(monkeypatch):
    """mock ScanService.scan: 只有 B1 命中, 断言 filter_history 只返回该 symbol 当日行。"""
    mod = _load_strategy_module()

    class FakeHit:
        def __init__(self, symbol, sub_dt=None, type_="B1", sub_source_unavailable=False):
            self.symbol = symbol
            self.type = type_
            self.dt = "2026-11-12"
            self.price = 12.34
            self.sub_dt = sub_dt  # 需求2: 次级别背驰点日期 (区间套下钻)
            self.sub_source_unavailable = sub_source_unavailable  # G: 源级失败标记

    class FakeResult:
        # B2 不受 B1 次级别确认开关影响 (无 sub_dt → 旧3段格式);
        # B1 带次级别日期 → 4段格式 (价格段占位)
        hits = (
            FakeHit("600000.SH", type_="B2"),
            FakeHit("600000.SH", sub_dt="2026-11-13"),
        )
        warnings = ()

    captured = {}

    class FakeScanService:
        def scan(self, req):
            captured["freq"] = req.freq
            captured["symbols"] = req.symbols
            captured["signal_types"] = req.signal_types
            captured["div_base"] = req.divergence.zs_pullback_base
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["600000.SH", "000001.SZ", "002027.SZ"])
    out, warnings = mod.filter_history(df, {"freq": "30分钟", "max_symbols": 3, "signal_types": "B1", "bs_zs_pullback_base": "zg"})
    assert warnings == []

    assert out.height == 1
    assert out["symbol"].to_list() == ["600000.SH"]
    assert out["date"].max() == date(2026, 11, 20)
    # 信号详情随行透出 (前端 B1/B2 信号列); 需求2: 有次级别日期 → 第4段,
    # 无次级别日期保持旧3段格式
    assert "czsc_signal" in out.columns
    assert out["czsc_signal"].to_list() == ["B2@2026-11-12@12.34, B1@2026-11-12@12.34@2026-11-13"]
    assert captured["freq"] == "30分钟"
    assert captured["signal_types"] == ("B1",)
    assert captured["div_base"] == "zg"
    assert len(captured["symbols"]) == 3


def test_b1_without_sub_dt_dropped_by_default(monkeypatch):
    """B1 次级别确认默认开启 (2026-11-23): 无 sub_dt 的 B1 丢弃; B2 与带确认的 B1 保留。"""
    mod = _load_strategy_module()

    class FakeHit:
        def __init__(self, type_, sub_dt=None, sub_source_unavailable=False):
            self.symbol = "600000.SH"
            self.type = type_
            self.dt = "2026-11-12"
            self.price = 12.34
            self.sub_dt = sub_dt
            self.sub_source_unavailable = sub_source_unavailable

    class FakeResult:
        hits = (FakeHit("B1"), FakeHit("B1", sub_dt="2026-11-13"), FakeHit("B2"))
        warnings = ()

    class FakeScanService:
        def scan(self, req):
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["600000.SH"])
    out, _warnings = mod.filter_history(df, {})  # 默认 bs_b1_sub_confirm=True
    assert out.height == 1
    assert out["czsc_signal"].to_list() == [
        "B1@2026-11-12@12.34@2026-11-13, B2@2026-11-12@12.34"
    ]


def test_b1_sub_confirm_disabled_keeps_unconfirmed_b1(monkeypatch):
    """关闭开关 (bs_b1_sub_confirm=False): 未确认 B1 也保留。"""
    mod = _load_strategy_module()

    class FakeHit:
        def __init__(self, type_, sub_dt=None, sub_source_unavailable=False):
            self.symbol = "600000.SH"
            self.type = type_
            self.dt = "2026-11-12"
            self.price = 12.34
            self.sub_dt = sub_dt
            self.sub_source_unavailable = sub_source_unavailable

    class FakeResult:
        hits = (FakeHit("B1"), FakeHit("B2"))
        warnings = ()

    class FakeScanService:
        def scan(self, req):
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["600000.SH"])
    out, _warnings = mod.filter_history(df, {"bs_b1_sub_confirm": False})
    assert out["czsc_signal"].to_list() == [
        "B1@2026-11-12@12.34, B2@2026-11-12@12.34"
    ]


def test_filter_history_empty_hits_returns_empty(monkeypatch):
    mod = _load_strategy_module()

    class FakeResult:
        hits = ()
        warnings = ()

    class FakeScanService:
        def scan(self, req):
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["600000.SH"])
    out, _warnings = mod.filter_history(df, {})
    assert out.is_empty()


def test_filter_history_caps_candidates_by_amount(monkeypatch):
    """max_symbols 截断: 只把成交额最大的 N 只交给 czsc 扫描。"""
    mod = _load_strategy_module()
    captured = {}

    class FakeResult:
        hits = ()
        warnings = ()

    class FakeScanService:
        def scan(self, req):
            captured["symbols"] = req.symbols
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["A.SZ", "B.SZ", "C.SZ"])
    df = df.with_columns(
        pl.when(pl.col("symbol") == "A.SZ").then(3e8)
        .when(pl.col("symbol") == "B.SZ").then(9e8)
        .otherwise(1e8).alias("amount")
    )
    mod.filter_history(df, {"max_symbols": 2})
    assert len(captured["symbols"]) == 2
    assert "B.SZ" in captured["symbols"]  # 成交额最大必入选


def test_b1_source_unavailable_retained_with_warning(monkeypatch):
    """G (2026-11-23): 次级别源不可用的 B1 保留 (不丢弃) 并返回警告;
    扫描层 warnings 也随元组透传。"""
    mod = _load_strategy_module()

    class FakeHit:
        def __init__(self, type_, sub_dt=None, sub_source_unavailable=False):
            self.symbol = "600000.SH"
            self.type = type_
            self.dt = "2026-11-12"
            self.price = 12.34
            self.sub_dt = sub_dt
            self.sub_source_unavailable = sub_source_unavailable

    scan_warning = "次级别(30分钟)数据源不可用, 1 个命中的区间套确认被跳过"
    FakeResult = type(
        "FakeResult", (), {
            "hits": (
                FakeHit("B1", sub_source_unavailable=True),  # 源不可用 → 保留
                FakeHit("B1"),                                # 有数据未确认 → 丢弃
                FakeHit("B1", sub_dt="2026-11-13"),           # 已确认 → 保留
            ),
            "warnings": (scan_warning,),
        }
    )

    class FakeScanService:
        def scan(self, req):
            return FakeResult()

    monkeypatch.setattr(mod, "ScanService", FakeScanService)
    df = _history(["600000.SH"])
    out, warnings = mod.filter_history(df, {})  # 默认 bs_b1_sub_confirm=True

    # 未确认 B1 被丢弃, 源不可用 B1 与已确认 B1 保留 (均旧3段格式)
    assert out["czsc_signal"].to_list() == [
        "B1@2026-11-12@12.34, B1@2026-11-12@12.34@2026-11-13"
    ]
    # 扫描层警告透传 + 源不可用保留计数警告
    assert scan_warning in warnings
    assert any("未经区间套确认即保留" in w for w in warnings)
