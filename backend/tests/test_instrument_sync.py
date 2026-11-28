"""instrument_sync 防缩水守卫测试 (2026-11-24 深市换手率回归)。

背景: TickFlow 单交易所 503 时旧逻辑拿部分成功 (仅沪市) 的残缺快照
整体覆盖全量 → 深市 float_shares 丢失 → enriched 深市换手率全 null →
换手率基础过滤静默排除整市。守卫语义:
  - tickflow 路径逐交易所合并: 失败交易所保留旧快照行 (原 as_of)
  - 三所全失败 → 返回 0 不动快照
  - provider 整体路径: 新行数 < 现存 80% 时拒绝覆盖
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from app.services import instrument_sync


def _item(symbol: str, exchange: str) -> dict:
    return {
        "symbol": symbol,
        "name": f"测试{symbol[:6]}",
        "code": symbol.split(".")[0],
        "exchange": exchange,
        "region": "CN",
        "type": "stock",
        "ext": {
            "listing_date": "2020-01-01",
            "total_shares": 1e9,
            "float_shares": 8e8,
            "tick_size": 0.01,
            "limit_up": 11.0,
            "limit_down": 9.0,
        },
    }


class _FakeTickflow:
    """按 exchange → 是否抛错/返回空 可配置的假 tickflow client。"""

    def __init__(self, fail: set[str], empty: set[str] | None = None):
        self._fail = fail
        self._empty = empty or set()
        self.exchanges = self

    def get_instruments(self, ex: str, instrument_type: str = "stock"):
        if ex in self._fail:
            raise RuntimeError("503 Service Unavailable")
        if ex in self._empty:
            return []
        return [_item(f"60000{i}.{ex}", ex) for i in range(1, 4)]


def _write_snapshot(data_dir: Path, rows: list[dict], as_of: date) -> None:
    df = pl.DataFrame(rows).with_columns(pl.lit(as_of).alias("as_of"))
    out = data_dir / "instruments" / "instruments.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    instrument_sync.atomic_write_parquet(df, out)


def _old_full_snapshot(data_dir: Path) -> None:
    """11-23 19:11 全量快照的模拟: 三市各 3 只, as_of=2026-11-23。

    行结构与生产一致 (走 _flatten_instruments, ext 已展开成平列)。
    """
    items = (
        [_item(f"60000{i}.SH", "SH") for i in range(1, 4)]
        + [_item(f"00000{i}.SZ", "SZ") for i in range(1, 4)]
        + [_item(f"92000{i}.BJ", "BJ") for i in range(1, 4)]
    )
    _write_snapshot(data_dir, instrument_sync._flatten_instruments(items), date(2026, 11, 23))


def test_partial_exchange_failure_keeps_old_rows(tmp_path, monkeypatch):
    """SZ/BJ 503 时: SH 更新为今天, SZ/BJ 保留旧快照行与原 as_of。"""
    _old_full_snapshot(tmp_path)
    monkeypatch.setattr(
        instrument_sync, "_fetch_instruments_via_provider", lambda: None
    )
    monkeypatch.setattr(
        instrument_sync, "get_client",
        lambda: _FakeTickflow(fail={"SZ", "BJ"}),
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    df = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")

    assert rows == 9  # 3 新 (SH) + 6 旧 (SZ/BJ)
    sh = df.filter(pl.col("symbol").str.ends_with(".SH"))
    sz = df.filter(pl.col("symbol").str.ends_with(".SZ"))
    bj = df.filter(pl.col("symbol").str.ends_with(".BJ"))
    # SH 本次拉取成功 → as_of 更新为今天
    assert sh.height == 3
    assert set(sh["as_of"].to_list()) == {date.today()}
    # SZ/BJ 保留旧行, as_of 维持旧快照日期 (陈旧优于缺失)
    assert sz.height == 3 and bj.height == 3
    assert set(sz["as_of"].to_list()) == {date(2026, 11, 23)}
    assert set(bj["as_of"].to_list()) == {date(2026, 11, 23)}
    # 保留下来的旧行 float_shares 完整 (换手率可算)
    assert sz["float_shares"].null_count() == 0


def test_all_exchanges_fail_leaves_snapshot_untouched(tmp_path, monkeypatch):
    """三所全失败 → 返回 0, 快照原样 (连 as_of 都不变)。"""
    _old_full_snapshot(tmp_path)
    before = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")
    monkeypatch.setattr(
        instrument_sync, "_fetch_instruments_via_provider", lambda: None
    )
    monkeypatch.setattr(
        instrument_sync, "get_client",
        lambda: _FakeTickflow(fail={"SH", "SZ", "BJ"}),
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    after = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")

    assert rows == 0
    assert before.equals(after)


def test_provider_shrink_guard_rejects_overwrite(tmp_path, monkeypatch):
    """provider 路径: 新行数 < 现存 80% → 拒绝覆盖, 保留旧快照。"""
    _old_full_snapshot(tmp_path)  # 现存 9 行
    monkeypatch.setattr(
        instrument_sync,
        "_fetch_instruments_via_provider",
        lambda: [_item(f"60000{i}.SH", "SH") for i in range(1, 4)],  # 3 行 < 9*0.8
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    df = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")

    assert rows == 0
    assert df.height == 9  # 旧快照原样


def test_provider_healthy_sync_overwrites(tmp_path, monkeypatch):
    """provider 路径: 行数充足 → 正常覆盖 (守卫不误伤)。"""
    _old_full_snapshot(tmp_path)
    provider_rows = (
        [_item(f"60000{i}.SH", "SH") for i in range(1, 4)]
        + [_item(f"00000{i}.SZ", "SZ") for i in range(1, 4)]
        + [_item(f"92000{i}.BJ", "BJ") for i in range(1, 4)]
    )
    monkeypatch.setattr(
        instrument_sync, "_fetch_instruments_via_provider", lambda: provider_rows
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    assert rows == 9


def test_first_sync_without_existing_snapshot(tmp_path, monkeypatch):
    """无现存快照 → 直接写入, 无守卫拦截。"""
    monkeypatch.setattr(
        instrument_sync, "_fetch_instruments_via_provider", lambda: None
    )
    monkeypatch.setattr(
        instrument_sync, "get_client", lambda: _FakeTickflow(fail=set())
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    df = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")

    assert rows == 9
    assert df.height == 9
    assert set(df["as_of"].to_list()) == {date.today()}


def test_empty_exchange_response_counts_as_failure(tmp_path, monkeypatch):
    """交易所返回空列表 (而非异常) 同样走保留旧快照路径。"""
    _old_full_snapshot(tmp_path)
    monkeypatch.setattr(
        instrument_sync, "_fetch_instruments_via_provider", lambda: None
    )
    monkeypatch.setattr(
        instrument_sync, "get_client",
        lambda: _FakeTickflow(fail=set(), empty={"SZ", "BJ"}),
    )
    rows = instrument_sync.sync_instruments(tmp_path)
    df = pl.read_parquet(tmp_path / "instruments" / "instruments.parquet")

    assert rows == 9  # 3 新 (SH) + 6 旧 (SZ/BJ)
    assert df.filter(pl.col("symbol").str.ends_with(".SZ")).height == 3
