"""czsc 接口契约模型 — Pydantic v2, 与前端 api.ts 类型对齐。

设计原则:
    - 不 import czsc 库 (schemas 永远可加载, 即使 czsc 未装)
    - 字段命名与前端 TypeScript interface 一致 (snake_case ↔ snake_case)
    - 响应包裹 {ok: bool, ...} 让前端区分成功/业务错误
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FxItem(BaseModel):
    """分型。mark: 'Mark.G'=顶分型, 'Mark.D'=底分型。"""
    dt: str
    mark: str
    fx: str | None = None
    high: float
    low: float


class BiItem(BaseModel):
    """笔。direction: 'Direction.Up'/'Direction.Down'。"""
    sdt: str
    edt: str
    direction: str
    high: float
    low: float
    length: int
    power: float | None = None


class ZsItem(BaseModel):
    """中枢。zs_range=[zd, zg] (下沿, 上沿), 兼容旧前端契约;
    zd/zg/gg/dd 为 czsc 1.0.2 原生字段 (中枢上下沿 / 区间最值)。"""
    zs_range: list[float]
    zd: float | None = None  # 中枢下沿
    zg: float | None = None  # 中枢上沿
    gg: float | None = None  # 区间最高
    dd: float | None = None  # 区间最低
    level: int = 1  # czsc 1.0.2 无 level 概念, 保留兼容
    start_dt: str
    end_dt: str
    valid: bool = True


class BarItem(BaseModel):
    """K 线一根。dt 为字符串 (ISO datetime 或 date), OHLCV 数值。"""
    dt: str
    open: float
    high: float
    low: float
    close: float
    vol: float = 0.0
    amount: float = 0.0


class MacdItem(BaseModel):
    """MACD 一根。dif/dea/macd 为双线 + 柱值, 前 max(26,9)-1 根可能为 None。
    参数固定 12/26/9 (对齐示例图 "MACD · 12/26/9")。
    """
    dt: str
    dif: float | None = None    # DIFF = EMA12 - EMA26
    dea: float | None = None    # DEA  = EMA(DIFF, 9)
    macd: float | None = None   # MACD hist = 2 * (DIFF - DEA)


class AnalyzeResult(BaseModel):
    """同步/流式分析最终结果。"""
    ok: bool = True
    symbol: str
    symbol_name: str | None = None  # 中文名 (前端透传, 不查库)
    freq: str
    bar_count: int
    fx_list: list[FxItem] = Field(default_factory=list)
    bi_list: list[BiItem] = Field(default_factory=list)
    zs_list: list[ZsItem] = Field(default_factory=list)
    bars: list[BarItem] = Field(default_factory=list)
    macd: list[MacdItem] = Field(default_factory=list)
    signals: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] | None = None
    source: str = "primary"
    cached: bool = False


class HealthResult(BaseModel):
    """健康检查 — 同时暴露能力可用性, 前端可据此渲染入口。"""
    ok: bool = True
    version: str | None = None
    czsc_native_available: bool = False
    data_sources: list[str] = Field(default_factory=list)
    eastmoney_fallback: bool = False


class CapabilitiesResult(BaseModel):
    """能力检测端点 — 与 HealthResult 互补, 专门给前端「是否展示入口」用。"""
    available: bool
    version: str | None = None
    native_ready: bool = False
    eastmoney_fallback: bool = False
    install_hint: str | None = None


class RefreshRequest(BaseModel):
    """数据刷新请求体。"""
    symbol: str
    freq: str = "日线"
    start_date: str | None = None
    end_date: str | None = None


class RefreshResult(BaseModel):
    ok: bool = True
    symbol: str
    freq: str
    cached_bars: int = 0
    latest_date: str | None = None
    source: str = "primary"


class ErrorResponse(BaseModel):
    """统一错误响应包裹。"""
    ok: bool = False
    error: dict[str, Any]


# ===== SSE 事件载荷 (用于流式响应, 非 HTTP body) =====

class StatusEvent(BaseModel):
    phase: str
    symbol: str
    bar_count: int | None = None


class PartialEvent(BaseModel):
    fx_list: list[FxItem] | None = None
    bi_list: list[BiItem] | None = None
    zs_list: list[ZsItem] | None = None
    progress: float


class DoneEvent(BaseModel):
    result: AnalyzeResult


class ErrorEvent(BaseModel):
    code: str
    message: str
