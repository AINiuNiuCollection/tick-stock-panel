"""market data 按日分区扫描缓存测试 — 指纹失效保证新分区可见 (无陈旧风险)。"""
from datetime import date

import polars as pl

from app.config import settings
from app.custom.market.data import load_index_daily


def _write_partition(root, dt: date, symbol: str = "000001.SH", close: float = 100.0):
    d = root / "kline_index_daily" / f"date={dt.isoformat()}" / "part.parquet"
    d.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": [symbol],
            "date": [dt],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [1000.0],
            "amount": [close * 1000],
        }
    ).write_parquet(d)


def test_new_partition_visible_after_cache(monkeypatch, tmp_path):
    """关键正确性: 已缓存后再回填新分区, 下次 load 必须读到 (指纹失效)。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_partition(tmp_path, date(2024, 1, 2))
    df1 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df1.height == 1

    _write_partition(tmp_path, date(2024, 1, 3))
    df2 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df2.height == 2


def test_cache_hit_returns_same_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_partition(tmp_path, date(2024, 1, 2), close=1234.5)
    df1 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    df2 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df1.height == df2.height == 1
    assert df1["close"][0] == df2["close"][0] == 1234.5


def test_rewritten_partition_invalidates(monkeypatch, tmp_path):
    """同分区文件被重写 (mtime 变化) 也必须失效。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _write_partition(tmp_path, date(2024, 1, 2), close=100.0)
    df1 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df1["close"][0] == 100.0

    _write_partition(tmp_path, date(2024, 1, 2), close=200.0)
    df2 = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df2["close"][0] == 200.0


def test_empty_root_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    df = load_index_daily("000001.SH", date(1990, 1, 1), date(2100, 1, 1))
    assert df.is_empty()
