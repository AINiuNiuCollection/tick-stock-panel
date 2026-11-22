"""东财兜底数据源 — 受 settings.czsc_eastmoney_fallback 开关控制。"""
from __future__ import annotations

import logging
from datetime import date

import polars as pl

logger = logging.getLogger(__name__)


class EastmoneyKlineSource:
    name = "eastmoney"

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        from app.config import settings

        if not settings.czsc_eastmoney_fallback:
            return None
        try:
            from ...eastmoney_fallback import EastmoneyFallbackError, fetch_kline
        except ImportError as exc:
            logger.warning("eastmoney fallback module unavailable: %s", exc)
            return None
        try:
            return fetch_kline(symbol, freq, start, end)
        except EastmoneyFallbackError as exc:
            logger.warning(
                "eastmoney fallback failed for %s: [%s] %s", symbol, exc.code, exc.message
            )
            return None
        except Exception as exc:
            logger.warning("eastmoney fallback unexpected error: %s", exc)
            return None
