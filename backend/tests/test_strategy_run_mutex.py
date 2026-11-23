"""需求C (2026-11-23): 定时触发与手动运行的并发互斥。

engine.run 维护进程级运行计数 (唯一登记点, 手动/批量/定时全路径收敛),
run_scheduled_strategy 据此在同策略运行中跳过本次, 避免共用 strategy_cache
的并发写入互相覆盖。
"""
from types import SimpleNamespace

import pytest

from app.services import strategy_schedule
from app.strategy import engine as engine_mod
from app.strategy.engine import (
    StrategyEngine,
    is_strategy_running,
    release_strategy_run,
    try_acquire_strategy_run,
)


@pytest.fixture(autouse=True)
def _clean_running_registry():
    """每个用例前后清空运行登记, 避免用例间串扰。"""
    with engine_mod._running_lock:
        engine_mod._running_counts.clear()
    yield
    with engine_mod._running_lock:
        engine_mod._running_counts.clear()


def test_try_acquire_rejects_while_running():
    assert try_acquire_strategy_run("s1") is True
    assert try_acquire_strategy_run("s1") is False  # 已在运行 → 拒绝
    release_strategy_run("s1")
    assert try_acquire_strategy_run("s1") is True  # 释放后可再登记
    release_strategy_run("s1")
    assert not is_strategy_running("s1")


def test_refcount_survives_nested_release():
    """定时侧 try_acquire + engine.run 内部登记 → 计数嵌套, 任一先释放不误清。"""
    assert try_acquire_strategy_run("s1")
    with engine_mod._running_lock:
        engine_mod._running_counts["s1"] = 2  # 模拟 engine.run 内部 +1
    release_strategy_run("s1")  # engine.run 先结束
    assert is_strategy_running("s1")  # 定时侧仍持有
    release_strategy_run("s1")
    assert not is_strategy_running("s1")


def test_engine_run_wrapper_marks_running(monkeypatch):
    """run() 执行期间登记可见, 结束后只释放自己那层, 预登记不误清。"""
    eng = StrategyEngine.__new__(StrategyEngine)
    seen = {}

    def fake_impl(self, strategy_id, context, pool=None, params=None, overrides=None):
        seen["during"] = is_strategy_running(strategy_id)
        return "RESULT"

    monkeypatch.setattr(StrategyEngine, "_run_impl", fake_impl)
    assert try_acquire_strategy_run("mx")  # 模拟定时侧预登记
    assert eng.run("mx", None) == "RESULT"
    assert seen["during"] is True
    assert is_strategy_running("mx")  # run 只释放自己那层, 预登记存活
    release_strategy_run("mx")
    assert not is_strategy_running("mx")


def test_scheduled_run_skips_when_strategy_running(monkeypatch):
    """同策略运行中 → 定时任务跳过: 不触后续链路、不回写 last_run。

    state.repo=None: 若互斥检查缺失, 代码会走到 repo.store 抛 AttributeError
    被兜底 except 捕获 → record_run 被调 + error 非 already running, 断言可区分。
    """
    engine_stub = SimpleNamespace(has=lambda sid: True)
    monkeypatch.setattr(
        strategy_schedule, "_app_state",
        SimpleNamespace(repo=None, strategy_engine=engine_stub),
    )
    recorded: list = []
    monkeypatch.setattr(strategy_schedule, "record_run", lambda *a, **k: recorded.append((a, k)))

    assert try_acquire_strategy_run("czsc_b1b2")  # 模拟手动运行持有中
    out = strategy_schedule.run_scheduled_strategy("czsc_b1b2")
    release_strategy_run("czsc_b1b2")

    assert out == {"ok": False, "skipped": True, "error": "already running"}
    assert recorded == []  # 跳过不算失败, 不回写 last_run
    assert not is_strategy_running("czsc_b1b2")


def test_scheduled_run_not_found_records_error(monkeypatch):
    """策略不存在时仍走 record_run(not found) — 互斥检查不拦截该路径。"""
    engine_stub = SimpleNamespace(has=lambda sid: False)
    monkeypatch.setattr(
        strategy_schedule, "_app_state",
        SimpleNamespace(repo=None, strategy_engine=engine_stub),
    )
    recorded: list = []
    monkeypatch.setattr(strategy_schedule, "record_run", lambda *a, **k: recorded.append((a, k)))

    out = strategy_schedule.run_scheduled_strategy("ghost")
    assert out == {"ok": False, "error": "strategy not found"}
    assert recorded and recorded[0][1].get("error") == "strategy not found"
