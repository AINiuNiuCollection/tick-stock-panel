"""分析编排层 — 唯一调用 czsc.CZSC 的入口。

职责:
    1. 取数: 主工程 MarketDataProvider 优先, EastmoneyFetcher 兜底
    2. 调用 czsc.CZSC 完成缠论分析 (分型/笔/中枢/信号)
    3. CPU 密集运算通过线程池 run_in_executor 隔离
    4. 返回 AnalyzeResult

不直接处理 HTTP, 由 routes.py 路由层调用本模块。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

from app.config import settings

logger = logging.getLogger(__name__)

# 默认分析参数 (与 czsc 库惯例一致)
DEFAULT_MAX_BI_NUM = 100
DEFAULT_MIN_BI_LEN = 7
# 预热窗口: CZSC 需要足够 K 线才能稳定识别笔/中枢
WARMUP_DAYS = 60  # 日历日, 约 40 交易日


class AnalyzerError(Exception):
    """分析层异常。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ===== czsc 可用性探测 (惰性) =====

_HAS_CZSC: bool | None = None
_CZSC_VERSION: str | None = None


def _probe_czsc() -> tuple[bool, str | None]:
    """惰性探测 czsc 是否可用。结果缓存, 避免每次请求重复 import。"""
    global _HAS_CZSC, _CZSC_VERSION
    if _HAS_CZSC is not None:
        return _HAS_CZSC, _CZSC_VERSION
    try:
        import czsc  # noqa: F401
        from czsc import CZSC  # noqa: F401
        _HAS_CZSC = True
        _CZSC_VERSION = getattr(czsc, "__version__", None)
    except ImportError as exc:
        logger.info("czsc not installed, analyzer disabled: %s", exc)
        _HAS_CZSC = False
        _CZSC_VERSION = None
    return _HAS_CZSC, _CZSC_VERSION


# ===== 数据获取: 主源优先, 东财兜底 =====

def _fetch_from_primary(
    symbol: str,
    freq: str,
    start: date,
    end: date,
) -> pl.DataFrame | None:
    """尝试从主工程 MarketDataProvider 取数。

    主工程 provider 走 enriched 前复权口径, 与东财 fqt=1 一致。

    Returns:
        polars DataFrame (列: dt/open/high/low/close/vol/amount) 或 None (主源不可用)
    """
    try:
        from app.data_providers.registry import get_provider
    except ImportError as exc:
        logger.warning("primary provider registry unavailable: %s", exc)
        return None

    try:
        provider = get_provider()
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary provider init failed: %s", exc)
        return None

    # 主工程 provider 是 datetime 区间
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time().replace(microsecond=0))

    try:
        if freq in ("日线", "周线", "月线"):
            raw = provider.get_daily(
                symbols=[symbol],
                start_time=start_dt,
                end_time=end_dt,
                asset_type="stock",
            )
        else:
            # 分钟K: freq 中文 → provider 频率字符串
            # 主工程 provider 用 "1m"/"5m" 等, 这里只支持东财兼容的 5/15/30/60 分钟
            freq_map = {"5分钟": "5m", "15分钟": "15m", "30分钟": "30m", "60分钟": "60m"}
            provider_freq = freq_map.get(freq)
            if provider_freq is None:
                logger.warning("primary provider unsupported freq: %s", freq)
                return None
            raw = provider.get_minute(
                symbols=[symbol],
                start_time=start_dt,
                end_time=end_dt,
                asset_type="stock",
                freq=provider_freq,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary provider fetch failed for %s: %s", symbol, exc)
        return None

    if raw is None or raw.is_empty():
        return None

    # 主工程 normalizer 标准 schema:
    #   daily:  symbol/date/open/high/low/close/volume/amount/quote_ts
    #   minute: 类似但 date 为 datetime
    # 转换为 czsc serve 标准 schema: dt/open/high/low/close/vol/amount
    try:
        df = raw
        # 列名归一化
        rename_map: dict[str, str] = {}
        if "date" in df.columns and "dt" not in df.columns:
            rename_map["date"] = "dt"
        if "volume" in df.columns and "vol" not in df.columns:
            rename_map["volume"] = "vol"
        if rename_map:
            df = df.rename(rename_map)
        # 仅保留 czsc 需要的列
        keep = [c for c in ("dt", "open", "high", "low", "close", "vol", "amount") if c in df.columns]
        df = df.select(keep)
        # dt 转 datetime
        if "dt" in df.columns and df["dt"].dtype != pl.Datetime:
            df = df.with_columns(pl.col("dt").cast(pl.Datetime, strict=False))
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary provider schema normalize failed: %s", exc)
        return None


def _fetch_from_eastmoney(
    symbol: str,
    freq: str,
    start: date,
    end: date,
) -> pl.DataFrame | None:
    """东财兜底取数。"""
    if not settings.czsc_eastmoney_fallback:
        return None
    try:
        from .eastmoney_fallback import fetch_kline, EastmoneyFallbackError
    except ImportError as exc:
        logger.warning("eastmoney fallback module unavailable: %s", exc)
        return None
    try:
        return fetch_kline(symbol, freq, start, end)
    except EastmoneyFallbackError as exc:
        logger.warning("eastmoney fallback failed for %s: [%s] %s", symbol, exc.code, exc.message)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("eastmoney fallback unexpected error: %s", exc)
        return None


def _fetch_kline(
    symbol: str,
    freq: str,
    start: date,
    end: date,
) -> tuple[pl.DataFrame, str]:
    """取数编排: 主源优先, 东财兜底。

    Returns:
        (DataFrame, source) — source 标识数据来源 ("primary" / "eastmoney" / "primary+eastmoney")
    """
    primary_df = _fetch_from_primary(symbol, freq, start, end)
    if primary_df is not None and not primary_df.is_empty():
        return primary_df, "primary"

    east_df = _fetch_from_eastmoney(symbol, freq, start, end)
    if east_df is not None and not east_df.is_empty():
        return east_df, "eastmoney"

    # 都失败, 返回空
    return pl.DataFrame(schema={
        "dt": pl.Datetime, "open": pl.Float64, "high": pl.Float64,
        "low": pl.Float64, "close": pl.Float64, "vol": pl.Float64, "amount": pl.Float64,
    }), "empty"


# ===== czsc.CZSC 分析 (同步, 在线程池中执行) =====

def _calc_ema(values: list[float], period: int) -> list[float | None]:
    """EMA(N) 指数移动平均。前 period-1 个为 None, 之后用标准 EMA 递推:
    EMA_t = (close_t * k) + EMA_{t-1} * (1-k), k = 2/(period+1)。
    第一根有效 EMA 用前 period 根的简单平均作种子 (与 czsc/通用 MACD 一致)。
    """
    if not values:
        return []
    k = 2.0 / (period + 1)
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[tuple[float | None, float | None, float | None]]:
    """计算 MACD(12,26,9): 返回 [(dif, dea, macd_hist), ...]。

    - DIF  = EMA(fast) - EMA(slow)
    - DEA  = EMA(DIF, signal)  (只在 DIF 有效段计算)
    - HIST = 2 * (DIF - DEA)   (与示例图及 czsc/通达信一致)

    前 slow-1 根 DIF 为 None, DEA 在 DIF 之前 signal-1 根为 None。
    """
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    n = len(closes)
    dif_arr: list[float | None] = [None] * n
    first_valid = -1
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif_arr[i] = ema_fast[i] - ema_slow[i]  # type: ignore[operator]
            if first_valid < 0:
                first_valid = i
    # DEA = EMA(DIF, signal), 仅在 DIF 有效段计算
    dea_arr: list[float | None] = [None] * n
    if first_valid >= 0:
        dif_slice = [d for d in dif_arr[first_valid:] if d is not None]  # type: ignore[misc]
        dea_slice = _calc_ema(dif_slice, signal)
        # 映射回原数组下标 (dif_slice[0] 对应 first_valid)
        for j, v in enumerate(dea_slice):
            dea_arr[first_valid + j] = v
    out: list[tuple[float | None, float | None, float | None]] = []
    for i in range(n):
        d = dif_arr[i]
        e = dea_arr[i]
        hist = None if (d is None or e is None) else 2 * (d - e)
        out.append((d, e, hist))
    return out


def _analyze_sync(
    symbol: str,
    freq: str,
    start: date,
    end: date,
    max_bi_num: int,
    min_bi_len: int,
    features: list[str],
) -> dict[str, Any]:
    """同步分析 — 在线程池中调用, 不阻塞事件循环。

    Raises:
        AnalyzerError: 取数失败 / czsc 分析失败
    """
    # 取数
    bars_df, source = _fetch_kline(symbol, freq, start, end)
    if bars_df.is_empty():
        raise AnalyzerError(
            "NO_DATA",
            f"no kline data for {symbol} {freq} ({start} ~ {end}); "
            f"primary and eastmoney fallback both empty",
        )

    # 转换为 RawBar
    from .converters import df_to_raw_bars
    bars = df_to_raw_bars(bars_df, freq)
    if not bars:
        raise AnalyzerError(
            "CONVERT_FAILED",
            f"convert to RawBar failed for {symbol} {freq}",
        )

    # 调用 czsc.CZSC 分析
    # czsc 1.0.2 签名: CZSC(bars: list[RawBar], max_bi_num=N, min_bi_len=M)
    # 旧版 (0.x) 用 CZSC(symbol, ...) + update(bar) 增量, 1.0+ 改为整体传入 bars。
    from czsc import CZSC
    from .converters import fx_to_dict, bi_to_dict, zs_to_dict
    from .schemas import FxItem, BiItem, ZsItem

    c = CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)

    # 转换结果到 schema
    fx_list = [FxItem(**fx_to_dict(fx)) for fx in c.fx_list] if "fx" in features else []
    bi_list = [BiItem(**bi_to_dict(bi)) for bi in c.bi_list] if "bi" in features else []
    zs_list = [ZsItem(**zs_to_dict(zs)) for zs in c.zs_list] if "zs" in features else []

    # K 线 bars (供前端图表渲染 candlestick + 作为 fx/bi/zs 坐标轴类目)
    from .schemas import BarItem, MacdItem
    bars_out: list[BarItem] = []
    for bar in bars:
        bars_out.append(BarItem(
            dt=str(bar.dt),
            open=float(bar.open), high=float(bar.high),
            low=float(bar.low), close=float(bar.close),
            vol=float(bar.vol) if bar.vol is not None else 0.0,
            amount=float(bar.amount) if bar.amount is not None else 0.0,
        ))

    # MACD(12,26,9) — 前端示例图含 MACD 副图, 在后端计算避免前端重复实现 EMA。
    closes = [b.close for b in bars_out]
    macd_seq = _calc_macd(closes, 12, 26, 9)
    macd_out: list[MacdItem] = []
    for bar, (dif, dea, hist) in zip(bars_out, macd_seq):
        macd_out.append(MacdItem(
            dt=bar.dt,
            dif=dif,
            dea=dea,
            macd=hist,
        ))

    signals: dict[str, Any] = {}
    if "signals" in features:
        try:
            signals = dict(c.signals) if c.signals else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("extract signals failed: %s", exc)
            signals = {}

    return {
        "symbol": symbol,
        "freq": freq,
        "bar_count": len(bars),
        "fx_list": fx_list,
        "bi_list": bi_list,
        "zs_list": zs_list,
        "bars": bars_out,
        "macd": macd_out,
        "signals": signals,
        "warnings": None,
        "source": source,
        "cached": False,
    }


async def analyze_async(
    symbol: str,
    freq: str,
    start: date | None = None,
    end: date | None = None,
    max_bi_num: int = DEFAULT_MAX_BI_NUM,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
    features: list[str] | None = None,
) -> dict[str, Any]:
    """异步分析入口 — 通过线程池隔离 CPU 密集运算。

    Raises:
        AnalyzerError: czsc 未安装 / 取数失败 / 分析超时 / 内部错误
    """
    has_czsc, _ = _probe_czsc()
    if not has_czsc:
        raise AnalyzerError(
            "CZSC_NOT_INSTALLED",
            "czsc library not installed; run: uv sync --extra czsc",
        )

    features = features or ["fx", "bi", "zs", "signals"]
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=365 + WARMUP_DAYS)

    loop = asyncio.get_event_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                _analyze_sync,
                symbol, freq, start, end, max_bi_num, min_bi_len, features,
            ),
            timeout=settings.czsc_analyze_timeout_s,
        )
    except asyncio.TimeoutError as exc:
        raise AnalyzerError(
            "ANALYZE_TIMEOUT",
            f"czsc analyze timeout after {settings.czsc_analyze_timeout_s}s",
        ) from exc
    except AnalyzerError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AnalyzerError("INTERNAL_ERROR", f"czsc analyze failed: {exc}") from exc

    return result


# ===== 流式分析 (SSE) =====

async def analyze_stream(
    symbol: str,
    freq: str,
    start: date | None = None,
    end: date | None = None,
    max_bi_num: int = DEFAULT_MAX_BI_NUM,
    min_bi_len: int = DEFAULT_MIN_BI_LEN,
    features: list[str] | None = None,
):
    """流式分析异步生成器, 产出 SSE 事件 dict。

    事件类型:
        {"event": "status", "data": {"phase": "fetching_kline", ...}}
        {"event": "status", "data": {"phase": "analyzing", "bar_count": N}}
        {"event": "partial", "data": {"fx_list": [...], "progress": 0.4}}
        {"event": "done", "data": {"result": {...}}}
        {"event": "error", "data": {"code": "...", "message": "..."}}
    """
    has_czsc, _ = _probe_czsc()
    if not has_czsc:
        yield {"event": "error", "data": {
            "code": "CZSC_NOT_INSTALLED",
            "message": "czsc library not installed; run: uv sync --extra czsc",
        }}
        return

    features = features or ["fx", "bi", "zs", "signals"]
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=365 + WARMUP_DAYS)

    # 阶段 1: 取数 (线程池)
    yield {"event": "status", "data": {"phase": "fetching_kline", "symbol": symbol}}
    await asyncio.sleep(0)

    loop = asyncio.get_event_loop()
    try:
        bars_df, source = await loop.run_in_executor(
            None, _fetch_kline, symbol, freq, start, end,
        )
    except Exception as exc:  # noqa: BLE001
        yield {"event": "error", "data": {"code": "FETCH_FAILED", "message": str(exc)}}
        return

    if bars_df.is_empty():
        yield {"event": "error", "data": {
            "code": "NO_DATA",
            "message": f"no kline data for {symbol} {freq}",
        }}
        return

    # 阶段 2: 转换 + 分析 (线程池, 一次完成)
    yield {"event": "status", "data": {
        "phase": "analyzing", "symbol": symbol, "bar_count": bars_df.height,
    }}
    await asyncio.sleep(0)

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                _analyze_sync,
                symbol, freq, start, end, max_bi_num, min_bi_len, features,
            ),
            timeout=settings.czsc_analyze_timeout_s,
        )
    except asyncio.TimeoutError:
        yield {"event": "error", "data": {
            "code": "ANALYZE_TIMEOUT",
            "message": f"czsc analyze timeout after {settings.czsc_analyze_timeout_s}s",
        }}
        return
    except AnalyzerError as exc:
        yield {"event": "error", "data": {"code": exc.code, "message": exc.message}}
        return
    except Exception as exc:  # noqa: BLE001
        yield {"event": "error", "data": {"code": "INTERNAL_ERROR", "message": str(exc)}}
        return

    # 阶段 3: 分批产出结果
    if "fx" in features:
        yield {"event": "partial", "data": {
            "fx_list": [f.model_dump() for f in result["fx_list"]],
            "progress": 0.4,
        }}
        await asyncio.sleep(0)

    if "bi" in features:
        yield {"event": "partial", "data": {
            "bi_list": [b.model_dump() for b in result["bi_list"]],
            "progress": 0.7,
        }}
        await asyncio.sleep(0)

    if "zs" in features:
        yield {"event": "partial", "data": {
            "zs_list": [z.model_dump() for z in result["zs_list"]],
            "progress": 0.9,
        }}
        await asyncio.sleep(0)

    yield {"event": "done", "data": {"result": {**result, "ok": True}}}
