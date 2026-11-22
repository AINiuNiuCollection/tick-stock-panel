import polars as pl
from pathlib import Path

parquet = Path(r"D:\Code\githubDemo\tick-stock-panel\backend\data\cache\market_data\all_stocks_daily.parquet")
df = pl.read_parquet(parquet)

sym = "603696.SH"
date = "2025-12-04"

row = df.filter((pl.col("symbol") == sym) & (pl.col("date") == date))
if row.is_empty():
    print("无数据")
else:
    r = row.row(0)
    cols = df.columns
    print(f"=== {sym} {date} OHLC ===")
    for c in ["open", "high", "low", "close"]:
        idx = cols.index(c)
        print(f"  {c}: {r[idx]:.6f}")
    
    o, h, l, c = [r[cols.index(x)] for x in ["open", "high", "low", "close"]]
    spread = max(o, h, l, c) - min(o, h, l, c)
    tolerance = max(abs(c) * 1e-4, 0.01)
    same_price = spread <= tolerance
    
    print(f"\n  涨停价(理论): {r[cols.index('close')]:.6f}")
    print(f"  OHLC价差: {spread:.6f}")
    print(f"  容差: {tolerance:.6f}")
    print(f"  same_price(封板): {same_price}")
    print(f"  limit_up_locked: {r[cols.index('limit_up_locked')]}")
    
    # 检查前一日收盘价
    prev = df.filter((pl.col("symbol") == sym) & (pl.col("date") < date)).sort("date").tail(1)
    if not prev.is_empty():
        prev_close = prev.row(0)[cols.index("close")]
        limit_up_price = prev_close * 1.10
        print(f"\n  前日收盘: {prev_close:.6f}")
        print(f"  涨停价(前日×1.10): {limit_up_price:.6f}")
        print(f"  当日收盘: {c:.6f}")
        print(f"  收盘 >= 涨停价? {c >= limit_up_price - 0.005}")
