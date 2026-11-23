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
from collections.abc import AsyncIterator
from datetime import date, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.config import settings

from .analyzer import (
    DEFAULT_MAX_BI_NUM,
    DEFAULT_MIN_BI_LEN,
    AnalyzerError,
    _fetch_kline,
    _probe_czsc,
    analyze_async,
    analyze_stream,
    error_status,
    get_default_service,
)
from .config import (
    DEFAULT_BS_OUTPUT_MODE,
    DEFAULT_CENTER_UNIT,
    DEFAULT_SCAN_FREQ,
    DEFAULT_SCAN_LIMIT,
    DEFAULT_SCAN_LOOKBACK_DAYS,
    DEFAULT_SCAN_MAX_SIGNAL_AGE,
    DEFAULT_SCAN_MAX_WORKERS,
    DEFAULT_SCAN_POOL,
    AnalyzeRequest,
    ScanRequest,
)
from .schemas import (
    CapabilitiesResult,
    HealthResult,
    RefreshRequest,
    RefreshResult,
)

logger = logging.getLogger(__name__)

API_VERSION = 1


def _build_error_response(
    code: str, message: str, hint: str | None = None, status: int = 503
) -> JSONResponse:
    """统一错误响应。"""
    error_obj: dict[str, str] = {"code": code, "message": message}
    if hint:
        error_obj["hint"] = hint
    return JSONResponse(
        status_code=status,
        content={"ok": False, "error": error_obj},
        headers={"X-Czsc-Api-Version": str(API_VERSION)},
    )


def _parse_ma_periods(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        return [int(p.strip()) for p in value.split(",") if p.strip()]
    except ValueError:
        return None


def _build_success_response(data: dict, status: int = 200) -> Response:
    """统一成功响应, 带契约版本头。"""
    body = json.dumps(data, default=str, ensure_ascii=False).encode()
    return Response(
        content=body,
        status_code=status,
        headers={"X-Czsc-Api-Version": str(API_VERSION)},
        media_type="application/json",
    )


def build_router() -> APIRouter:
    """构建 czsc 路由。在 setup() 中调用, 由 loader 自动发现。"""
    if not settings.czsc_enabled:
        router = APIRouter(prefix="/api/czsc", tags=["czsc"])

        @router.get("/health")
        async def health_disabled() -> JSONResponse:
            return _build_error_response(
                "CZSC_DISABLED",
                "czsc extension disabled by config (czsc_enabled=false)",
            )

        @router.get("/capabilities")
        async def capabilities_disabled() -> JSONResponse:
            return _build_success_response(
                CapabilitiesResult(
                    available=False, install_hint="set czsc_enabled=true to enable"
                ).model_dump()
            )

        @router.get("/analyze")
        async def analyze_disabled() -> JSONResponse:
            return _build_error_response("CZSC_DISABLED", "czsc extension disabled")

        @router.get("/analyze/stream")
        async def analyze_stream_disabled() -> StreamingResponse:
            async def _err() -> AsyncIterator[bytes]:
                err = json.dumps({"code": "CZSC_DISABLED", "message": "czsc extension disabled"})
                yield f"event: error\ndata: {err}\n\n".encode()

            return StreamingResponse(_err(), media_type="text/event-stream")

        @router.post("/data/refresh")
        async def refresh_disabled() -> JSONResponse:
            return _build_error_response("CZSC_DISABLED", "czsc extension disabled")

        @router.post("/scan")
        async def scan_disabled() -> JSONResponse:
            return _build_error_response("CZSC_DISABLED", "czsc extension disabled")

        @router.get("/scan/{task_id}")
        async def scan_task_disabled(task_id: str) -> JSONResponse:
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
        start_date: date | None = None,
        end_date: date | None = None,
        max_bi_num: int = Query(DEFAULT_MAX_BI_NUM, ge=10, le=500),
        min_bi_len: int = Query(
            DEFAULT_MIN_BI_LEN,
            ge=6,
            le=30,
            description="笔最少K线数(第62课: 笔至少5根K线, 此处含端点至少6)",
        ),
        features: str = Query("fx,bi,zs,signals,bs_points"),
        force_refresh: bool = Query(False),
        symbol_name: str | None = Query(None, description="标的中文名 (前端透传, 不查库)"),
        bs_macd_area_mode: str = Query(
            "split", description="背驰 MACD 面积口径: split/total_abs/dif_dea"
        ),
        bs_use_dif: bool = Query(True, description="背驰是否启用 DIF 极值条件"),
        bs_use_dea: bool = Query(
            False,
            description="[已废弃] 缠师原文未要求 DEA, 保留参数兼容旧前端, 内部忽略",
        ),
        bs_use_macd_area: bool = Query(True, description="背驰是否启用 MACD 面积条件"),
        bs_use_zero_axis: bool = Query(
            False,
            description=(
                "背驰是否启用 MACD 0轴回抽条件(第24课): a/c 两段之间 DIF 须回拉触及 0 轴, "
                "过滤零轴下弱势反弹的假背驰; 默认关闭"
            ),
        ),
        bs_divergence_logic: str = Query(
            "and", description="背驰条件组合: and=面积与DIF同时满足(严格); or=任一满足(第27课)"
        ),
        bs_trend_overlap_mode: str = Query(
            "practical",
            description=(
                "趋势中枢重叠口径(第18课趋势成立前提): "
                "practical=[ZD,ZG]核心区间(第20课原文中枢区间, 默认); "
                "strict=[DD,GG]波动区间(影线扫过即重叠, 更保守, 一/二类点更少)"
            ),
        ),
        bs_zs_pullback_base: str = Query(
            "zg", description="回抽最小深度基准: zg=中枢上沿(默认,第20课三买以ZG为锚); height=中枢高度"
        ),
        bs_zs_pullback_min_depth: float = Query(
            0.0, ge=0.0, description="回抽最小进入深度(绝对价格), 与比例取大; 默认0关闭"
        ),
        bs_zs_pullback_min_ratio: float = Query(
            0.02, ge=0.0, le=1.0, description="回抽最小进入深度比例, 默认0.02(2%)"
        ),
        bs_enable_interval_nest: bool = Query(
            False, description="区间套下钻: 对买卖点做30分钟次级别背驰确认(第27课)"
        ),
        bs_output_mode: str = Query(
            DEFAULT_BS_OUTPUT_MODE,
            description=(
                "B2/S2 输出模式: structural=第17课结构定义, 背驰/次级别降为置信度标注(默认); "
                "strict=盘整背驰+次级别确认为必要条件(旧口径)"
            ),
        ),
        center_unit: str = Query(
            DEFAULT_CENTER_UNIT,
            description=(
                "中枢构造单元: bi=笔级中枢(默认); xianduan=笔合成线段后再构造线段级中枢(第83课)"
            ),
        ),
        ma_periods: str | None = Query(
            None, description="逗号分隔的 SMA 周期, 如 '5,20,250'; 后端取数自动扩展暖机"
        ),
    ) -> JSONResponse:
        """同步分析 (适合日K等小数据量)。"""
        ma_periods_list = _parse_ma_periods(ma_periods)

        request = AnalyzeRequest.from_query(
            symbol=symbol,
            freq=freq,
            start=start_date,
            end=end_date,
            max_bi_num=max_bi_num,
            min_bi_len=min_bi_len,
            features=features,
            symbol_name=symbol_name,
            ma_periods=ma_periods_list,
            bs_macd_area_mode=bs_macd_area_mode,
            bs_use_dif=bs_use_dif,
            bs_use_dea=bs_use_dea,
            bs_use_macd_area=bs_use_macd_area,
            bs_use_zero_axis=bs_use_zero_axis,
            bs_divergence_logic=bs_divergence_logic,
            bs_trend_overlap_mode=bs_trend_overlap_mode,
            bs_zs_pullback_base=bs_zs_pullback_base,
            bs_zs_pullback_min_depth=bs_zs_pullback_min_depth,
            bs_zs_pullback_min_ratio=bs_zs_pullback_min_ratio,
            bs_enable_interval_nest=bs_enable_interval_nest,
            bs_output_mode=bs_output_mode,
            center_unit=center_unit,
            force_refresh=force_refresh,
        )
        try:
            result = await analyze_async(request)
            payload = {
                **result,
                "ok": True,
                "fx_list": [f.model_dump() for f in result.get("fx_list", [])],
                "bi_list": [b.model_dump() for b in result.get("bi_list", [])],
                "zs_list": [z.model_dump() for z in result.get("zs_list", [])],
                "bars": [bar.model_dump() for bar in result.get("bars", [])],
                "macd": [m.model_dump() for m in result.get("macd", [])],
                "mas": result.get("mas", []),
                "bs_points": [bp.model_dump() for bp in result.get("bs_points", [])],
            }
            return _build_success_response(payload)
        except AnalyzerError as exc:
            hint = "run: uv sync --extra czsc" if exc.code == "CZSC_NOT_INSTALLED" else None
            return _build_error_response(
                exc.code, exc.message, hint, status=error_status(exc.code)
            )

    @router.get("/analyze/stream")
    async def analyze_stream_endpoint(
        symbol: str = Query(...),
        freq: str = Query("日线"),
        start_date: date | None = None,
        end_date: date | None = None,
        max_bi_num: int = Query(DEFAULT_MAX_BI_NUM, ge=10, le=500),
        min_bi_len: int = Query(
            DEFAULT_MIN_BI_LEN,
            ge=6,
            le=30,
            description="笔最少K线数(第62课: 笔至少5根K线, 此处含端点至少6)",
        ),
        features: str = Query("fx,bi,zs,signals,bs_points"),
        force_refresh: bool = Query(False),
        symbol_name: str | None = Query(None, description="标的中文名 (前端透传, 不查库)"),
        bs_macd_area_mode: str = Query("split"),
        bs_use_dif: bool = Query(True),
        bs_use_dea: bool = Query(False),
        bs_use_macd_area: bool = Query(True),
        bs_use_zero_axis: bool = Query(
            False, description="背驰是否启用 MACD 0轴回抽条件(第24课), 默认关闭"
        ),
        bs_divergence_logic: str = Query("and", description="背驰组合: and=严格; or=第27课口径"),
        bs_trend_overlap_mode: str = Query(
            "practical",
            description="趋势中枢重叠(第18课): practical=[ZD,ZG]核心区间(默认); strict=[DD,GG]波动区间(更保守)",
        ),
        bs_zs_pullback_base: str = Query(
            "zg", description="回抽最小深度基准: zg=中枢上沿(默认); height=中枢高度"
        ),
        bs_zs_pullback_min_depth: float = Query(
            0.0, ge=0.0, description="回抽最小进入深度(绝对价格), 与比例取大"
        ),
        bs_zs_pullback_min_ratio: float = Query(
            0.02, ge=0.0, le=1.0, description="回抽最小进入深度比例, 默认0.02(2%)"
        ),
        bs_enable_interval_nest: bool = Query(False, description="区间套下钻到30分钟次级别"),
        bs_output_mode: str = Query(
            DEFAULT_BS_OUTPUT_MODE,
            description="B2/S2 输出模式: structural=结构定义+置信度标注(默认); strict=旧口径(背驰必要)",
        ),
        center_unit: str = Query(
            DEFAULT_CENTER_UNIT,
            description="中枢构造单元: bi(默认)/xianduan, 与 /analyze 同口径",
        ),
        ma_periods: str | None = Query(
            None, description="逗号分隔的 SMA 周期, 如 '5,20,250'"
        ),
    ) -> StreamingResponse:
        """SSE 流式分析 (适合分钟K等大数据量)。"""
        request = AnalyzeRequest.from_query(
            symbol=symbol,
            freq=freq,
            start=start_date,
            end=end_date,
            max_bi_num=max_bi_num,
            min_bi_len=min_bi_len,
            features=features,
            symbol_name=symbol_name,
            ma_periods=_parse_ma_periods(ma_periods),
            bs_macd_area_mode=bs_macd_area_mode,
            bs_use_dif=bs_use_dif,
            bs_use_dea=bs_use_dea,
            bs_use_macd_area=bs_use_macd_area,
            bs_use_zero_axis=bs_use_zero_axis,
            bs_divergence_logic=bs_divergence_logic,
            bs_trend_overlap_mode=bs_trend_overlap_mode,
            bs_zs_pullback_base=bs_zs_pullback_base,
            bs_zs_pullback_min_depth=bs_zs_pullback_min_depth,
            bs_zs_pullback_min_ratio=bs_zs_pullback_min_ratio,
            bs_enable_interval_nest=bs_enable_interval_nest,
            bs_output_mode=bs_output_mode,
            center_unit=center_unit,
            force_refresh=force_refresh,
        )

        async def stream_gen() -> AsyncIterator[bytes]:
            try:
                async for event in analyze_stream(request):
                    event_type = event["event"]
                    payload = json.dumps(event["data"], ensure_ascii=False, default=str)
                    yield f"event: {event_type}\ndata: {payload}\n\n".encode()
            except Exception as exc:
                logger.exception("czsc SSE stream unexpected error")
                err = json.dumps({"code": "INTERNAL_ERROR", "message": str(exc)})
                yield f"event: error\ndata: {err}\n\n".encode()

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
        """数据刷新 — 重新取数并清空分析缓存, 触发主工程数据源刷新。"""
        has_czsc, _ = _probe_czsc()
        if not has_czsc:
            return _build_error_response(
                "CZSC_NOT_INSTALLED",
                "czsc library not installed",
                hint="run: uv sync --extra czsc",
            )

        end = date.today()
        start = end - timedelta(days=365)
        try:
            df, source = _fetch_kline(body.symbol, body.freq, start, end)
        except Exception as exc:
            return _build_error_response("FETCH_FAILED", str(exc), status=500)

        if df.is_empty():
            return _build_error_response("NO_DATA", f"no data for {body.symbol} {body.freq}")

        get_default_service().clear_cache()

        latest = df["dt"].max()
        latest_date = latest.date().isoformat() if latest is not None else None
        result = RefreshResult(
            symbol=body.symbol,
            freq=body.freq,
            cached_bars=df.height,
            latest_date=latest_date,
            source=source,
        )
        return _build_success_response(result.model_dump())

    @router.post("/scan")
    async def scan_signals(
        pool: str = Query(DEFAULT_SCAN_POOL, description="股票池 id"),
        symbols: str | None = Query(None, description="显式标的, 逗号分隔, 优先于 pool"),
        freq: str = Query(DEFAULT_SCAN_FREQ, description="级别: 日线/周线/30分钟/..."),
        as_of: date | None = None,  # 扫描截止日, 默认今日 (裸 None 避开 B008, FastAPI 同样识别为可选 query)
        lookback_days: int = Query(DEFAULT_SCAN_LOOKBACK_DAYS, ge=60, le=2000),
        signal_types: str = Query("B1,B2", description="目标信号, 逗号分隔"),
        max_signal_age: int = Query(DEFAULT_SCAN_MAX_SIGNAL_AGE, ge=0, description="信号最大年龄(自然日), 0=不限"),
        min_divergence_hits: int = Query(0, ge=0, le=2, description="至少命中几个背驰条件"),
        order_by: str = Query("dt_desc", description="dt_desc / divergence_desc"),
        limit: int = Query(DEFAULT_SCAN_LIMIT, ge=1, le=500),
        max_workers: int = Query(DEFAULT_SCAN_MAX_WORKERS, ge=1, le=32),
        max_symbols: int | None = Query(None, ge=1, description="扫描标的上限"),
        force_refresh: bool = Query(False),
        # 判定口径 — 与 /analyze 同名同默认
        bs_macd_area_mode: str = Query("split"),
        bs_use_dif: bool = Query(True),
        bs_use_macd_area: bool = Query(True),
        bs_use_zero_axis: bool = Query(False, description="背驰 0轴回抽条件(第24课), 默认关闭"),
        bs_divergence_logic: str = Query("and"),
        bs_trend_overlap_mode: str = Query("practical"),
        bs_zs_pullback_base: str = Query("zg"),
        bs_zs_pullback_min_depth: float = Query(0.0, ge=0.0),
        bs_zs_pullback_min_ratio: float = Query(0.02, ge=0.0, le=1.0),
        bs_output_mode: str = Query(
            DEFAULT_BS_OUTPUT_MODE,
            description="B2/S2 输出模式: structural(默认)/strict, 与 /analyze 同口径",
        ),
    ) -> Response:
        """B1/B2 信号选股 — 与单股 /analyze 完全同口径。"""
        has_czsc, _ = _probe_czsc()
        if not has_czsc:
            return _build_error_response(
                "CZSC_NOT_INSTALLED", "czsc library not installed", hint="run: uv sync --extra czsc"
            )

        from .application.scanner import ScanService, get_scan_service
        from .config import DivergenceConfig

        divergence = DivergenceConfig(
            macd_area_mode=bs_macd_area_mode,
            use_dif=bs_use_dif,
            use_macd_area=bs_use_macd_area,
            use_zero_axis=bs_use_zero_axis,
            divergence_logic=bs_divergence_logic,
            trend_overlap_mode=bs_trend_overlap_mode,
            zs_pullback_base=bs_zs_pullback_base,
            zs_pullback_min_depth=bs_zs_pullback_min_depth,
            zs_pullback_min_ratio=bs_zs_pullback_min_ratio,
            bs_output_mode=bs_output_mode,
        )
        req = ScanRequest(
            pool=pool,
            symbols=tuple(s.strip() for s in (symbols or "").split(",") if s.strip()),
            freq=freq,
            as_of=as_of,
            lookback_days=lookback_days,
            signal_types=tuple(s.strip().upper() for s in signal_types.split(",") if s.strip()),
            max_signal_age=max_signal_age,
            min_divergence_hits=min_divergence_hits,
            order_by=order_by,
            limit=limit,
            max_workers=max_workers,
            max_symbols=max_symbols,
            force_refresh=force_refresh,
            divergence=divergence,
        ).normalized()

        svc = get_scan_service()
        pairs, _ = svc.resolve_symbols(req)
        if ScanService.should_use_async(req, len(pairs)):
            task_id = svc.start_task(req)
            return _build_success_response({"ok": True, "task_id": task_id, "status": "running", "total": len(pairs)})

        result = svc.scan(req)
        return _build_success_response(result.model_dump())

    @router.get("/scan/progress")
    async def scan_progress() -> Response:
        """全局扫描进度 (策略面板同步链路轮询用)。

        返回最近一次/正在进行的扫描进度, 含正在检测的标的。
        前端在 run_preset 挂起期间以 ~1s 间隔轮询本端点展示进度条。
        """
        from .application.scanner import get_scan_progress

        return _build_success_response(get_scan_progress())

    @router.get("/scan/{task_id}")
    async def scan_task(task_id: str) -> Response:
        """查询异步扫描任务进度/结果。"""
        from .application.scanner import get_scan_service

        status = get_scan_service().get_task(task_id)
        if status is None:
            return _build_error_response("SCAN_TASK_NOT_FOUND", f"scan task {task_id} not found", status=404)
        return _build_success_response(status.model_dump())

    return router
