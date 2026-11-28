"""事件效果统计引擎 (设计 §2.2, P3-T3)。

对每条 (approved+major+有 source, 由调用方用 is_countable 过滤) 事件计算:
    - T+1 / T+5 / T+20 / T+60 交易日收益 (相对事件前收盘, 百分数);
    - 事件后 20 日最大上涨 / 最大回撤 (窗口内收盘极值 vs 前收盘, 百分数);
    - 技术背景: 事件时收盘是否在 20 日线上/下 (不足 20 根 K 线为 None);
      缠论笔方向列为 v2, 本期不做。

口径约定:
    - 事件 date = 生效交易日; T+1 = 生效日起第一个交易日的收盘 (如 9-24 发布会,
      前收盘=9-23, T+1=9-24 当日涨幅);
    - 基准 = 事件前最后一个交易日收盘 (前收盘);
    - 前向数据不足的档位返回 None (不算 0)。

聚合 (设计 §2.2): direction × 技术背景 分组中位数收益 + n; n < 5 的分组
    不显示中位数 (med=None), 只显示样本数 — 前端按此渲染。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

import polars as pl

from app.custom.market.events import PolicyEvent

_HORIZONS = (1, 5, 20, 60)
_MA_PERIOD = 20


@dataclass
class EventStats:
    """单条事件的统计结果 (前端逐条展示)。"""

    event_id: str
    base_close: float  # 事件前收盘 (基准)
    t1: float | None  # T+1 收益 % (前向不足 None)
    t5: float | None
    t20: float | None
    t60: float | None
    max_up_20: float | None  # 事件后20日最大上涨 % (窗口=T+1..T+20 收盘)
    max_dd_20: float | None  # 事件后20日最大回撤 % (可负)
    above_ma20: bool | None  # 事件时收盘在20日线上? 数据不足 None
    bi_direction: str | None = None  # 事件时所在缠论日线笔方向 (v2, 由调用方经 bi_context 注入)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "base_close": round(self.base_close, 4),
            "t1": self.t1,
            "t5": self.t5,
            "t20": self.t20,
            "t60": self.t60,
            "max_up_20": self.max_up_20,
            "max_dd_20": self.max_dd_20,
            "above_ma20": self.above_ma20,
            "bi_direction": self.bi_direction,
        }


def _pct(later: float, base: float) -> float:
    return round((later / base - 1) * 100, 2)


def compute_event_stats(
    event: PolicyEvent, dates: list[date], closes: list[float]
) -> EventStats | None:
    """计算单条事件统计; 事件不在 K 线范围内 (无前收盘) 返回 None。"""
    # 定位生效日起第一个交易日 index (二分: dates 升序)
    lo, t_idx = 0, len(dates)
    while lo < len(dates):
        if dates[lo] >= event.date:
            t_idx = lo
            break
        lo += 1
    if t_idx == 0 or t_idx >= len(dates):
        return None  # 无前收盘 / 事件在数据范围外
    base_idx = t_idx - 1
    base = float(closes[base_idx])

    def horizon_ret(k: int) -> float | None:
        i = t_idx + k - 1  # T+1 = t_idx 当日
        return _pct(float(closes[i]), base) if i < len(closes) else None

    win = closes[t_idx : t_idx + _MA_PERIOD]
    max_up_20 = _pct(max(win), base) if win else None
    max_dd_20 = _pct(min(win), base) if win else None

    if base_idx + 1 >= _MA_PERIOD:
        ma20 = sum(closes[base_idx + 1 - _MA_PERIOD : base_idx + 1]) / _MA_PERIOD
        above_ma20 = bool(float(closes[t_idx]) > ma20)
    else:
        above_ma20 = None

    return EventStats(
        event_id=event.id,
        base_close=base,
        t1=horizon_ret(1),
        t5=horizon_ret(5),
        t20=horizon_ret(20),
        t60=horizon_ret(60),
        max_up_20=max_up_20,
        max_dd_20=max_dd_20,
        above_ma20=above_ma20,
    )


def compute_events_stats(
    events: list[PolicyEvent],
    kline: pl.DataFrame,
    bi_directions: dict[str, str | None] | None = None,
) -> list[EventStats]:
    """批量计算; kline 须含 date/close 列 (升序), 通常为 load_index_daily 全历史。

    bi_directions: 事件 id -> 缠论日线笔方向 (bi_context 注入, 缺省不带)。
    """
    if kline.is_empty():
        return []
    dates = [d.date() if hasattr(d, "date") else d for d in kline["date"].to_list()]
    closes = kline["close"].to_list()
    out: list[EventStats] = []
    for ev in events:
        st = compute_event_stats(ev, dates, closes)
        if st is not None:
            st.bi_direction = (bi_directions or {}).get(ev.id)
            out.append(st)
    return out


def aggregate(
    events: list[PolicyEvent], stats: list[EventStats], dim: str = "ma20"
) -> list[dict]:
    """direction × 技术背景 分组中位数 (n<5 只显示样本数, 设计 §2.2)。

    dim: "ma20" (默认, 20日线上/下) 或 "bi" (缠论日线笔方向, v2 可选维度)。
    23 条样本按三维切全会落入 n<5, bi 维度默认不进前端统计表, 仅 API 可选。
    """
    by_id = {s.event_id: s for s in stats}
    groups: dict[tuple[str, str | None], list[EventStats]] = {}
    for ev in events:
        st = by_id.get(ev.id)
        if st is None:
            continue
        if dim == "bi":
            position = st.bi_direction
        else:
            position = None if st.above_ma20 is None else ("above" if st.above_ma20 else "below")
        key = (ev.direction, position)
        groups.setdefault(key, []).append(st)

    def med(vals: list[float | None]) -> float | None:
        xs = [v for v in vals if v is not None]
        return round(statistics.median(xs), 2) if xs else None

    rows: list[dict] = []
    for (direction, position), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        n = len(members)
        row: dict = {
            "direction": direction,
            "n": n,
        }
        # 维度字段: 默认行为 (ma20) 与既有响应 schema 逐字节一致, bi 为可选扩展
        if dim == "bi":
            row["bi_direction"] = position
        else:
            row["ma20_position"] = position
        if n >= 5:
            row.update(
                {
                    "median_t1": med([m.t1 for m in members]),
                    "median_t5": med([m.t5 for m in members]),
                    "median_t20": med([m.t20 for m in members]),
                    "median_t60": med([m.t60 for m in members]),
                }
            )
        rows.append(row)
    return rows
