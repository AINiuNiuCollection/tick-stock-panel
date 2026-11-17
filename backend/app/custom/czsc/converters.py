"""schema ↔ czsc 类型边界胶水。

符合 czsc 宪法: "PyO3 类型系统无法跨越的边界处理" 允许保留 Python 胶水。
本模块职责:
    - polars DataFrame → list[RawBar] (输入 czsc.CZSC)
    - czsc.FX/BI/ZS 对象 → schema dict (输出 HTTP 响应)

不在此模块做参数归一化或行为适配, 仅做类型转换。

注意: czsc 1.0.2 起 RawBar 不再接受 open_interest 字段 (A股也无持仓量)。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import polars as pl

from czsc import Freq, RawBar


def df_to_raw_bars(df: pl.DataFrame, freq: str) -> list[RawBar]:
    """polars DataFrame → list[RawBar] (按 dt 升序)。

    Args:
        df: 标准化 schema (dt/open/high/low/close/vol/amount)
        freq: 中文频率名 ("日线" / "30分钟" 等)

    Returns:
        升序排列的 RawBar 列表
    """
    if df.is_empty():
        return []
    df = df.sort("dt")
    rows = df.to_dicts()
    bars: list[RawBar] = []
    for row in rows:
        dt_val = row["dt"]
        # 日K的 dt 可能是 date 或 datetime, 统一转 datetime
        if isinstance(dt_val, date) and not isinstance(dt_val, datetime):
            dt_val = datetime.combine(dt_val, datetime.min.time())
        elif not isinstance(dt_val, datetime):
            # polars 可能返回 string, 兜底转换
            dt_val = datetime.fromisoformat(str(dt_val))
        # czsc 1.0.2 RawBar 字段: symbol/id/freq/dt/open/close/high/low/vol/amount
        # 不再接受 open_interest (已移除)
        bar = RawBar(
            symbol="",  # CZSC 构造时传入 symbol, bar 内可不填
            id=len(bars),
            freq=Freq(freq),
            dt=dt_val,
            open=float(row["open"]),
            close=float(row["close"]),
            high=float(row["high"]),
            low=float(row["low"]),
            vol=float(row["vol"]),
            amount=float(row.get("amount") or 0.0),
        )
        bars.append(bar)
    return bars


def fx_to_dict(fx: Any) -> dict[str, Any]:
    """czsc.FX → schema 兼容 dict。

    czsc 1.0.2: mark 是 str ("底分型 Mark" / "顶分型 Mark"), fx 是 float。
    """
    return {
        "dt": str(fx.dt),
        "mark": str(fx.mark),
        "fx": str(fx.fx),
        "high": float(fx.high),
        "low": float(fx.low),
    }


def bi_to_dict(bi: Any) -> dict[str, Any]:
    """czsc.BI → schema 兼容 dict。

    czsc 1.0.2: direction 是 str ("向上 Direction" / "向下 Direction"),
    power 是 float (非 None)。
    """
    return {
        "sdt": str(bi.sdt),
        "edt": str(bi.edt),
        "direction": str(bi.direction),
        "high": float(bi.high),
        "low": float(bi.low),
        "length": int(bi.length),
        "power": float(bi.power) if bi.power is not None else None,
    }


def zs_to_dict(zs: Any) -> dict[str, Any]:
    """czsc.ZS → schema 兼容 dict。

    czsc 1.0.2 ZS 原生字段: zd (下沿) / zg (上沿) / gg (区间最高) / dd (区间最低)
    / sdt / edt / is_valid() 方法 / bis (笔列表)。
    无 zs_range / level / valid 字段, 这里做兼容映射:
        zs_range = [zd, zg]   — 与前端 CzscZs.zs_range 契约保持
        level    = 1           — czsc 1.0.2 无 level 概念, 默认 1
        valid    = is_valid()  — 调用方法取布尔值
    """
    zd = float(zs.zd)
    zg = float(zs.zg)
    gg = float(zs.gg)
    dd = float(zs.dd)
    # is_valid 在 1.0.2 是方法
    is_valid_attr = zs.is_valid
    valid = bool(is_valid_attr()) if callable(is_valid_attr) else bool(is_valid_attr)
    return {
        "zs_range": [zd, zg],
        "zd": zd,
        "zg": zg,
        "gg": gg,
        "dd": dd,
        "level": 1,
        "start_dt": str(zs.sdt),
        "end_dt": str(zs.edt),
        "valid": valid,
    }
