"""SublevelVerifier 源不可用熔断: 连续取数失败后应暂停触链, 冷却期返回 None。

背景: 全市场策略扫描时每个 B2/S2 候选都触发次级别取数; 分钟源整体不可用
(代理环境 baostock 恒败 + 东财空 body)时, 旧实现每个候选都重复完整失败
循环 (登录失败 + 3 次重试), 刷屏日志并拖慢扫描。
"""
from __future__ import annotations

import sys
import types
from datetime import date

import polars as pl

import app.custom.czsc.adapters.kline.sublevel as sublevel
from app.custom.czsc.adapters.kline.source import KlineResult, empty_kline


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


def _install_czsc_stub(monkeypatch) -> None:
    """注入 czsc 桩: 测试不依赖真实 czsc 库是否安装。"""
    monkeypatch.setitem(
        sys.modules, "czsc", types.SimpleNamespace(CZSC=object)
    )
    # 转换恒返回空 → 非空帧走 "数据不足" (None, False) 分支, 不算源失败
    monkeypatch.setattr(sublevel, "to_raw_bars", lambda frame, freq: [])


def _nonempty_result() -> KlineResult:
    df = pl.DataFrame({
        "dt": [pl.datetime(2026, 1, 5, 10, 0)],
        "open": [10.0], "high": [10.5], "low": [9.8],
        "close": [10.2], "vol": [1000.0], "amount": [10200.0],
    })
    return KlineResult(frame=df, source="test")


def test_consecutive_source_failures_trigger_cooldown(monkeypatch):
    _install_czsc_stub(monkeypatch)
    chain = _ScriptedChain([RuntimeError("net down")] * 10)
    v = sublevel.SublevelVerifier(chain)

    # 前 3 次: 每次都真实触链并失败
    for i in range(3):
        assert v.verify("600519.SH", "日线", date(2026, 1, i + 1)) is None
    assert chain.calls == 3
    assert v._cooldown_until > 0  # 熔断已进入冷却

    # 第 4 次 (新候选日期): 冷却期内直接返回 None, 不再触链
    assert v.verify("600519.SH", "日线", date(2026, 2, 1)) is None
    assert chain.calls == 3


def test_cooldown_expiry_probes_once_then_rearms(monkeypatch):
    _install_czsc_stub(monkeypatch)
    chain = _ScriptedChain([RuntimeError("net down")] * 10)
    v = sublevel.SublevelVerifier(chain)
    for i in range(3):
        v.verify("600519.SH", "日线", date(2026, 1, i + 1))
    assert chain.calls == 3

    # 模拟冷却结束: 下一次 verify 作为探测, 真实触链一次
    v._cooldown_until = 0.0
    assert v.verify("600519.SH", "日线", date(2026, 2, 1)) is None
    assert chain.calls == 4
    assert v._cooldown_until > 0  # 探测仍失败 → 重新进入冷却

    # 冷却期内后续候选不再触链 (每窗口最多一次外呼)
    v.verify("600519.SH", "日线", date(2026, 2, 2))
    assert chain.calls == 4


def test_non_source_failure_resets_streak(monkeypatch):
    _install_czsc_stub(monkeypatch)
    chain = _ScriptedChain([
        RuntimeError("net down"),      # 源失败 streak=1
        RuntimeError("net down"),      # 源失败 streak=2
        _nonempty_result(),            # 有数据但不足 → (None, False), streak 归零
        RuntimeError("net down"),      # 源失败 streak=1 → 不触发熔断
    ])
    v = sublevel.SublevelVerifier(chain)

    assert v.verify("600519.SH", "日线", date(2026, 1, 1)) is None
    assert v.verify("600519.SH", "日线", date(2026, 1, 2)) is None
    assert v.verify("600519.SH", "日线", date(2026, 1, 3)) is None
    assert v._fail_streak == 0
    assert v._cooldown_until == 0.0  # 未达阈值, 无熔断

    # 第 4 次仍会触链 (streak 已被非源失败归零, 未进冷却)
    assert v.verify("600519.SH", "日线", date(2026, 1, 4)) is None
    assert chain.calls == 4
    assert v._cooldown_until == 0.0


def test_memoized_key_skips_fetch(monkeypatch):
    _install_czsc_stub(monkeypatch)
    chain = _ScriptedChain([_nonempty_result()])
    v = sublevel.SublevelVerifier(chain)

    assert v.verify("600519.SH", "日线", date(2026, 1, 5)) is None
    assert v.verify("600519.SH", "日线", date(2026, 1, 5)) is None  # 同 key 命中 memo
    assert chain.calls == 1


def test_empty_frame_counts_as_source_failure(monkeypatch):
    _install_czsc_stub(monkeypatch)
    chain = _ScriptedChain([KlineResult(frame=empty_kline(), source="test")] * 10)
    v = sublevel.SublevelVerifier(chain)

    for i in range(3):
        assert v.verify("600519.SH", "日线", date(2026, 1, i + 1)) is None
    assert chain.calls == 3
    assert v._cooldown_until > 0  # 全源空帧与异常同样计入熔断
