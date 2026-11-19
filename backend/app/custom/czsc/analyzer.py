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
    返回的 DataFrame 在 czsc 标准列 (dt/open/high/low/close/vol/amount) 之外,
    附带预计算的 MACD 三列 (macd_dif/macd_dea/macd_hist), 由主工程
    `indicators.pipeline.compute_indicators` 统一口径计算, 避免本模块
    重复实现 EMA 递推。分钟 K 线不计算 MACD (主工程 compute_indicators 仅
    适配日线 schema), 仍由 _analyze_sync 后续路径处理。

    Returns:
        polars DataFrame 或 None (主源不可用)
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
        # dt 转 datetime (compute_indicators 不要求 datetime, 但 czsc 转换层需要)
        if "dt" in df.columns and df["dt"].dtype != pl.Datetime:
            df = df.with_columns(pl.col("dt").cast(pl.Datetime, strict=False))

        # 日线/周线/月线: 复用主工程 compute_indicators 预算 MACD, 与主工程回测/选股口径一致。
        # 分钟线: compute_indicators 仅适配日线 schema (.over("symbol") 按 date 排序), 跳过,
        # 由 _analyze_sync 走兜底路径 (返回的 df 不含 macd_* 列)。
        if freq in ("日线", "周线", "月线") and "close" in df.columns:
            df = _attach_macd_from_pipeline(df)

        # 仅保留 czsc 需要的列 + MACD 列 (若存在)
        keep_base = [c for c in ("dt", "open", "high", "low", "close", "vol", "amount") if c in df.columns]
        keep_macd = [c for c in ("macd_dif", "macd_dea", "macd_hist") if c in df.columns]
        df = df.select(keep_base + keep_macd)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.warning("primary provider schema normalize failed: %s", exc)
        return None


def _attach_macd_from_pipeline(df: pl.DataFrame) -> pl.DataFrame:
    """复用主工程 `indicators.pipeline.compute_indicators` 计算 MACD(12,26,9)。

    compute_indicators 输入契约: 必须含 symbol/date/open/high/low/close/volume;
    输出追加 macd_dif/macd_dea/macd_hist 三列 (按 symbol 分组 .over("symbol") 递推)。
    本函数:
        1. 把 czsc schema (dt/vol) 临时反归一化为主工程 schema (date/volume/symbol);
        2. 调 compute_indicators 仅计算 MACD 闭包 (needed={"macd_dif","macd_dea","macd_hist"});
        3. 取回 macd 三列并 restore 列名, 不破坏外部 dt/vol 命名。
    失败时返回原 df (不附带 MACD), 由调用方降级到实时计算路径。

    Note: 周线/月线在主工程无独立计算路径, 这里仍走日线相同的 ewm 递推
    (close 序列就是周/月 close 序列, EMA 递推与频率无关, 仅暖机根数相同)。
    """
    try:
        from app.indicators.pipeline import compute_indicators
    except ImportError as exc:
        logger.warning("compute_indicators unavailable, skip MACD precompute: %s", exc)
        return df

    if df.is_empty() or "close" not in df.columns:
        return df

    try:
        # 构造 compute_indicators 所需的输入 schema
        work = df
        rename_to_pipe: dict[str, str] = {}
        if "dt" in work.columns and "date" not in work.columns:
            rename_to_pipe["dt"] = "date"
        if "vol" in work.columns and "volume" not in work.columns:
            rename_to_pipe["vol"] = "volume"
        if rename_to_pipe:
            work = work.rename(rename_to_pipe)
        # compute_indicators 按 .over("symbol") 分组, 单标的也要有 symbol 列
        if "symbol" not in work.columns:
            work = work.with_columns(pl.lit("_czsc").alias("symbol"))
        # date 转 Date (compute_indicators 内部 sort(["symbol","date"]))
        if "date" in work.columns and work["date"].dtype != pl.Date:
            work = work.with_columns(pl.col("date").cast(pl.Date, strict=False))

        work = compute_indicators(
            work,
            needed={"macd_dif", "macd_dea", "macd_hist"},
        )

        # 取回 macd 三列, 反归一化列名
        macd_cols = [c for c in ("macd_dif", "macd_dea", "macd_hist") if c in work.columns]
        if not macd_cols:
            logger.warning("compute_indicators returned no macd columns for czsc")
            return df
        out = work.select(["date", *macd_cols]) if "date" in work.columns else work.select(macd_cols)
        # 对齐回原 df: 用 date 反 rename 为 dt 与原 df join
        if "date" in out.columns:
            out = out.rename({"date": "dt"})
        # 原 df 的 dt 是 datetime, out 的 dt 现在是 Date —— 统一 cast 后 join
        if "dt" in out.columns and df["dt"].dtype != out["dt"].dtype:
            out = out.with_columns(pl.col("dt").cast(df["dt"].dtype, strict=False))
        # join 按行序对齐 (两边都按 dt 升序)
        df_sorted = df.sort("dt")
        out_sorted = out.sort("dt")
        if df_sorted.height != out_sorted.height:
            logger.warning(
                "compute_indicators row count mismatch: df=%d macd=%d, skip attach",
                df_sorted.height, out_sorted.height,
            )
            return df
        # 行序对齐, 直接拼接 macd 列
        for c in macd_cols:
            df_sorted = df_sorted.with_columns(out_sorted[c].alias(c))
        return df_sorted
    except Exception as exc:  # noqa: BLE001
        logger.warning("compute_indicators MACD precompute failed, fallback to runtime calc: %s", exc)
        return df


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

def _to_float_or_none(v: Any) -> float | None:
    """polars 列 to_list 后的值归一化: NaN/None → None, 其余转 float。

    compute_indicators 用 polars ewm_mean(adjust=False), 首值种子递推,
    理论上不会产生 null (除非 close 列本身有 null); 中间若出现 NaN
    (0/0 等) 应视为缺值。与 czsc 库 compute_macd 口径一致。
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _calc_ema(values: list[float], period: int) -> list[float | None]:
    """EMA(N) 指数移动平均 — 首值种子递推口径。

    与 czsc 库 `czsc.utils.plotting._macd._ema`、主工程 `compute_indicators`
    (polars `ewm_mean(adjust=False)`) 完全一致:
        EMA[0] = close[0]
        EMA[t] = (2*close[t] + EMA[t-1]*(period-1)) / (period+1)

    该口径从第一根起就有值, 无暖机空白段, 与通达信/同花顺一致。
    (TA-Lib 的「前 N 根均值作种子」是另一种约定, 本项目不采用。)
    """
    if not values:
        return []
    out: list[float | None] = []
    prev = float(values[0])
    out.append(prev)
    for i in range(1, len(values)):
        prev = (2 * float(values[i]) + prev * (period - 1)) / (period + 1)
        out.append(prev)
    return out


def _calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[tuple[float | None, float | None, float | None]]:
    """计算 MACD(12,26,9): 返回 [(dif, dea, macd_hist), ...]。

    口径与 czsc 库 `compute_macd`、主工程 `compute_indicators` 完全一致:
        - DIF  = EMA(fast) - EMA(slow)   (首值种子, 从 idx 0 起有效)
        - DEA  = EMA(DIF, signal)
        - HIST = 2 * (DIF - DEA)

    本函数作为降级路径 (分钟线 / 东财兜底 / compute_indicators 不可用),
    主路径日线已由 _fetch_from_primary → _attach_macd_from_pipeline 预算。
    """
    ema_fast = _calc_ema(closes, fast)
    ema_slow = _calc_ema(closes, slow)
    dif_arr = [f - s if (f is not None and s is not None) else None
               for f, s in zip(ema_fast, ema_slow)]
    # DEA = EMA(DIF, signal); DIF 从 idx 0 起有效, 直接整体递推
    dif_vals = [d if d is not None else 0.0 for d in dif_arr]
    dea_arr = _calc_ema(dif_vals, signal)
    out: list[tuple[float | None, float | None, float | None]] = []
    for d, e in zip(dif_arr, dea_arr):
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
    symbol_name: str | None = None,
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

    # MACD(12,26,9):
    #   主源日线 → _fetch_from_primary 已通过 compute_indicators 预算并附带
    #             macd_dif/macd_dea/macd_hist 列, 直接读取 (口径与主工程一致)。
    #   其他场景 (分钟线 / 东财兜底 / compute_indicators 失败降级) → 实时计算。
    macd_out: list[MacdItem] = []
    has_precomputed_macd = (
        not bars_df.is_empty()
        and all(c in bars_df.columns for c in ("macd_dif", "macd_dea", "macd_hist"))
    )
    if has_precomputed_macd:
        # bars_df 与 bars_out 同源同序 (df_to_raw_bars 内部 sort("dt"))
        # 但 bars 可能因转换失败被截断, 这里以 bars_out 为准按 dt 对齐取值
        bars_df_sorted = bars_df.sort("dt")
        # 行数对齐保护: 仅在完全对齐时直接 zip, 否则降级
        if bars_df_sorted.height == len(bars_out):
            dif_seq = bars_df_sorted["macd_dif"].to_list()
            dea_seq = bars_df_sorted["macd_dea"].to_list()
            hist_seq = bars_df_sorted["macd_hist"].to_list()
            for bar, dif, dea, hist in zip(bars_out, dif_seq, dea_seq, hist_seq):
                macd_out.append(MacdItem(
                    dt=bar.dt,
                    dif=_to_float_or_none(dif),
                    dea=_to_float_or_none(dea),
                    macd=_to_float_or_none(hist),
                ))
        else:
            logger.warning(
                "precomputed macd row count mismatch (df=%d bars=%d), fallback to runtime calc",
                bars_df_sorted.height, len(bars_out),
            )
            has_precomputed_macd = False

    if not has_precomputed_macd:
        closes = [b.close for b in bars_out]
        macd_seq = _calc_macd(closes, 12, 26, 9)
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
        "symbol_name": symbol_name,
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
    symbol_name: str | None = None,
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
                symbol, freq, start, end, max_bi_num, min_bi_len, features, symbol_name,
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
    symbol_name: str | None = None,
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
                symbol, freq, start, end, max_bi_num, min_bi_len, features, symbol_name,
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
