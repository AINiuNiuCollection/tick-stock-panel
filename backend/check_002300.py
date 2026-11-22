import polars as pl
from pathlib import Path

# Read the raw kline data for 2025-12-04
parquet_dir = Path(r"D:\Code\githubDemo\tick-stock-panel\data\kline_daily\date=2025-12-04")
df = pl.read_parquet(parquet_dir / "*.parquet")

sym = "002300.SZ"
row = df.filter(pl.col("symbol") == sym)
if row.is_empty():
    print("无数据")
else:
    r = row.row(0)
    cols = df.columns
    print(f"=== {sym} 2025-12-04 原始OHLC ===")
    for c in ["open", "high", "low", "close"]:
        idx = cols.index(c)
        print(f"  {c}: {r[idx]}")
    
    o, h, l, c = [r[cols.index(x)] for x in ["open", "high", "low", "close"]]
    spread = max(o, h, l, c) - min(o, h, l, c)
    tolerance = max(abs(c) * 1e-4, 0.01)
    same_price = spread <= tolerance
    
    print(f"\n  OHLC价差: {spread:.6f}")
    print(f"  容差: {tolerance:.6f}")
    print(f"  same_price(封板): {same_price}")

# Also check 2025-12-03
parquet_dir_prev = Path(r"D:\Code\githubDemo\tick-stock-panel\data\kline_daily\date=2025-12-03")
if parquet_dir_prev.exists():
    df_prev = pl.read_parquet(parquet_dir_prev / "*.parquet")
    row_prev = df_prev.filter(pl.col("symbol") == sym)
    if not row_prev.is_empty():
        r_prev = row_prev.row(0)
        cols_prev = df_prev.columns
        print(f"\n=== {sym} 2025-12-03 原始OHLC ===")
        for c in ["open", "high", "low", "close"]:
            idx = cols_prev.index(c)
            print(f"  {c}: {r_prev[idx]}")
        o_prev, h_prev, l_prev, c_prev = [r_prev[cols_prev.index(x)] for x in ["open", "high", "low", "close"]]
        spread_prev = max(o_prev, h_prev, l_prev, c_prev) - min(o_prev, h_prev, l_prev, c_prev)
        tolerance_prev = max(abs(c_prev) * 1e-4, 0.01)
        same_price_prev = spread_prev <= tolerance_prev
        print(f"\n  OHLC价差: {spread_prev:.6f}")
        print(f"  容差: {tolerance_prev:.6f}")
        print(f"  same_price(封板): {same_price_prev}")