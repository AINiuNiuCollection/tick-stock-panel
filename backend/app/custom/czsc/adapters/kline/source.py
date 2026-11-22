"""K 线数据源契约与空结果。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl

EMPTY_KLINE_SCHEMA: dict[str, pl.DataType] = {
    "dt": pl.Datetime,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "vol": pl.Float64,
    "amount": pl.Float64,
}


def empty_kline() -> pl.DataFrame:
    return pl.DataFrame(schema=EMPTY_KLINE_SCHEMA)


@dataclass(frozen=True)
class KlineResult:
    frame: pl.DataFrame
    source: str

    @property
    def is_empty(self) -> bool:
        return self.frame.is_empty()


class KlineSource(Protocol):
    name: str

    def fetch(self, symbol: str, freq: str, start: date, end: date) -> pl.DataFrame | None:
        """返回 czsc 标准 schema 的 DataFrame; 不可用返回 None。"""
        ...
