"""区间套下钻 —— 缠师第27课"精确大转折点寻找程序定理"。

原文: "某大级别的转折点,可以通过不同级别背驰段的逐级收缩范围而确定。
       先找到其背驰段,然后在次级别图里,找出相应背驰段在次级别里的背驰段,
       将该过程反复进行下去。"

本模块实现区间套的【第一层下钻】: 日线买卖点 → 30分钟次级别背驰确认。
- 大级别(日线)给出背驰段窗口 [sdt, edt];
- 次级别(30分钟)在该窗口内重新分解, 找同向背驰段;
- 返回是否确认 + 收缩后的次级别背驰区间(用于精确定位)。

不依赖 czsc 原生对象, 输入为次级别的 Bi 快照列表, 保持领域层纯净。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Bi, MacdPoint


@dataclass(frozen=True)
class NestResult:
    """区间套下钻结果。

    confirmed: 次级别是否存在同向背驰段(区间套是否成立)
    level: 下钻到的级别标识, 如 "30分钟"
    sub_div_start / sub_div_end: 次级别背驰段的起止时间(收缩后的定位区间)
    sub_ratio: 次级别背驰力度比 (area_cur / area_a, <1 为背驰)
    bi_count: 次级别分解得到的笔数(数据充分性指标)
    note: 人类可读结论 / 降级原因
    source_unavailable: 源级失败标记 (取数异常/全源空帧/熔断冷却, 2026-11-23) —
        区别于"有数据但未确认": 调用方据此保留信号并向前端报错, 而非静默丢弃
    """
    confirmed: bool
    level: str
    sub_div_start: datetime | None = None
    sub_div_end: datetime | None = None
    sub_ratio: float | None = None
    bi_count: int = 0
    note: str = ""
    source_unavailable: bool = False


def _macd_area(bi: Bi, macd: list[MacdPoint], direction: str) -> tuple[float | None, list[float]]:
    """笔区间内同向 MACD 柱面积 (缠师第24课: 向下看绿柱, 向上看红柱)。"""
    vals: list[float] = []
    total = 0.0
    for m in macd:
        if not (bi.range_sdt <= _to_dt(m.dt) <= bi.range_edt):
            continue
        if m.macd is None:
            continue
        if direction == "down" and m.macd < 0:
            total += abs(m.macd)
            vals.append(m.macd)
        elif direction == "up" and m.macd > 0:
            total += m.macd
            vals.append(m.macd)
    return (total if vals else None), vals


def _to_dt(value: str) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("T", " "))


def find_sublevel_divergence(
    sub_bis: list[Bi],
    sub_macd: list[MacdPoint],
    direction: str,
    level: str = "30分钟",
    min_bi: int = 3,
) -> NestResult:
    """在次级别笔序列中找同向背驰段 —— 区间套第一层下钻。

    判定口径与日线趋势背驰一致(缠师第24课):
        1. c 段创新低/新高;
        2. c 段 MACD 同向面积 < a 段。
    a/c 为同向笔且中间隔反向笔(笔方向交替保证)。

    Args:
        sub_bis: 次级别笔快照(按时间升序)
        sub_macd: 与次级别 bars 对齐的 MACD 序列
        direction: 目标方向 "down"(对应买点) / "up"(对应卖点)
        level: 级别标识
        min_bi: 最少笔数, 不足则结构不可靠

    Returns:
        NestResult
    """
    if direction not in ("down", "up"):
        return NestResult(False, level, note=f"无效方向 {direction}")
    if len(sub_bis) < min_bi:
        return NestResult(
            False, level, bi_count=len(sub_bis),
            note=f"次级别笔数不足({len(sub_bis)}<{min_bi}),结构不可靠",
        )

    # 从最新同向笔往前找 a/c 两段(a 在前, c 在后, 中间隔反向笔)
    same_dir = [b for b in sub_bis if b.direction == direction]
    for pos in range(len(same_dir) - 1, 0, -1):
        c = same_dir[pos]
        a = same_dir[pos - 1]
        # c 必须创新低/新高
        if direction == "down" and c.low >= a.low:
            continue
        if direction == "up" and c.high <= a.high:
            continue
        area_a, _ = _macd_area(a, sub_macd, direction)
        area_c, _ = _macd_area(c, sub_macd, direction)
        if area_a is None or area_c is None or area_a <= 0:
            continue
        ratio = area_c / area_a
        if ratio < 1.0:
            return NestResult(
                confirmed=True,
                level=level,
                sub_div_start=a.sdt,
                sub_div_end=c.edt,
                sub_ratio=round(ratio, 4),
                bi_count=len(sub_bis),
                note=f"次级别{direction}背驰确认: c段面积/ a段面积={ratio:.3f}<1",
            )
    return NestResult(
        False, level, bi_count=len(sub_bis),
        note="次级别窗口内未找到同向背驰段(区间套未确认)",
    )
