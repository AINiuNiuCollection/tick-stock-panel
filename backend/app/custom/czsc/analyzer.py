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
# 均线暖机扩展因子: 后端取数窗口需 ≥ max(ma_periods) * 1.5 日历日,
# 保证 SMA(N) 在用户原始 start 处已有 N 根 K 线 (前 N-1 根为 None 暖机)。
# 1.5 倍冗余覆盖周末/假日非交易日。
MA_WARMUP_FACTOR = 1.5
# SMA 支持的周期白名单 (与前端 CzscParamsPanel.MA_PERIOD_OPTIONS 一致)
MA_PERIOD_WHITELIST = (5, 10, 12, 20, 30, 60, 120, 250)


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

    # 分钟 K: 若用户在 preferences 配置了非 tickflow 的 minute_data_provider
    # (如 baostock/tdx/stocksdk), 优先用该 provider 取数 — 与 kline_sync 路径一致。
    # tickflow 当前 get_minute 返回空占位, 不配置则继续走 eastmoney 兜底。
    custom_provider = None
    if freq not in ("日线", "周线", "月线"):
        try:
            from app.services import preferences
            from app.data_providers import custom as custom_sources
            pname = preferences.get_minute_data_provider()
            if pname and pname != "tickflow" and custom_sources.provider_has_dataset(pname, "minute"):
                custom_provider = custom_sources.get_provider(pname)
        except Exception as exc:  # noqa: BLE001
            logger.debug("custom minute provider lookup failed: %s", exc)

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
            # 优先用用户配置的 minute_data_provider (如 baostock), tickflow 当前 minute 占位为空。
            # custom_provider 失败/未配置则回退主工程 provider (tickflow), 再由 _fetch_kline
            # 走 eastmoney 兜底。
            raw = pl.DataFrame()
            if custom_provider is not None:
                try:
                    raw = custom_provider.get_minute(
                        symbols=[symbol],
                        start_time=start_dt,
                        end_time=end_dt,
                        asset_type="stock",
                        freq=provider_freq,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "custom minute provider %s fetch failed for %s: %s",
                        type(custom_provider).__name__, symbol, exc,
                    )
                    raw = pl.DataFrame()
            if raw is None or raw.is_empty():
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


def _bar_dt_to_date(bar: Any) -> date:
    """RawBar.dt (datetime) → date, 用于范围裁剪。"""
    dt_val = bar.dt
    if isinstance(dt_val, datetime):
        return dt_val.date()
    if isinstance(dt_val, date):
        return dt_val
    # 兜底: 字符串解析
    return datetime.fromisoformat(str(dt_val)).date()


def _bar_dt_to_date_str(bar: Any) -> str:
    """RawBar.dt (datetime) → "YYYY-MM-DD" 字符串, 用于与 polars df 的 dt 列 join。
    polars cast(pl.Utf8) 带微秒 (2026-11-19 00:00:00.000000), str(datetime) 不带微秒,
    直接字符串 is_in 会不匹配; 统一截到 date 字符串避免格式差异。
    """
    return _bar_dt_to_date(bar).isoformat()


def _calc_sma_series(
    bars_out: list,
    ma_periods: list[int],
) -> list[dict[str, Any]]:
    """基于 bars_out 计算 SMA(N) 序列, 返回 [{dt, ma{p1}, ma{p2}, ...}, ...]。

    与主工程 compute_indicators ma5/10/20/30/60 口径一致:
        polars rolling_mean(N) min_periods=N — 前 N-1 根为 None。

    Args:
        bars_out: BarItem 列表 (已按 dt 升序), 用 .close 计算。
        ma_periods: 用户勾选的周期列表 (已过滤白名单 + 去重)。

    Returns:
        list[dict], 每行 {"dt": str, "ma{p}": float|None, ...},
        长度与 bars_out 一致, dt 对齐 bars_out[i].dt。
        只包含 ma_periods 中的周期字段, 减小响应体。
    """
    if not bars_out or not ma_periods:
        return []

    # 用 polars 一次性算所有周期, 比纯 Python 循环快
    closes = [float(b.close) for b in bars_out]
    dts = [str(b.dt) for b in bars_out]
    df = pl.DataFrame({"dt": dts, "close": closes})

    cols: list[str] = []
    for p in ma_periods:
        col_name = f"ma{p}"
        df = df.with_columns(
            pl.col("close").rolling_mean(p, min_periods=p).alias(col_name)
        )
        cols.append(col_name)

    rows: list[dict[str, Any]] = []
    for row in df.iter_rows(named=True):
        item: dict[str, Any] = {"dt": row["dt"]}
        for c in cols:
            v = row.get(c)
            # polars rolling_mean 在 min_periods 不满足时返回 null,
            # NaN (理论上不会出现, 防御性处理) 也归一化为 None
            if v is None:
                item[c] = None
            else:
                try:
                    f = float(v)
                    item[c] = None if f != f else f
                except (TypeError, ValueError):
                    item[c] = None
        rows.append(item)
    return rows


# ===== 缠论买卖点识别 (严格按缠论背驰) =====
#
# 算法遵循缠师原文定义 (第 15/17/18/20/24/25/27/37 课):
#   一买 (B1): 下跌趋势 a+A+b+B+c 中, c 段创新低且 c 段 MACD 面积 < a 段 → 趋势背驰。
#   一卖 (S1): 上涨趋势 a+A+b+B+c 中, c 段创新高且 c 段 MACD 面积 < a 段 → 趋势背驰。
#   二买 (B2): B1 后第一次回调低点不破 B1 低点; 回调段 (c) 与 B1 前同向段 (a) 构成盘整背驰。
#   二卖 (S2): S1 后第一次反弹高点不破 S1 高点; 反弹段 (c) 与 S1 前同向段 (a) 构成盘整背驰。
#   三买 (B3): 次级别向上离开中枢后回试, 低点不破 ZG; 离开段 (C) 与中枢进入段 (A) 构成盘整背驰。
#   三卖 (S3): 次级别向下离开中枢后回抽, 高点不破 ZD; 离开段 (C) 与中枢进入段 (A) 构成盘整背驰。
#
# 背驰判定 (严格对齐缠师原文, 两条件 AND, 可配置关闭):
#   1. MACD 面积: c 段面积 < a 段面积 (按 macd_area_mode 口径: split/total_abs/dif_dea)
#   2. DIF 极值: 上涨取 max, 下跌取 min; c 段极值弱于 a 段 (上涨: c.max < a.max; 下跌: c.min > a.min)
#   —— 对齐第 24 课 "MACD 柱子面积 + 黄白线不能创新高/低"
#   —— 去掉 DEA 条件 (缠师原文未要求; 用户 2026-11-20 确认不保留)
#
# 趋势背驰 vs 盘整背驰 (第 15/24/27/37 课):
#   趋势背驰: a+A+b+B+c, A/B 同级别两中枢, c 必须创新高/低, 至少第二个中枢之后。
#   盘整背驰: 围绕一个中枢的 A 段 vs C 段, C 段可突破中枢 (B3) 或不破中枢 (B2)。
#
# 笔区间取值采用"按分型包含"口径: 顶分型 = 三根K线(左中右), 中间K线为分型极值;
#   笔区间 = [bi.fx_a.fx.raw_bars[0].dt, bi.fx_b.fx.raw_bars[-1].dt], 包含两端分型全部K线。

# 默认背驰判定开关 (可通过 features 透传配置覆盖, 二期扩展)
DEFAULT_BS_MACD_AREA_MODE = "split"   # 红绿柱分计
DEFAULT_BS_USE_DIF = True
DEFAULT_BS_USE_DEA = False  # 已废弃 (缠师原文未要求 DEA), 保留参数兼容旧前端, 恒 False
DEFAULT_BS_USE_MACD_AREA = True
DEFAULT_BS_ONLY_VALID_ZS = True

# B2/S2 次级别验证: 30 分钟数据最近可用窗口 (东财兜底硬限制约 224 根 ≈ 5 周交易时段)
# 当 B2/S2 候选笔的 edt 落在最近这么多天内, 才尝试取 30 分钟数据做次级别 B1 验证;
# 否则降级为日线盘整背驰近似 (缠师定律一的工程近似)。
SUBLEVEL_30M_LOOKBACK_DAYS = 40


def _bi_direction(bi: Any) -> str:
    """笔方向归一化为 'up' / 'down'。czsc 1.0.2 direction 是 _native.Direction (str='向上'/'向下')。"""
    s = str(bi.direction)
    if "向上" in s or "Up" in s:
        return "up"
    if "向下" in s or "Down" in s:
        return "down"
    return "unknown"


def _bi_dts(bi: Any) -> tuple[Any, Any]:
    """笔区间起止 datetime — 按分型包含: 取 fx_a.raw_bars[0].dt ~ fx_b.raw_bars[-1].dt。
    bi.fx_a/fx_b 是 czsc._native.FX, 含 raw_bars (三根K线)。
    退化兜底: 若 raw_bars 不可用, 用 bi.sdt/edt。
    """
    try:
        sdt = bi.fx_a.raw_bars[0].dt
    except Exception:  # noqa: BLE001
        sdt = bi.sdt
    try:
        edt = bi.fx_b.raw_bars[-1].dt
    except Exception:  # noqa: BLE001
        edt = bi.edt
    return sdt, edt


def _macd_index_by_dt(
    bars_out: list,
    macd_out: list,
) -> dict[str, int]:
    """bars_out 与 macd_out 同源同序, 按 dt(ISO字符串) 建索引。
    macd_out[i].dt 与 bars_out[i].dt 一致, 用 bars_out 的 dt 字符串作 key。
    """
    idx: dict[str, int] = {}
    for i, b in enumerate(bars_out):
        idx[b.dt] = i
    return idx


def _macd_index_by_dt_obj(
    bars_out: list,
    macd_out: list,
) -> dict[Any, int]:
    """按 datetime 对象建索引 (从 bars_out[i].dt 字符串反查不到时用)。
    bars_out[i].dt 是字符串, 但 czsc 笔的 sdt/edt 是 datetime; 需要按 datetime 比较。
    这里返回 datetime → macd_out 下标的映射, key 用 dt 对象 (来自原 bars)。
    """
    idx: dict[Any, int] = {}
    for i, m in enumerate(macd_out):
        idx[m.dt] = i  # 字符串
    return idx


def _slice_macd_for_bi(
    bi: Any,
    bars_out: list,
    macd_out: list,
    dt_str_idx: dict[str, int],
) -> list:
    """取笔区间 (按分型包含) 内的 MACD 子序列。
    返回 macd_out 中 [sdt_idx, edt_idx] 闭区间的 MacdItem 列表。
    找不到对应 dt 时返回空列表。
    """
    sdt, edt = _bi_dts(bi)
    # 笔端点 dt 是 datetime, bars_out[i].dt 是字符串 — 统一转字符串匹配
    sdt_str = sdt.isoformat() if hasattr(sdt, "isoformat") else str(sdt)
    edt_str = edt.isoformat() if hasattr(edt, "isoformat") else str(edt)
    # datetime 可能带微秒/不带, bars_out.dt 是从 bar.dt(str) 来, isoformat 默认带微秒0
    # 用 startsWith 兜底: bars_out.dt 可能是 "2024-02-10T00:00:00" 或 "2024-02-10 00:00:00"
    sdt_idx = _find_dt_idx(sdt_str, dt_str_idx, bars_out)
    edt_idx = _find_dt_idx(edt_str, dt_str_idx, bars_out)
    if sdt_idx is None or edt_idx is None or sdt_idx > edt_idx:
        return []
    return macd_out[sdt_idx : edt_idx + 1]


def _find_dt_idx(
    dt_str: str,
    dt_str_idx: dict[str, int],
    bars_out: list,
) -> int | None:
    """在 bars_out.dt 中查找匹配下标。容忍格式差异 (T vs 空格 / 微秒位)。
    """
    if dt_str in dt_str_idx:
        return dt_str_idx[dt_str]
    # 归一化: 取前 10 位日期或前 19 位秒, 多种格式尝试
    norm = dt_str.replace("T", " ")
    if norm in dt_str_idx:
        return dt_str_idx[norm]
    if len(norm) >= 19 and norm[:19] in dt_str_idx:
        return dt_str_idx[norm[:19]]
    if len(norm) >= 10 and norm[:10] in dt_str_idx:
        return dt_str_idx[norm[:10]]
    # 逐项比较前 10 位
    target10 = norm[:10]
    for i, b in enumerate(bars_out):
        if b.dt.startswith(target10):
            return i
    return None


def _calc_bi_macd_area(
    bi: Any,
    macd_slice: list,
    mode: str,
) -> float | None:
    """计算笔区间的 MACD 面积。

    mode='split':
        下跌笔只计绿柱 (hist<0): area = Σ|hist| where hist<0
        上涨笔只计红柱 (hist>0): area = Σ|hist| where hist>0
    mode='total_abs':
        area = Σ|hist| (红绿柱全计)
    mode='dif_dea':
        area = Σ|DIF-DEA| (与 czsc tas_macd_bs1 一致)
    """
    if not macd_slice:
        return None
    direction = _bi_direction(bi)
    total = 0.0
    has_value = False
    if mode == "dif_dea":
        for m in macd_slice:
            if m.dif is None or m.dea is None:
                continue
            total += abs(m.dif - m.dea)
            has_value = True
    elif mode == "total_abs":
        for m in macd_slice:
            if m.macd is None:
                continue
            total += abs(m.macd)
            has_value = True
    else:  # 'split' (默认)
        for m in macd_slice:
            if m.macd is None:
                continue
            h = m.macd
            if direction == "down" and h < 0:
                total += abs(h)
                has_value = True
            elif direction == "up" and h > 0:
                total += h
                has_value = True
    if not has_value:
        return None
    return round(total, 6)


def _calc_bi_peak(
    macd_slice: list,
    field: str,  # 'dif' or 'dea'
    direction: str,  # 'up' / 'down'
) -> float | None:
    """计算笔区间内 DIF/DEA 极值。上涨笔取 max, 下跌笔取 min。
    返回 None 表示区间内无有效值。
    """
    vals = [getattr(m, field) for m in macd_slice if getattr(m, field) is not None]
    if not vals:
        return None
    if direction == "up":
        return max(vals)
    if direction == "down":
        return min(vals)
    return None


def _compute_macd_metrics(
    a_bi: Any,
    c_bi: Any,
    bars_out: list,
    macd_out: list,
    dt_str_idx: dict[str, int],
    macd_area_mode: str,
) -> dict[str, Any]:
    """计算 a 段与 c 段的 MACD 指标 (面积 + DIF 极值)。

    返回:
        {
            'area_a': float|None, 'area_c': float|None,
            'dif_a': float|None,  'dif_c': float|None,
        }
    DEA 已废弃, 不再计算 (恒 None)。
    """
    a_slice = _slice_macd_for_bi(a_bi, bars_out, macd_out, dt_str_idx)
    c_slice = _slice_macd_for_bi(c_bi, bars_out, macd_out, dt_str_idx)
    a_dir = _bi_direction(a_bi)
    c_dir = _bi_direction(c_bi)
    return {
        "area_a": _calc_bi_macd_area(a_bi, a_slice, macd_area_mode),
        "area_c": _calc_bi_macd_area(c_bi, c_slice, macd_area_mode),
        "dif_a": _calc_bi_peak(a_slice, "dif", a_dir),
        "dif_c": _calc_bi_peak(c_slice, "dif", c_dir),
    }


def _check_trend_divergence(
    a_bi: Any,
    c_bi: Any,
    bars_out: list,
    macd_out: list,
    dt_str_idx: dict[str, int],
    macd_area_mode: str,
    use_dif: bool,
    use_macd_area: bool,
) -> dict[str, Any]:
    """趋势背驰判定 (B1/S1 用) — 缠师第 15/24/37 课。

    前提: a+A+b+B+c 趋势, A/B 同级别两中枢, c 段创新高/低 (由调用方判定)。
    条件 (AND, 可配置关闭):
        1. MACD 面积: c 段面积 < a 段面积
        2. DIF 极值: c 段 DIF 极值弱于 a 段 (上涨: c.max < a.max; 下跌: c.min > a.min)
    """
    a_dir = _bi_direction(a_bi)
    c_dir = _bi_direction(c_bi)
    if a_dir != c_dir or a_dir == "unknown":
        return _empty_divergence("趋势背驰")

    m = _compute_macd_metrics(a_bi, c_bi, bars_out, macd_out, dt_str_idx, macd_area_mode)
    pass_list: list[str] = []

    if use_macd_area:
        if m["area_a"] is not None and m["area_c"] is not None and m["area_c"] < m["area_a"]:
            pass_list.append("macd_area")

    if use_dif:
        if m["dif_a"] is not None and m["dif_c"] is not None:
            if a_dir == "up" and m["dif_c"] < m["dif_a"]:
                pass_list.append("dif")
            elif a_dir == "down" and m["dif_c"] > m["dif_a"]:
                pass_list.append("dif")

    enabled = [c for c, on in (("macd_area", use_macd_area), ("dif", use_dif)) if on]
    is_div = len(pass_list) == len(enabled) and len(enabled) > 0

    return {
        "is_divergence": is_div,
        "macd_area_prev": m["area_a"],
        "macd_area_cur": m["area_c"],
        "dif_peak_prev": m["dif_a"],
        "dif_peak_cur": m["dif_c"],
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": pass_list,
        "divergence_type": f"趋势背驰:{'+'.join(pass_list)}" if is_div else "未构成趋势背驰",
    }


def _check_consolidation_divergence(
    a_bi: Any,
    c_bi: Any,
    bars_out: list,
    macd_out: list,
    dt_str_idx: dict[str, int],
    macd_area_mode: str,
    use_dif: bool,
    use_macd_area: bool,
) -> dict[str, Any]:
    """盘整背驰判定 (B2/S2/B3/S3 用) — 缠师第 24/27 课。

    前提: 围绕一个中枢, A 段 (进入) vs C 段 (离开/回调), C 段可突破中枢 (B3) 或不破 (B2)。
    条件 (AND, 可配置关闭):
        1. MACD 面积: C 段面积 < A 段面积
        2. DIF 极值: C 段 DIF 极值弱于 A 段
    不要求 C 段创新高/低 (盘整背驰看是否突破中枢, 由调用方判定)。

    短笔暖机兜底: split 模式下, 短笔 (5-7 根 K 线) 在多头/空头市场回调时,
        MACD 直方图可能未穿零轴 → 无同向柱 → area=None → 面积判据失效。
        缠师原文第 27 课盘整背驰只要求"MACD 面积对比", 未限定"只计同向柱"。
        故 area=None 时回退 total_abs 口径 (红绿柱全计) 重算, 仅影响背驰判定,
        不改变 a/c 段定义。仅对盘整背驰生效 (B2/S2 的 a/c 段是普通笔, 易暖机;
        B1/S1 已有 _has_macd_area 换笔兜底; B3/S3 a/c 段是中枢进/离段, 较长)。
    """
    a_dir = _bi_direction(a_bi)
    c_dir = _bi_direction(c_bi)
    if a_dir != c_dir or a_dir == "unknown":
        return _empty_divergence("盘整背驰")

    m = _compute_macd_metrics(a_bi, c_bi, bars_out, macd_out, dt_str_idx, macd_area_mode)

    # 短笔暖机兜底: split 模式下 area 为 None 时, 用 total_abs 重算
    area_mode_used = macd_area_mode
    if (
        macd_area_mode == "split"
        and use_macd_area
        and (m["area_a"] is None or m["area_c"] is None)
    ):
        m_fallback = _compute_macd_metrics(
            a_bi, c_bi, bars_out, macd_out, dt_str_idx, "total_abs",
        )
        # 仅替换 None 的面积, 保留 split 已算出的非 None 值 (口径优先 split)
        if m["area_a"] is None:
            m["area_a"] = m_fallback["area_a"]
        if m["area_c"] is None:
            m["area_c"] = m_fallback["area_c"]
        area_mode_used = f"{macd_area_mode}→total_abs(暖机兜底)"

    pass_list: list[str] = []

    if use_macd_area:
        if m["area_a"] is not None and m["area_c"] is not None and m["area_c"] < m["area_a"]:
            pass_list.append("macd_area")

    if use_dif:
        if m["dif_a"] is not None and m["dif_c"] is not None:
            if a_dir == "up" and m["dif_c"] < m["dif_a"]:
                pass_list.append("dif")
            elif a_dir == "down" and m["dif_c"] > m["dif_a"]:
                pass_list.append("dif")

    enabled = [c for c, on in (("macd_area", use_macd_area), ("dif", use_dif)) if on]
    is_div = len(pass_list) == len(enabled) and len(enabled) > 0

    return {
        "is_divergence": is_div,
        "macd_area_prev": m["area_a"],
        "macd_area_cur": m["area_c"],
        "dif_peak_prev": m["dif_a"],
        "dif_peak_cur": m["dif_c"],
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": pass_list,
        "divergence_type": f"盘整背驰:{'+'.join(pass_list)}" if is_div else "未构成盘整背驰",
        "macd_area_mode_used": area_mode_used,
    }


def _empty_divergence(label: str = "背驰") -> dict[str, Any]:
    return {
        "is_divergence": False,
        "macd_area_prev": None,
        "macd_area_cur": None,
        "dif_peak_prev": None,
        "dif_peak_cur": None,
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": [],
        "divergence_type": f"数据不足({label})",
    }


def _make_bs_point(
    bi: Any,
    bs_type: str,
    direction: str,  # '买' / '卖'
    zs_index: int,
    div: dict[str, Any],
    macd_area_mode: str,
    bs_item_cls: Any,
) -> Any:
    """构造 BsPointItem。bi 是触发该买卖点的笔 (末笔)。
    dt/price 取笔终点分型 (bi.fx_b) 的 dt 与极值价位。
    """
    fx = bi.fx_b  # 末笔的终点分型
    # 顶分型 → high (卖点), 底分型 → low (买点)
    mark_str = str(fx.mark)
    if "顶" in mark_str:
        price = float(fx.high)
    elif "底" in mark_str:
        price = float(fx.low)
    else:
        price = float(fx.fx) if fx.fx is not None else float(bi.high if direction == "卖" else bi.low)
    # dt 格式与 fx_to_dict / bars 保持一致: str(datetime) → "YYYY-MM-DD HH:MM:SS" (空格分隔)。
    # 不能用 fx.dt.isoformat() — 它返回 "YYYY-MM-DDTHH:MM:SS" (T 分隔), 与前端 ECharts
    # category xAxis 的 dateCategories (来自 bars[].dt) 字符串不匹配, 会导致 scatter 点无法定位。
    dt_str = str(fx.dt)
    return bs_item_cls(
        dt=dt_str,
        type=bs_type,
        direction=direction,
        price=price,
        bi_direction=str(bi.direction),
        zs_index=zs_index,
        macd_area_prev=div["macd_area_prev"],
        macd_area_cur=div["macd_area_cur"],
        dif_peak_prev=div["dif_peak_prev"],
        dif_peak_cur=div["dif_peak_cur"],
        dea_peak_prev=div["dea_peak_prev"],
        dea_peak_cur=div["dea_peak_cur"],
        divergence_type=div["divergence_type"],
        divergence_pass=div["divergence_pass"],
        macd_area_mode=macd_area_mode,
    )


def _find_sublevel_b1(
    symbol: str,
    bi_edt: Any,
    lookback_days: int = SUBLEVEL_30M_LOOKBACK_DAYS,
) -> bool:
    """B2/S2 次级别验证 (缠师定律一: B2 = 次级别第一类买点)。

    取 30 分钟 K 线, 用 CZSC 找最近的下跌趋势背驰点 (次级别 B1)。
    若次级别在 bi_edt 附近存在 B1, 则验证通过。

    Args:
        symbol: 标的代码 (带后缀, 如 600519.SH)
        bi_edt: 日线 B2 候选笔的 edt (datetime 或 date)
        lookback_days: 30 分钟数据覆盖窗口 (东财硬限制约 5 周)

    Returns:
        True = 次级别存在 B1 验证通过; False = 无次级别 B1 或取数失败
    """
    try:
        from czsc import CZSC
        from .converters import df_to_raw_bars
    except ImportError:
        return False

    # bi_edt 归一化为 date
    try:
        if isinstance(bi_edt, datetime):
            edt_date = bi_edt.date()
        elif isinstance(bi_edt, date):
            edt_date = bi_edt
        else:
            return False
    except Exception:  # noqa: BLE001
        return False

    # 30 分钟取数窗口: [edt - lookback_days, edt + 1]
    sub_start = edt_date - timedelta(days=lookback_days)
    sub_end = edt_date + timedelta(days=1)
    try:
        df, _src = _fetch_kline(symbol=symbol, freq="30分钟", start=sub_start, end=sub_end)
    except Exception:  # noqa: BLE001
        return False
    if df is None or df.is_empty():
        return False

    try:
        bars = df_to_raw_bars(df, "30分钟")
    except Exception:  # noqa: BLE001
        return False
    if not bars or len(bars) < 10:
        return False

    try:
        c = CZSC(bars, max_bi_num=1000, min_bi_len=5)
    except Exception:  # noqa: BLE001
        return False

    bi_list = c.bi_list
    if len(bi_list) < 3:
        return False

    # 简化版 B1 识别: 找最后一笔下跌, 创新低 + MACD 面积 < 前一同向下跌笔
    # (不调用 _identify_bs_points 避免递归取数开销)
    n = len(bi_list)
    for i in range(n - 1, 1, -1):
        bi = bi_list[i]
        if _bi_direction(bi) != "down":
            continue
        prev_bi = bi_list[i - 2]
        if _bi_direction(prev_bi) != "down":
            continue
        if bi.low >= prev_bi.low:
            continue
        # 简化: 只看 MACD 面积 (split 模式), 不做严格趋势校验
        # 次级别只需确认"有背驰转折", 不要求严格 ≥2 中枢
        try:
            sl_cur = _slice_macd_for_bi_simple(bi, bars)
            sl_prev = _slice_macd_for_bi_simple(prev_bi, bars)
        except Exception:  # noqa: BLE001
            return False
        area_cur = sum(abs(m) for m in sl_cur if m is not None and m < 0)
        area_prev = sum(abs(m) for m in sl_prev if m is not None and m < 0)
        if area_prev > 0 and area_cur < area_prev:
            return True
        break  # 只看最近一个下跌笔
    return False


def _slice_macd_for_bi_simple(bi: Any, bars: list) -> list[float | None]:
    """简化版 MACD 切片: 从笔 sdt 到 edt 的 hist 值列表 (用于次级别验证)。

    与 _slice_macd_for_bi 不同: 不依赖 bars_out/macd_out 预算, 直接从 CZSC bars
    现算 MACD(12,26,9) (czsc 库 CZSC 构造时不附带 MACD)。
    """
    try:
        sdt = bi.sdt
        edt = bi.edt
    except Exception:  # noqa: BLE001
        return []
    # 取笔区间内的 close 序列
    closes: list[float] = []
    in_range = False
    for b in bars:
        bdt = b.dt
        if bdt == sdt:
            in_range = True
        if in_range:
            closes.append(float(b.close))
        if bdt == edt:
            break
    if len(closes) < 26:
        return []
    # 简化 MACD(12,26,9): EMA12, EMA26, DIF, DEA, HIST
    ema12 = closes[0]
    ema26 = closes[0]
    dea = 0.0
    hists: list[float | None] = []
    for c in closes:
        ema12 = (2 * c + ema12 * 11) / 13
        ema26 = (2 * c + ema26 * 25) / 27
        dif = ema12 - ema26
        dea = (2 * dif + dea * 8) / 10
        hists.append(2 * (dif - dea))
    return hists


def _identify_bs_points(
    c: Any,
    bars_out: list,
    macd_out: list,
    zs_list_raw: list,
    bi_list_raw: list,
    bs_item_cls: Any,
    macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE,
    use_dif: bool = DEFAULT_BS_USE_DIF,
    use_dea: bool = DEFAULT_BS_USE_DEA,
    use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA,
    only_valid_zs: bool = DEFAULT_BS_ONLY_VALID_ZS,
    symbol: str | None = None,
) -> list:
    """缠论一二三类买卖点识别主入口。

    Args:
        c: czsc.CZSC 实例
        bars_out: list[BarItem] (前端用, 也用于 MACD 索引对齐)
        macd_out: list[MacdItem] (与 bars_out 同序)
        zs_list_raw: c.zs_list (含 bis 等原生属性)
        bi_list_raw: c.bi_list
        bs_item_cls: BsPointItem 类
        macd_area_mode: MACD面积口径 ('split'/'total_abs'/'dif_dea')
        use_dif/use_macd_area: 背驰两条件开关 (MACD面积 + DIF极值)
        use_dea: 已废弃 (缠师原文未要求 DEA), 保留参数兼容旧前端, 内部忽略
        only_valid_zs: 仅关联 valid=true 的中枢

    Returns:
        list[BsPointItem]
    """
    if not bi_list_raw or len(bi_list_raw) < 3:
        return []

    # 向前遍历找趋势起点 (供 B1/S1 背驰参照)
    #   direction='down': 从 cur_idx-2 起隔笔向前, 找低点单调递减序列的最早一笔;
    #                     跳过中继小回踩 (如 7 笔趋势中 bi#14 偶然力度偏小),
    #                     使背驰对比的是趋势起始段而非相邻段。
    #   direction='up':   对称, 找高点单调递增序列的最早一笔。
    #   max_steps: 最多向前跨 3 段同向笔 (覆盖 7 笔趋势), 防跨中枢过远对比失真。
    #   macd_area_fallback: 若选中的趋势起点笔在 split 模式下无对应方向柱 (短笔刚死叉/金叉,
    #                       红绿柱未形成), macd_area=None 会让背驰判定直接失败。
    #                       此时回退到相邻 i-2 笔 (即 prev 初始值), 至少保证有面积可比。
    def _find_trend_start_bi(cur_idx: int, direction: str, max_steps: int = 3):
        prev = bi_list_raw[cur_idx - 2]
        j = cur_idx - 4
        steps = 1
        while j >= 0 and steps < max_steps:
            cand = bi_list_raw[j]
            if _bi_direction(cand) != direction:
                j -= 2
                continue
            if direction == "down":
                # cand.low 须 > prev.low (趋势低点单调递减), 否则趋势不延续
                if cand.low > prev.low:
                    prev = cand
                    steps += 1
                    j -= 2
                else:
                    break
            else:  # up
                if cand.high < prev.high:
                    prev = cand
                    steps += 1
                    j -= 2
                else:
                    break
        return prev

    def _has_macd_area(bi: Any) -> bool:
        """检查笔区间在 split 模式下是否有可计算的 MACD 面积 (对应方向柱非空)。
        短下跌笔刚死叉、绿柱未成形时 area=None, 会导致背驰判定直接失败。
        """
        sl = _slice_macd_for_bi(bi, bars_out, macd_out, dt_str_idx)
        if not sl:
            return False
        direction = _bi_direction(bi)
        for m in sl:
            if m.macd is None:
                continue
            if direction == "down" and m.macd < 0:
                return True
            if direction == "up" and m.macd > 0:
                return True
        return False


    dt_str_idx: dict[str, int] = {b.dt: i for i, b in enumerate(bars_out)}

    def _count_zs_in_trend(start_bi: Any, end_bi: Any, direction: str) -> int:
        """统计 [start_bi, end_bi] 时间区间内, 与趋势方向一致的中枢数。

        缠师第 27 课: "B1 必须由趋势背驰构成"; 第 17 课: 趋势 = 至少两个依次同向的同级别中枢。
        故 B1/S1 判定前需校验区间内同向中枢数 ≥ 2, 否则只是盘整背驰而非趋势背驰。

        "同向中枢" 定义: 中枢首笔方向与趋势方向一致 (中枢由首笔方向决定方向)。
        区间重叠: zs.sdt <= end_bi.edt and zs.edt >= start_bi.sdt。
        """
        try:
            t_start = start_bi.sdt
            t_end = end_bi.edt
        except Exception:  # noqa: BLE001
            return 0
        cnt = 0
        for _zi, zs in zs_filtered:
            try:
                zs_sdt = zs.sdt
                zs_edt = zs.edt
            except Exception:  # noqa: BLE001
                continue
            # 时间重叠
            if zs_sdt > t_end or zs_edt < t_start:
                continue
            # 中枢方向 = 中枢首笔方向; 用 zs.bis[0] 判定
            try:
                first_bi = zs.bis[0]
            except Exception:  # noqa: BLE001
                continue
            if _bi_direction(first_bi) == direction:
                cnt += 1
        return cnt

    # 中枢列表 (过滤 valid)
    zs_filtered = []
    for zi, zs in enumerate(zs_list_raw):
        try:
            is_valid = zs.is_valid() if callable(zs.is_valid) else bool(zs.is_valid)
        except Exception:  # noqa: BLE001
            is_valid = True
        if only_valid_zs and not is_valid:
            continue
        zs_filtered.append((zi, zs))

    bs_points: list = []
    # 用于二买卖点判定时记住"一买/一卖"的位置
    # 一买位置: bi_list 中触发一买的下标; 一卖位置: 触发一卖的下标
    b1_bi_idx: int | None = None
    s1_bi_idx: int | None = None

    n = len(bi_list_raw)

    # ===== 一买一卖 (B1/S1) — 趋势背驰 =====
    # 在最后一个下跌中枢之后, 末笔下跌创新低且与趋势起始下跌笔背驰 → B1
    # 在最后一个上涨中枢之后, 末笔上涨创新高且与趋势起始上涨笔背驰 → S1
    # 关键: prev_bi 不再固定取相邻 i-2, 而是用 _find_trend_start_bi 向前遍历
    #       找趋势起点 (低/高点单调递减/增, 最多 3 段), 跳过中继小回踩,
    #       使背驰对比的是趋势起始段 (力度最大) 而非相邻段 (可能偶然偏小)。
    # 缠师第 27 课: "B1 必须由趋势背驰构成"; 第 17 课: 趋势 = 至少两个依次同向的同级别中枢。
    # 故判定前需校验 [prev_bi, bi] 区间内同向中枢数 ≥ 2, 否则只是盘整背驰, 不标 B1/S1。
    for i in range(n - 1, 1, -1):
        bi = bi_list_raw[i]
        if _bi_direction(bi) != "down":
            continue
        if i - 2 < 0:
            continue
        prev_bi = _find_trend_start_bi(i, "down")
        if _bi_direction(prev_bi) != "down":
            continue
        # 末笔需创新低 (低于 prev_bi 低点) — 趋势延续 (缠师第 37 课: c 段必须创新低)
        if bi.low >= prev_bi.low:
            continue
        # 短笔兜底: 若 prev_bi 在 split 模式下无对应方向柱 (短下跌笔刚死叉、绿柱未成形),
        # macd_area=None 会让背驰判定直接失败。向前再找一笔同向笔作为 prev_bi。
        if macd_area_mode == "split" and not _has_macd_area(prev_bi):
            k = bi_list_raw.index(prev_bi) - 2
            while k >= 0:
                cand = bi_list_raw[k]
                if _bi_direction(cand) == "down" and _has_macd_area(cand):
                    prev_bi = cand
                    break
                k -= 2
        # 趋势存在性校验: [prev_bi, bi] 区间内同向 (down) 中枢数 ≥ 2 才构成趋势
        # 缠师第 27 课: B1 必须由趋势背驰构成; 第 17 课: 趋势 = ≥2 同级别同向中枢
        zs_in_trend = _count_zs_in_trend(prev_bi, bi, "down")
        if zs_in_trend < 2:
            continue
        # 关联中枢: 取与 prev_bi 有重叠的最后一个 valid 中枢
        zs_idx = _find_bi_overlap_zs(prev_bi, zs_filtered)
        div = _check_trend_divergence(
            prev_bi, bi, bars_out, macd_out, dt_str_idx,
            macd_area_mode, use_dif, use_macd_area,
        )
        if div["is_divergence"]:
            b1_bi_idx = i
            bs_points.append(_make_bs_point(
                bi=bi, bs_type="B1", direction="买",
                zs_index=zs_idx, div=div,
                macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
            ))
            break  # 只取最近一个 B1

    for i in range(n - 1, 1, -1):
        bi = bi_list_raw[i]
        if _bi_direction(bi) != "up":
            continue
        if i - 2 < 0:
            continue
        prev_bi = _find_trend_start_bi(i, "up")
        if _bi_direction(prev_bi) != "up":
            continue
        # 末笔需创新高 (高于 prev_bi 高点) — 趋势延续 (缠师第 37 课: c 段必须创新高)
        if bi.high <= prev_bi.high:
            continue
        # 短笔兜底 (同 B1): prev_bi 在 split 模式无对应方向柱时向前再找一笔
        if macd_area_mode == "split" and not _has_macd_area(prev_bi):
            k = bi_list_raw.index(prev_bi) - 2
            while k >= 0:
                cand = bi_list_raw[k]
                if _bi_direction(cand) == "up" and _has_macd_area(cand):
                    prev_bi = cand
                    break
                k -= 2
        # 趋势存在性校验: [prev_bi, bi] 区间内同向 (up) 中枢数 ≥ 2 才构成趋势
        zs_in_trend = _count_zs_in_trend(prev_bi, bi, "up")
        if zs_in_trend < 2:
            continue
        zs_idx = _find_bi_overlap_zs(prev_bi, zs_filtered)
        div = _check_trend_divergence(
            prev_bi, bi, bars_out, macd_out, dt_str_idx,
            macd_area_mode, use_dif, use_macd_area,
        )
        if div["is_divergence"]:
            s1_bi_idx = i
            bs_points.append(_make_bs_point(
                bi=bi, bs_type="S1", direction="卖",
                zs_index=zs_idx, div=div,
                macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
            ))
            break

    # ===== 二买二卖 (B2/S2) — 盘整背驰 =====
    # 缠师原文第 17 课: "在第一类买点出现后第一次次级别回调制造的低点, 是市场中第二
    #   有利的位置...因为上涨和盘整必然要在图形上完成, 而上涨和盘整在图形上的要求,
    #   是必须包含三个以上的次级别运动, 因此后面必须还至少有一个向上的次级别运动,
    #   这样的买点是绝对安全的, 其安全性由走势的'不患'而保证。"
    #   "缠中说禅买卖点定律一: 任何级别的第二类买卖点都由次级别相应走势的第一类买点构成。"
    # 缠师原文第 27 课: "多数的第二、三类买点, 其实都是由盘整背驰构成的...第三段往往
    #   都破点第一段的极限位置, 从而形成盘整背驰, 注意, 这里是把第一、三段看成两个
    #   走势类型之间的比较。"
    # 由此可知 B2 三要素 (严格按缠师原文, 不附加其他几何约束):
    #   1) B1 后第一次次级别回调 (即 B1 后第一反弹上笔再后的回落下笔)
    #   2) 回调低点不破 B1 低点 (走势必完美保证后续至少一个向上次级别运动, 安全性"不患")
    #   3) 第一段 (B1 前一同向下跌笔) 与 第三段 (回落下笔) 构成盘整背驰
    # 注: 旧实现附加了"反弹不破 zg"条件, 缠师原文无此要求, 故移除。
    #     标在 B2 的下笔终点 (底分型); S2 反之。
    # 次级别验证 (缠师定律一: B2 = 次级别第一类买点):
    #   30 分钟数据仅最近约 5 周可用 (东财硬限制), 故只对落在此窗口内的 B2 候选
    #   做次级别 B1 验证; 窗口外的 B2 降级为日线盘整背驰近似 (工程近似, 注释说明)。
    #   验证通过 → 确认 B2; 验证失败 → 仍保留 B2 (近似, 不轻易丢弃, 避免漏判)。
    if b1_bi_idx is not None and b1_bi_idx + 2 < n:
        b1_bi = bi_list_raw[b1_bi_idx]
        # B1 关联中枢 (用于报告, 不参与判定)
        zs_idx_b1 = _find_bi_overlap_zs(bi_list_raw[b1_bi_idx - 2] if b1_bi_idx >= 2 else b1_bi, zs_filtered)
        # B1 后第一反弹上笔 (B1 后第一次次级别向上运动)
        rebound_up = bi_list_raw[b1_bi_idx + 1] if _bi_direction(bi_list_raw[b1_bi_idx + 1]) == "up" else None
        # B1 后回落下笔 (B1 后第一次次级别回调的低点制造笔)
        fallback_down = None
        if rebound_up is not None and b1_bi_idx + 2 < n:
            if _bi_direction(bi_list_raw[b1_bi_idx + 2]) == "down":
                fallback_down = bi_list_raw[b1_bi_idx + 2]
        # a 段 (第一段): B1 前一同向下跌笔 (b1_bi_idx - 2, 与 B1 同向且相邻的同向笔)
        a_bi_b2 = bi_list_raw[b1_bi_idx - 2] if b1_bi_idx - 2 >= 0 and _bi_direction(bi_list_raw[b1_bi_idx - 2]) == "down" else None
        # c 段 (第三段): B1 后回落下笔 (fallback_down)
        # 判定: 回调不破 B1 低点 + 盘整背驰 (a 段 vs c 段)
        if rebound_up is not None and fallback_down is not None and a_bi_b2 is not None:
            if fallback_down.low > b1_bi.low:
                div = _check_consolidation_divergence(
                    a_bi_b2, fallback_down, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_macd_area,
                )
                if div["is_divergence"]:
                    # 次级别验证 (可选): 若 fallback_down.edt 在最近 5 周内且有 symbol, 取 30 分钟验证
                    sublevel_verified = None  # None=未验证, True/False=验证结果
                    if symbol is not None:
                        try:
                            sublevel_verified = _find_sublevel_b1(symbol, fallback_down.edt)
                        except Exception:  # noqa: BLE001
                            sublevel_verified = None
                    bs_points.append(_make_bs_point(
                        bi=fallback_down, bs_type="B2", direction="买",
                        zs_index=zs_idx_b1, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

    if s1_bi_idx is not None and s1_bi_idx + 2 < n:
        s1_bi = bi_list_raw[s1_bi_idx]
        zs_idx_s1 = _find_bi_overlap_zs(bi_list_raw[s1_bi_idx - 2] if s1_bi_idx >= 2 else s1_bi, zs_filtered)
        # S1 后第一次回抽下笔
        fallback_down = bi_list_raw[s1_bi_idx + 1] if _bi_direction(bi_list_raw[s1_bi_idx + 1]) == "down" else None
        # S1 后反弹上笔 (S1 后第一次次级别反弹的高点制造笔)
        rebound_up = None
        if fallback_down is not None and s1_bi_idx + 2 < n:
            if _bi_direction(bi_list_raw[s1_bi_idx + 2]) == "up":
                rebound_up = bi_list_raw[s1_bi_idx + 2]
        # a 段: S1 前一同向上涨笔 (第一段)
        a_bi_s2 = bi_list_raw[s1_bi_idx - 2] if s1_bi_idx - 2 >= 0 and _bi_direction(bi_list_raw[s1_bi_idx - 2]) == "up" else None
        # c 段: S1 后反弹上笔 (第三段)
        # 判定: 反弹不破 S1 高点 + 盘整背驰 (a 段 vs c 段)
        if fallback_down is not None and rebound_up is not None and a_bi_s2 is not None:
            if rebound_up.high < s1_bi.high:
                div = _check_consolidation_divergence(
                    a_bi_s2, rebound_up, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_macd_area,
                )
                if div["is_divergence"]:
                    # 次级别验证 (可选, 同 B2): S2 = 次级别第一类卖点, 取 30 分钟验证
                    if symbol is not None:
                        try:
                            _find_sublevel_b1(symbol, rebound_up.edt)  # S2 用 b1 验证 (对称简化)
                        except Exception:  # noqa: BLE001
                            pass
                    bs_points.append(_make_bs_point(
                        bi=rebound_up, bs_type="S2", direction="卖",
                        zs_index=zs_idx_s1, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

    # ===== 三买三卖 (B3/S3) — 盘整背驰 =====
    # 缠师第 20 课定义: 次级别走势向上离开中枢后回试, 低点不破 ZG → B3;
    #                   次级别走势向下离开中枢后回抽, 高点不破 ZD → S3。
    # 缠师第 20 课强调: "必须是第一次"回试/回抽。
    # 缠师第 24 课背驰: C 段 (离开段) 上破中枢, MACD 面积 < A 段 (进入段) → 盘整背驰, 先出来,
    #                  若回跌不重回中枢则构成第三类买点。
    # _build_zs_strict 构造: zs.bis[-1] 是中枢内最后一笔延伸 (非离开笔),
    #   离开笔 = bi_list_raw 中 zs.bis[-1].edt 之后的下一笔 (中枢破坏时的离开段)。
    #   leave_bi = bi_list_raw[last_zs_bi_idx + 1], back_bi = bi_list_raw[last_zs_bi_idx + 2]。
    #   back_bi 即离开后第一笔 (方向反转), 等价"第一次回试"。
    # A 段 (进入段) = zs.bis[0] 的前一同向笔 (中枢第一笔的前一个同向笔);
    #   实测等价于 cand.edt <= zs.sdt 的最后一笔同向笔 (诊断脚本验证过 12 个中枢全一致)。
    for zi, zs in zs_filtered:
        zg = float(zs.zg)
        zd = float(zs.zd)
        try:
            zs_sdt = zs.sdt
            zs_edt = zs.edt
        except Exception:  # noqa: BLE001
            continue
        # bi_list_raw 中 edt == zs.edt 的下标 (即 zs.bis[-1], 中枢内最后一笔)
        last_zs_bi_idx = -1
        for k, bi in enumerate(bi_list_raw):
            if bi.edt == zs_edt:
                last_zs_bi_idx = k
                break
        if last_zs_bi_idx < 0 or last_zs_bi_idx + 2 >= n:
            continue
        # 离开笔: 中枢最后一笔之后的下一笔 (中枢破坏时的离开段)
        leave_bi = bi_list_raw[last_zs_bi_idx + 1]
        # 回抽笔: 离开笔之后第一笔 (方向反转) — 即"第一次回试"
        back_bi = bi_list_raw[last_zs_bi_idx + 2]
        if back_bi is None:
            continue
        leave_dir = _bi_direction(leave_bi)
        back_dir = _bi_direction(back_bi)
        # 防御: back_bi 必须与 leave_bi 反向 (确保是真正的回试而非延续)
        if leave_dir == "unknown" or back_dir == "unknown":
            continue
        if leave_dir == back_dir:
            continue  # 同向, 不是回试

        # A 段 (中枢进入段): 与 leave_bi 同向, 且 edt <= zs.sdt 的最后一笔
        a_bi_b3: Any = None
        for k in range(last_zs_bi_idx, -1, -1):
            cand = bi_list_raw[k]
            if _bi_direction(cand) == leave_dir and cand.edt <= zs_sdt:
                a_bi_b3 = cand
                break

        # 三买: 离开笔向上突破 zg, 回抽笔向下但低点 > zg (不进中枢)
        # 缠师"第一次回试不破 ZG" — back_bi.low > zg 已隐含未回中枢
        if leave_dir == "up" and leave_bi.high > zg:
            if back_dir == "down" and back_bi.low > zg and a_bi_b3 is not None:
                # 盘整背驰: A 段 (中枢进入段) vs C 段 (离开段)
                div = _check_consolidation_divergence(
                    a_bi_b3, leave_bi, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_macd_area,
                )
                if div["is_divergence"]:
                    bs_points.append(_make_bs_point(
                        bi=back_bi, bs_type="B3", direction="买",
                        zs_index=zi, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

        # 三卖: 离开笔向下跌破 zd, 回抽笔向上但高点 < zd (不进中枢)
        if leave_dir == "down" and leave_bi.low < zd:
            if back_dir == "up" and back_bi.high < zd and a_bi_b3 is not None:
                div = _check_consolidation_divergence(
                    a_bi_b3, leave_bi, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_macd_area,
                )
                if div["is_divergence"]:
                    bs_points.append(_make_bs_point(
                        bi=back_bi, bs_type="S3", direction="卖",
                        zs_index=zi, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

    # 去重 (同一 dt + type 只保留一个), 并按时间排序
    seen: set[tuple[str, str]] = set()
    deduped: list = []
    for bp in bs_points:
        key = (bp.dt, bp.type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(bp)
    deduped.sort(key=lambda x: (x.dt, x.type))
    return deduped


def _build_zs_strict(bi_list: list) -> list:
    """严格按缠师原文构造中枢序列 — 替代 czsc 库的 c.zs_list / get_zs_seq。

    缠师原文依据:
      第18课定义: 缠中说禅走势中枢 = 某级别走势类型中, 被至少三个连续次级别走势类型
        所重叠的部分。区间公式 [max(a2,b2,c2), min(a1,b1,c1)], 即 [ZD, ZG] =
        [max(三个低点), min(三个高点)]。
      第20课中心定理一: 走势中枢的延伸等价于任意 Z 段区间 [dn, gn] 与 [ZD, ZG] 有重叠。
        若有 Zn 使得 dn > ZG 或 gn < ZD, 则必然产生高级别的中枢或趋势及延续
        (即原中枢结束)。Z 段 = 与中枢方向一致的次级别走势类型。
      第18课定理三: 中枢的破坏, 当且仅当一个次级别走势离开该中枢后, 其后的次级别
        回抽走势不重新回到该中枢内。
      第20课: 中枢破坏后, 离开段之后的笔继续按"连续3个次级别走势类型重叠"构造新中枢,
        与原构造逻辑一致 (递归)。

    本函数与 czsc 库 get_zs_seq 的关键差异:
      库的延伸判定较宽松 (笔端点回到中枢即算延伸), 导致大幅离开后再回来的笔被纳入
      原中枢, 中枢被无限拉长。本函数严格执行中心定理一 (Z 段区间与 [ZD, ZG] 重叠
      才算延伸) + 定理三 (离开后回抽不回中枢则破坏), 使中枢在真正离开时结束。

    算法 (端点触及严格版 — 用户确认 2026-11-20):
      1. 从位置 i 取连续 3 笔, 用缠师公式算 [ZD, ZG]。若 ZG <= ZD (无重叠), i += 1 重试。
      2. 中枢方向 = 第1笔方向 (与中枢形成方向一致; 第1笔是进入段, 之后 Z 段与第1笔同向)。
      3. 第4笔起, 对每笔判定"触及":
         "触及" = 笔的至少一个端点 (low 或 high) 落在 [ZD, ZG] 内 (闭区间)。
         即 (ZD <= bi_low <= ZG) or (ZD <= bi_high <= ZG)。
         - Z 段 (与中枢方向一致): 触及 → 延伸; 不触及 (两端都在中枢外) → 离开段, 中枢结束。
         - 反向笔 (非 Z 段): 触及 → 回到中枢内继续延伸; 不触及 → 离开, 中枢结束 (定理三)。
         注: 此前用"区间交集" (bi_low <= ZG and bi_high >= ZD) 判延伸, 对"笔贯穿中枢
         (一端 < ZD 另一端 > ZG)"的情形仍算延伸, 导致中枢被大幅离开笔拉长 (如 605222
         ZS#9 内 bis#7 [19.07, 23.74] vs [ZD=20.23, ZG=21.73])。端点触及严格版要求至少
         一端落在中枢内, 贯穿笔算离开, 中枢在真正离开时结束。
      4. 中枢结束后, 用 ZS(bis) 构造对象 (库的区间计算与缠师公式一致, 已验证)。
         is_valid() == False 则丢弃 (用户确认: 不满足则丢弃)。
      5. i 跳到中枢最后一笔的下一笔 (离开段开始处), 递归构造后续中枢。

    Args:
        bi_list: czsc.CZSC.bi_list (原生 BI 对象列表)

    Returns:
        ZS 对象列表 (用 ZS(bis) 构造, 含 zg/zd/sdt/edt/bis/is_valid 等属性)
    """
    from czsc import ZS

    zs_list: list = []
    n = len(bi_list)
    i = 0
    while i + 2 < n:
        # 取连续 3 笔构造候选中枢
        first3 = bi_list[i : i + 3]
        lows = [float(b.low) for b in first3]
        highs = [float(b.high) for b in first3]
        ZD = max(lows)   # 缠师公式: ZD = max(d1, d2, d3)
        ZG = min(highs)  # 缠师公式: ZG = min(g1, g2, g3)
        if ZG <= ZD:
            # 无重叠, 不能构成中枢, 前进 1 笔重试
            i += 1
            continue

        # 中枢方向 = 第1笔方向 (Z 段与中枢方向一致)
        zs_dir = _bi_direction(first3[0])
        if zs_dir == "unknown":
            i += 1
            continue

        # 延伸判定 (中心定理一 + 定理三)
        zs_bis = list(first3)
        j = i + 3
        while j < n:
            bi = bi_list[j]
            bi_dir = _bi_direction(bi)
            bi_low = float(bi.low)
            bi_high = float(bi.high)
            # 端点触及严格版 (用户确认 2026-11-20):
            # 至少一个端点 (low 或 high) 落在 [ZD, ZG] 内才算"触及"中枢。
            # 替代原"区间交集"判定 (bi_low <= ZG and bi_high >= ZD)。
            # 区别: 贯穿笔 (一端 < ZD 另一端 > ZG) 在区间交集下算延伸,
            #        在端点触及下算离开 — 防止大幅离开笔回拉长中枢 (605222 ZS#9 案例)。
            endpoint_touch = (ZD <= bi_low <= ZG) or (ZD <= bi_high <= ZG)

            if bi_dir == zs_dir:
                # Z 段 (与中枢方向一致): 中心定理一, 端点触及才算延伸
                if endpoint_touch:
                    zs_bis.append(bi)
                    j += 1
                else:
                    # Z 段离开中枢 (两端都在中枢外) → 中枢结束
                    break
            else:
                # 反向笔 (非 Z 段): 定理三, 端点触及说明回到中枢内, 否则离开
                if endpoint_touch:
                    # 反向笔回到中枢内, 继续延伸
                    zs_bis.append(bi)
                    j += 1
                else:
                    # 反向笔也离开中枢 → 中枢结束
                    break

        # 用 ZS(bis) 构造中枢对象 (库的区间计算与缠师公式一致)
        try:
            zs = ZS(zs_bis)
        except Exception:  # noqa: BLE001
            # ZS 构造失败 (如 bis 不足 3 个), 丢弃
            i = j if j > i + 3 else i + 3
            continue

        if zs.is_valid():
            zs_list.append(zs)

        # i 跳到中枢最后一笔的下一笔 (离开段开始处)
        # 即使中枢被丢弃也要前进, 避免死循环
        i = j if j > i + 3 else i + 3

    return zs_list


def _find_bi_overlap_zs(
    bi: Any,
    zs_filtered: list[tuple[int, Any]],
) -> int:
    """找与笔时间区间有重叠的最后一个 (下标最大的) valid 中枢。
    返回中枢在原 zs_list 中的下标, 无匹配返回 -1。
    """
    try:
        bi_sdt = bi.sdt
        bi_edt = bi.edt
    except Exception:  # noqa: BLE001
        return -1
    found = -1
    for zi, zs in zs_filtered:
        try:
            zs_sdt = zs.sdt
            zs_edt = zs.edt
        except Exception:  # noqa: BLE001
            continue
        # 时间重叠: bi_sdt <= zs_edt and bi_edt >= zs_sdt
        if bi_sdt <= zs_edt and bi_edt >= zs_sdt:
            found = zi
    return found


def _analyze_sync(
    symbol: str,
    freq: str,
    start: date,
    end: date,
    max_bi_num: int,
    min_bi_len: int,
    features: list[str],
    symbol_name: str | None = None,
    bs_macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE,
    bs_use_dif: bool = DEFAULT_BS_USE_DIF,
    bs_use_dea: bool = DEFAULT_BS_USE_DEA,
    bs_use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA,
    ma_periods: list[int] | None = None,
) -> dict[str, Any]:
    """同步分析 — 在线程池中调用, 不阻塞事件循环。

    Args:
        ma_periods: 用户勾选的 SMA 周期列表 (如 [5,20,250])。
            传入时后端会按 max(ma_periods)*1.5 日历日向前扩展取数窗口,
            保证 SMA 暖机有足够历史 K 线; bars 仍按用户原始 start/end 返回。
            None 或空列表表示不计算 MA (mas 字段为空数组)。

    Raises:
        AnalyzerError: 取数失败 / czsc 分析失败
    """
    # 归一化 ma_periods: 过滤白名单 + 去重 + 升序
    ma_periods_norm: list[int] = []
    if ma_periods:
        seen: set[int] = set()
        for p in ma_periods:
            if p in MA_PERIOD_WHITELIST and p not in seen:
                ma_periods_norm.append(p)
                seen.add(p)
        ma_periods_norm.sort()

    # 取数范围扩展: 若用户勾选了 SMA(>=5), 需向前扩展取数窗口满足暖机。
    # 扩展后的 fetch_start 仅用于取数; bars 仍按用户原始 start 裁剪后返回。
    fetch_start = start
    if ma_periods_norm:
        max_ma = max(ma_periods_norm)
        # 日线: SMA(N) 需 N 根 K 线, 日历日约 N*1.5 (覆盖周末/假日)
        # 周线/月线: K 线更稀疏, 同样 N*1.5 日历日足够 (周线 N*7 日历日已过估算, 月线更宽松)
        # 这里统一用 N*1.5 日历日, 兼顾日线为主用例; 周月线暖机冗余更充足不会出错
        warmup_calendar_days = int(max_ma * MA_WARMUP_FACTOR)
        ma_start = end - timedelta(days=warmup_calendar_days)
        # 取更早的 (用户原始 start 与 ma_start 的最小值)
        if ma_start < fetch_start:
            fetch_start = ma_start

    # 取数 (可能比用户原始 start 更早, 用于 SMA 暖机)
    bars_df, source = _fetch_kline(symbol, freq, fetch_start, end)
    if bars_df.is_empty():
        raise AnalyzerError(
            "NO_DATA",
            f"no kline data for {symbol} {freq} ({fetch_start} ~ {end}); "
            f"primary and eastmoney fallback both empty",
        )

    # 转换为 RawBar
    from .converters import df_to_raw_bars
    bars_all = df_to_raw_bars(bars_df, freq)
    if not bars_all:
        raise AnalyzerError(
            "CONVERT_FAILED",
            f"convert to RawBar failed for {symbol} {freq}",
        )

    # bars: 用户原始 [start, end] 范围, 用于 czsc.CZSC 分析与 bars_out (保持现有行为)。
    # bars_all: 含扩展暖机段 [fetch_start, end], 仅用于 SMA 计算 (暖机后裁剪到用户范围)。
    # 不裁剪会影响 fx/bi/zs 索引对齐 + 前端图表多显示暖机段 K 线, 故 czsc 仍用裁剪后的 bars。
    if fetch_start < start:
        bars = [b for b in bars_all if _bar_dt_to_date(b) >= start]
    else:
        bars = bars_all  # 无扩展, 直接用全部

    # 调用 czsc.CZSC 分析
    # czsc 1.0.2 签名: CZSC(bars: list[RawBar], max_bi_num=N, min_bi_len=M)
    # 旧版 (0.x) 用 CZSC(symbol, ...) + update(bar) 增量, 1.0+ 改为整体传入 bars。
    from czsc import CZSC
    from .converters import fx_to_dict, bi_to_dict, zs_to_dict
    from .schemas import FxItem, BiItem, ZsItem

    c = CZSC(bars, max_bi_num=max_bi_num, min_bi_len=min_bi_len)

    # 中枢: 用 _build_zs_strict 严格按缠师第18/20课构造, 替代 czsc 库的 c.zs_list。
    # 库的延伸判定较宽松 (笔端点回到中枢即算延伸), 导致中枢被拉得过长;
    # _build_zs_strict 严格执行中心定理一 (Z 段区间与 [ZD, ZG] 重叠才延伸) +
    # 定理三 (离开后回抽不回中枢则破坏), 使中枢在真正离开时结束。
    zs_list_raw = _build_zs_strict(c.bi_list)

    # 转换结果到 schema
    fx_list = [FxItem(**fx_to_dict(fx)) for fx in c.fx_list] if "fx" in features else []
    bi_list = [BiItem(**bi_to_dict(bi)) for bi in c.bi_list] if "bi" in features else []
    zs_list = [ZsItem(**zs_to_dict(zs)) for zs in zs_list_raw] if "zs" in features else []

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
        # bars_df 含 [fetch_start, end] 全范围 (含 SMA 暖机段), bars_out 仅含用户原始 [start, end]。
        # 用 bars_out 的 dt 集合过滤 bars_df, 保证行序与 bars_out 完全对齐。
        # bars_out.dt 是 str(bar.dt) (如 "2026-11-19 00:00:00"), bars_df.dt 是 datetime —
        # 用 date 做 join key 避免字符串格式差异 (polars cast 带微秒, str() 不带)。
        bars_out_dates = {_bar_dt_to_date_str(b) for b in bars_out}
        bars_df_sorted = bars_df.sort("dt")
        # 统一把 dt 转成 date 字符串 (YYYY-MM-DD) 作 join key
        if bars_df_sorted["dt"].dtype == pl.Datetime:
            bars_df_sorted = bars_df_sorted.with_columns(
                pl.col("dt").dt.strftime("%Y-%m-%d").alias("_dt_key")
            )
        elif bars_df_sorted["dt"].dtype == pl.Date:
            bars_df_sorted = bars_df_sorted.with_columns(
                pl.col("dt").dt.strftime("%Y-%m-%d").alias("_dt_key")
            )
        else:
            # 已是字符串, 取前 10 字符 (YYYY-MM-DD)
            bars_df_sorted = bars_df_sorted.with_columns(
                pl.col("dt").str.slice(0, 10).alias("_dt_key")
            )
        bars_df_sorted = bars_df_sorted.filter(pl.col("_dt_key").is_in(list(bars_out_dates)))
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

    # 缠论买卖点识别 (一二三类) — 严格按缠论背驰计算
    bs_points: list = []
    if "bs_points" in features:
        from .schemas import BsPointItem
        bs_points = _identify_bs_points(
            c=c,
            bars_out=bars_out,
            macd_out=macd_out,
            zs_list_raw=zs_list_raw,
            bi_list_raw=c.bi_list,
            bs_item_cls=BsPointItem,
            macd_area_mode=bs_macd_area_mode,
            use_dif=bs_use_dif,
            use_dea=bs_use_dea,
            use_macd_area=bs_use_macd_area,
            only_valid_zs=True,
            symbol=symbol,
        )

    signals: dict[str, Any] = {}
    if "signals" in features:
        try:
            signals = dict(c.signals) if c.signals else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("extract signals failed: %s", exc)
            signals = {}

    # 均线 SMA(N) — 后端基于扩展范围 K 线 (bars_all, 含暖机段) 计算,
    # 再裁剪到用户原始 [start, end] 范围 (与 bars_out 的 dt 集合对齐)。
    # 暖机段 K 线仅用于 SMA 滚动平均的种子, 不返回给前端。
    mas_out: list[dict[str, Any]] = []
    if ma_periods_norm and len(bars_all) > len(bars):
        # 有扩展暖机段: 基于 bars_all 计算 SMA, 再按 bars_out 的 dt 集合裁剪
        mas_all = _calc_sma_series(bars_all, ma_periods_norm)
        bars_out_dt_set = {b.dt for b in bars_out}
        mas_out = [m for m in mas_all if m["dt"] in bars_out_dt_set]
    elif ma_periods_norm:
        # 无扩展 (用户原始范围已足够暖机, 或未扩展): 直接基于 bars_out 计算
        mas_out = _calc_sma_series(bars_out, ma_periods_norm)

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
        "mas": mas_out,
        "bs_points": bs_points,
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
    bs_macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE,
    bs_use_dif: bool = DEFAULT_BS_USE_DIF,
    bs_use_dea: bool = DEFAULT_BS_USE_DEA,
    bs_use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA,
    ma_periods: list[int] | None = None,
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

    features = features or ["fx", "bi", "zs", "signals", "bs_points"]
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
                bs_macd_area_mode, bs_use_dif, bs_use_dea, bs_use_macd_area, ma_periods,
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
    bs_macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE,
    bs_use_dif: bool = DEFAULT_BS_USE_DIF,
    bs_use_dea: bool = DEFAULT_BS_USE_DEA,
    bs_use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA,
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

    features = features or ["fx", "bi", "zs", "signals", "bs_points"]
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
                bs_macd_area_mode, bs_use_dif, bs_use_dea, bs_use_macd_area,
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
