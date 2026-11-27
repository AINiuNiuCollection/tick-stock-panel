"""主工程 MarketDataProvider 取数 — 尊重用户在 preferences 中配置的数据源。

路由规则 (与主工程 kline_sync 一致):
    - 日线: preferences.get_daily_data_provider(); 自定义源需声明 daily 数据集,
      不可用/为空时回退内置 provider (TickFlow)。
    - 分钟: preferences.get_minute_data_provider(); 自定义源需声明 minute 数据集,
      失败/为空时回退内置 provider, 最终由 chain 走东财兜底。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import polars as pl

from ..indicators import attach_macd_from_pipeline
from .resample import resample_daily_frame

logger = logging.getLogger(__name__)

_DAILY_FREQS = ("日线", "周线", "月线")
_MINUTE_FREQ_MAP = {"5分钟": "5m", "15分钟": "15m", "30分钟": "30m", "60分钟": "60m"}


class PrimaryKlineSource:
    name = "primary"

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        try:
            from app.data_providers import custom as custom_sources
            from app.data_providers.registry import get_provider as get_builtin
            from app.services import preferences
        except ImportError as exc:
            logger.warning("primary provider infrastructure unavailable: %s", exc)
            return None

        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end, datetime.max.time().replace(microsecond=0))

        try:
            if freq in _DAILY_FREQS:
                raw = self._fetch_daily(
                    symbol, start_dt, end_dt, preferences, custom_sources, get_builtin
                )
            else:
                provider_freq = _MINUTE_FREQ_MAP.get(freq)
                if provider_freq is None:
                    logger.warning("primary provider unsupported freq: %s", freq)
                    return None
                raw = self._fetch_minute(
                    symbol,
                    start_dt,
                    end_dt,
                    provider_freq,
                    preferences,
                    custom_sources,
                    get_builtin,
                )
        except Exception as exc:
            logger.warning("primary provider fetch failed for %s: %s", symbol, exc)
            return None

        if raw is None or raw.is_empty():
            return None
        return self._normalize(raw, freq)

    def _fetch_daily(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        preferences: Any,
        custom_sources: Any,
        get_builtin: Any,
    ) -> pl.DataFrame:
        raw: pl.DataFrame | None = None
        pname = preferences.get_daily_data_provider()
        if pname and pname != "tickflow":
            try:
                if custom_sources.provider_has_dataset(pname, "daily"):
                    raw = custom_sources.get_provider(pname).get_daily(
                        symbols=[symbol],
                        start_time=start_dt,
                        end_time=end_dt,
                        asset_type="stock",
                    )
            except Exception as exc:
                logger.warning("custom daily provider %s failed for %s: %s", pname, symbol, exc)
                raw = None
        if raw is None or raw.is_empty():
            raw = get_builtin().get_daily(
                symbols=[symbol],
                start_time=start_dt,
                end_time=end_dt,
                asset_type="stock",
            )
        return raw

    def _fetch_minute(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        provider_freq: str,
        preferences: Any,
        custom_sources: Any,
        get_builtin: Any,
    ) -> pl.DataFrame:
        custom = None
        pname = preferences.get_minute_data_provider()
        if pname and pname != "tickflow":
            try:
                if custom_sources.provider_has_dataset(pname, "minute"):
                    custom = custom_sources.get_provider(pname)
            except Exception as exc:
                logger.debug("custom minute provider lookup failed: %s", exc)

        raw = pl.DataFrame()
        if custom is not None:
            try:
                raw = custom.get_minute(
                    symbols=[symbol],
                    start_time=start_dt,
                    end_time=end_dt,
                    asset_type="stock",
                    freq=provider_freq,
                )
                if raw is None or raw.is_empty():
                    logger.warning(
                        "custom minute provider %s returned empty for %s %s (%s ~ %s)",
                        pname,
                        symbol,
                        provider_freq,
                        start_dt,
                        end_dt,
                    )
                    raw = pl.DataFrame()
            except Exception as exc:
                logger.warning(
                    "custom minute provider %s fetch failed for %s: %s",
                    type(custom).__name__,
                    symbol,
                    exc,
                )
                raw = pl.DataFrame()
        if raw is None or raw.is_empty():
            raw = get_builtin().get_minute(
                symbols=[symbol],
                start_time=start_dt,
                end_time=end_dt,
                asset_type="stock",
                freq=provider_freq,
            )
        return raw

    def _normalize(self, raw: pl.DataFrame, freq: str) -> pl.DataFrame | None:
        try:
            df = raw
            rename_map: dict[str, str] = {}
            # baostock 分钟 provider 返回 datetime 列, 主工程日线返回 date 列,
            # 两者都需归一到内部契约 dt; 否则分钟结果会丢失时间轴, 阻塞级别递归。
            if "dt" not in df.columns:
                if "datetime" in df.columns:
                    rename_map["datetime"] = "dt"
                elif "date" in df.columns:
                    rename_map["date"] = "dt"
            if "volume" in df.columns and "vol" not in df.columns:
                rename_map["volume"] = "vol"
            if rename_map:
                df = df.rename(rename_map)
            if "dt" in df.columns and df["dt"].dtype != pl.Datetime:
                df = df.with_columns(pl.col("dt").cast(pl.Datetime, strict=False))

            if freq in _DAILY_FREQS and "close" in df.columns:
                # 周线/月线: 主源日K行先按级别聚合再挂 MACD (2026-11-26 修复:
                # 此前周/月线直接返回日线行, 级别错配)。
                df = resample_daily_frame(df, freq)
                df = attach_macd_from_pipeline(df)

            keep_base = [
                c for c in ("dt", "open", "high", "low", "close", "vol", "amount")
                if c in df.columns
            ]
            keep_macd = [c for c in ("macd_dif", "macd_dea", "macd_hist") if c in df.columns]
            return df.select(keep_base + keep_macd)
        except Exception as exc:
            logger.warning("primary provider schema normalize failed: %s", exc)
            return None
