"""取数链 — 按顺序尝试数据源, 首个非空结果胜出。

线程安全 TTL 结果缓存: 扫描/次级别验证会对同一 (symbol, freq, start, end)
重复取数, 网络源 (TickFlow/baostock 免费档) 间歇失败时单次可达数十秒,
缓存让重复请求毫秒级命中。
"""
from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import date

from .eastmoney import EastmoneyKlineSource
from .local_daily import LocalDailyKlineSource
from .primary import PrimaryKlineSource
from .source import KlineResult, KlineSource, empty_kline

logger = logging.getLogger(__name__)

_CACHE_TTL_S = 600.0       # 10 分钟
_CACHE_MAXSIZE = 4096      # 覆盖 300 只 × 多级别扫描


class KlineSourceChain:
    def __init__(self, sources: list[KlineSource], *, cache_ttl_s: float = _CACHE_TTL_S) -> None:
        self._sources = list(sources)
        self._cache: OrderedDict[tuple[object, ...], tuple[float, KlineResult]] = OrderedDict()
        self._cache_ttl = cache_ttl_s
        self._cache_lock = threading.Lock()

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> KlineResult:
        key = (symbol, freq, start, end)
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None:
                ts, result = hit
                if now - ts <= self._cache_ttl:
                    self._cache.move_to_end(key)
                    return result
                self._cache.pop(key, None)

        for source in self._sources:
            try:
                frame = source.fetch(symbol, freq, start, end)
            except Exception as exc:
                logger.warning("kline source %s failed: %s", source.name, exc)
                continue
            if frame is not None and not frame.is_empty():
                result = KlineResult(frame=frame, source=source.name)
                with self._cache_lock:
                    self._cache[key] = (time.monotonic(), result)
                    self._cache.move_to_end(key)
                    while len(self._cache) > _CACHE_MAXSIZE:
                        self._cache.popitem(last=False)
                return result
        return KlineResult(frame=empty_kline(), source="empty")


def build_default_chain() -> KlineSourceChain:
    # local_daily 优先: 全市场日K本地持久副本, 毫秒级且零网络依赖;
    # 数据过旧/缺失时自然落到 primary (TickFlow/自定义源) 与 eastmoney 兜底。
    return KlineSourceChain([LocalDailyKlineSource(), PrimaryKlineSource(), EastmoneyKlineSource()])
