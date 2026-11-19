"""东方财富历史 K 线兜底获取 — push2his.eastmoney.com。

仅当主工程 MarketDataProvider 不可用 (None 模式 / 接口失败) 时启用,
由 settings.czsc_eastmoney_fallback 控制开关。

接口: GET https://push2his.eastmoney.com/api/qt/stock/kline/get
参数:
    secid: {market}.{code}  (1=沪, 0=深, 1=京)
    fields1: f1,f2,f3,f4,f5,f6
    fields2: f51,f52,f53,f54,f55,f56,f57,f58
    klt: 101=日, 102=周, 103=月, 5=5分钟, 15=15分钟, 30=30分钟, 60=60分钟
    fqt: 0=不复权, 1=前复权 (与主工程 enriched 口径一致), 2=后复权
    beg/end: YYYYMMDD

风险:
    - 公开 API 无 SLA, 接口可能变更
    - 频率限制 (实测同 IP 高频会被临时封禁)
    - SSL: 默认 verify=False 以兼容企业代理自签名证书;
      生产环境通过 CZSC_SERVE_VERIFY_SSL=true 强制校验
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from typing import Any

import httpx
import polars as pl

logger = logging.getLogger(__name__)

# 东财 klt 代码映射 (Freq → klt)
_KLT_MAP: dict[str, int] = {
    "日线": 101,
    "周线": 102,
    "月线": 103,
    "5分钟": 5,
    "15分钟": 15,
    "30分钟": 30,
    "60分钟": 60,
}

# 东财 secid 市场前缀 (symbol 后缀 → market code)
_MARKET_PREFIX: dict[str, int] = {
    ".SH": 1,  # 沪市
    ".SZ": 0,  # 深市
    ".BJ": 1,  # 北交所 (东财归入沪市 secid=1)
}

# 6 位代码无后缀时的市场推断 (沪深规则; 8/4 开头为北交所, 归东财 secid=1)
def _infer_suffix(code: str) -> str:
    """6 位纯数字代码 → 交易所后缀推断。

    沪市: 6/9 开头 (600/601/603/605/688/900 B 股)
    深市: 0/2/3 开头 (000/001/002/003/300 创业板/200 B 股)
    北交所: 4/8 开头 (430/830 新三板)
    """
    if not code.isdigit() or len(code) != 6:
        raise EastmoneyFallbackError(
            "INVALID_SYMBOL",
            f"cannot infer suffix for non-6-digit code: {code}",
        )
    head = code[0]
    if head in ("6", "9"):
        return ".SH"
    if head in ("0", "2", "3"):
        return ".SZ"
    if head in ("4", "8"):
        return ".BJ"
    raise EastmoneyFallbackError(
        "INVALID_SYMBOL",
        f"cannot infer suffix for unknown code prefix {head}: {code}",
    )

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.5
_REQUEST_TIMEOUT = 10.0

# 主工程 normalizer 标准 schema
_SCHEMA = {
    "dt": pl.Datetime,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "vol": pl.Float64,
    "amount": pl.Float64,
}


class EastmoneyFallbackError(Exception):
    """东财兜底取数异常。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def _symbol_to_secid(symbol: str) -> str:
    """600519.SH → 1.600519; 000001.SZ → 0.000001; 600519 → 自动推断 .SH"""
    suffix = None
    for s in _MARKET_PREFIX:
        if symbol.endswith(s):
            suffix = s
            break
    if suffix is None:
        # 无后缀: 按代码前缀推断市场
        suffix = _infer_suffix(symbol)
        code = symbol
    else:
        code = symbol[: -len(suffix)]
    if not code.isdigit() or len(code) != 6:
        raise EastmoneyFallbackError(
            "INVALID_SYMBOL",
            f"invalid code part: {symbol}",
        )
    return f"{_MARKET_PREFIX[suffix]}.{code}"


def _parse_klines(raw: list[str]) -> pl.DataFrame:
    """解析东财 klines 字符串数组为标准 schema DataFrame。"""
    if not raw:
        return pl.DataFrame(schema=_SCHEMA)

    rows: list[dict[str, Any]] = []
    for line in raw:
        parts = line.split(",")
        if len(parts) < 7:
            logger.warning("eastmoney fallback: skip malformed kline: %s", line)
            continue
        try:
            rows.append({
                "dt": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "vol": float(parts[5]),
                "amount": float(parts[6]),
            })
        except (ValueError, IndexError) as exc:
            logger.warning("eastmoney fallback: parse kline failed: %s (%s)", line, exc)
            continue

    if not rows:
        return pl.DataFrame(schema=_SCHEMA)

    df = pl.DataFrame(rows)
    df = df.with_columns(pl.col("dt").str.to_datetime(strict=False))
    return df


def _resolve_verify() -> bool:
    """根据 CZSC_SERVE_VERIFY_SSL 环境变量决定是否校验 SSL。"""
    env = os.environ.get("CZSC_SERVE_VERIFY_SSL", "").lower()
    return env in ("1", "true", "yes")


def fetch_kline(
    symbol: str,
    freq: str,
    start: date,
    end: date,
) -> pl.DataFrame:
    """从东财公开 API 拉取 K 线, 返回标准 schema DataFrame。

    Args:
        symbol: 必须带后缀, 如 600519.SH
        freq: 中文频率名 (日线/周线/月线/5分钟/15分钟/30分钟/60分钟)
        start/end: 日期范围

    Returns:
        polars DataFrame, 列: dt/open/high/low/close/vol/amount

    Raises:
        EastmoneyFallbackError: 取数失败
    """
    if freq not in _KLT_MAP:
        raise EastmoneyFallbackError(
            "INVALID_FREQ",
            f"eastmoney unsupported freq: {freq}",
        )
    secid = _symbol_to_secid(symbol)
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "klt": _KLT_MAP[freq],
        "fqt": 1,  # 前复权
        "beg": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "lmt": 5000,
    }

    verify = _resolve_verify()
    if not verify:
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "eastmoney fallback SSL verification disabled "
            "(set CZSC_SERVE_VERIFY_SSL=true for production)"
        )

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=_REQUEST_TIMEOUT, verify=verify) as client:
                resp = client.get(
                    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
                    params=params,
                )
                resp.raise_for_status()
                # 响应体可能非 JSON (企业代理拦截页 / 空响应 / HTML 错误页),
                # resp.json() 会抛 json.JSONDecodeError (ValueError 子类),
                # 归入重试逻辑而非直接失败 — 代理偶发拦截重试可能恢复。
                try:
                    data = resp.json()
                except ValueError as exc:
                    # 记录响应体前 200 字符便于排查代理拦截内容
                    body_preview = resp.text[:200] if resp.text else "(empty)"
                    logger.warning(
                        "eastmoney fallback JSON parse failed (attempt %d/%d): %s; body preview: %s",
                        attempt + 1, _MAX_RETRIES, exc, body_preview,
                    )
                    last_exc = exc
                    if attempt < _MAX_RETRIES - 1:
                        time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                        continue
                    raise EastmoneyFallbackError(
                        "INVALID_RESPONSE",
                        f"eastmoney response not JSON for {symbol} (secid={secid}); "
                        f"body preview: {body_preview}",
                    )
                if data.get("data") is None:
                    raise EastmoneyFallbackError(
                        "SYMBOL_NOT_FOUND",
                        f"eastmoney returned null data for secid={secid}",
                    )
                klines = (data.get("data") or {}).get("klines")
                if not isinstance(klines, list):
                    raise EastmoneyFallbackError(
                        "INVALID_RESPONSE",
                        f"eastmoney response missing klines array for {symbol}",
                    )
                df = _parse_klines(klines)
                # 按日期过滤 (东财可能返回略超范围的边界数据)
                if freq in ("日线", "周线", "月线") and not df.is_empty():
                    df = df.filter(
                        (pl.col("dt").dt.date() >= start)
                        & (pl.col("dt").dt.date() <= end)
                    )
                return df
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            logger.warning(
                "eastmoney fallback HTTP %s (attempt %d/%d)",
                exc.response.status_code, attempt + 1, _MAX_RETRIES,
            )
        except httpx.RequestError as exc:
            last_exc = exc
            logger.warning(
                "eastmoney fallback request error: %s (attempt %d/%d)",
                exc, attempt + 1, _MAX_RETRIES,
            )
        except EastmoneyFallbackError:
            raise  # 业务错误不重试
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))

    raise EastmoneyFallbackError(
        "FETCH_FAILED",
        f"eastmoney fallback failed after {_MAX_RETRIES} retries: {last_exc}",
    )


def supports_freq(freq: str) -> bool:
    """是否支持该频率。"""
    return freq in _KLT_MAP
