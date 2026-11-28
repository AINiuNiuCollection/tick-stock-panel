"""日线 → 周/月 K 重采样 (2026-11-26 修复: 周/月线此前直接返回日线行)。

背景: local_daily / primary 两个日K源对 ("日线","周线","月线") 返回的都是
日线行, 链首 local_daily 稳定命中导致周/月线分析实际在用日线数据
(600809.SH 周线返回 ~2500 根"周K"实为日K)。eastmoney 兜底原生支持
周(102)/月(103), 但永远轮不到。修复口径: 日K源在返回前按级别聚合,
与 eastmoney 原生周/月 K 对齐; MACD 等指标列由调用方在聚合后的
序列上重算 (粒度失效不迁移)。

聚合规则 (标准 OHLCV 重采样):
    周线 → ISO 周 (周一) 归位; 月线 → 自然月首日归位
    open=首, high=max, low=min, close=末, vol/amount=求和
"""
from __future__ import annotations

import logging

import polars as pl

logger = logging.getLogger(__name__)

RESAMPLE_FREQS = ("周线", "月线")


def resample_daily_frame(df: pl.DataFrame, freq: str) -> pl.DataFrame:
    """日线 schema (dt/open/high/low/close/vol/amount) → 周/月 K 聚合。

    非 周/月 freq 原样返回 (日线/分钟不聚合); 空 df 原样返回。
    聚合后仅保留基础列 — macd_* 等指标列粒度随聚合失效, 由调用方
    在聚合后的序列上重算 (与 eastmoney 原生路径无指标列的口径一致)。
    """
    if freq not in RESAMPLE_FREQS or df.is_empty() or "dt" not in df.columns:
        return df
    required = ("dt", "open", "high", "low", "close", "vol")
    if not all(c in df.columns for c in required):
        logger.warning("resample skip: missing columns %s", set(required) - set(df.columns))
        return df

    every = "1w" if freq == "周线" else "1mo"
    agg = [
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("vol").sum(),
    ]
    if "amount" in df.columns:
        agg.append(pl.col("amount").sum())
    try:
        out = (
            df.sort("dt")
            .group_by(pl.col("dt").dt.truncate(every).alias("dt"))
            .agg(agg)
            .sort("dt")
        )
    except Exception as exc:  # noqa: BLE001 — 聚合失败保守降级返回日线行并告警
        logger.warning("resample daily→%s failed, fallback to daily rows: %s", freq, exc)
        return df
    return out.select([c for c in ("dt", "open", "high", "low", "close", "vol", "amount") if c in out.columns])
