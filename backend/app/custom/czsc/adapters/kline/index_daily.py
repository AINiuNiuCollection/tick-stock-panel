"""本地指数日K数据源 — 读取盘后管道同步的 kline_index_daily parquet。

大盘研究页 (docs/index_tracker_design_2026-11-27.md) P0-2: 上证指数
1990→今全历史已由 scripts/backfill_market_daily.py 深回填, 本源把指数
分区接入缠论取数链, 让缠论引擎 (月/周/日线分析、买卖点) 可直接分析
指数, 无需网络源。

与 LocalDailyKlineSource 的差异:
    - 只服务白名单指数 symbol (精确匹配含后缀), 不做后缀推断 ——
      "000001" 无后缀是平安银行 (SZ 股票), 绝不能推断成上证指数;
    - 指数无复权/无 enriched MACD 列, MACD 由服务层 fallback 计算;
    - 白名单外 symbol 一律返回 None, 落回链上下一个源, 对个股零影响。
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import polars as pl

from app.config import settings

from .resample import resample_daily_frame

logger = logging.getLogger(__name__)

_DAILY_FREQS = ("日线", "周线", "月线")
_MAX_STALE_DAYS = 4

_PARTITION_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")

# 白名单: 本地分区中有深度历史的分析用指数。新增对照指数时在此扩展。
INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "000001.SH",  # 上证综合
        "000016.SH",  # 上证50
        "000300.SH",  # 沪深300
        "000905.SH",  # 中证500
        "000852.SH",  # 中证1000
        "399001.SZ",  # 深证成指
        "399006.SZ",  # 创业板指
    }
)


class IndexDailyKlineSource:
    name = "index_daily"

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(settings.data_dir) / "kline_index_daily"

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        if freq not in _DAILY_FREQS:
            return None
        if symbol not in INDEX_SYMBOLS:
            return None
        if not self._root.exists():
            return None
        try:
            return self._fetch_daily(symbol, freq, start, end)
        except Exception as exc:  # noqa: BLE001 — 本地读失败降级到链上下一个源
            logger.warning("index_daily fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_daily(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        files: list[Path] = []
        for entry in sorted(self._root.iterdir()):
            m = _PARTITION_RE.match(entry.name)
            if not m:
                continue
            d = date.fromisoformat(m.group(1))
            if start <= d <= end:
                part = entry / "part.parquet"
                if part.exists():
                    files.append(part)
        if not files:
            return None

        df = pl.read_parquet(files)
        df = df.filter(
            (pl.col("symbol") == symbol)
            & (pl.col("date") >= start)
            & (pl.col("date") <= end)
        ).select(["date", "open", "high", "low", "close", "volume", "amount"])
        if df.is_empty():
            return None

        # 新鲜度: 本地最大日期距 end 超过容差 → 过旧, 交给网络源
        max_d = df["date"].max()
        if (end - max_d).days > _MAX_STALE_DAYS:
            return None

        out = df.rename({"date": "dt", "volume": "vol"}).sort("dt")
        # 周线/月线: 分区是日K副本, 按级别聚合 (与 local_daily 同修复口径)
        out = resample_daily_frame(out, freq)
        keep = [c for c in ("dt", "open", "high", "low", "close", "vol", "amount") if c in out.columns]
        return out.select(keep)
