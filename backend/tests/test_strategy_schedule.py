"""策略每日定时筛选调度测试。"""
from __future__ import annotations

import json

import pytest

from app.services import strategy_schedule as ss


class StubScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}

    def add_job(self, fn, **kwargs):
        self.jobs[kwargs["id"]] = kwargs

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


@pytest.fixture(autouse=True)
def _tmp_schedules(tmp_path, monkeypatch):
    path = tmp_path / "user_data" / "strategy_schedules.json"
    monkeypatch.setattr(ss, "_SCHEDULES_PATH", path)
    yield
    if path.exists():
        path.unlink()


def test_set_and_get_schedule(tmp_path):
    entry = ss.set_schedule("s1", enabled=True, hour=17, minute=30)
    assert entry == {"enabled": True, "hour": 17, "minute": 30, "last_run": None}
    got = ss.get_schedule("s1")
    assert got is not None and got["hour"] == 17 and got["enabled"] is True
    # 持久化到磁盘
    data = json.loads((tmp_path / "user_data" / "strategy_schedules.json").read_text(encoding="utf-8"))
    assert "s1" in data


def test_set_schedule_invalid_time():
    with pytest.raises(ValueError):
        ss.set_schedule("s1", enabled=True, hour=24, minute=0)
    with pytest.raises(ValueError):
        ss.set_schedule("s1", enabled=True, hour=8, minute=60)


def test_record_run_preserves_entry():
    ss.set_schedule("s1", enabled=True, hour=9, minute=0)
    ss.record_run("s1", ok=True, total=12)
    entry = ss.get_schedule("s1")
    assert entry["last_run"]["ok"] is True
    assert entry["last_run"]["total"] == 12
    assert entry["enabled"] is True and entry["hour"] == 9
    ss.record_run("s1", ok=False, error="boom")
    assert ss.get_schedule("s1")["last_run"]["error"] == "boom"


def test_record_run_ignores_unknown_strategy():
    ss.record_run("nope", ok=True, total=1)  # 不抛异常即可
    assert ss.get_schedule("nope") is None


def test_sync_job_register_and_remove():
    stub = StubScheduler()
    ss.set_schedule("s1", enabled=True, hour=16, minute=0)
    ss.sync_job(stub, "s1")
    job = stub.jobs["strategy_schedule_s1"]
    assert job["args"] == ["s1"]
    assert "mon-fri" in str(job["trigger"])
    # 禁用后移除
    ss.set_schedule("s1", enabled=False, hour=16, minute=0)
    ss.sync_job(stub, "s1")
    assert "strategy_schedule_s1" not in stub.jobs


def test_restore_scheduled_jobs():
    stub = StubScheduler()
    ss.set_schedule("a", enabled=True, hour=8, minute=30)
    ss.set_schedule("b", enabled=False, hour=9, minute=30)
    n = ss.restore_scheduled_jobs(stub)
    assert n == 1
    assert list(stub.jobs.keys()) == ["strategy_schedule_a"]
    assert stub.jobs["strategy_schedule_a"]["args"] == ["a"]
