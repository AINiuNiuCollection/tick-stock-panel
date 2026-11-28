"""市场宽度 (breadth) — kline_daily_enriched 全历史逐日宽度序列 (v3-⑤)。

口径 (全市场 = 沪深北三市个股, enriched 分区不含指数):
    pct_above_ma20    — 收盘 ≥ 自身 MA20 的个股占比 (0~1)
    pct_new_high_60d  — 收盘创自身 60 日新高的个股占比 (0~1)
    total_amount      — 全市场当日成交额合计
    amount_pctile_250 — total_amount 在最近 250 日样本中的分位 (与总览量能水位同约定)
    amount_level      — extreme_high ≥0.9 / extreme_low ≤0.1 / normal

产出: data/research/breadth_daily.parquet + 指纹 sidecar (breadth_fingerprint.json)。
指纹 = 分区数 + 最新分区日期; 不一致视为缩水/过期, 调用方需重建。
计算为全量重算 (约 4108 分区 × 5500 行), 由后台脚本或显式 rebuild 触发,
不在普通只读请求中执行。
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

RESEARCH_SUBDIR = "research"
BREADTH_FNAME = "breadth_daily.parquet"
FINGERPRINT_FNAME = "breadth_fingerprint.json"
ENRICHED_SUBDIR = "kline_daily_enriched"
MA_PERIOD = 20
NEW_HIGH_PERIOD = 60
PCTILE_WINDOW = 250


def enriched_dir(data_root: str | Path) -> Path:
    return Path(data_root) / ENRICHED_SUBDIR


def research_dir(data_root: str | Path) -> Path:
    return Path(data_root) / RESEARCH_SUBDIR


def _partition_fingerprint(root: str | Path) -> dict:
    """分区指纹 (轻量, 只读目录名不读数据): 分区数 + 最新分区日期。"""
    edir = enriched_dir(root)
    names = sorted(p.name for p in edir.glob("date=*") if p.is_dir())
    return {
        "partition_count": len(names),
        "last_partition": names[-1].removeprefix("date=") if names else None,
    }


def breadth_path(data_root: str | Path) -> Path:
    return research_dir(data_root) / BREADTH_FNAME


def _fingerprint_path(data_root: str | Path) -> Path:
    return research_dir(data_root) / FINGERPRINT_FNAME


def load_breadth(data_root: str | Path) -> pl.DataFrame | None:
    """读已算好的宽度序列; 指纹不匹配 (数据更新过) 返回 None 表示需重建。"""
    fp = _fingerprint_path(data_root)
    parq = breadth_path(data_root)
    if not fp.is_file() or not parq.is_file():
        return None
    try:
        saved = json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if saved != _partition_fingerprint(data_root):
        return None
    return pl.read_parquet(parq)


def compute_breadth(data_root: str | Path) -> pl.DataFrame:
    """全量重算逐日宽度序列并落盘 (parquet + 指纹)。"""
    edir = enriched_dir(data_root)
    lf = pl.scan_parquet(str(edir / "date=*" / "*.parquet")).select(
        ["symbol", "date", "close", "amount"]
    )
    df = (
        lf.sort(["symbol", "date"])
        .with_columns(
            pl.col("close").rolling_mean(MA_PERIOD).over("symbol").alias("ma20"),
            # min_periods=1: 历史不足 60 日时按可得样本判定 (上市次日起即可知是否新高)
            pl.col("close")
            .rolling_max(NEW_HIGH_PERIOD, min_samples=1)
            .over("symbol")
            .alias("high60"),
        )
        .filter(pl.col("ma20").is_not_null() & pl.col("high60").is_not_null())
        .group_by("date")
        .agg(
            (pl.col("close") >= pl.col("ma20")).mean().alias("pct_above_ma20"),
            (pl.col("close") >= pl.col("high60")).mean().alias("pct_new_high_60d"),
            pl.col("amount").sum().alias("total_amount"),
            pl.len().alias("sample_count"),
        )
        .sort("date")
    ).collect()

    # total_amount 近 250 日分位 (滚动窗口小, 转一次性 numpy 滑窗)
    import numpy as np

    totals = df["total_amount"].to_numpy()
    pctile = np.full(len(totals), np.nan)
    for i in range(len(totals)):
        lo = max(0, i - PCTILE_WINDOW + 1)
        win = totals[lo : i + 1]
        if len(win) >= 2:
            pctile[i] = float((win < win[-1]).sum()) / (len(win) - 1)
    df = df.with_columns(
        pl.Series("amount_pctile_250", pctile),
    ).with_columns(
        pl.when(pl.col("amount_pctile_250") >= 0.9)
        .then(pl.lit("extreme_high"))
        .when(pl.col("amount_pctile_250") <= 0.1)
        .then(pl.lit("extreme_low"))
        .otherwise(pl.lit("normal"))
        .alias("amount_level")
    )

    out_dir = research_dir(data_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(breadth_path(data_root))
    _fingerprint_path(data_root).write_text(
        json.dumps(_partition_fingerprint(data_root), ensure_ascii=False), encoding="utf-8"
    )
    return df
