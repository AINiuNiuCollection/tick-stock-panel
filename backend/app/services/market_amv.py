"""0AMV (活跃市值) 日级时序计算与持久化。

0AMV = Σ (close × float_shares × FREE_FLOAT_RATIO)  for all stocks where volume > 0
- close: 前复权价(与工程其他指标一致)
- float_shares: instruments 快照(历史无股本变更数据, 与 regime/mainline 同口径)
- FREE_FLOAT_RATIO: 自由流通比例近似系数。工程数据源(tickflow SDK)只提供流通股本,
  不提供自由流通股本, 无法逐股精确计算自由流通市值。用全市场经验系数 0.179 近似,
  经 2026-09-07~10 四天验证, 与指南针 0AMV 误差 ±2%。
  系数选取依据: 自由流通市值/流通市值 4日观测值 0.1758/0.1784/0.1808/0.1816, 均值 0.179。
  局限: 不同股票自由流通比例差异大(银行 5-15%, 小盘股 ~100%), 系数法无法反映个股差异,
  当市场结构发生变化(如大盘股集中涨跌)时误差可能扩大。
- volume > 0: 有成交才计入(活跃判定)

衍生指标: active_count(活跃股票数), amv_ma5, amv_ma20

架构类比 regime_builder: 服务层 builder + date-keyed parquet + API 端点。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

# ───────────────────────── 路径与读写 ─────────────────────────

AMV_DIR = "amv_history"

# 自由流通比例近似系数: 0AMV 与指南针对齐用。
# 工程数据源只有流通股本(float_shares), 无自由流通股本(free_float_shares)。
# 经 2026-09-07~10 四天验证: 自由流通市值/流通市值 = 0.1758~0.1816, 取均值 0.179。
# 局限: 无法反映个股差异(银行 5-15% vs 小盘股 ~100%), 误差 ±2%。
FREE_FLOAT_RATIO = 0.179


def amv_path(data_dir: Path) -> Path:
    return data_dir / AMV_DIR / "part.parquet"


def load_amv_history(data_dir: Path) -> pl.DataFrame:
    """读取全部 0AMV 时序; 不存在返回空 DataFrame。"""
    p = amv_path(data_dir)
    if not p.exists():
        return pl.DataFrame()
    try:
        return pl.read_parquet(p)
    except Exception as e:  # noqa: BLE001
        logger.warning("load_amv_history failed: %s", e)
        return pl.DataFrame()


def upsert_amv_history(data_dir: Path, new_rows: pl.DataFrame) -> None:
    """按 date 覆盖(upsert): 重算的天覆盖旧行, 新天追加。

    schema 对齐: 旧数据可能缺少新列(如后续新增 amv_ma60), 通过 lit(None) 补齐,
    使 vertical_relaxed concat 不因列不一致报错。与 regime_builder 同模式。
    """
    if new_rows.is_empty() or "date" not in new_rows.columns:
        return
    p = amv_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_dates = set(new_rows["date"].to_list())
    old = load_amv_history(data_dir)
    if old.is_empty():
        combined = new_rows
    else:
        # anti-join: 排除重算天(新数据覆盖), 保留旧数据中未被重算的天
        kept = old.filter(~pl.col("date").is_in(list(new_dates)))
        # 按 new_rows 列顺序对齐: 旧数据缺列补 None, 多列截断
        target_cols = new_rows.columns
        keep_exprs = []
        for c in target_cols:
            if c in kept.columns:
                keep_exprs.append(pl.col(c))
            else:
                keep_exprs.append(pl.lit(None).alias(c))
        kept = kept.select(keep_exprs)
        new_rows = new_rows.select(target_cols)
        combined = pl.concat([kept, new_rows], how="vertical_relaxed")
    # unique(keep="last") 兜底: 理论上 anti-join 已去重, 但防御性保留
    combined = combined.sort("date").unique(subset=["date"], keep="last")
    combined.write_parquet(p)


def get_amv_coverage(data_dir: Path) -> dict:
    """返回 0AMV 时序的覆盖元信息。"""
    df = load_amv_history(data_dir)
    if df.is_empty():
        return {"rows": 0, "earliest_date": None, "latest_date": None}
    return {
        "rows": df.height,
        "earliest_date": str(df["date"].min()),
        "latest_date": str(df["date"].max()),
    }


# ───────────────────────── 日级聚合 ─────────────────────────


def _aggregate_amv(df: pl.DataFrame) -> pl.DataFrame:
    """对含 date/symbol/close/volume/float_shares 的 DataFrame 做日级聚合。

    返回: date, amv, active_count

    - volume > 0 过滤: 仅计入当日有成交的股票(活跃判定), 停牌/零成交不计入。
      这是 0AMV "Active" 的核心定义 — 与总市值(含停牌)区分。
    - amv = Σ(close × float_shares): 前复权价 × 流通股本, 单位为元。
    - active_count: 活跃股票数, 反映市场参与广度。
    """
    if df.is_empty():
        return pl.DataFrame(schema={"date": pl.Date, "amv": pl.Float64, "active_count": pl.UInt32})

    # 活跃判定: volume > 0 (有成交才计入, 停牌股排除)
    active = df.filter(pl.col("volume") > 0)
    if active.is_empty():
        return pl.DataFrame(schema={"date": pl.Date, "amv": pl.Float64, "active_count": pl.UInt32})

    result = (
        active
        .with_columns((pl.col("close") * pl.col("float_shares") * FREE_FLOAT_RATIO).alias("mv"))
        .group_by("date")
        .agg(
            pl.col("mv").sum().alias("amv"),
            pl.len().alias("active_count"),
        )
        .sort("date")
    )
    # active_count 转 UInt32 (group_by len() 返回 UInt32, 显式 cast 保证 schema 稳定)
    result = result.with_columns(pl.col("active_count").cast(pl.UInt32))
    return result


def _add_ma(df: pl.DataFrame) -> pl.DataFrame:
    """添加 amv_ma5 / amv_ma20 移动均线。

    min_periods=1: 前 4(或 19) 天数据不足窗口时, 用已有天数算均值而非填 None,
    使图表首段不出现断线。与 regime_builder 的 rolling_mean 口径一致。
    """
    if df.is_empty() or "amv" not in df.columns:
        return df
    df = df.sort("date")
    df = df.with_columns([
        pl.col("amv").rolling_mean(window_size=5, min_periods=1).alias("amv_ma5"),
        pl.col("amv").rolling_mean(window_size=20, min_periods=1).alias("amv_ma20"),
    ])
    return df


# ───────────────────────── 批量计算 ─────────────────────────


def run_amv_batch(repo, start: date, end: date) -> pl.DataFrame:
    """批量计算 [start, end] 区间的 0AMV 日级时序。

    双路径策略:
    1. 快路径 — 内存 enriched 缓存(含 float_shares, 覆盖近期 ~300 天):
       repo.get_enriched_range() 直接返回 join 好的 DataFrame, 秒级。
    2. 慢路径 — parquet scan + instruments join:
       超出缓存窗口(如全量重算早年数据)时, enriched parquet 不存 float_shares
       (写盘前 drop), 需从 instruments.parquet 快照 join 补齐。

    float_shares 口径: instruments 快照(当前股本, 无历史变更数据),
    与 regime/mainline 同口径 — 早年数据有归属漂移, 已知限制。
    """
    instruments = repo.get_instruments()
    float_cols = ["symbol", "float_shares"]
    instruments_float = instruments.select(float_cols) if not instruments.is_empty() else pl.DataFrame()

    # 快路径: 内存 enriched 缓存(已 join float_shares, 覆盖近期 ~300 天)
    try:
        df = repo.get_enriched_range(
            start.isoformat(),
            end.isoformat(),
            columns=["symbol", "date", "close", "volume", "float_shares"],
        )
        if df is not None and not df.is_empty() and "float_shares" in df.columns:
            logger.info("amv batch: from enriched cache, %d rows", df.height)
            return _add_ma(_aggregate_amv(df))
    except Exception as e:  # noqa: BLE001
        logger.debug("amv batch: cache miss (%s), falling back to parquet scan", e)

    # 慢路径: enriched parquet 不存 float_shares, 需 join instruments 快照
    enriched_dir = repo.store.data_dir / "kline_daily_enriched"
    if not enriched_dir.exists():
        logger.warning("amv batch: enriched dir not found")
        return pl.DataFrame()

    df = (
        pl.scan_parquet(enriched_dir / "**" / "*.parquet")
        .filter((pl.col("date") >= start) & (pl.col("date") <= end))
        .select(["symbol", "date", "close", "volume"])
        .collect()
    )
    if df.is_empty():
        return pl.DataFrame()

    # join float_shares from instruments
    if not instruments_float.is_empty():
        df = df.join(instruments_float, on="symbol", how="left")
        df = df.filter(pl.col("float_shares").is_not_null() & (pl.col("float_shares") > 0))
    else:
        logger.warning("amv batch: no instruments float_shares available")
        return pl.DataFrame()

    logger.info("amv batch: from parquet scan, %d rows", df.height)
    return _add_ma(_aggregate_amv(df))


# ───────────────────────── 缺口/stale 检测 ─────────────────────────


def _enriched_date_set(repo) -> set[date]:
    """扫描 kline_daily_enriched 分区目录, 返回所有已有日期集合。"""
    enriched_dir = repo.store.data_dir / "kline_daily_enriched"
    dates: set[date] = set()
    if not enriched_dir.exists():
        return dates
    for part in enriched_dir.glob("date=*/part.parquet"):
        try:
            ds = part.parent.name.replace("date=", "")
            dates.add(date.fromisoformat(ds))
        except ValueError:
            continue
    return dates


def _detect_stale_dates(data_dir: Path, repo) -> list[date]:
    """检测 amv 已有但需要重算的天(enriched 被覆写)。

    判据: enriched 分区 parquet 的 mtime > amv_history parquet 的 mtime,
    说明该天 enriched 数据在 amv 计算后被重写(如复权因子更新导致 enriched 重算),
    对应 amv 行已过期需重算。与 regime_builder._detect_stale_dates 同模式。
    """
    p = amv_path(data_dir)
    if not p.exists():
        return []
    amv_mtime = p.stat().st_mtime
    enriched_dir = repo.store.data_dir / "kline_daily_enriched"
    if not enriched_dir.exists():
        return []
    stale: list[date] = []
    existing = load_amv_history(data_dir)
    if existing.is_empty():
        return []
    existing_dates = set(existing["date"].to_list())
    for part in enriched_dir.glob("date=*/part.parquet"):
        try:
            ds = part.parent.name.replace("date=", "")
            d = date.fromisoformat(ds)
        except (ValueError, OSError):
            continue
        if d not in existing_dates:
            continue
        try:
            if part.stat().st_mtime > amv_mtime:
                stale.append(d)
        except OSError:
            continue
    return sorted(stale)


# ───────────────────────── 增量计算 ─────────────────────────


def compute_amv_incremental(repo, data_dir: Path, *, today: date | None = None) -> pl.DataFrame:
    """增量计算 0AMV(供 daily_pipeline / 启动补算调用)。

    双检测:
    1. 缺口(missing): enriched 有该天数据但 amv_history 没有 → 新增天, 首次计算。
    2. 过期(stale): amv 已有该天, 但 enriched 分区 mtime 比 amv 文件新 → 数据被覆写, 需重算。

    合并 missing + stale 去重后, 用 run_amv_batch 批量计算并 upsert。
    通常增量仅 1 天(当日新数据); stale 仅在复权因子更新等场景触发。
    """
    today = today or date.today()
    existing = load_amv_history(data_dir)

    enriched_dates = _enriched_date_set(repo)
    existing_dates = set(existing["date"].to_list()) if not existing.is_empty() else set()
    missing = sorted(d for d in enriched_dates if d not in existing_dates and d <= today)

    stale = _detect_stale_dates(data_dir, repo)

    to_compute = sorted(set(missing) | set(stale))
    if not to_compute:
        logger.debug("amv incremental: nothing to compute")
        return pl.DataFrame()

    logger.info("amv incremental: compute %d days (missing=%d, stale=%d)",
                len(to_compute), len(missing), len(stale))
    new_rows = run_amv_batch(repo, start=to_compute[0], end=to_compute[-1])
    if not new_rows.is_empty():
        upsert_amv_history(data_dir, new_rows)
    return new_rows


def recompute_amv_full(repo, data_dir: Path) -> pl.DataFrame:
    """全量重算 0AMV(从 enriched 最早日期到最新日期)。"""
    enriched_dates = _enriched_date_set(repo)
    if not enriched_dates:
        logger.warning("amv recompute: no enriched data")
        return pl.DataFrame()
    start = min(enriched_dates)
    end = max(enriched_dates)
    logger.info("amv recompute: full range %s ~ %s", start, end)
    new_rows = run_amv_batch(repo, start=start, end=end)
    if not new_rows.is_empty():
        upsert_amv_history(data_dir, new_rows)
    return new_rows
