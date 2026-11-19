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


class BsPointItem(BaseModel):
    """缠论买卖点 (一二三类)。

    type 取值: 'B1'/'B2'/'B3' (第一/二/三类买点), 'S1'/'S2'/'S3' (第一/二/三类卖点)。
    direction: '买' / '卖'。
    dt/price: 买卖点所在 K 线 (笔端点分型 K 线) 的日期与价位 (顶分型取 high, 底分型取 low)。
    bi_direction: 触发该买卖点的笔方向 ('Direction.Up'/'Direction.Down')。
    zs_index: 关联的中枢在 zs_list 中的下标 (无中枢关联的 B1/S1 取 -1)。

    背驰详细信息 (严格按缠论计算, 鼠标悬浮显示):
        macd_area_prev / macd_area_cur   — 前后两同向笔的 MACD 柱面积 (按 macd_area_mode 口径)
        dif_peak_prev / dif_peak_cur     — 前后两笔区间内 DIF 极值 (上涨取 max, 下跌取 min)
        dea_peak_prev / dea_peak_cur     — 前后两笔区间内 DEA 极值
        divergence_type                  — 背驰类型描述, 如 'MACD面积+DIF+DEA三重背驰'
        divergence_pass                  — 本次判定命中的背驰条件集合, 如 ['macd_area','dif','dea']

    macd_area_mode 取值 (与后端 _identify_bs_points 配置一致):
        'split'     — 红绿柱分计 (默认; 下跌笔只计绿柱面积, 上涨笔只计红柱面积)
        'total_abs' — 笔区间内 Σ|hist| (含红绿柱)
        'dif_dea'   — 两次金叉/死叉之间 Σ|DIF-DEA| (对齐 czsc tas_macd_bs1 口径)
    """
    dt: str
    type: str                       # B1/B2/B3/S1/S2/S3
    direction: str                  # 买/卖
    price: float
    bi_direction: str
    zs_index: int = -1
    macd_area_prev: float | None = None
    macd_area_cur: float | None = None
    dif_peak_prev: float | None = None
    dif_peak_cur: float | None = None
    dea_peak_prev: float | None = None
    dea_peak_cur: float | None = None
    divergence_type: str | None = None
    divergence_pass: list[str] = Field(default_factory=list)
    macd_area_mode: str = "split"


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
    bs_points: list[BsPointItem] = Field(default_factory=list)
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
