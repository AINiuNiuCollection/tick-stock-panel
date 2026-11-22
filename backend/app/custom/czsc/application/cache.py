"""分析结果缓存 — 进程内 LRU + TTL, 线程安全。"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


def _copy(value: dict[str, Any]) -> dict[str, Any]:
    return {k: (list(v) if isinstance(v, list) else v) for k, v in value.items()}


class AnalysisCache:
    def __init__(self, maxsize: int = 128, ttl_s: float = 300.0) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_s
        self._data: OrderedDict[tuple[object, ...], tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[object, ...]) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            ts, value = item
            if now - ts > self._ttl:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return _copy(value)

    def put(self, key: tuple[object, ...], value: dict[str, Any]) -> None:
        with self._lock:
            self._data[key] = (time.monotonic(), _copy(value))
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
