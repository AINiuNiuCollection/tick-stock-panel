"""本地日K分区数据源 — 优先读盘后管道同步的 kline_daily_enriched parquet。

动机: 缠论逐股分析是网络密集场景 (300 只扫描), TickFlow/baostock 免费源
间歇性失败时单股取数可达数十秒 (SDK 超时 30s × 重试 3), 导致 run_preset
整体超时。本地分区是全市场日K的持久副本, 单股毫秒级。

新鲜度判定: 本地最大日期距请求 end 不超过 _MAX_STALE_DAYS 天才返回
(覆盖周末/节假日 + 盘后管道 1 天延迟); 数据过旧时返回 None, 让 chain
落到 primary/eastmoney 网络源, 正确性优先。

注意: force_refresh 语义不穿透到 chain 层, 本源始终优先本地数据;
需要强制联网刷新时请直接删除本地分区或走 /api/czsc/data/refresh。
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from app.config import settings

from ..indicators import attach_macd_from_pipeline

logger = logging.getLogger(__name__)

_DAILY_FREQS = ("日线", "周线", "月线")
_MAX_STALE_DAYS = 4  # 本地最大日期距 end 的最大容差 (自然日)

_PARTITION_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")


class LocalDailyKlineSource:
    name = "local_daily"

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(settings.data_dir) / "kline_daily_enriched"

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        if freq not in _DAILY_FREQS:
            return None
        if not self._root.exists():
            return None
        try:
            return self._fetch_daily(symbol, start, end)
        except Exception as exc:  # noqa: BLE001 — 本地读失败静默降级到网络源
            logger.warning("local_daily fetch failed for %s: %s", symbol, exc)
            return None

    def _fetch_daily(self, symbol: str, start: date, end: date) -> pl.DataFrame | None:
        # 收集覆盖 [start, end] 的分区目录 (分区名 date=YYYY-MM-DD)
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

        # 新鲜度: 本地最大日期距 end 超过容差 → 数据过旧, 交给网络源
        max_d = df["date"].max()
        if (end - max_d).days > _MAX_STALE_DAYS:
            return None

        out = df.rename({"date": "dt", "volume": "vol"}).sort("dt")
        out = attach_macd_from_pipeline(out)
        keep = [c for c in ("dt", "open", "high", "low", "close", "vol", "amount") if c in out.columns]
        keep += [c for c in ("macd_dif", "macd_dea", "macd_hist") if c in out.columns]
        return out.select(keep)
