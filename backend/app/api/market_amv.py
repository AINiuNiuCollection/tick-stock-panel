"""0AMV (活跃市值) API — 时序查询 + 手动重算。

装配逻辑在 app.services.market_amv(纯函数), API 层薄壳 + TTL 缓存。
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

import polars as pl
from fastapi import APIRouter, Query, Request

from app.services import market_amv

router = APIRouter(prefix="/api/market-amv", tags=["market-amv"])

_CACHE_TTL = 5.0
_cache: dict[str, Any] | None = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()


def invalidate_amv_cache() -> None:
    """清空 0AMV 查询缓存。批算/重算后调用。"""
    global _cache, _cache_ts
    with _cache_lock:
        _cache = None
        _cache_ts = 0.0


def _data_dir(request: Request) -> Any:
    return request.app.state.repo.store.data_dir


def _df_to_records(df) -> list[dict]:
    """polars DataFrame → JSON 安全的 list[dict](date 转 ISO 字符串)。"""
    if df is None or df.is_empty():
        return []
    records = []
    for r in df.to_dicts():
        if "date" in r and r["date"] is not None:
            r["date"] = str(r["date"])
        records.append(r)
    return records


@router.get("/history")
def amv_history(
    request: Request,
    start: date | None = Query(None),
    end: date | None = Query(None),
    limit: int = Query(250, ge=1, le=5000),
):
    """0AMV 历史时序(含 amv/active_count/amv_ma5/amv_ma20)。默认最近 N 天。

    - 不传 start/end: 返回最近 limit 天(按日期降序截取后再升序返回)。
    - 传 start/end: 返回完整日期范围, limit 不截断(与 regime_history 同口径)。
    """
    global _cache, _cache_ts
    cache_key = f"hist|{start}|{end}|{limit}"
    with _cache_lock:
        if (
            _cache is not None
            and _cache.get("key") == cache_key
            and (time.time() - _cache_ts) < _CACHE_TTL
        ):
            return _cache["data"]

    df = market_amv.load_amv_history(_data_dir(request))
    if df.is_empty():
        result: dict = {"rows": [], "total": 0}
    else:
        if start:
            df = df.filter(pl.col("date") >= start)
        if end:
            df = df.filter(pl.col("date") <= end)
        # limit 仅在"最近 N 天"模式(未传 start/end)生效;
        # 日期范围模式(传了 start/end, 如"全部")应返回完整范围, 不截断。
        if start is None and end is None:
            df = df.sort("date", descending=True).head(limit)
        df = df.sort("date")
        rows = _df_to_records(df)
        result = {"rows": rows, "total": len(rows)}

    with _cache_lock:
        _cache = {"key": cache_key, "data": result}
        _cache_ts = time.time()
    return result


@router.get("/coverage")
def amv_coverage(request: Request):
    """0AMV 数据覆盖元信息。"""
    return market_amv.get_amv_coverage(_data_dir(request))


@router.post("/recompute")
def amv_recompute(request: Request, start: date | None = None, end: date | None = None):
    """手动触发重算(全量或指定区间)。管理员操作。

    - 不传 start: 强制全量重算(enriched 最早日 ~ 最新日), 覆盖所有已有行。
      与 daily_pipeline 的增量补差(compute_amv_incremental)不同 — 此接口面向
      人工「我要重新算一遍」的预期, 必须真正重算而非增量补缺口。
    - 传 start: 仅重算 [start, end] 区间。
    """
    # 全量走慢路径(parquet scan + instruments join), 大区间耗时较长
    repo = request.app.state.repo
    data_dir = _data_dir(request)
    if start is None:
        new_rows = market_amv.recompute_amv_full(repo, data_dir)
    else:
        end = end or date.today()
        new_rows = market_amv.run_amv_batch(repo, start=start, end=end)
        if not new_rows.is_empty():
            market_amv.upsert_amv_history(data_dir, new_rows)

    invalidate_amv_cache()
    return {
        "ok": True,
        "computed": new_rows.height if not new_rows.is_empty() else 0,
    }
