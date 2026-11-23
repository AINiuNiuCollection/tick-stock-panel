"""应用服务 — 编排取数、分析、缓存与流式输出。

analyzer.py 保留为薄门面 (公共 API 不变), 具体流程收敛到本模块。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import asdict
from typing import Any

from app.config import settings

from ..adapters import indicators
from ..adapters.czsc_adapter import bar_date, probe_czsc, run_czsc, to_raw_bars
from ..adapters.kline.chain import KlineSourceChain, build_default_chain
from ..adapters.kline.multilevel import IntervalNestVerifier
from ..adapters.kline.source import KlineResult
from ..adapters.kline.sublevel import SublevelVerifier
from ..config import AnalyzeRequest
from ..domain.bs_points import identify_bs_points
from ..domain.models import DtIndex
from ..domain.zs import build_zs_strict
from ..errors import AnalyzerError
from ..schemas import BarItem, BiItem, BsPointItem, FxItem, MacdItem, ZsItem
from .cache import AnalysisCache

logger = logging.getLogger(__name__)


class AnalyzeService:
    def __init__(
        self,
        chain: KlineSourceChain,
        sublevel: SublevelVerifier | None = None,
        cache: AnalysisCache | None = None,
        nest: IntervalNestVerifier | None = None,
    ) -> None:
        self._chain = chain
        self._sublevel = sublevel
        self._cache = cache or AnalysisCache()
        self._nest = nest

    def fetch(self, symbol: str, freq: str, start, end) -> KlineResult:
        return self._chain.fetch(symbol, freq, start, end)

    def clear_cache(self) -> None:
        self._cache.clear()

    def analyze(self, request: AnalyzeRequest) -> dict[str, Any]:
        req = request.with_defaults()
        key = req.cache_key()
        if not req.force_refresh:
            cached = self._cache.get(key)
            if cached is not None:
                cached["cached"] = True
                return cached

        fetch_start = req.fetch_start()
        result = self._run(req, fetch_start)
        self._cache.put(key, result)
        return result

    def _run(self, req: AnalyzeRequest, fetch_start) -> dict[str, Any]:
        result = self._chain.fetch(req.symbol, req.freq, fetch_start, req.end)
        if result.frame.is_empty():
            raise AnalyzerError(
                "NO_DATA",
                f"no kline data for {req.symbol} {req.freq} ({fetch_start} ~ {req.end}); "
                f"configured minute provider, TickFlow, and eastmoney fallback all empty",
            )
        return self._analyze_frame(req, result.frame, fetch_start, result.source)

    def _analyze_frame(
        self,
        req: AnalyzeRequest,
        df,
        fetch_start,
        source: str,
    ) -> dict[str, Any]:
        bars_all = to_raw_bars(df, req.freq)
        if not bars_all:
            raise AnalyzerError("CONVERT_FAILED", f"convert to RawBar failed for {req.symbol} {req.freq}")

        bars = [b for b in bars_all if bar_date(b) >= req.start] if fetch_start < req.start else bars_all
        fxs, bis, signals = run_czsc(bars, req.max_bi_num, req.min_bi_len)
        zs_raw = build_zs_strict(
            bis,
            min_pullback_depth=req.divergence.zs_pullback_min_depth,
            min_pullback_ratio=req.divergence.zs_pullback_min_ratio,
            pullback_base=req.divergence.zs_pullback_base,
        )

        bars_out = [
            BarItem(
                dt=str(bar.dt),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                vol=float(bar.vol) if bar.vol is not None else 0.0,
                amount=float(bar.amount) if bar.amount is not None else 0.0,
            )
            for bar in bars
        ]

        fx_list = (
            [
                FxItem(
                    dt=str(fx.dt),
                    mark=fx.raw_mark,
                    fx=fx.raw_fx,
                    high=fx.high,
                    low=fx.low,
                )
                for fx in fxs
            ]
            if "fx" in req.features
            else []
        )
        bi_list = (
            [
                BiItem(
                    sdt=str(bi.sdt),
                    edt=str(bi.edt),
                    direction=bi.raw_direction,
                    high=bi.high,
                    low=bi.low,
                    length=bi.length,
                    power=bi.power,
                )
                for bi in bis
            ]
            if "bi" in req.features
            else []
        )
        zs_list = (
            [
                ZsItem(
                    zs_range=[zs.zd, zs.zg],
                    zd=zs.zd,
                    zg=zs.zg,
                    gg=zs.gg,
                    dd=zs.dd,
                    level=1,
                    start_dt=str(zs.sdt),
                    end_dt=str(zs.edt),
                    valid=zs.valid,
                )
                for zs in zs_raw
            ]
            if "zs" in req.features
            else []
        )

        macd_points = indicators.precomputed_macd_points(bars_out, df)
        if macd_points is None:
            macd_points = indicators.macd_points_from_bars(bars_out)
        macd_out = [
            MacdItem(dt=m.dt, dif=m.dif, dea=m.dea, macd=m.macd) for m in macd_points
        ]

        bs_points: list[BsPointItem] = []
        if "bs_points" in req.features:
            verifier = None
            if self._sublevel is not None:
                _sub, _freq, _sym = self._sublevel, req.freq, req.symbol
                # 按分析级别下钻次级别 (日线→30分钟, 30分钟→5分钟...);
                # 无更低级别配置时 verify 内部降级放行, 与无验证器语义一致。
                verifier = lambda edt: _sub.verify(_sym, _freq, edt)  # noqa: E731
            dt_index = DtIndex.from_bars(bars_out)
            # 区间套下钻: 有 nest 验证器且请求开启时, 对买卖点做次级别背驰标注。
            nest_verifier = None
            if self._nest is not None and req.divergence.enable_interval_nest:
                nest = self._nest
                symbol = req.symbol

                def nest_verifier(dt, bs_type, direction, _nest=nest, _symbol=symbol, _freq=req.freq):
                    return _nest.verify(_symbol, _freq, dt, direction)
            neutral = identify_bs_points(
                bis, zs_raw, macd_points, dt_index, req.divergence, verifier, nest_verifier
            )
            bs_points = [BsPointItem(**asdict(bp)) for bp in neutral]

        mas_out = indicators.sma_for_range(bars_all, bars_out, req.ma_periods)

        return {
            "symbol": req.symbol,
            "symbol_name": req.symbol_name,
            "freq": req.freq,
            "bar_count": len(bars),
            "fx_list": fx_list,
            "bi_list": bi_list,
            "zs_list": zs_list,
            "bars": bars_out,
            "macd": macd_out,
            "mas": mas_out,
            "bs_points": bs_points,
            "signals": signals if "signals" in req.features else {},
            "warnings": None,
            "source": source,
            "cached": False,
        }

    def _partial_events(
        self, req: AnalyzeRequest, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for feature, key, progress in (
            ("fx", "fx_list", 0.4),
            ("bi", "bi_list", 0.7),
            ("zs", "zs_list", 0.9),
        ):
            if feature in req.features:
                events.append(
                    {
                        "event": "partial",
                        "data": {
                            key: [item.model_dump() for item in payload[key]],
                            "progress": progress,
                        },
                    }
                )
        return events

    async def stream(self, request: AnalyzeRequest):
        req = request.with_defaults()
        has_czsc, _ = probe_czsc()
        if not has_czsc:
            yield {
                "event": "error",
                "data": {
                    "code": "CZSC_NOT_INSTALLED",
                    "message": "czsc library not installed; run: uv sync --extra czsc",
                },
            }
            return

        if not req.force_refresh:
            cached = self._cache.get(req.cache_key())
            if cached is not None:
                cached["cached"] = True
                yield {
                    "event": "status",
                    "data": {
                        "phase": "cached",
                        "symbol": req.symbol,
                        "bar_count": cached.get("bar_count"),
                    },
                }
                for event in self._partial_events(req, cached):
                    yield event
                    await asyncio.sleep(0)
                yield {"event": "done", "data": {"result": {**cached, "ok": True}}}
                return

        yield {
            "event": "status",
            "data": {"phase": "fetching_kline", "symbol": req.symbol},
        }
        await asyncio.sleep(0)

        fetch_start = req.fetch_start()
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, self._chain.fetch, req.symbol, req.freq, fetch_start, req.end
            )
        except Exception as exc:
            yield {"event": "error", "data": {"code": "FETCH_FAILED", "message": str(exc)}}
            return

        if result.frame.is_empty():
            yield {
                "event": "error",
                "data": {
                    "code": "NO_DATA",
                    "message": f"no kline data for {req.symbol} {req.freq}",
                },
            }
            return

        yield {
            "event": "status",
            "data": {
                "phase": "analyzing",
                "symbol": req.symbol,
                "bar_count": result.frame.height,
            },
        }
        await asyncio.sleep(0)

        try:
            payload = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    self._analyze_frame,
                    req,
                    result.frame,
                    fetch_start,
                    result.source,
                ),
                timeout=settings.czsc_analyze_timeout_s,
            )
        except TimeoutError:
            yield {
                "event": "error",
                "data": {
                    "code": "ANALYZE_TIMEOUT",
                    "message": f"czsc analyze timeout after {settings.czsc_analyze_timeout_s}s",
                },
            }
            return
        except AnalyzerError as exc:
            yield {"event": "error", "data": {"code": exc.code, "message": exc.message}}
            return
        except Exception as exc:
            yield {"event": "error", "data": {"code": "INTERNAL_ERROR", "message": str(exc)}}
            return

        if not req.force_refresh:
            self._cache.put(req.cache_key(), payload)

        for event in self._partial_events(req, payload):
            yield event
            await asyncio.sleep(0)

        yield {"event": "done", "data": {"result": {**payload, "ok": True}}}


_default_service: AnalyzeService | None = None
_service_lock = threading.Lock()


def build_default_service() -> AnalyzeService:
    chain = build_default_chain()
    return AnalyzeService(
        chain,
        SublevelVerifier(chain),
        # maxsize 覆盖策略面板默认 300 只扫描; 128 会互相驱逐导致重复分析
        AnalysisCache(maxsize=2048, ttl_s=600.0),
        IntervalNestVerifier(chain),
    )


def get_default_service() -> AnalyzeService:
    global _default_service
    if _default_service is None:
        with _service_lock:
            if _default_service is None:
                _default_service = build_default_service()
    return _default_service


def set_default_service(service: AnalyzeService | None) -> None:
    """测试用: 注入替身服务。"""
    global _default_service
    _default_service = service
