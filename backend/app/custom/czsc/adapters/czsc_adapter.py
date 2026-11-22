"""czsc 原生对象 → 领域模型适配器。

所有对 `czsc._native` 属性的读取集中在此, domain/application 不再依赖原生对象,
从而在 czsc 升级时把兼容风险收敛到一个文件。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import polars as pl

from ..domain.models import Bi, Fx

logger = logging.getLogger(__name__)

_HAS_CZSC: bool | None = None
_CZSC_VERSION: str | None = None


def probe_czsc() -> tuple[bool, str | None]:
    """惰性探测 czsc 是否可用, 结果缓存。"""
    global _HAS_CZSC, _CZSC_VERSION
    if _HAS_CZSC is not None:
        return _HAS_CZSC, _CZSC_VERSION
    try:
        import czsc
        from czsc import CZSC  # noqa: F401

        _HAS_CZSC = True
        _CZSC_VERSION = getattr(czsc, "__version__", None)
    except ImportError as exc:
        logger.info("czsc not installed, analyzer disabled: %s", exc)
        _HAS_CZSC = False
        _CZSC_VERSION = None
    return _HAS_CZSC, _CZSC_VERSION


def reset_probe() -> None:
    """测试用: 清空探测缓存。"""
    global _HAS_CZSC, _CZSC_VERSION
    _HAS_CZSC = None
    _CZSC_VERSION = None


def _mark_kind(mark: Any) -> str:
    s = str(mark)
    if "顶" in s or s == "Mark.G" or s.endswith(".G"):
        return "top"
    if "底" in s or s == "Mark.D" or s.endswith(".D"):
        return "bottom"
    return "unknown"


def _direction(value: Any) -> str:
    s = str(value)
    if "向上" in s or "Up" in s:
        return "up"
    if "向下" in s or "Down" in s:
        return "down"
    return "unknown"


def _price(fx: Any, kind: str, fallback: float) -> float:
    if kind == "top":
        return float(fx.high)
    if kind == "bottom":
        return float(fx.low)
    value = getattr(fx, "fx", None)
    return float(value) if value is not None else fallback


def adapt_fx(fx: Any) -> Fx:
    raw_mark = str(fx.mark)
    return Fx(
        dt=fx.dt,
        mark=_mark_kind(raw_mark),
        high=float(fx.high),
        low=float(fx.low),
        raw_mark=raw_mark,
        raw_fx=str(fx.fx),
    )


def adapt_bi(bi: Any) -> Bi:
    try:
        range_sdt = bi.fx_a.raw_bars[0].dt
    except Exception:
        range_sdt = bi.sdt
    try:
        range_edt = bi.fx_b.raw_bars[-1].dt
    except Exception:
        range_edt = bi.edt

    start_mark = _mark_kind(bi.fx_a.mark)
    end_mark = _mark_kind(bi.fx_b.mark)
    return Bi(
        sdt=bi.sdt,
        edt=bi.edt,
        range_sdt=range_sdt,
        range_edt=range_edt,
        direction=_direction(bi.direction),
        raw_direction=str(bi.direction),
        high=float(bi.high),
        low=float(bi.low),
        length=int(bi.length),
        power=float(bi.power) if bi.power is not None else None,
        start_mark=start_mark,
        end_mark=end_mark,
        start_price=_price(bi.fx_a, start_mark, float(bi.low)),
        end_price=_price(bi.fx_b, end_mark, float(bi.high)),
    )


def to_raw_bars(df: pl.DataFrame, freq: str) -> list[Any]:
    from ..converters import df_to_raw_bars

    return df_to_raw_bars(df, freq)


def run_czsc(
    bars: list[Any],
    max_bi_num: int,
    min_bi_len: int,
) -> tuple[list[Fx], list[Bi], dict[str, Any]]:
    """调用 czsc.CZSC 并快照为领域模型。"""
    from czsc import CZSC

    c = CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)
    fxs = [adapt_fx(fx) for fx in c.fx_list]
    bis = [adapt_bi(bi) for bi in c.bi_list]
    try:
        signals = dict(c.signals) if c.signals else {}
    except Exception as exc:
        logger.warning("extract signals failed: %s", exc)
        signals = {}
    return fxs, bis, signals


def bar_date(bar: Any) -> date:
    """RawBar.dt (datetime/date/str) → date。"""
    value = bar.dt
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def bar_date_str(bar: Any) -> str:
    return bar_date(bar).isoformat()
