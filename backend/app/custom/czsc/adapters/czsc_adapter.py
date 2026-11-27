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


def _fx_kind(fx: Any) -> str:
    return _mark_kind(str(fx.mark))


def _endpoints_to_bi(a: Any, b: Any, index: dict[Any, int]) -> Bi:
    """相邻两个笔端点 (异向分型) → Bi 领域模型。"""
    a_kind, b_kind = _fx_kind(a), _fx_kind(b)
    if a_kind == "top":
        direction, raw_direction = "down", "向下"
        high, low = float(a.high), float(b.low)
    else:
        direction, raw_direction = "up", "向上"
        high, low = float(b.high), float(a.low)
    return Bi(
        sdt=a.dt,
        edt=b.dt,
        range_sdt=a.raw_bars[0].dt,
        range_edt=b.raw_bars[-1].dt,
        direction=direction,
        raw_direction=raw_direction,
        high=high,
        low=low,
        length=index[b.dt] - index[a.dt] + 1,
        power=None,
        start_mark=a_kind,
        end_mark=b_kind,
        start_price=float(a.high if a_kind == "top" else a.low),
        end_price=float(b.high if b_kind == "top" else b.low),
    )


def _rebuild_tail_bis(
    c: Any,
    bars: list[Any],
    min_bi_len: int,
) -> list[Bi] | None:
    """对 czsc 未完成笔 (bi_list[-1]) 按缠师第 62 课规则重组装。

    czsc 增量笔算法在「急速 V 型反转 + 紧随反弹分型间隔 < min_bi_len +
    后续未创新极值」形态下会丢弃已成立的分段端点, 尾部整段锁进一根
    未完成笔, 直到趋势新极值才解锁 (实证 600809 周线 2024-05 后死锁,
    与窗口起点无关, 属库固有保守机制)。

    通用规则 (只作用于 bi_list[-1], 确认历史笔 bi_list[:-1] 不动):
      1. 顶底分型交替 (czsc fx_list 保证严格交替, 同向做吸收取更极端者);
      2. 相邻端点间隔 (含端点 K 线, bar 索引差+1) >= min_bi_len 才确认
         端点, 不足则跳过该分型 (第 62 课);
      3. 结果不足两笔返回 None, 保持 czsc 原输出 (非触发走势零变化)。
    """
    native_bis = c.bi_list
    if not native_bis:
        return None
    pivot = native_bis[-1].fx_a
    index = {b.dt: i for i, b in enumerate(bars)}
    if pivot is None or pivot.dt not in index:
        return None
    endpoints: list[Any] = [pivot]
    for fx in c.fx_list:
        if fx.dt <= pivot.dt or fx.dt not in index:
            continue
        prev = endpoints[-1]
        if _fx_kind(fx) == _fx_kind(prev):
            # pivot (endpoints[0]) 与前一确认笔共享端点, 不可被吸收,
            # 否则重组链起点后移, 与 bi_list[-2] 衔接断裂。
            if len(endpoints) == 1:
                continue
            # 同向吸收: 顶取更高, 底取更低, 只前进不回退
            if _fx_kind(fx) == "top":
                if fx.high > prev.high:
                    endpoints[-1] = fx
            elif fx.low < prev.low:
                endpoints[-1] = fx
            continue
        # 异向: 间隔含端点 >= min_bi_len 才确认, 否则跳过 (第 62 课)
        if index[fx.dt] - index[prev.dt] + 1 < min_bi_len:
            continue
        endpoints.append(fx)
    if len(endpoints) < 2:
        return None
    return [_endpoints_to_bi(a, b, index) for a, b in zip(endpoints, endpoints[1:])]


def run_czsc(
    bars: list[Any],
    max_bi_num: int,
    min_bi_len: int,
) -> tuple[list[Fx], list[Bi], dict[str, Any]]:
    """调用 czsc.CZSC 并快照为领域模型。"""
    from czsc import CZSC

    c = CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)
    fxs = [adapt_fx(fx) for fx in c.fx_list]
    rebuilt = _rebuild_tail_bis(c, bars, min_bi_len)
    if rebuilt is not None:
        last_native = adapt_bi(c.bi_list[-1])
        # 1 笔且端点与 czsc 原未完成笔相同 → 空转换, 保持 czsc 原笔
        # (避免 length/power 语义无谓漂移)。
        if len(rebuilt) == 1 and (
            rebuilt[0].sdt == last_native.sdt and rebuilt[0].edt == last_native.edt
        ):
            rebuilt = None
    if rebuilt is not None:
        bis = [adapt_bi(bi) for bi in c.bi_list[:-1]] + rebuilt
    else:
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
