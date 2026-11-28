"""事件背景 — 缠论日线笔方向 (v2, 设计 §2.2 完整要求)。

对每条 countable 事件补充「事件生效日所在日线笔的方向」:
    - 复用缠论引擎 (czsc_adapter.run_czsc) 对上证全历史日K跑一次笔序列,
      与缠论多级别 Tab 同口径 (同 min_bi_len/max_bi_num 链路, 不另写笔判断);
    - 取笔结构中 sdt <= 事件日 <= edt 的包含笔方向; 事件日恰在相邻笔共享
      端点时取"到达该端点"的笔 (即刚走完的方向);
    - 事件早于首笔 (数据暖机不足) 返回 None (不虚构), 前端显示"笔数据不足";
    - czsc 未安装 (optional-dependency) 时优雅降级为空 map, 不影响统计。

性能: 单次 CZSC 全历史运行按 (symbol, 数据首末日期, 根数, 笔参数) 缓存,
/events 系列请求只付一次成本; kline 来自 data.py 的 _RAW_CACHE, 缓存键与
其指纹思路一致 (回填后首末日期/根数变化自动失效)。

口径注意: 全历史最终笔结构存在少量"事后修正"边缘情形 (缠论笔端点需确认
K线), 作为事件背景披露可接受 — 与 B/S 点信号同级别的口径约束见
docs/czsc_audit_report 系列。
"""
from __future__ import annotations

import logging
from datetime import date

import polars as pl

logger = logging.getLogger(__name__)

# 全历史笔数上限: czsc 默认 max_bi_num=100 只保留近端笔, 事件库横跨
# 1990s→今, 需放大约一个数量级覆盖全部 countable 事件日期。
_FULL_MAX_BI_NUM = 2000

# (symbol, first, last, n_rows, max_bi_num, min_bi_len) -> [(sdt, edt, dir), ...]
_BI_CACHE: dict[tuple, tuple[tuple[date, date, str], ...] | None] = {}


def _run_bi_series(kline: pl.DataFrame, symbol: str, min_bi_len: int, max_bi_num: int):
    """全历史日K → 笔序列 (缓存)。kline 为 load_index_daily 输出 (date/OHLC/volume)。"""
    try:
        from app.custom.czsc.adapters.czsc_adapter import probe_czsc, run_czsc
        from app.custom.czsc.converters import df_to_raw_bars
    except ImportError:  # pragma: no cover — czsc 子包随主工程存在
        return None

    ok, _ver = probe_czsc()
    if not ok:
        return None

    first, last = kline["date"].min(), kline["date"].max()
    key = (symbol, str(first), str(last), kline.height, max_bi_num, min_bi_len)
    if key in _BI_CACHE:
        return _BI_CACHE[key]

    bars = df_to_raw_bars(
        kline.rename({"date": "dt", "volume": "vol"}), "日线"
    )
    if not bars:
        _BI_CACHE[key] = None
        return None
    try:
        _fxs, bis, _signals = run_czsc(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)
        series = tuple(
            (bi.sdt.date() if hasattr(bi.sdt, "date") else bi.sdt,
             bi.edt.date() if hasattr(bi.edt, "date") else bi.edt,
             bi.direction)
            for bi in bis
        )
    except Exception as exc:  # noqa: BLE001 — 笔计算失败降级, 不影响事件统计
        logger.warning("bi_context run_czsc failed for %s: %s", symbol, exc)
        _BI_CACHE[key] = None
        return None
    _BI_CACHE[key] = series
    return series


def bi_directions_for(
    events: list,
    kline: pl.DataFrame,
    symbol: str = "000001.SH",
    min_bi_len: int = 7,
) -> dict[str, str | None]:
    """事件 id -> 所在日线笔方向 ('up'/'down'/None)。"""
    if not events or kline.is_empty():
        return {}
    series = _run_bi_series(kline, symbol, min_bi_len, _FULL_MAX_BI_NUM)
    if not series:
        return {ev.id: None for ev in events}

    def direction_at(day: date) -> str | None:
        for sdt, edt, direction in series:
            if sdt <= day <= edt:
                # 含共享端点时取第一匹配 = 到达该端点的笔 (刚走完的方向)
                return direction
        return None

    out: dict[str, str | None] = {}
    for ev in events:
        out[ev.id] = direction_at(ev.date)
    return out


def current_bi_direction(
    kline: pl.DataFrame, symbol: str, day: date, min_bi_len: int = 7
) -> str | None:
    """指定日 (通常=最新K线日) 所在日线笔方向 — 总览快照复用同一笔序列。"""
    if kline.is_empty():
        return None
    series = _run_bi_series(kline, symbol, min_bi_len, _FULL_MAX_BI_NUM)
    if not series:
        return None
    for sdt, edt, direction in series:
        if sdt <= day <= edt:
            return direction
    return None
