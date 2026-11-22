"""分析门面 — 公共 API 保持不变, 具体流程委托 application.service。

历史入口 `analyze_async` / `analyze_stream` / `_fetch_kline` / `_probe_czsc`
继续可用; 内部实现已拆分到 config / domain / adapters / application。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.config import settings

from .adapters.czsc_adapter import probe_czsc
from .application.service import get_default_service, set_default_service
from .config import (
    DEFAULT_BS_MACD_AREA_MODE,
    DEFAULT_BS_ONLY_VALID_ZS,
    DEFAULT_BS_USE_DIF,
    DEFAULT_BS_USE_MACD_AREA,
    DEFAULT_DIVERGENCE_LOGIC,
    DEFAULT_MAX_BI_NUM,
    DEFAULT_MIN_BI_LEN,
    DEFAULT_TREND_OVERLAP_MODE,
    MA_PERIOD_WHITELIST,
    MA_WARMUP_FACTOR,
    SUBLEVEL_30M_LOOKBACK_DAYS,
    WARMUP_DAYS,
    AnalyzeRequest,
)
from .errors import AnalyzerError, error_status

__all__ = [
    "DEFAULT_BS_MACD_AREA_MODE",
    "DEFAULT_BS_ONLY_VALID_ZS",
    "DEFAULT_BS_USE_DIF",
    "DEFAULT_BS_USE_MACD_AREA",
    "DEFAULT_DIVERGENCE_LOGIC",
    "DEFAULT_MAX_BI_NUM",
    "DEFAULT_MIN_BI_LEN",
    "DEFAULT_TREND_OVERLAP_MODE",
    "MA_PERIOD_WHITELIST",
    "MA_WARMUP_FACTOR",
    "SUBLEVEL_30M_LOOKBACK_DAYS",
    "WARMUP_DAYS",
    "AnalyzeRequest",
    "AnalyzerError",
    "_fetch_kline",
    "_probe_czsc",
    "analyze_async",
    "analyze_stream",
    "error_status",
    "get_default_service",
    "set_default_service",
]


def _probe_czsc() -> tuple[bool, str | None]:
    return probe_czsc()


def _fetch_kline(symbol: str, freq: str, start, end) -> tuple[Any, str]:
    """取数编排 (兼容旧入口): 主源优先, 东财兜底。"""
    result = get_default_service().fetch(symbol, freq, start, end)
    return result.frame, result.source


def _request_from_kwargs(kwargs: dict[str, Any]) -> AnalyzeRequest:
    """兼容旧版关键字调用方式 (symbol=..., freq=...)。"""
    try:
        symbol = kwargs.pop("symbol")
    except KeyError as exc:
        raise TypeError("symbol is required") from exc
    request = AnalyzeRequest.from_query(
        symbol=symbol,
        freq=kwargs.pop("freq", "日线"),
        start=kwargs.pop("start", None),
        end=kwargs.pop("end", None),
        max_bi_num=kwargs.pop("max_bi_num", DEFAULT_MAX_BI_NUM),
        min_bi_len=kwargs.pop("min_bi_len", DEFAULT_MIN_BI_LEN),
        features=kwargs.pop("features", None),
        symbol_name=kwargs.pop("symbol_name", None),
        ma_periods=kwargs.pop("ma_periods", None),
        bs_macd_area_mode=kwargs.pop("bs_macd_area_mode", DEFAULT_BS_MACD_AREA_MODE),
        bs_use_dif=kwargs.pop("bs_use_dif", DEFAULT_BS_USE_DIF),
        bs_use_dea=kwargs.pop("bs_use_dea", False),
        bs_use_macd_area=kwargs.pop("bs_use_macd_area", DEFAULT_BS_USE_MACD_AREA),
        bs_divergence_logic=kwargs.pop("bs_divergence_logic", DEFAULT_DIVERGENCE_LOGIC),
        bs_trend_overlap_mode=kwargs.pop("bs_trend_overlap_mode", DEFAULT_TREND_OVERLAP_MODE),
        bs_enable_interval_nest=kwargs.pop("bs_enable_interval_nest", False),
    )
    if kwargs:
        raise TypeError(f"unexpected arguments: {sorted(kwargs)}")
    return request


def _coerce_request(
    request: AnalyzeRequest | str | None,
    kwargs: dict[str, Any],
) -> AnalyzeRequest:
    if isinstance(request, str):
        kwargs.setdefault("symbol", request)
        request = None
    if request is None:
        return _request_from_kwargs(kwargs)
    if kwargs:
        raise TypeError("pass either AnalyzeRequest or keyword arguments, not both")
    return request


async def analyze_async(
    request: AnalyzeRequest | str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """异步分析入口 — 线程池隔离 CPU 密集运算, 带超时。"""
    request = _coerce_request(request, kwargs)
    has_czsc, _ = _probe_czsc()
    if not has_czsc:
        raise AnalyzerError(
            "CZSC_NOT_INSTALLED",
            "czsc library not installed; run: uv sync --extra czsc",
        )

    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, get_default_service().analyze, request),
            timeout=settings.czsc_analyze_timeout_s,
        )
    except TimeoutError as exc:
        raise AnalyzerError(
            "ANALYZE_TIMEOUT",
            f"czsc analyze timeout after {settings.czsc_analyze_timeout_s}s",
        ) from exc
    except AnalyzerError:
        raise
    except Exception as exc:
        raise AnalyzerError("INTERNAL_ERROR", f"czsc analyze failed: {exc}") from exc


def analyze_stream(
    request: AnalyzeRequest | str | None = None,
    **kwargs: Any,
):
    """流式分析异步生成器, 产出 SSE 事件 dict。"""
    return get_default_service().stream(_coerce_request(request, kwargs))
