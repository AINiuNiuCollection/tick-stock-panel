"""ScreenerService.clamp_as_of 单元测试 — 方案B (2026-11-25):

17:00 截止规则的调用方侧钳制: as_of 为今天且 now<17:00 时钳到今天之前
最近的 enriched 分区日期; 盘后/历史日期/无更早分区时原样返回。
"""
from __future__ import annotations

from datetime import date, datetime

import app.services.screener as screener_mod
from app.services.screener import ScreenerService


class _FakeStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir


class _FakeRepo:
    def __init__(self, data_dir):
        self.store = _FakeStore(data_dir)


def _make_partitions(root, dates):
    enriched = root / "kline_daily_enriched"
    for d in dates:
        p = enriched / f"date={d.isoformat()}"
        p.mkdir(parents=True, exist_ok=True)
        (p / "part.parquet").touch()


class _FakeClock:
    """替身 datetime — 只需支持 now() 返回固定时间。"""

    def __init__(self, now: datetime):
        self._now = now

    def now(self):
        return self._now


def test_before_17_clamps_today_to_previous_partition(tmp_path, monkeypatch):
    today = date.today()
    prev = today.fromordinal(today.toordinal() - 1)
    _make_partitions(tmp_path, [prev, today])
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=10)))
    )
    assert svc.clamp_as_of(today) == prev


def test_at_or_after_17_keeps_today(tmp_path, monkeypatch):
    today = date.today()
    prev = today.fromordinal(today.toordinal() - 1)
    _make_partitions(tmp_path, [prev, today])
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=17)))
    )
    assert svc.clamp_as_of(today) == today


def test_historical_as_of_unchanged(tmp_path, monkeypatch):
    today = date.today()
    past = date(today.year - 1, 1, 5)
    _make_partitions(tmp_path, [past])
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=9)))
    )
    assert svc.clamp_as_of(past) == past


def test_no_prior_partition_returns_as_of(tmp_path, monkeypatch):
    today = date.today()
    _make_partitions(tmp_path, [today])  # 只有今日分区
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=9)))
    )
    assert svc.clamp_as_of(today) == today


def test_clamps_to_max_prior_partition_and_skips_invalid_names(tmp_path, monkeypatch):
    today = date.today()
    older = today.fromordinal(today.toordinal() - 3)
    prev = today.fromordinal(today.toordinal() - 1)
    enriched = tmp_path / "kline_daily_enriched"
    for name in (f"date={older.isoformat()}", f"date={prev.isoformat()}", "date=not-a-date"):
        p = enriched / name
        p.mkdir(parents=True, exist_ok=True)
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=10)))
    )
    assert svc.clamp_as_of(today) == prev


def test_missing_enriched_dir_returns_as_of(tmp_path, monkeypatch):
    today = date.today()
    svc = ScreenerService(_FakeRepo(tmp_path), asset_type="stock")
    monkeypatch.setattr(
        screener_mod, "datetime", _FakeClock(datetime.combine(today, datetime.min.time().replace(hour=10)))
    )
    assert svc.clamp_as_of(today) == today
