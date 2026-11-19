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
# 算法遵循缠论原文定义:
#   一买 (B1): 下跌趋势中, 最后一个下跌中枢之后, 末笔创新低且与前一同向下跌笔构成趋势背驰。
#   一卖 (S1): 上涨趋势中, 最后一个上涨中枢之后, 末笔创新高且与前一同向上涨笔构成趋势背驰。
#   二买 (B2): 一买之后, 第一次反弹 (上笔) 不破一买前的中枢上沿zg, 随后的下笔低点不破一买低点。
#   二卖 (S2): 一卖之后, 第一次回抽 (下笔) 不破一卖前的中枢下沿zd, 随后的上笔高点不破一卖高点。
#   三买 (B3): 中枢突破后, 回抽笔低点不进入中枢 (即 > zg), 站稳中枢上沿之上。
#   三卖 (S3): 中枢跌破后, 反弹笔高点不进入中枢 (即 < zd), 被压制在中枢下沿之下。
#
# 背驰判定 (严格按缠论: MACD面积 + DIF/DEA线高点, 三条件AND, 可配置关闭):
#   取末笔 (last) 与前一同向笔 (prev) 对比:
#     1. MACD面积: 按笔区间分型包含的K线累计 (mode=split/total_abs/dif_dea), last_area < prev_area
#     2. DIF极值: 上涨笔取max, 下跌笔取min; last极值弱于prev极值 (上涨:max更小; 下跌:min更大)
#     3. DEA极值: 同上
#   三条件同时满足 (使用对应开关) 才算背驰成立。
#
# 笔区间取值采用"按分型包含"口径: 顶分型 = 三根K线(左中右), 中间K线为分型极值;
#   笔区间 = [bi.fx_a.fx.raw_bars[0].dt, bi.fx_b.fx.raw_bars[-1].dt], 包含两端分型全部K线。

# 默认背驰判定开关 (可通过 features 透传配置覆盖, 二期扩展)
DEFAULT_BS_MACD_AREA_MODE = "split"   # 红绿柱分计
DEFAULT_BS_USE_DIF = True
DEFAULT_BS_USE_DEA = True
DEFAULT_BS_USE_MACD_AREA = True
DEFAULT_BS_ONLY_VALID_ZS = True


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


def _check_divergence(
    prev_bi: Any,
    last_bi: Any,
    bars_out: list,
    macd_out: list,
    dt_str_idx: dict[str, int],
    macd_area_mode: str,
    use_dif: bool,
    use_dea: bool,
    use_macd_area: bool,
) -> dict[str, Any]:
    """判定 prev_bi 与 last_bi (同向) 是否构成背驰。

    返回:
        {
            'is_divergence': bool,
            'macd_area_prev': float|None,
            'macd_area_cur': float|None,
            'dif_peak_prev': float|None,
            'dif_peak_cur': float|None,
            'dea_peak_prev': float|None,
            'dea_peak_cur': float|None,
            'divergence_pass': list[str],   # 命中的条件
            'divergence_type': str,
        }
    """
    prev_dir = _bi_direction(prev_bi)
    last_dir = _bi_direction(last_bi)
    if prev_dir != last_dir or prev_dir == "unknown":
        return _empty_divergence()

    prev_slice = _slice_macd_for_bi(prev_bi, bars_out, macd_out, dt_str_idx)
    last_slice = _slice_macd_for_bi(last_bi, bars_out, macd_out, dt_str_idx)

    area_prev = _calc_bi_macd_area(prev_bi, prev_slice, macd_area_mode)
    area_cur = _calc_bi_macd_area(last_bi, last_slice, macd_area_mode)
    dif_prev = _calc_bi_peak(prev_slice, "dif", prev_dir)
    dif_cur = _calc_bi_peak(last_slice, "dif", last_dir)
    dea_prev = _calc_bi_peak(prev_slice, "dea", prev_dir)
    dea_cur = _calc_bi_peak(last_slice, "dea", last_dir)

    pass_list: list[str] = []

    # 条件1: MACD面积递减
    if use_macd_area:
        if area_prev is not None and area_cur is not None and area_cur < area_prev:
            pass_list.append("macd_area")
        elif area_prev is None or area_cur is None:
            # 数据缺失时不强行判定, 视为该条件未通过
            pass

    # 条件2: DIF极值弱化
    if use_dif:
        if dif_prev is not None and dif_cur is not None:
            if prev_dir == "up" and dif_cur < dif_prev:
                pass_list.append("dif")
            elif prev_dir == "down" and dif_cur > dif_prev:
                pass_list.append("dif")

    # 条件3: DEA极值弱化
    if use_dea:
        if dea_prev is not None and dea_cur is not None:
            if prev_dir == "up" and dea_cur < dea_prev:
                pass_list.append("dea")
            elif prev_dir == "down" and dea_cur > dea_prev:
                pass_list.append("dea")

    # 计算实际启用的条件总数 (用户可能关闭某些条件)
    enabled = []
    if use_macd_area:
        enabled.append("macd_area")
    if use_dif:
        enabled.append("dif")
    if use_dea:
        enabled.append("dea")

    is_div = len(pass_list) == len(enabled) and len(enabled) > 0

    # 背驰类型描述
    if is_div:
        type_str = "+".join(pass_list) + "背驰"
    else:
        type_str = "未构成背驰"

    return {
        "is_divergence": is_div,
        "macd_area_prev": area_prev,
        "macd_area_cur": area_cur,
        "dif_peak_prev": dif_prev,
        "dif_peak_cur": dif_cur,
        "dea_peak_prev": dea_prev,
        "dea_peak_cur": dea_cur,
        "divergence_pass": pass_list,
        "divergence_type": type_str,
    }


def _empty_divergence() -> dict[str, Any]:
    return {
        "is_divergence": False,
        "macd_area_prev": None,
        "macd_area_cur": None,
        "dif_peak_prev": None,
        "dif_peak_cur": None,
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": [],
        "divergence_type": "数据不足",
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
        use_dif/use_dea/use_macd_area: 三条件开关
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
    for i in range(n - 1, 1, -1):
        bi = bi_list_raw[i]
        if _bi_direction(bi) != "down":
            continue
        if i - 2 < 0:
            continue
        prev_bi = _find_trend_start_bi(i, "down")
        if _bi_direction(prev_bi) != "down":
            continue
        # 末笔需创新低 (低于 prev_bi 低点) — 趋势延续
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
        # 关联中枢: 取与 prev_bi 有重叠的最后一个 valid 中枢
        zs_idx = _find_bi_overlap_zs(prev_bi, zs_filtered)
        div = _check_divergence(
            prev_bi, bi, bars_out, macd_out, dt_str_idx,
            macd_area_mode, use_dif, use_dea, use_macd_area,
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
        zs_idx = _find_bi_overlap_zs(prev_bi, zs_filtered)
        div = _check_divergence(
            prev_bi, bi, bars_out, macd_out, dt_str_idx,
            macd_area_mode, use_dif, use_dea, use_macd_area,
        )
        if div["is_divergence"]:
            s1_bi_idx = i
            bs_points.append(_make_bs_point(
                bi=bi, bs_type="S1", direction="卖",
                zs_index=zs_idx, div=div,
                macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
            ))
            break

    # ===== 二买二卖 (B2/S2) =====
    # B2: B1 之后的第一个反弹上笔, 不破 B1 前中枢的 zg; 然后回落, 下笔低点不破 B1 低点
    #     标在 B2 的下笔终点 (底分型)。
    # S2: S1 之后的第一个回抽下笔, 不破 S1 前中枢的 zd; 然后反弹, 上笔高点不破 S1 高点
    #     标在 S2 的上笔终点 (顶分型)。
    if b1_bi_idx is not None and b1_bi_idx + 2 < n:
        b1_bi = bi_list_raw[b1_bi_idx]
        # B1 关联中枢 (取最近的)
        zs_idx_b1 = _find_bi_overlap_zs(bi_list_raw[b1_bi_idx - 2] if b1_bi_idx >= 2 else b1_bi, zs_filtered)
        zg = None
        for zi, zs in zs_filtered:
            if zi == zs_idx_b1:
                zg = float(zs.zg)
                break
        # B1 后第一反弹上笔
        rebound_up = bi_list_raw[b1_bi_idx + 1] if _bi_direction(bi_list_raw[b1_bi_idx + 1]) == "up" else None
        # B1 后回落下笔
        fallback_down = None
        if rebound_up is not None and b1_bi_idx + 2 < n:
            if _bi_direction(bi_list_raw[b1_bi_idx + 2]) == "down":
                fallback_down = bi_list_raw[b1_bi_idx + 2]
        if rebound_up is not None and fallback_down is not None and zg is not None:
            # 反弹不破 zg, 回落不破 B1 低点 → B2
            if rebound_up.high < zg and fallback_down.low > b1_bi.low:
                # 二买卖点也用背驰判定 (用户要求全部统一)
                prev_down = bi_list_raw[b1_bi_idx]  # B1 本身就是前一下跌笔
                div = _check_divergence(
                    prev_down, fallback_down, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_dea, use_macd_area,
                )
                if div["is_divergence"]:
                    bs_points.append(_make_bs_point(
                        bi=fallback_down, bs_type="B2", direction="买",
                        zs_index=zs_idx_b1, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

    if s1_bi_idx is not None and s1_bi_idx + 2 < n:
        s1_bi = bi_list_raw[s1_bi_idx]
        zs_idx_s1 = _find_bi_overlap_zs(bi_list_raw[s1_bi_idx - 2] if s1_bi_idx >= 2 else s1_bi, zs_filtered)
        zd = None
        for zi, zs in zs_filtered:
            if zi == zs_idx_s1:
                zd = float(zs.zd)
                break
        fallback_down = bi_list_raw[s1_bi_idx + 1] if _bi_direction(bi_list_raw[s1_bi_idx + 1]) == "down" else None
        rebound_up = None
        if fallback_down is not None and s1_bi_idx + 2 < n:
            if _bi_direction(bi_list_raw[s1_bi_idx + 2]) == "up":
                rebound_up = bi_list_raw[s1_bi_idx + 2]
        if fallback_down is not None and rebound_up is not None and zd is not None:
            if fallback_down.low > zd and rebound_up.high < s1_bi.high:
                prev_up = bi_list_raw[s1_bi_idx]
                div = _check_divergence(
                    prev_up, rebound_up, bars_out, macd_out, dt_str_idx,
                    macd_area_mode, use_dif, use_dea, use_macd_area,
                )
                if div["is_divergence"]:
                    bs_points.append(_make_bs_point(
                        bi=rebound_up, bs_type="S2", direction="卖",
                        zs_index=zs_idx_s1, div=div,
                        macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                    ))

    # ===== 三买三卖 (B3/S3) =====
    # 中枢突破后回抽不破上沿 (B3) / 跌破中枢后反弹不破下沿 (S3)
    # 遍历每个 valid 中枢, 找中枢之后第一次离开中枢的笔 + 紧接着的回抽/反弹笔
    for zi, zs in zs_filtered:
        zg = float(zs.zg)
        zd = float(zs.zd)
        # 找中枢 bis 在 bi_list_raw 中的范围 (bi_list_raw 不一定与 zs.bis 同引用, 用 dt 匹配)
        # 简化: 用 zs.sdt/edt 找 bi_list_raw 中包含的中枢区间笔
        try:
            zs_sdt = zs.sdt
            zs_edt = zs.edt
        except Exception:  # noqa: BLE001
            continue
        # bi_list_raw 中起点 >= zs.sdt 且终点 <= zs.edt 的笔是中枢内笔; 之后的笔是离开笔
        end_idx = -1
        for k, bi in enumerate(bi_list_raw):
            if bi.edt == zs_edt:
                end_idx = k
                break
        if end_idx < 0 or end_idx + 2 >= n:
            continue
        # 离开笔: 中枢之后第一笔
        leave_bi = bi_list_raw[end_idx + 1]
        # 回抽笔: 离开笔之后第一笔
        back_bi = bi_list_raw[end_idx + 2] if end_idx + 2 < n else None
        if back_bi is None:
            continue

        # 三买: 离开笔向上突破 zg, 回抽笔向下但低点 > zg (不进中枢)
        if _bi_direction(leave_bi) == "up" and leave_bi.high > zg:
            if _bi_direction(back_bi) == "down" and back_bi.low > zg:
                # 离开笔 vs 前一同向上笔背驰 (统一背驰判定)
                prev_up = bi_list_raw[end_idx - 1] if end_idx - 1 >= 0 and _bi_direction(bi_list_raw[end_idx - 1]) == "up" else None
                if prev_up is not None:
                    div = _check_divergence(
                        prev_up, leave_bi, bars_out, macd_out, dt_str_idx,
                        macd_area_mode, use_dif, use_dea, use_macd_area,
                    )
                    if div["is_divergence"]:
                        bs_points.append(_make_bs_point(
                            bi=back_bi, bs_type="B3", direction="买",
                            zs_index=zi, div=div,
                            macd_area_mode=macd_area_mode, bs_item_cls=bs_item_cls,
                        ))

        # 三卖: 离开笔向下跌破 zd, 回抽笔向上但高点 < zd (不进中枢)
        if _bi_direction(leave_bi) == "down" and leave_bi.low < zd:
            if _bi_direction(back_bi) == "up" and back_bi.high < zd:
                prev_down = bi_list_raw[end_idx - 1] if end_idx - 1 >= 0 and _bi_direction(bi_list_raw[end_idx - 1]) == "down" else None
                if prev_down is not None:
                    div = _check_divergence(
                        prev_down, leave_bi, bars_out, macd_out, dt_str_idx,
                        macd_area_mode, use_dif, use_dea, use_macd_area,
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
            zs_list_raw=c.zs_list,
            bi_list_raw=c.bi_list,
            bs_item_cls=BsPointItem,
            macd_area_mode=bs_macd_area_mode,
            use_dif=bs_use_dif,
            use_dea=bs_use_dea,
            use_macd_area=bs_use_macd_area,
            only_valid_zs=True,
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
