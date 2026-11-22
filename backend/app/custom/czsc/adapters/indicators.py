"""技术指标适配 — EMA/MACD/SMA 与主工程 compute_indicators 口径一致。

主路径: 日线由 `attach_macd_from_pipeline` 复用主工程预算, 避免重复实现。
降级路径: 分钟线 / 东财兜底 / 预算失败时用 `calc_macd` 实时计算。
"""
from __future__ import annotations

import logging
from typing import Any

import polars as pl

from ..domain.models import MacdPoint

logger = logging.getLogger(__name__)


def to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def calc_ema(values: list[float], period: int) -> list[float | None]:
    """EMA(N) 首值种子递推: EMA[0]=close[0], EMA[t]=(2*c+prev*(N-1))/(N+1)。"""
    if not values:
        return []
    out: list[float | None] = []
    prev = float(values[0])
    out.append(prev)
    for i in range(1, len(values)):
        prev = (2 * float(values[i]) + prev * (period - 1)) / (period + 1)
        out.append(prev)
    return out


def calc_macd(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[tuple[float | None, float | None, float | None]]:
    """MACD(12,26,9): DIF=EMA12-EMA26, DEA=EMA(DIF,9), HIST=2*(DIF-DEA)。"""
    ema_fast = calc_ema(closes, fast)
    ema_slow = calc_ema(closes, slow)
    dif_arr = [
        f - s if (f is not None and s is not None) else None
        for f, s in zip(ema_fast, ema_slow, strict=False)
    ]
    dif_vals = [d if d is not None else 0.0 for d in dif_arr]
    dea_arr = calc_ema(dif_vals, signal)
    out: list[tuple[float | None, float | None, float | None]] = []
    for d, e in zip(dif_arr, dea_arr, strict=False):
        hist = None if (d is None or e is None) else 2 * (d - e)
        out.append((d, e, hist))
    return out


def macd_points_from_bars(bars_out: list[Any]) -> list[MacdPoint]:
    closes = [float(b.close) for b in bars_out]
    seq = calc_macd(closes, 12, 26, 9)
    return [
        MacdPoint(dt=b.dt, dif=dif, dea=dea, macd=hist)
        for b, (dif, dea, hist) in zip(bars_out, seq, strict=False)
    ]


def _dt_date_key(value: Any) -> str:
    if isinstance(value, str):
        return value[:10]
    return str(value)[:10]


def precomputed_macd_points(
    bars_out: list[Any],
    df: pl.DataFrame,
) -> list[MacdPoint] | None:
    """读取 df 中预算的 macd_* 列并与 bars_out 对齐; 无法对齐返回 None。"""
    macd_cols = ("macd_dif", "macd_dea", "macd_hist")
    if df.is_empty() or not all(c in df.columns for c in macd_cols):
        return None

    try:
        bars_out_dates = {_dt_date_key(b.dt) for b in bars_out}
        work = df.sort("dt")
        dtype = work["dt"].dtype
        if dtype in (pl.Datetime, pl.Date):
            work = work.with_columns(pl.col("dt").dt.strftime("%Y-%m-%d").alias("_dt_key"))
        else:
            work = work.with_columns(pl.col("dt").str.slice(0, 10).alias("_dt_key"))
        work = work.filter(pl.col("_dt_key").is_in(list(bars_out_dates)))
        if work.height != len(bars_out):
            logger.warning(
                "precomputed macd row count mismatch (df=%d bars=%d), fallback to runtime calc",
                work.height,
                len(bars_out),
            )
            return None
        dif_seq = work["macd_dif"].to_list()
        dea_seq = work["macd_dea"].to_list()
        hist_seq = work["macd_hist"].to_list()
        return [
            MacdPoint(
                dt=bar.dt,
                dif=to_float_or_none(dif),
                dea=to_float_or_none(dea),
                macd=to_float_or_none(hist),
            )
            for bar, dif, dea, hist in zip(bars_out, dif_seq, dea_seq, hist_seq, strict=False)
        ]
    except Exception as exc:
        logger.warning("precomputed macd align failed, fallback to runtime calc: %s", exc)
        return None


def attach_macd_from_pipeline(df: pl.DataFrame) -> pl.DataFrame:
    """复用主工程 compute_indicators 计算 MACD 三列并拼回 df。"""
    try:
        from app.indicators.pipeline import compute_indicators
    except ImportError as exc:
        logger.warning("compute_indicators unavailable, skip MACD precompute: %s", exc)
        return df

    if df.is_empty() or "close" not in df.columns:
        return df

    try:
        work = df
        rename_to_pipe: dict[str, str] = {}
        if "dt" in work.columns and "date" not in work.columns:
            rename_to_pipe["dt"] = "date"
        if "vol" in work.columns and "volume" not in work.columns:
            rename_to_pipe["vol"] = "volume"
        if rename_to_pipe:
            work = work.rename(rename_to_pipe)
        if "symbol" not in work.columns:
            work = work.with_columns(pl.lit("_czsc").alias("symbol"))
        if "date" in work.columns and work["date"].dtype != pl.Date:
            work = work.with_columns(pl.col("date").cast(pl.Date, strict=False))

        work = compute_indicators(work, needed={"macd_dif", "macd_dea", "macd_hist"})

        macd_cols = [c for c in ("macd_dif", "macd_dea", "macd_hist") if c in work.columns]
        if not macd_cols:
            logger.warning("compute_indicators returned no macd columns for czsc")
            return df
        out = (
            work.select(["date", *macd_cols])
            if "date" in work.columns
            else work.select(macd_cols)
        )
        if "date" in out.columns:
            out = out.rename({"date": "dt"})
        if "dt" in out.columns and df["dt"].dtype != out["dt"].dtype:
            out = out.with_columns(pl.col("dt").cast(df["dt"].dtype, strict=False))

        df_sorted = df.sort("dt")
        out_sorted = out.sort("dt")
        if df_sorted.height != out_sorted.height:
            logger.warning(
                "compute_indicators row count mismatch: df=%d macd=%d, skip attach",
                df_sorted.height,
                out_sorted.height,
            )
            return df
        for c in macd_cols:
            df_sorted = df_sorted.with_columns(out_sorted[c].alias(c))
        return df_sorted
    except Exception as exc:
        logger.warning("compute_indicators MACD precompute failed, fallback to runtime calc: %s", exc)
        return df


def compute_sma_series(bars: list[Any], periods: tuple[int, ...] | list[int]) -> list[dict[str, Any]]:
    """SMA(N) 序列, 返回 [{"dt", "ma5", ...}], 长度与 bars 一致。"""
    if not bars or not periods:
        return []
    closes = [float(b.close) for b in bars]
    dts = [str(b.dt) for b in bars]
    df = pl.DataFrame({"dt": dts, "close": closes})
    cols: list[str] = []
    for p in periods:
        col_name = f"ma{p}"
        df = df.with_columns(pl.col("close").rolling_mean(p, min_samples=p).alias(col_name))
        cols.append(col_name)

    rows: list[dict[str, Any]] = []
    for row in df.iter_rows(named=True):
        item: dict[str, Any] = {"dt": row["dt"]}
        for c in cols:
            item[c] = to_float_or_none(row.get(c))
        rows.append(item)
    return rows


def sma_for_range(
    bars_all: list[Any],
    bars_out: list[Any],
    periods: tuple[int, ...],
) -> list[dict[str, Any]]:
    """基于含暖机段的 bars_all 计算, 再裁剪到 bars_out 范围。"""
    if not periods:
        return []
    if len(bars_all) > len(bars_out):
        rows = compute_sma_series(bars_all, periods)
        keep = {b.dt for b in bars_out}
        return [r for r in rows if r["dt"] in keep]
    return compute_sma_series(bars_out, periods)
