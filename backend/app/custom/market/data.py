"""raw 分区日K读取 — 大盘研究专用数据入口。

不做指标计算、不走 enriched 路径 (enriched 只保留近一年滚动窗口),
直接 scan hive 分区拿全历史 8 列 (symbol,date,open,high,low,close,volume,amount)。
返回统一 schema: date(datetime), open/high/low/close(float), amount(float)。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import polars as pl

from app.config import settings

_PARTITION_RE = re.compile(r"^date=\d{4}-\d{2}-\d{2}$")

_COLUMNS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]

# 按日分区全历史扫描缓存: /api/market/events 系列每次请求都要读 ~8800 个分区小文件,
# 叠加层单页会触发 20+ 次 series 请求, 不缓存则串行 20+ 秒。
# 缓存键含数据指纹 (分区名 + mtime), 新回填分区/重写文件自动失效, 无陈旧风险。
_RAW_CACHE: dict[tuple[str, str], tuple[tuple[tuple[str, int], ...], pl.DataFrame]] = {}


def _list_partitions(root: Path) -> list[Path]:
    files: list[Path] = []
    if root.exists():
        for entry in sorted(root.iterdir()):
            if _PARTITION_RE.match(entry.name):
                part = entry / "part.parquet"
                if part.exists():
                    files.append(part)
    return files


def _scan_raw(root: Path, symbol: str) -> pl.DataFrame:
    """读取指定 symbol 的全历史 raw 日K; 无数据返回空表。"""
    files = _list_partitions(root)
    if not files:
        return pl.DataFrame(schema={c: pl.String for c in _COLUMNS})
    fingerprint = tuple((p.parent.name, p.stat().st_mtime_ns) for p in files)
    key = (str(root), symbol)
    hit = _RAW_CACHE.get(key)
    if hit is not None and hit[0] == fingerprint:
        return hit[1]
    df = pl.read_parquet(files)
    out = df.filter(pl.col("symbol") == symbol).select(_COLUMNS).sort("date")
    _RAW_CACHE[key] = (fingerprint, out)
    return out


def load_index_daily(symbol: str, start: date, end: date) -> pl.DataFrame:
    """指数日K (raw, 不复权)。symbol 须含后缀, 如 '000001.SH'。"""
    root = Path(settings.data_dir) / "kline_index_daily"
    df = _scan_raw(root, symbol)
    if df.is_empty():
        return df
    return df.filter((pl.col("date") >= start) & (pl.col("date") <= end))


def load_etf_daily(symbol: str, start: date, end: date) -> pl.DataFrame:
    """ETF 日K (raw, 不复权)。symbol 须含后缀, 如 '510300.SH'。"""
    root = Path(settings.data_dir) / "kline_etf_daily"
    df = _scan_raw(root, symbol)
    if df.is_empty():
        return df
    return df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
