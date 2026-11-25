"""标的维表同步服务。

盘前 9:10 调用 tf.exchanges.get_instruments("SH"/"SZ"/"BJ", type="stock")
获取全量标的元数据，flatten ext 字段，写入 instruments.parquet。

Starter+ 盘后可用 quotes.get(universes) 顺便补充 name。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.services.fs_utils import atomic_write_parquet
from app.tickflow.client import get_client

logger = logging.getLogger(__name__)

_EXCHANGES = ["SH", "SZ", "BJ"]


def _flatten_instruments(items: list[dict]) -> list[dict]:
    """把 SDK 返回的 Instrument 列表 flatten 成扁平行。"""
    rows = []
    for item in items:
        row = {
            "symbol": item.get("symbol"),
            "name": item.get("name"),
            "code": item.get("code"),
            "exchange": item.get("exchange"),
            "region": item.get("region"),
            "type": item.get("type"),
        }
        ext = item.get("ext") or {}
        row["listing_date"] = ext.get("listing_date")
        row["total_shares"] = ext.get("total_shares")
        row["float_shares"] = ext.get("float_shares")
        row["tick_size"] = ext.get("tick_size")
        row["limit_up"] = ext.get("limit_up")
        row["limit_down"] = ext.get("limit_down")
        rows.append(row)
    return rows


def _fetch_instruments_via_provider() -> list[dict] | None:
    """若当前日K数据源不是 tickflow 且该 provider 提供 get_instruments, 用它拉标的维表。

    返回 flatten 行列表; 未命中(仍应走 tickflow)时返回 None。
    标的维表跟随日K数据源(二者天然耦合, 无独立偏好项)。
    """
    from app.services import preferences

    provider_name = preferences.get_daily_data_provider()
    if provider_name == "tickflow":
        return None
    from app.data_providers import custom as custom_sources

    if not custom_sources.is_custom_provider(provider_name):
        return None
    provider = custom_sources.get_provider(provider_name)
    if not hasattr(provider, "get_instruments"):
        return None
    try:
        items = provider.get_instruments("stock") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("provider %s get_instruments 失败: %s", provider_name, e)
        return None
    rows = _flatten_instruments(items)
    logger.info("instruments via %s: %d stocks", provider_name, len(rows))
    return rows


def sync_instruments(data_dir: Path) -> int:
    """全量同步标的维表 → data/instruments/instruments.parquet。

    返回写入的行数; 0 = 本次未写入 (拉取全失败或触发防缩水守卫)。

    防缩水守卫 (2026-11-24): 上游 TickFlow 单交易所 503 时, 旧逻辑会拿
    部分成功 (仅沪市 ~2400 行) 的残缺快照整体覆盖全量 (~5900 行), 导致
    深市 float_shares 丢失 → enriched 深市换手率全 null → 换手率基础
    过滤静默排除整市 (策略零命中排查实测)。改为:
      - tickflow 路径: 逐交易所合并 — 拉取成功的交易所覆盖更新, 失败的
        交易所保留旧快照行 (保留其原 as_of, 数据陈旧但优于缺失);
      - provider 整体路径: 新行数 < 现存快照 80% 且现存非空时拒绝覆盖。
    """
    out = data_dir / "instruments" / "instruments.parquet"
    existing: pl.DataFrame | None = None
    if out.exists():
        try:
            existing = pl.read_parquet(out)
        except Exception as e:  # noqa: BLE001
            logger.warning("instruments existing snapshot read failed: %s", e)

    provider_rows = _fetch_instruments_via_provider()
    if provider_rows is not None:
        # provider 路径: 整体覆盖 + 缩水守卫
        if (
            existing is not None
            and not existing.is_empty()
            and provider_rows
            and len(provider_rows) < existing.height * 0.8
        ):
            logger.warning(
                "instruments 防缩水守卫: provider 返回 %d 行 < 现存快照 %d 行的 80%%, 保留旧快照",
                len(provider_rows), existing.height,
            )
            return 0
        all_rows: list[dict] = provider_rows
    else:
        # 未命中非 tickflow provider → 走 tickflow 直连, 逐交易所合并
        tf = get_client()
        new_rows: list[dict] = []
        failed: list[str] = []
        for ex in _EXCHANGES:
            try:
                items = tf.exchanges.get_instruments(ex, instrument_type="stock")
                if items:
                    new_rows.extend(_flatten_instruments(items))
                    logger.info("instruments %s: %d stocks", ex, len(items))
                else:
                    failed.append(ex)
            except Exception as e:
                failed.append(ex)
                logger.warning("get_instruments(%s) failed: %s", ex, e)
        # 三所全失败 → 维持"未写入"语义, 不动现存快照
        if not new_rows:
            return 0
        # 失败交易所保留旧快照行 (as_of 原样, 陈旧优于缺失)
        if failed and existing is not None and not existing.is_empty():
            keep = existing.filter(
                pl.any_horizontal([pl.col("symbol").str.ends_with(f".{ex}") for ex in failed])
            )
            if not keep.is_empty():
                new_rows.extend(keep.to_dicts())
                logger.warning(
                    "instruments %s 拉取失败, 旧快照保留 %d 行 (as_of 不变)",
                    ",".join(failed), keep.height,
                )
        all_rows = new_rows

    if not all_rows:
        return 0

    df = pl.DataFrame(all_rows)
    # 本次新拉取的行无 as_of (置今天); 从旧快照保留的行携带原 as_of
    if "as_of" not in df.columns:
        df = df.with_columns(pl.lit(date.today()).alias("as_of"))
    else:
        df = df.with_columns(
            pl.col("as_of").fill_null(pl.lit(date.today())).alias("as_of")
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_parquet(df, out)

    logger.info("instruments synced: %d rows → %s", df.height, out)
    return df.height


def enrich_names_from_quotes(
    data_dir: Path,
    quotes_data: list[dict],
) -> int:
    """从 quotes 响应中提取 name，更新 instruments 维表（兜底补充）。

    盘后 quotes.get(universes) 返回的数据中包含 ext.name，
    用来补充 instruments 中可能缺失的 name。
    """
    if not quotes_data:
        return 0

    # 构建 symbol → name 映射
    name_map: dict[str, str] = {}
    for q in quotes_data:
        symbol = q.get("symbol", "")
        ext = q.get("ext") or {}
        name = ext.get("name") or q.get("name", "")
        if symbol and name:
            name_map[symbol] = name

    if not name_map:
        return 0

    inst_path = data_dir / "instruments" / "instruments.parquet"
    if not inst_path.exists():
        return 0

    df = pl.read_parquet(inst_path)

    # 只更新空 name 的行
    updates = pl.DataFrame({
        "symbol": list(name_map.keys()),
        "_new_name": list(name_map.values()),
    })
    df = df.join(updates, on="symbol", how="left")
    df = df.with_columns(
        pl.when(pl.col("name").is_null() | (pl.col("name") == ""))
        .then(pl.col("_new_name"))
        .otherwise(pl.col("name"))
        .alias("name"),
    ).drop("_new_name")

    atomic_write_parquet(df, inst_path)
    logger.info("instruments name enriched from quotes: %d names", len(name_map))
    return len(name_map)
