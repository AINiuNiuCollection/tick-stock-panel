"""czsc 路由层 — 注册 /api/czsc/* 端点。

设计:
    - 缺 czsc 库时返回 503 + 安装提示 (不抛 500, 不影响主工程)
    - 契约版本头 X-Czsc-Api-Version: 1
    - 流式分析走 SSE (text/event-stream)
    - 数据刷新走主工程数据源 (主源优先, 东财兜底)
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.config import settings

from .analyzer import (
    AnalyzerError,
    _probe_czsc,
    analyze_async,
    analyze_stream,
    DEFAULT_MAX_BI_NUM,
    DEFAULT_MIN_BI_LEN,
)
from .schemas import (
    AnalyzeResult,
    CapabilitiesResult,
    ErrorResponse,
    HealthResult,
    RefreshRequest,
    RefreshResult,
)

logger = logging.getLogger(__name__)

API_VERSION = 1


def _build_error_response(code: str, message: str, hint: str | None = None, status: int = 503) -> JSONResponse:
    """统一错误响应。"""
    error_obj: dict[str, str] = {"code": code, "message": message}
    if hint:
        error_obj["hint"] = hint
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": error_obj},
        headers={"X-Czsc-Api-Version": str(API_VERSION)},
    )


def _build_success_response(data: dict, status: int = 200) -> JSONResponse:
    """统一成功响应, 带契约版本头。"""
    return JSONResponse(
        status_code=status,
        content=data,
        headers={"X-Czsc-Api-Version": str(API_VERSION)},
    )


def build_router() -> APIRouter:
    """构建 czsc 路由。在 setup() 中调用, 由 loader 自动发现。"""
    if not settings.czsc_enabled:
        # 配置层关闭: 仍注册路由但所有端点返回 503
        router = APIRouter(prefix="/api/czsc", tags=["czsc"])

        @router.get("/health")
        async def health_disabled() -> JSONResponse:
            return _build_error_response(
                "CZSC_DISABLED", "czsc extension disabled by config (czsc_enabled=false)",
            )

        @router.get("/capabilities")
        async def capabilities_disabled() -> JSONResponse:
            return _build_success_response(CapabilitiesResult(
                available=False, install_hint="set czsc_enabled=true to enable",
            ).model_dump())

        @router.get("/analyze")
        async def analyze_disabled() -> JSONResponse:
            return _build_error_response("CZSC_DISABLED", "czsc extension disabled")

        @router.get("/analyze/stream")
        async def analyze_stream_disabled() -> StreamingResponse:
            async def _err() -> AsyncIterator[bytes]:
                err = json.dumps({"code": "CZSC_DISABLED", "message": "czsc extension disabled"})
                yield f"event: error\ndata: {err}\n\n".encode("utf-8")
            return StreamingResponse(_err(), media_type="text/event-stream")

        @router.post("/data/refresh")
        async def refresh_disabled() -> JSONResponse:
            return _build_error_response("CZSC_DISABLED", "czsc extension disabled")

        return router

    # ===== 正常路径: czsc_enabled=true =====
    router = APIRouter(prefix="/api/czsc", tags=["czsc"])

    @router.get("/health")
    async def health() -> JSONResponse:
        """健康检查 + czsc 可用性 + 数据源清单。"""
        has_czsc, version = _probe_czsc()
        data_sources = ["primary"]
        if settings.czsc_eastmoney_fallback:
            data_sources.append("eastmoney")
        result = HealthResult(
            ok=has_czsc,
            version=version,
            czsc_native_available=has_czsc,
            data_sources=data_sources,
            eastmoney_fallback=settings.czsc_eastmoney_fallback,
        )
        if not has_czsc:
            return _build_success_response(result.model_dump(), status=503)
        return _build_success_response(result.model_dump())

    @router.get("/capabilities")
    async def capabilities() -> JSONResponse:
        """能力检测 — 前端据此渲染入口 (不硬编码能力清单)。"""
        has_czsc, version = _probe_czsc()
        result = CapabilitiesResult(
            available=has_czsc,
            version=version,
            native_ready=has_czsc,
            eastmoney_fallback=settings.czsc_eastmoney_fallback,
            install_hint=None if has_czsc else "run: uv sync --extra czsc",
        )
        return _build_success_response(result.model_dump())

    @router.get("/analyze")
    async def analyze(
        symbol: str = Query(..., description="标的代码, 如 600519.SH"),
        freq: str = Query("日线"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        max_bi_num: int = Query(DEFAULT_MAX_BI_NUM, ge=10, le=500),
        min_bi_len: int = Query(DEFAULT_MIN_BI_LEN, ge=3, le=30),
        features: str = Query("fx,bi,zs,signals"),
        force_refresh: bool = Query(False),
    ) -> JSONResponse:
        """同步分析 (适合日K等小数据量)。"""
        _ = force_refresh  # 首版忽略, 每次重新取数; 二期可接缓存层
        feature_list = [f.strip() for f in features.split(",") if f.strip()]
        try:
            result = await analyze_async(
                symbol=symbol, freq=freq,
                start=start_date, end=end_date,
                max_bi_num=max_bi_num, min_bi_len=min_bi_len,
                features=feature_list,
            )
            return _build_success_response({**result, "ok": True})
        except AnalyzerError as exc:
            status = 503 if exc.code == "CZSC_NOT_INSTALLED" else 500
            hint = "run: uv sync --extra czsc" if exc.code == "CZSC_NOT_INSTALLED" else None
            return _build_error_response(exc.code, exc.message, hint, status=status)

    @router.get("/analyze/stream")
    async def analyze_stream_endpoint(
        symbol: str = Query(...),
        freq: str = Query("日线"),
        start_date: date | None = Query(None),
        end_date: date | None = Query(None),
        max_bi_num: int = Query(DEFAULT_MAX_BI_NUM, ge=10, le=500),
        min_bi_len: int = Query(DEFAULT_MIN_BI_LEN, ge=3, le=30),
        features: str = Query("fx,bi,zs,signals"),
        force_refresh: bool = Query(False),
    ) -> StreamingResponse:
        """SSE 流式分析 (适合分钟K等大数据量)。"""
        _ = force_refresh
        feature_list = [f.strip() for f in features.split(",") if f.strip()]

        async def stream_gen() -> AsyncIterator[bytes]:
            try:
                async for event in analyze_stream(
                    symbol=symbol, freq=freq,
                    start=start_date, end=end_date,
                    max_bi_num=max_bi_num, min_bi_len=min_bi_len,
                    features=feature_list,
                ):
                    event_type = event["event"]
                    payload = json.dumps(event["data"], ensure_ascii=False, default=str)
                    yield f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.exception("czsc SSE stream unexpected error")
                err = json.dumps({"code": "INTERNAL_ERROR", "message": str(exc)})
                yield f"event: error\ndata: {err}\n\n".encode("utf-8")

        return StreamingResponse(
            stream_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Czsc-Api-Version": str(API_VERSION),
            },
        )

    @router.post("/data/refresh")
    async def refresh_data(body: RefreshRequest) -> JSONResponse:
        """数据刷新 — 取数并丢弃 (本扩展无独立缓存, 仅触发主工程数据源刷新)。

        首版: 验证 symbol/freq 能取到数据, 返回最新日期; 不写本地缓存。
        二期可接入主工程 parquet 缓存层。
        """
        has_czsc, _ = _probe_czsc()
        if not has_czsc:
            return _build_error_response(
                "CZSC_NOT_INSTALLED",
                "czsc library not installed",
                hint="run: uv sync --extra czsc",
            )

        from .analyzer import _fetch_kline
        end = date.today()
        from datetime import timedelta
        start = end - timedelta(days=365)
        try:
            df, source = _fetch_kline(body.symbol, body.freq, start, end)
        except Exception as exc:  # noqa: BLE001
            return _build_error_response("FETCH_FAILED", str(exc), status=500)

        if df.is_empty():
            return _build_error_response("NO_DATA", f"no data for {body.symbol} {body.freq}")

        latest = df["dt"].max()
        latest_date = latest.date().isoformat() if latest is not None else None
        result = RefreshResult(
            symbol=body.symbol, freq=body.freq,
            cached_bars=df.height, latest_date=latest_date, source=source,
        )
        return _build_success_response(result.model_dump())

    return router
