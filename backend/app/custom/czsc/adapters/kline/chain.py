"""取数链 — 按顺序尝试数据源, 首个非空结果胜出。"""
from __future__ import annotations

import logging
from datetime import date

from .eastmoney import EastmoneyKlineSource
from .primary import PrimaryKlineSource
from .source import KlineResult, KlineSource, empty_kline

logger = logging.getLogger(__name__)


class KlineSourceChain:
    def __init__(self, sources: list[KlineSource]) -> None:
        self._sources = list(sources)

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> KlineResult:
        for source in self._sources:
            try:
                frame = source.fetch(symbol, freq, start, end)
            except Exception as exc:
                logger.warning("kline source %s failed: %s", source.name, exc)
                continue
            if frame is not None and not frame.is_empty():
                return KlineResult(frame=frame, source=source.name)
        return KlineResult(frame=empty_kline(), source="empty")


def build_default_chain() -> KlineSourceChain:
    return KlineSourceChain([PrimaryKlineSource(), EastmoneyKlineSource()])
