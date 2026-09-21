"""通达信本地二进制文件解析器。

支持文件格式:
  - .day   日K线, 32字节/记录, 小端序
  - .lc1   1分钟线, 32字节/记录, 小端序
  - .lc5   5分钟线, 32字节/记录, 小端序
  - gbbq   股本变更权息, 32字节/记录(自动检测24字节), 小端序

所有解析均为纯 struct.unpack, 无第三方依赖。
返回 polars DataFrame, 字段对齐 data_providers/schemas.py 的 canonical schema。
"""
from __future__ import annotations

import struct
from datetime import date as date_type, datetime
from pathlib import Path

import polars as pl

# 记录长度常量
_DAY_REC_SIZE = 32
_LC_REC_SIZE = 32
_GBBQ_REC_SIZE_CANDIDATES = (32, 28)

# .day 记录格式: date(int32 YYYYMMDD) open(int32 ×100) high(int32 ×100)
#                low(int32 ×100) close(int32 ×100) amount(float32)
#                volume(int32 股) reserved(int32)
_DAY_FMT = "<iiiiifii"
_DAY_STRUCT = struct.Struct(_DAY_FMT)

# .lc1/.lc5 记录格式: date(uint16) time(uint16) open(float32) high(float32)
#                     low(float32) close(float32) amount(float32)
#                     volume(int32 股) reserved(int32)
# date 编码: (year-2004)×2048 + month×100 + day (方案 A, mootdx 主流)
# time 编码: HHMM (如 931 = 09:31)
_LC_FMT = "<HHfffffii"
_LC_STRUCT = struct.Struct(_LC_FMT)

# gbbq 记录格式 (32字节版): market(uint16) code(char[6]) date(uint32)
#   songzhuang(float32) fenhong(float32) peigu(float32)
#   peigujia(float32) reserved(float32)
_GBBQ_FMT_32 = "<H6sIfffff"
_GBBQ_STRUCT_32 = struct.Struct(_GBBQ_FMT_32)
# 28字节版: 无 reserved 字段 (market + code + date + 4个float)
_GBBQ_FMT_28 = "<H6sIffff"
_GBBQ_STRUCT_28 = struct.Struct(_GBBQ_FMT_28)


# ============================================================
# .day 文件解析
# ============================================================

def read_day_file(path: Path, symbol: str) -> pl.DataFrame:
    """读取 .day 文件 → polars DataFrame。

    返回列: symbol, date(Date), open, high, low, close, volume(手), amount(元)
    价格 ÷100 转浮点元, volume ÷100 股→手。
    """
    raw = path.read_bytes()
    n = len(raw) // _DAY_REC_SIZE
    records = []
    for i in range(n):
        off = i * _DAY_REC_SIZE
        try:
            date_int, o, h, l, c, amt, vol, _ = _DAY_STRUCT.unpack_from(raw, off)
        except struct.error:
            break
        # 跳过全零记录(文件尾部 padding)
        if date_int == 0:
            continue
        year = date_int // 10000
        month = (date_int // 100) % 100
        day = date_int % 100
        try:
            d = date_type(year, month, day)
        except Exception:
            continue
        records.append({
            "symbol": symbol,
            "date": d,
            "open": o / 100.0,
            "high": h / 100.0,
            "low": l / 100.0,
            "close": c / 100.0,
            "volume": vol / 100.0,   # 股 → 手
            "amount": float(amt),
        })
    if not records:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "date": pl.Date,
            "open": pl.Float64, "high": pl.Float64,
            "low": pl.Float64, "close": pl.Float64,
            "volume": pl.Float64, "amount": pl.Float64,
        })
    return pl.DataFrame(records)


# ============================================================
# .lc1 / .lc5 文件解析
# ============================================================

def _detect_lc_date_encoding(raw: bytes) -> str:
    """自动检测 .lc1/.lc5 的 date 字段(uint16)编码方案。

    方案 A (mootdx 主流): date = (year - 2004) × 2048 + month × 100 + day
    方案 B (部分新版):    date = YYYYMMDD ÷ 100 (如 20260105 → 20260.105, 不通用)
                        实际方案 B 用 uint16 无法存 YYYYMMDD, 故 B 为 直接存 year-2004 的 Julian day

    通过前 3 条记录尝试方案 A 解码, 年份落在 2010-2030 则采用, 否则回退 B。
    """
    n = min(3, len(raw) // _LC_REC_SIZE)
    for i in range(n):
        off = i * _LC_REC_SIZE
        try:
            date_uint16 = struct.unpack_from("<H", raw, off)[0]
        except struct.error:
            continue
        # 方案 A 解码
        if date_uint16 > 0:
            year = date_uint16 // 2048 + 2004
            if 2010 <= year <= 2030:
                return "A"
    return "B"


def _decode_lc_date(date_uint16: int) -> tuple[int, int, int]:
    """解码 date 字段(uint16) → (year, month, day)。

    返回 (0, 0, 0) 表示无效。
    """
    if date_uint16 <= 0:
        return (0, 0, 0)
    # 方案 A: (year - 2004) × 2048 + month × 100 + day
    year = date_uint16 // 2048 + 2004
    rem = date_uint16 % 2048
    month = rem // 100
    day = rem % 100
    if 1 <= month <= 12 and 1 <= day <= 31 and 2010 <= year <= 2030:
        return (year, month, day)
    # 方案 B: 部分版本使用 (year-2004) × 12 × 31 + (month-1) × 31 + (day-1)
    # 尝试反推
    if date_uint16 > 0:
        # 估算: 总天数编码
        approx_year = date_uint16 // (12 * 31) + 2004
        if 2010 <= approx_year <= 2030:
            rem2 = date_uint16 - (approx_year - 2004) * 12 * 31
            month_b = rem2 // 31 + 1
            day_b = rem2 % 31 + 1
            if 1 <= month_b <= 12 and 1 <= day_b <= 31:
                return (approx_year, month_b, day_b)
    return (0, 0, 0)


def _decode_lc_time(time_uint16: int) -> tuple[int, int]:
    """解码 time 字段(uint16) → (hour, minute)。

    time 编码为 HHMM (如 931 = 09:31, 1500 = 15:00)。
    返回 (0, 0) 表示无效。
    """
    if time_uint16 == 0:
        return (0, 0)
    hour = time_uint16 // 100
    minute = time_uint16 % 100
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return (hour, minute)
    return (0, 0)


def read_lc_file(path: Path, symbol: str, freq: str) -> pl.DataFrame:
    """读取 .lc1/.lc5 文件 → polars DataFrame。

    返回列: symbol, datetime(naive datetime), open, high, low, close, volume(手), amount(元), freq
    datetime 为北京墙钟 naive, volume ÷100 股→手。

    .lc1/.lc5 记录格式 (32 字节):
      date(uint16) time(uint16) open(float32) high(float32)
      low(float32) close(float32) amount(float32)
      volume(int32 股) reserved(int32)
    date 编码方案 A (mootdx 主流): (year-2004)×2048 + month×100 + day
    time 编码: HHMM (如 931 = 09:31, 1500 = 15:00)
    """
    raw = path.read_bytes()
    n = len(raw) // _LC_REC_SIZE
    if n == 0:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "datetime": pl.Datetime,
            "open": pl.Float64, "high": pl.Float64,
            "low": pl.Float64, "close": pl.Float64,
            "volume": pl.Float64, "amount": pl.Float64, "freq": pl.Utf8,
        })

    encoding = _detect_lc_date_encoding(raw)
    records = []

    for i in range(n):
        off = i * _LC_REC_SIZE
        try:
            date_uint16, time_uint16, o, h, l, c, amt, vol, _ = _LC_STRUCT.unpack_from(raw, off)
        except struct.error:
            break
        if date_uint16 == 0:
            continue

        year, month, day = _decode_lc_date(date_uint16)
        if year == 0:
            continue
        hour, minute = _decode_lc_time(time_uint16)

        try:
            dt = datetime(year, month, day, hour, minute)
        except ValueError:
            continue

        # 过滤无效日期
        if dt.year < 2010:
            continue

        records.append({
            "symbol": symbol,
            "datetime": dt,
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": vol / 100.0,   # 股 → 手
            "amount": float(amt),
            "freq": freq,
        })

    if not records:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "datetime": pl.Datetime,
            "open": pl.Float64, "high": pl.Float64,
            "low": pl.Float64, "close": pl.Float64,
            "volume": pl.Float64, "amount": pl.Float64, "freq": pl.Utf8,
        })
    return pl.DataFrame(records)


# ============================================================
# gbbq 文件解析
# ============================================================

# market 字段 → 交易所后缀
_MARKET_TO_EXCHANGE = {0: "SZ", 1: "SH", 2: "BJ"}


def _detect_gbbq_record_size(file_size: int) -> int:
    """自动检测 gbbq 记录长度: 32 vs 24 字节。"""
    for size in _GBBQ_REC_SIZE_CANDIDATES:
        if file_size % size == 0:
            return size
    return _GBBQ_REC_SIZE_CANDIDATES[0]  # 默认 32


def read_gbbq_file(path: Path) -> pl.DataFrame:
    """读取 gbbq 文件 → 除权除息事件 DataFrame。

    返回列: symbol, trade_date(Date), event_date(int YYYYMMDD),
            songzhuang, fenhong, peigu, peigujia
    symbol 从 market + code 推导, 格式如 600519.SH。
    """
    raw = path.read_bytes()
    file_size = len(raw)
    if file_size == 0:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "trade_date": pl.Date,
            "songzhuang": pl.Float64, "fenhong": pl.Float64,
            "peigu": pl.Float64, "peigujia": pl.Float64,
        })

    rec_size = _detect_gbbq_record_size(file_size)
    st = _GBBQ_STRUCT_32 if rec_size == 32 else _GBBQ_STRUCT_28
    n = file_size // rec_size

    records = []
    for i in range(n):
        off = i * rec_size
        try:
            if rec_size == 32:
                market, code_bytes, date_int, sz, fh, pg, pgj, _ = st.unpack_from(raw, off)
            else:
                market, code_bytes, date_int, sz, fh, pg, pgj = st.unpack_from(raw, off)
        except struct.error:
            break

        # 解码股票代码
        code = code_bytes.decode("ascii", errors="replace").rstrip("\x00").strip()
        if not code or len(code) != 6:
            continue

        exchange = _MARKET_TO_EXCHANGE.get(market)
        if not exchange:
            continue
        symbol = f"{code}.{exchange}"

        # 解码日期
        if date_int == 0:
            continue
        year = date_int // 10000
        month = (date_int // 100) % 100
        day = date_int % 100
        try:
            d = date_type(year, month, day)
        except Exception:
            continue

        records.append({
            "symbol": symbol,
            "trade_date": d,
            "songzhuang": float(sz),
            "fenhong": float(fh),
            "peigu": float(pg),
            "peigujia": float(pgj),
        })

    if not records:
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "trade_date": pl.Date,
            "songzhuang": pl.Float64, "fenhong": pl.Float64,
            "peigu": pl.Float64, "peigujia": pl.Float64,
        })
    return pl.DataFrame(records)


def compute_ex_factor(
    events: pl.DataFrame,
    daily_close: pl.DataFrame,
) -> pl.DataFrame:
    """从 gbbq 除权事件 + 日K前收盘 计算单事件比值 ex_factor。

    公式: ratio = (C - D + P × K) / (C × (1 + S + P))
      S = songzhuang (送转股/股)
      D = fenhong (每股分红/元)
      P = peigu (配股/股)
      K = peigujia (配股价/元)
      C = 除权日前一交易日 close (从 daily_close 读取)

    返回列: symbol, trade_date(Date), ex_factor(Float64)
    """
    if events.is_empty() or daily_close.is_empty():
        return pl.DataFrame(schema={
            "symbol": pl.Utf8, "trade_date": pl.Date, "ex_factor": pl.Float64,
        })

    # 为每个除权事件找前一交易日 close
    # daily_close: [symbol, date, close]
    # events: [symbol, trade_date, songzhuang, fenhong, peigu, peigujia]
    # join_asof 要求两侧按 asof 列单调递增, 且 by 列排序一致
    daily_sorted = (
        daily_close
        .select(["symbol", "date", "close"])
        .sort(["symbol", "date"])
    )
    events_sorted = events.sort(["symbol", "trade_date"])

    # join_asof backward: 每个事件取 < trade_date 的最近一条 close (排除除权日当天)
    # polars join_asof strategy=backward + allow_exact_matches=False 取严格 < 的最近一条
    result = events_sorted.join_asof(
        daily_sorted,
        left_on="trade_date",
        right_on="date",
        by="symbol",
        strategy="backward",
        allow_exact_matches=False,
    )

    # 计算单事件比值
    # ratio = (C - D + P × K) / (C × (1 + S + P))
    # 无前收盘(C=None)或分母为0时, ex_factor = None
    result = result.with_columns(
        pl.when(pl.col("close").is_not_null() & (pl.col("close") > 0))
        .then(
            (pl.col("close") - pl.col("fenhong") + pl.col("peigu") * pl.col("peigujia"))
            / (pl.col("close") * (1.0 + pl.col("songzhuang") + pl.col("peigu")))
        )
        .otherwise(None)
        .alias("ex_factor")
    )

    return result.select(["symbol", "trade_date", "ex_factor"]).drop_nulls(
        subset=["ex_factor"]
    )


# ============================================================
# 辅助函数: symbol ↔ 文件路径转换
# ============================================================

def symbol_to_file_path(vipdoc_dir: Path, symbol: str, ext: str) -> Path | None:
    """symbol (如 600519.SH) → vipdoc 目录下的文件路径。

    ext 决定子目录:
      .day  → lday/
      .lc1  → minline/
      .lc5  → fzline/
    """
    parts = symbol.split(".")
    if len(parts) != 2:
        return None
    code, exchange = parts
    ex_lower = exchange.lower()
    subdir_map = {".day": "lday", ".lc1": "minline", ".lc5": "fzline"}
    subdir = subdir_map.get(ext)
    if not subdir:
        return None
    return vipdoc_dir / ex_lower / subdir / f"{ex_lower}{code}{ext}"


def file_path_to_symbol(path: Path) -> str | None:
    """文件路径 (如 .../sh/lday/sh600519.day) → symbol (600519.SH)。"""
    name = path.stem  # sh600519
    if len(name) < 3:
        return None
    ex_prefix = name[:2].lower()  # sh
    code = name[2:]  # 600519
    exchange_map = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
    exchange = exchange_map.get(ex_prefix)
    if not exchange:
        return None
    return f"{code}.{exchange}"
