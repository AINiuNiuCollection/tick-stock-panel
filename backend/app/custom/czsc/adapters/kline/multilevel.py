"""多级别取数适配器 —— 区间套下钻的次级别数据来源。

优先走主工程 KlineSourceChain (baostock 30 分钟, 2015 起历史可选);
东财兜底仅近 5 周, 作为最后退路。数据不可用时明确降级, 不编造结果。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from ...domain.interval_nest import NestResult, find_sublevel_divergence
from ...domain.models import Bi
from ..czsc_adapter import _direction, to_raw_bars
from ..indicators import macd_points_from_bars
from .chain import KlineSourceChain

logger = logging.getLogger(__name__)

# 次级别下钻映射 (与 sublevel.SUB_FREQ_MAP 同口径; 第72课级别阶梯)
NEST_SUB_FREQ_MAP: dict[str, str] = {
    "日线": "30分钟",
    "60分钟": "15分钟",
    "30分钟": "5分钟",
    "15分钟": "5分钟",
}


class IntervalNestVerifier:
    """区间套验证器: 分析级别买卖点 → 次级别背驰确认 (第27课区间套)。

    次级别按分析级别自动下钻 (日线→30分钟, 30分钟→5分钟 ...), 级别不可错配。
    返回结构化 NestResult (含收缩区间/力度比), 而非裸 bool;
    用 baostock 长历史分钟数据, 不受东财 5 周限制;
    结果按 (symbol, freq, 日期, 方向) 记忆化。
    """

    def __init__(self, chain: KlineSourceChain, lookback_days: int = 60) -> None:
        self._chain = chain
        self._lookback = lookback_days
        self._memo: dict[tuple[str, str, str, str], NestResult] = {}

    def verify(
        self, symbol: str, freq: str, edt: date | datetime | str, direction: str
    ) -> NestResult:
        sub_freq = NEST_SUB_FREQ_MAP.get(freq)
        if sub_freq is None:
            return NestResult(
                False, freq, note=f"{freq} 无更低次级别配置, 跳过区间套确认"
            )
        edt_date = edt.date() if isinstance(edt, datetime) else (
            edt if isinstance(edt, date) else datetime.fromisoformat(str(edt)[:10]).date()
        )
        key = (symbol, freq, edt_date.isoformat(), direction)
        if key in self._memo:
            return self._memo[key]
        result = self._verify(symbol, sub_freq, edt_date, direction)
        self._memo[key] = result
        return result

    def _verify(
        self, symbol: str, sub_freq: str, edt_date: date, direction: str
    ) -> NestResult:
        if direction not in ("down", "up"):
            return NestResult(False, sub_freq, note=f"无效方向 {direction}")
        sub_start = edt_date - timedelta(days=self._lookback)
        sub_end = edt_date + timedelta(days=1)
        try:
            result = self._chain.fetch(symbol, sub_freq, sub_start, sub_end)
        except Exception as exc:
            logger.debug("sublevel fetch failed for %s: %s", symbol, exc)
            return NestResult(False, sub_freq, note=f"次级别取数失败: {type(exc).__name__}")
        if result.frame.is_empty():
            return NestResult(False, sub_freq, note="次级别数据为空(数据源不可用)")

        try:
            bars = to_raw_bars(result.frame, sub_freq)
        except Exception as exc:
            return NestResult(False, sub_freq, note=f"次级别 RawBar 转换失败: {type(exc).__name__}")
        if len(bars) < 30:
            return NestResult(
                False, sub_freq, bi_count=0,
                note=f"次级别K线不足({len(bars)}<30),结构不可靠",
            )

        # 次级别 CZSC 分解 → 笔快照 + MACD
        try:
            from czsc import CZSC
            c = CZSC(bars, max_bi_num=1000, min_bi_len=5)
        except Exception as exc:
            return NestResult(False, sub_freq, note=f"次级别 CZSC 分解失败: {type(exc).__name__}")

        sub_bis: list[Bi] = []
        for b in c.bi_list:
            try:
                rdt = b.fx_a.raw_bars[0].dt
                redt = b.fx_b.raw_bars[-1].dt
            except Exception:
                rdt, redt = b.sdt, b.edt
            sub_bis.append(
                Bi(
                    sdt=b.sdt, edt=b.edt, range_sdt=rdt, range_edt=redt,
                    direction=_direction(b.direction), raw_direction=str(b.direction),
                    high=float(b.high), low=float(b.low), length=int(b.length),
                    power=float(b.power) if b.power is not None else None,
                    start_mark="", end_mark="", start_price=float(b.low), end_price=float(b.high),
                )
            )
        if len(sub_bis) < 3:
            return NestResult(
                False, sub_freq, bi_count=len(sub_bis),
                note=f"次级别笔数不足({len(sub_bis)}<3),结构不可靠",
            )

        bars_like = [type("B", (), {"dt": str(b.dt), "close": float(b.close)})() for b in bars]
        sub_macd = macd_points_from_bars(bars_like)
        return find_sublevel_divergence(sub_bis, sub_macd, direction, sub_freq)
