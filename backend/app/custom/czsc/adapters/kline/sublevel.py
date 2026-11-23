"""B2/S2 次级别验证 — 缠师定律一 (第二类买卖点 = 次级别第一类买卖点)。

按分析级别自动下钻次级别 (级别不可错配):
    日线 → 30分钟; 60分钟 → 15分钟; 30分钟 → 5分钟; 15分钟 → 5分钟。
    5分钟/周线/月线无更低级别配置 → 返回 None (未验证, 调用方放行并标注)。
结果按 (symbol, freq, edt_date) 记忆化, 避免同一请求内重复取数。

历史缺陷 (三处, 均导致 B2/S2 被 fail-closed 全部拦截):
    1. 恒取 30 分钟数据 → 对 30 分钟级别分析是"用本级验证本级", 级别错配;
    2. MACD 按单笔从零预热且要求 >=26 根 → 分钟级别一笔仅约 5~10 根,
       切片永远不足 26 根 → 面积恒 0 → 验证恒 False;
       现改为整窗口一次性预热计算 MACD, 再按笔区间切片。
    3. 参照段用"相邻同向笔" → 定律一要求对比进入次级别一买/一卖的
       急跌/急涨段 (窗口极值笔), 而非相邻笔。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

from ...config import SUBLEVEL_30M_LOOKBACK_DAYS
from ..czsc_adapter import _direction, to_raw_bars
from .chain import KlineSourceChain

logger = logging.getLogger(__name__)

# 源不可用熔断: 次级别取数连续失败 (取数异常 / 全源空帧) 达阈值后,
# 冷却期内 verify 直接返回 None, 不再触链。
# 背景: 全市场策略扫描时每个 B2/S2 候选都触发一次次级别取数, 若分钟源
# 整体不可用 (如代理环境 baostock 原生 socket 恒失败 + 东财被中间盒子
# 返回空 body), 每个候选都重复 "登录失败 + 3 次重试" 会刷屏日志并拖慢扫描。
_SOURCE_FAIL_THRESHOLD = 3
_SOURCE_COOLDOWN_S = 300.0

# 次级别下钻映射 (第72课级别阶梯: 分析级别 → 用于验证的次级别)
SUB_FREQ_MAP: dict[str, str] = {
    "日线": "30分钟",
    "60分钟": "15分钟",
    "30分钟": "5分钟",
    "15分钟": "5分钟",
}


def sub_freq_of(freq: str) -> str | None:
    """返回该分析级别对应的次级别; 无更低级别配置时返回 None。"""
    return SUB_FREQ_MAP.get(freq)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _as_datetime(value: Any) -> datetime | None:
    """候选时刻: 精确到分钟级别, 用于截断次级别窗口 (不含候选之后的走势)。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.max.time())
    try:
        return datetime.fromisoformat(str(value)[:19])
    except ValueError:
        return None


def _macd_hists(bars: list[Any]) -> list[float]:
    """整窗口一次性预热计算 MACD hist (EMA12/26, DEA9, 与主图指标同参)。

    旧实现按单笔从零预热: 分钟级别一笔仅 5~10 根, 永远达不到 26 根预热,
    导致面积恒 0 / 验证恒 False。预热必须在窗口起点完成一次。
    """
    closes = [float(b.close) for b in bars]
    if len(closes) < 2:
        return []
    ema12 = closes[0]
    ema26 = closes[0]
    dea = 0.0
    hists: list[float] = []
    for c in closes:
        ema12 = (2 * c + ema12 * 11) / 13
        ema26 = (2 * c + ema26 * 25) / 27
        dif = ema12 - ema26
        dea = (2 * dif + dea * 8) / 10
        hists.append(2 * (dif - dea))
    return hists


def _bi_area(bi: Any, bars: list[Any], hists: list[float], sign: str) -> float:
    """笔区间内的同向柱面积: sign='down' 取绿柱(负), 'up' 取红柱(正)。

    切片用闭区间 [sdt, edt] 比较 (笔端点是分型极值所在 K 线的时间戳,
    与 bars 逐根 dt 闭区间匹配, 旧实现精确相等在时间错位时切出空序列)。
    """
    try:
        sdt, edt = bi.sdt, bi.edt
    except Exception:
        return 0.0
    total = 0.0
    for bar, h in zip(bars, hists, strict=False):
        if bar.dt < sdt:
            continue
        if bar.dt > edt:
            break
        if h is None:
            continue
        if sign == "down" and h < 0:
            total += abs(h)
        elif sign == "up" and h > 0:
            total += h
    return total


class SublevelVerifier:
    """verify 三态返回 (2026-11-23 结构化输出改造):
        True  = 次级别有数据且结构通过 (次级别一买/一卖确认);
        False = 次级别有数据但结构不通过 (位置前提不满足 / 力度不衰竭);
        None  = 无法验证 (无更低级别配置 / 取数失败 / 数据不足 / czsc 未装)。
    旧布尔口径的调用方应把 None 按"未验证"放行, 不得当作 False。

    源不可用熔断: 连续 _SOURCE_FAIL_THRESHOLD 次取数失败 (异常/空帧) 后,
    _SOURCE_COOLDOWN_S 冷却期内所有 verify 直接返回 None 不触链;
    冷却结束后下一次 verify 作为探测, 仍失败则重新进入冷却 (每窗口最多
    一次外呼)。任一非源失败结果 (成功判定 / 数据不足等) 归零失败计数。
    """

    def __init__(
        self,
        chain: KlineSourceChain,
        lookback_days: int = SUBLEVEL_30M_LOOKBACK_DAYS,
    ) -> None:
        self._chain = chain
        self._lookback = lookback_days
        self._memo: dict[tuple[str, str, date], bool | None] = {}
        self._lock = threading.Lock()
        self._fail_streak = 0
        self._cooldown_until = 0.0

    def verify(self, symbol: str, freq: str, edt: Any) -> bool | None:
        sub_freq = sub_freq_of(freq)
        if sub_freq is None:
            # 无更低级别配置 (5分钟/周线/月线) → 未验证, 调用方按 None 放行
            return None
        edt_date = _as_date(edt)
        if edt_date is None:
            return None
        key = (symbol, freq, edt_date)
        with self._lock:
            if key in self._memo:
                return self._memo[key]
            if time.monotonic() < self._cooldown_until:
                return None
        result, source_failed = self._verify(symbol, sub_freq, edt, edt_date)
        with self._lock:
            if source_failed:
                self._fail_streak += 1
                if (
                    self._fail_streak >= _SOURCE_FAIL_THRESHOLD
                    and time.monotonic() >= self._cooldown_until
                ):
                    self._cooldown_until = time.monotonic() + _SOURCE_COOLDOWN_S
                    logger.warning(
                        "sublevel kline source failed %d consecutive fetches; "
                        "pausing sublevel verification %.0fs "
                        "(verify returns None=未验证 during cooldown)",
                        self._fail_streak, _SOURCE_COOLDOWN_S,
                    )
            else:
                self._fail_streak = 0
            self._memo[key] = result
        return result

    def _verify(
        self, symbol: str, sub_freq: str, edt: Any, edt_date: date
    ) -> tuple[bool | None, bool]:
        """返回 (判定结果, 是否源级失败)。源级失败 = 取数异常或全源空帧,
        用于熔断计数; 其余 None (数据不足/转换失败/czsc 未装) 不计。"""
        try:
            from czsc import CZSC
        except ImportError:
            return None, False

        # 窗口: 候选时刻之前的次级别走势 (不含候选之后, 否则最后一笔
        # 会是候选之后的新笔, 候选笔本身被错过)。
        cand_dt = _as_datetime(edt)
        sub_start = edt_date - timedelta(days=self._lookback)
        sub_end = edt_date + timedelta(days=1)
        try:
            result = self._chain.fetch(symbol, sub_freq, sub_start, sub_end)
        except Exception:
            return None, True
        if result.frame.is_empty():
            return None, True

        try:
            bars = to_raw_bars(result.frame, sub_freq)
        except Exception:
            return None, False
        if cand_dt is not None:
            bars = [b for b in bars if b.dt <= cand_dt]
        if not bars or len(bars) < 10:
            return None, False

        try:
            c = CZSC(bars, max_bi_num=1000, min_bi_len=5)
        except Exception:
            return None, False

        bi_list = c.bi_list
        if len(bi_list) < 3:
            return None, False

        # 候选笔 = 截断后窗口最后一笔 (结束于候选时刻附近);
        # 参照段 = 同方向、终点为窗口极值的笔 (进入次级别一买/一卖的急跌/急涨段)。
        hists = _macd_hists(bars)
        cand = bi_list[-1]
        d = _direction(cand.direction)
        if d == "down":
            extreme = min(float(b.low) for b in bi_list)
            ref = next(
                (b for b in bi_list
                 if _direction(b.direction) == "down" and float(b.low) == extreme),
                None,
            )
            if ref is None or ref is cand:
                return False, False
            # 二买位置前提: 回调低点不破次级别一买低点
            if float(cand.low) <= extreme:
                return False, False
            area_cur = _bi_area(cand, bars, hists, "down")
            area_ref = _bi_area(ref, bars, hists, "down")
            return area_ref > 0 and area_cur < area_ref, False
        if d == "up":
            extreme = max(float(b.high) for b in bi_list)
            ref = next(
                (b for b in bi_list
                 if _direction(b.direction) == "up" and float(b.high) == extreme),
                None,
            )
            if ref is None or ref is cand:
                return False, False
            # 二卖位置前提: 回抽高点不破次级别一卖高点
            if float(cand.high) >= extreme:
                return False, False
            area_cur = _bi_area(cand, bars, hists, "up")
            area_ref = _bi_area(ref, bars, hists, "up")
            return area_ref > 0 and area_cur < area_ref, False
        return False, False
