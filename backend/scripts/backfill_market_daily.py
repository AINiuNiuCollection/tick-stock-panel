"""大盘研究 P0 数据底座: 上证指数与典型 ETF 日K 历史深度回填 (baostock → 本地分区)。

背景:
    kline_index_daily / kline_etf_daily 由 TickFlow 每日增量同步, 历史仅约
    一年 (250 行/标的)。大盘研究页需要月线缠论 (1990→今) 与长样本统计规律,
    用 baostock 一次性深回填。

口径 (2026-11-28 已探针验证):
    - 指数/ETF 均取 baostock **不复权** (adjustflag="3"), 与 TickFlow 写入的
      raw 分区口径一致 —— 接缝处价格/量/额对账到小数点后精度吻合
      (000001.SH 2026-11-26: 3476.882 / 4.54e8手 / 6.13e11元 双源一致)。
    - baostock volume 单位股 → 工程契约手 (provider._query_kline 已 ÷100)。
    - 只回填早于现有分区最早日期的历史段, 不触碰现有行 (幂等重跑安全;
      merge-upsert 仅在意外重叠时兜底)。

用法:
    cd backend && ./.venv/Scripts/python.exe scripts/backfill_market_daily.py
    (BAOSTOCK_PROXY 环境变量沿用主工程代理约定, 见 app/plugins/baostock/provider.py)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import polars as pl

from app.plugins.baostock.provider import BaostockProvider, _session_acquire, _session_release
from app.tickflow.repository import DataStore, KlineRepository

INDEX_SYMBOLS = ["000001.SH"]
ETF_SYMBOLS = [
    "510300.SH",  # 沪深300ETF (2012-05-28 上市)
    "510500.SH",  # 中证500ETF
    "588000.SH",  # 科创50ETF (2020-11-16)
    "512100.SH",  # 中证1000ETF (2016-11-04)
    "159915.SZ",  # 创业板ETF (2011-12-09)
]

CANONICAL_COLS = ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]


def _bs_code(symbol: str) -> str:
    code, suffix = symbol.split(".")
    return f"{suffix.lower()}.{code}"


def _min_existing_date(base: Path, symbol: str) -> date | None:
    """现有分区中该标的最早的日期 (分区目录名即日期)。"""
    if not base.exists():
        return None
    for d in sorted(p.name for p in base.iterdir() if p.name.startswith("date=")):
        ds = d.removeprefix("date=")
        f = base / d / "part.parquet"
        if not f.exists():
            continue
        try:
            df = pl.read_parquet(f)
        except Exception:
            continue
        if "symbol" in df.columns and symbol in df["symbol"].to_list():
            return date.fromisoformat(ds)
    return None


def backfill(prov: BaostockProvider, repo: KlineRepository, data_dir: Path) -> None:
    tasks: list[tuple[str, str, Path, object]] = [
        # (symbol, baostock_code, 分区目录, repo 写入方法)
        *[(s, _bs_code(s), data_dir / "kline_index_daily", repo.append_index_daily) for s in INDEX_SYMBOLS],
        *[(s, _bs_code(s), data_dir / "kline_etf_daily", repo.append_etf_daily) for s in ETF_SYMBOLS],
    ]
    for symbol, code, base, append in tasks:
        cutoff = _min_existing_date(base, symbol)
        print(f"[{symbol}] 现有最早日期: {cutoff}")
        df = prov._query_kline(code, "1990-12-19", "2026-11-27", "d", "3")
        if df is None or df.is_empty():
            print(f"[{symbol}] baostock 返回空, 跳过")
            continue
        df = df.with_columns(pl.lit(symbol).alias("symbol"))
        if cutoff is not None:
            before = df.height
            df = df.filter(pl.col("date") < cutoff)
            print(f"[{symbol}] baostock {before} 行 → 回填区间过滤后 {df.height} 行 (< {cutoff})")
        if df.is_empty():
            print(f"[{symbol}] 无需回填")
            continue
        out = df.select(CANONICAL_COLS).sort(["symbol", "date"])
        append(out)
        print(
            f"[{symbol}] 已写入 {out.height} 行: "
            f"{out['date'].min()} → {out['date'].max()}"
        )


def verify(repo: KlineRepository) -> None:
    """回填后对账: 每标的行数与起止日期。"""
    print("\n== 回填后对账 ==")
    con = repo.store.duckdb if hasattr(repo.store, "duckdb") else None
    import duckdb

    con = duckdb.connect()
    d = repo.store.data_dir.as_posix()
    for table, symbols in [("kline_index_daily", INDEX_SYMBOLS), ("kline_etf_daily", ETF_SYMBOLS)]:
        rows = con.execute(
            f"""SELECT symbol, count(*) n, min(date) lo, max(date) hi
                FROM read_parquet('{d}/{table}/**/*.parquet', union_by_name=true)
                WHERE symbol IN ({','.join(repr(s) for s in symbols)})
                GROUP BY symbol ORDER BY symbol"""
        ).fetchall()
        for sym, n, lo, hi in rows:
            print(f"{table} {sym}: {n} 行, {lo} → {hi}")


def main() -> None:
    store = DataStore()
    repo = KlineRepository(store)
    ok, msg = _session_acquire()
    if not ok:
        print(f"baostock login 失败: {msg}")
        sys.exit(1)
    try:
        prov = BaostockProvider()
        backfill(prov, repo, store.data_dir)
        repo.refresh_index_views()
    finally:
        _session_release()
    verify(repo)
    print("\n完成。")


if __name__ == "__main__":
    main()
