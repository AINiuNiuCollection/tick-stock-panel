"""区间套验证器熔断 + 命中次级别日期标注 (需求2, 2026-11-23)。

覆盖两块:
1. IntervalNestVerifier 源不可用熔断 — 与 SublevelVerifier 同口径
   (连续 3 次取数失败 → 300s 冷却, 每窗口一次探测);
   开启命中标注后每个 B1/B2 命中都触发次级别取数, 无熔断会复现
   #141 同款全市场刷屏。
2. ScanService._annotate_sub_dt — 命中截断后逐只标注 NestResult.sub_div_end;
   未确认/无验证器/单点异常均静默降级, 不影响命中本身。
"""
from __future__ import annotations

import sys
import types
from datetime import date, datetime

import polars as pl

import app.custom.czsc.adapters.kline.multilevel as multilevel
from app.custom.czsc.adapters.kline.source import KlineResult, empty_kline
from app.custom.czsc.application.scanner import ScanService
from app.custom.czsc.domain.interval_nest import NestResult
from app.custom.czsc.schemas import ScanHit


class _ScriptedChain:
    """按脚本依次响应 fetch: Exception → 抛出; 其他 → 原样返回。"""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0

    def fetch(self, symbol: str, freq: str, start, end):
        self.calls += 1
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        return step


def _install_stub(monkeypatch) -> None:
    """注入 czsc 桩: 测试不依赖真实 czsc 库是否安装。
    转换恒返回空 → 非空帧走 "数据不足" 分支, 不算源失败 (与 sublevel 测试同款)。"""
    monkeypatch.setitem(
        sys.modules, "czsc", types.SimpleNamespace(CZSC=object)
    )
    monkeypatch.setattr(multilevel, "to_raw_bars", lambda frame, freq: [])


def _nonempty_result() -> KlineResult:
    df = pl.DataFrame({
        "dt": [pl.datetime(2026, 1, 5, 10, 0)],
        "open": [10.0], "high": [10.5], "low": [9.8],
        "close": [10.2], "vol": [1000.0], "amount": [10200.0],
    })
    return KlineResult(frame=df, source="test")


# ===== IntervalNestVerifier 熔断 =====

def test_nest_consecutive_source_failures_trigger_cooldown(monkeypatch):
    _install_stub(monkeypatch)
    chain = _ScriptedChain([RuntimeError("net down")] * 10)
    v = multilevel.IntervalNestVerifier(chain)

    # 前 3 次: 每次都真实触链并失败 (返回未确认 NestResult, 不是 None)
    for i in range(3):
        nr = v.verify("600519.SH", "日线", date(2026, 1, i + 1), "down")
        assert isinstance(nr, NestResult) and nr.confirmed is False
        assert nr.source_unavailable is True  # G: 取数异常 → 源失败标记
    assert chain.calls == 3
    assert v._cooldown_until > 0  # 熔断已进入冷却

    # 第 4 次: 冷却期内直接返回降级结果, 不再触链
    nr = v.verify("600519.SH", "日线", date(2026, 2, 1), "down")
    assert nr.confirmed is False and "冷却" in nr.note
    assert nr.source_unavailable is True  # G: 冷却降级同样标源失败
    assert chain.calls == 3


def test_nest_cooldown_expiry_probes_once_then_rearms(monkeypatch):
    _install_stub(monkeypatch)
    chain = _ScriptedChain([RuntimeError("net down")] * 10)
    v = multilevel.IntervalNestVerifier(chain)
    for i in range(3):
        v.verify("600519.SH", "日线", date(2026, 1, i + 1), "down")
    assert chain.calls == 3

    # 模拟冷却结束: 下一次 verify 作为探测, 真实触链一次
    v._cooldown_until = 0.0
    v.verify("600519.SH", "日线", date(2026, 2, 1), "down")
    assert chain.calls == 4
    assert v._cooldown_until > 0  # 探测仍失败 → 重新进入冷却

    # 冷却期内后续候选不再触链 (每窗口最多一次外呼)
    v.verify("600519.SH", "日线", date(2026, 2, 2), "down")
    assert chain.calls == 4


def test_nest_non_source_failure_resets_streak(monkeypatch):
    _install_stub(monkeypatch)
    chain = _ScriptedChain([
        RuntimeError("net down"),      # 源失败 streak=1
        RuntimeError("net down"),      # 源失败 streak=2
        _nonempty_result(),            # 有数据但转换不足 → 非源失败, streak 归零
        RuntimeError("net down"),      # 源失败 streak=1 → 不触发熔断
    ])
    v = multilevel.IntervalNestVerifier(chain)

    v.verify("600519.SH", "日线", date(2026, 1, 1), "down")
    v.verify("600519.SH", "日线", date(2026, 1, 2), "down")
    v.verify("600519.SH", "日线", date(2026, 1, 3), "down")
    assert v._fail_streak == 0
    assert v._cooldown_until == 0.0  # 未达阈值, 无熔断

    # 第 4 次仍会触链 (streak 已被非源失败归零, 未进冷却)
    v.verify("600519.SH", "日线", date(2026, 1, 4), "down")
    assert chain.calls == 4
    assert v._cooldown_until == 0.0


def test_nest_empty_frame_counts_as_source_failure(monkeypatch):
    _install_stub(monkeypatch)
    chain = _ScriptedChain([KlineResult(frame=empty_kline(), source="test")] * 10)
    v = multilevel.IntervalNestVerifier(chain)

    for i in range(3):
        nr = v.verify("600519.SH", "日线", date(2026, 1, i + 1), "down")
        assert nr.confirmed is False
        assert nr.source_unavailable is True  # G: 全源空帧 → 源失败标记
    assert chain.calls == 3
    assert v._cooldown_until > 0  # 全源空帧与异常同样计入熔断


# ===== ScanService._annotate_sub_dt 标注 =====

def _hit(symbol: str = "600519.SH", dt: str = "2026-11-12T00:00:00") -> ScanHit:
    return ScanHit(symbol=symbol, freq="日线", type="B1", dt=dt, price=12.34)


class _StubNest:
    """verify 按构造脚本返回/抛出, 记录调用参数供断言。"""

    def __init__(self, result: object = None) -> None:
        self.result = result
        self.calls: list[tuple[str, str, str, str]] = []

    def verify(self, symbol: str, freq: str, edt, direction: str):
        self.calls.append((symbol, freq, str(edt), direction))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_annotate_sets_sub_dt_on_confirmed():
    nest = _StubNest(NestResult(
        True, "30分钟",
        sub_div_start=datetime(2026, 11, 10, 10, 0),
        sub_div_end=datetime(2026, 11, 13, 15, 0),
        sub_ratio=0.62,
    ))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit(), _hit(symbol="000001.SZ", dt="2026-11-05T00:00:00")]
    svc._annotate_sub_dt(hits)

    assert hits[0].sub_dt == "2026-11-13"
    assert hits[1].sub_dt == "2026-11-13"
    # 方向映射: 买点 → 次级别向下背驰
    assert nest.calls == [
        ("600519.SH", "日线", "2026-11-12T00:00:00", "down"),
        ("000001.SZ", "日线", "2026-11-05T00:00:00", "down"),
    ]


def test_annotate_skips_unconfirmed():
    nest = _StubNest(NestResult(False, "30分钟", note="区间套未确认"))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit()]
    svc._annotate_sub_dt(hits)
    assert hits[0].sub_dt is None  # 未确认 → 不标注


def test_annotate_without_nest_verifier_noop():
    # 分析器未暴露 nest_verifier (如旧配置未注入区间套) → 静默跳过
    svc = ScanService(analyzer=types.SimpleNamespace())
    hits = [_hit()]
    svc._annotate_sub_dt(hits)  # 不应抛异常
    assert hits[0].sub_dt is None


def test_annotate_exception_swallowed():
    nest = _StubNest(RuntimeError("sublevel source down"))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit(), _hit(symbol="000001.SZ")]
    svc._annotate_sub_dt(hits)  # 单点异常不中断后续标注
    assert hits[0].sub_dt is None
    assert hits[1].sub_dt is None
    assert len(nest.calls) == 2


def test_annotate_confirmed_but_no_sub_div_end():
    # 确认但 sub_div_end 为空 (理论不可达, 防御性) → 不标注
    nest = _StubNest(NestResult(True, "30分钟", note="确认"))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit()]
    svc._annotate_sub_dt(hits)
    assert hits[0].sub_dt is None


# ===== G (2026-11-23): 源不可用标记 =====

def test_annotate_marks_source_unavailable_and_counts():
    # 源级失败 → hit.sub_source_unavailable=True + 返回计数; 不标 sub_dt
    nest = _StubNest(NestResult(
        False, "30分钟", note="次级别数据为空(数据源不可用)", source_unavailable=True,
    ))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit(), _hit(symbol="000001.SZ")]
    unavailable = svc._annotate_sub_dt(hits)
    assert unavailable == 2
    assert all(h.sub_source_unavailable for h in hits)
    assert all(h.sub_dt is None for h in hits)


def test_annotate_unconfirmed_with_data_not_marked():
    # "有数据但未确认" 不算源失败 → 不置标记, 计数 0 (维持 fail-closed)
    nest = _StubNest(NestResult(False, "30分钟", note="区间套未确认"))
    svc = ScanService(analyzer=types.SimpleNamespace(nest_verifier=nest))
    hits = [_hit()]
    unavailable = svc._annotate_sub_dt(hits)
    assert unavailable == 0
    assert hits[0].sub_source_unavailable is False
