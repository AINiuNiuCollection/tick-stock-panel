"""B1/B2 信号选股扫描服务。

职责边界:
    - 只做编排: 池解析 → 并发逐股分析 → 按 BsPoint.type 过滤 → 排序产出
    - 单股分析一律复用 AnalyzeService.analyze, 不复制任何买卖点判定逻辑
    - 判定口径整体复用 DivergenceConfig, 与 /api/czsc/analyze 完全一致

设计参见 docs/czsc-b1b2-scanner-design.md。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import settings
from app.custom.czsc.config import ASYNC_SCAN_THRESHOLD, ScanRequest
from app.custom.czsc.schemas import ScanHit, ScanResult, ScanTaskStatus

logger = logging.getLogger(__name__)

# ===== 全局扫描进度注册表 =====
# 策略面板的 run_preset 是同步阻塞链路, 前端无法从响应中拿到逐股进度。
# scan() 执行过程中把 (done, total, current_symbol) 写入这份进程内注册表,
# 前端通过 GET /api/czsc/scan/progress 轮询展示"正在检测哪一只"。
_progress_lock = threading.Lock()
_progress_state: dict[str, Any] = {
    "active": False,
    "done": 0,
    "total": 0,
    "current_symbol": None,
    "started_at": None,     # iso 时间戳
    "updated_at": None,
}


def set_scan_progress(done: int, total: int, symbol: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with _progress_lock:
        if not _progress_state["active"]:
            _progress_state["started_at"] = now
        _progress_state["active"] = True
        _progress_state["done"] = done
        _progress_state["total"] = total
        if symbol:
            _progress_state["current_symbol"] = symbol
        _progress_state["updated_at"] = now


def mark_scan_done() -> None:
    with _progress_lock:
        _progress_state["active"] = False
        _progress_state["updated_at"] = datetime.now().isoformat(timespec="seconds")


def get_scan_progress() -> dict[str, Any]:
    with _progress_lock:
        return dict(_progress_state)

# 股票池解析延迟导入 (tickflow 依赖可选), 模块加载时不触发
def _get_pool(pool_id: str) -> list[str]:
    from app.tickflow.pools import get_pool
    return get_pool(pool_id)  # type: ignore[arg-type]


def _to_date(value: str | datetime | date | None) -> date | None:
    """把 bs_point.dt (str/datetime) 归一到 date。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except ValueError:
        return None


def _to_datetime(value: object) -> datetime | None:
    """把 bar.dt / bs_point.dt (str/date/datetime) 归一到 datetime。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("T", " ")[:19])
    except ValueError:
        return None


def _bar_age(bars: list[Any], signal_dt: object, as_of: date) -> int:
    """信号年龄 = 信号之后的本级别K线根数 (2026-11-23 需求):
    周线按周K线数、日线按交易日数 — 周末/节假日无K线不计 ("只计算交易日")。
    bars 不可得时回退自然日口径 (防御: 正常链路 analyze 恒返回 bars)。"""
    sig = _to_datetime(signal_dt)
    if sig is None:
        return 0
    if not bars:
        return (as_of - sig.date()).days
    end = datetime(as_of.year, as_of.month, as_of.day, 23, 59, 59)
    count = 0
    for b in bars:
        bdt = _to_datetime(getattr(b, "dt", None))
        if bdt is not None and sig < bdt <= end:
            count += 1
    return count


def _name_of(symbol: str, result: dict[str, Any]) -> str | None:
    value = result.get("symbol_name")
    return str(value) if value else None


class ScanService:
    """B1/B2 选股扫描器。同步扫描 + 轻量异步任务管理, 结果落盘。"""

    def __init__(self, analyzer: Any = None, data_dir: Path | None = None) -> None:
        self._analyzer = analyzer
        self._data_dir = data_dir or Path(settings.data_dir) / "czsc_scan"
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ---------- 依赖注入 ----------
    @property
    def analyzer(self) -> Any:
        if self._analyzer is None:
            from app.custom.czsc.application.service import get_default_service
            self._analyzer = get_default_service()
        return self._analyzer

    # ---------- 池解析 ----------
    def resolve_symbols(self, req: ScanRequest) -> tuple[list[tuple[str, str | None]], list[str]]:
        """返回 [(symbol, name), ...] 与 warnings。"""
        warnings: list[str] = []
        if req.symbols:
            pairs = [(s, None) for s in req.symbols]
        else:
            try:
                symbols = _get_pool(req.pool)
            except Exception as exc:
                logger.warning("scan pool fetch failed: %s", exc)
                return [], [f"股票池 {req.pool} 获取失败: {exc}"]
            if not symbols:
                return [], [f"股票池 {req.pool} 为空"]
            pairs = [(s, None) for s in symbols]
            # 过滤 ST/退市 — 用 instruments 维表 name 列; 读不到则不筛(只告警)
            try:
                import polars as pl
                path = Path(settings.data_dir) / "instruments" / "instruments.parquet"
                if path.exists():
                    names = dict(
                        pl.read_parquet(path).select("symbol", "name").iter_rows()
                    )
                    pairs = [
                        (s, str(names[s]) if s in names else None)
                        for s, _ in pairs
                        if not (s in names and any(k in str(names[s]) for k in ("ST", "退")))
                    ]
            except Exception as exc:
                warnings.append(f"ST 过滤跳过: {exc}")

        if req.max_symbols is not None:
            pairs = pairs[: req.max_symbols]
        # 分钟级别: 显式 symbols 已在 normalized 截断; 无 symbols 时由
        # validate_for_execution 用真实池规模拒绝, 不能在这里先截断否则校验失效
        return pairs, warnings

    # ---------- 命中提取 ----------
    def _extract_hits(
        self,
        symbol: str,
        name: str | None,
        result: dict[str, Any],
        req: ScanRequest,
        as_of: date,
    ) -> list[ScanHit]:
        hits: list[ScanHit] = []
        bars = result.get("bars") or []
        for bp in result.get("bs_points") or []:
            if getattr(bp, "type", None) not in req.signal_types:
                continue
            if getattr(bp, "direction", None) != "买":
                continue
            dt = _to_date(getattr(bp, "dt", None))
            if dt is None or dt > as_of:
                continue
            # 信号年龄按本级别K线根数计 (周线=周K线, 日线=交易日;
            # 周末/节假日无K线不计) — 2026-11-23 起, 原自然日口径作废
            age = _bar_age(bars, getattr(bp, "dt", None), as_of)
            if req.max_signal_age and age > req.max_signal_age:
                continue
            passes = list(getattr(bp, "divergence_pass", []) or [])
            # min_divergence_hits 语义修复 (2026-11-24 审计 P1-1): structural
            # 输出模式下 B2/B3 的盘整背驰只是置信度标注 (divergence_pass 可为
            # 空), 该过滤对它们是隐性绞杀 (全市场 80 个 B2 被杀 30 个);
            # strict 模式盘整背驰是必要条件, 维持过滤。B1/S1 趋势背驰在两种
            # 模式下都是必要条件, 恒参与过滤。
            structural_annotation_only = (
                req.divergence.bs_output_mode != "strict"
                and str(bp.type) in ("B2", "B3", "S2", "S3")
            )
            if not structural_annotation_only and len(passes) < req.min_divergence_hits:
                continue
            zs_range = None
            zs_list = result.get("zs_list") or []
            zi = getattr(bp, "zs_index", -1)
            if isinstance(zi, int) and 0 <= zi < len(zs_list):
                zs = zs_list[zi]
                zs_range = list(getattr(zs, "zs_range", []) or [
                    getattr(zs, "zd", None), getattr(zs, "zg", None)
                ])
                zs_range = [float(v) for v in zs_range if v is not None] or None
            hits.append(
                ScanHit(
                    symbol=symbol,
                    name=name or _name_of(symbol, result),
                    freq=req.freq,
                    type=str(bp.type),
                    direction="买",
                    dt=str(bp.dt),
                    price=float(bp.price),
                    signal_age_days=age,
                    divergence_type=getattr(bp, "divergence_type", None),
                    divergence_pass=passes,
                    definition_mode=str(getattr(bp, "definition_mode", "n/a") or "n/a"),
                    zs_range=zs_range,
                    level=str(getattr(bp, "level", req.freq) or req.freq),
                )
            )
        return hits

    # ---------- 次级别日期标注 (需求2, 2026-11-23; G 2026-11-23 加源不可用标记) ----------
    def _annotate_sub_dt(self, hits: list[ScanHit]) -> int:
        """命中截断后逐只区间套下钻, 标注次级别背驰点日期 (NestResult.sub_div_end)。

        放在截断后执行: 取数次数封顶于 limit, 不随扫描池规模放大;
        次级别源不可用时由 IntervalNestVerifier 熔断兜底 (每窗口一次探测)。
        单点异常静默跳过 — 次级别日期是展示增强, 不影响命中本身。

        G: 源级失败 (取数异常/空帧/冷却) 时置 hit.sub_source_unavailable=True
        并返回失败计数 — 调用方据此保留 B1 信号并向 warnings 追加提示;
        "有数据但未确认" 不置标记, 维持 fail-closed 丢弃。
        """
        nest = getattr(self.analyzer, "nest_verifier", None)
        if nest is None or not hits:
            return 0
        unavailable = 0
        for h in hits:
            direction = "down" if h.direction == "买" else "up"
            try:
                nr = nest.verify(h.symbol, h.freq, h.dt, direction)
            except Exception as exc:
                logger.debug("nest annotate failed for %s: %s", h.symbol, exc)
                continue
            if nr is None:
                continue
            if nr.source_unavailable:
                h.sub_source_unavailable = True
                unavailable += 1
            elif nr.confirmed and nr.sub_div_end is not None:
                h.sub_dt = str(nr.sub_div_end)[:10]
        return unavailable

    # ---------- 单股分析 ----------
    def _scan_one(
        self,
        symbol: str,
        name: str | None,
        req: ScanRequest,
        start: date,
        end: date,
    ) -> tuple[list[ScanHit], str | None]:
        """分析单只股票, 返回 (hits, error)。异常只记 error, 不抛出。"""
        try:
            analysis_req = req.analysis_request(symbol, name, start, end)
            result = self.analyzer.analyze(analysis_req)
            return self._extract_hits(symbol, name, result, req, end), None
        except Exception as exc:
            logger.warning("scan symbol %s failed: %s", symbol, exc)
            return [], f"{type(exc).__name__}: {exc}"

    # ---------- 同步扫描 ----------
    def scan(
        self,
        req: ScanRequest,
        *,
        progress: Callable[[int, int, str | None], None] | None = None,
    ) -> ScanResult:
        started = time.perf_counter()
        req = req.normalized()
        as_of = req.as_of or date.today()
        start = as_of - timedelta(days=req.lookback_days)
        pairs, warnings = self.resolve_symbols(req)
        # P2-1 (2026-11-24 审计): normalized() 的参数修正提示 (白名单外
        # signal_types 被忽略等) 并入结果告警 — 两条返回路径共用此 warnings
        if req.normalization_warnings:
            warnings = [*req.normalization_warnings, *warnings]

        errors_check = req.validate_for_execution(len(pairs))
        if errors_check:
            mark_scan_done()
            return ScanResult(
            pool=req.pool, freq=req.freq, as_of=as_of.isoformat(),
            hits=[], total=0, total_scanned=0, total_symbols=len(pairs),
            elapsed_ms=(time.perf_counter() - started) * 1000,
            errors={"__params__": "; ".join(errors_check)}, warnings=warnings,
            params=self._params_summary(req),
        )

        errors: dict[str, str] = {}
        hits: list[ScanHit] = []
        total = len(pairs)
        done = 0
        # 立即发布 total: 前端可据此估算等待窗口, 不必等第一只股票完成。
        set_scan_progress(0, total)
        try:
            with ThreadPoolExecutor(max_workers=req.max_workers, thread_name_prefix="czsc-scan") as pool:
                futures = {
                    pool.submit(self._scan_one, sym, name, req, start, as_of): sym
                    for sym, name in pairs
                }
                for future in as_completed(futures):
                    sym = futures[future]
                    try:
                        got, err = future.result(timeout=req.per_symbol_timeout_s + 5)
                    except Exception as exc:
                        got, err = [], f"{type(exc).__name__}: {exc}"
                    hits.extend(got)
                    if err:
                        errors[sym] = err
                    done += 1
                    # 全局注册表始终更新 (策略面板同步链路靠它 + /scan/progress 轮询)
                    set_scan_progress(done, total, sym)
                    if progress:
                        progress(done, total, sym)

            # 排序
            if req.order_by == "divergence_desc":
                hits.sort(key=lambda h: (-len(h.divergence_pass), h.dt), reverse=False)
            else:
                hits.sort(key=lambda h: h.dt, reverse=True)
            hits = hits[: req.limit]
            # 需求2: 最终命中逐只标注次级别背驰点日期 (区间套下钻, 有熔断兜底)
            # G: 源不可用的命中置 sub_source_unavailable, 策略侧保留 B1 并告警
            sub_unavailable = self._annotate_sub_dt(hits)
            if sub_unavailable > 0:
                warnings = [
                    *warnings,
                    f"次级别(30分钟)数据源不可用, {sub_unavailable} 个命中的区间套确认被跳过 — "
                    "源恢复前这些 B1 信号未经次级别背驰验证, 请谨慎参考",
                ]

            result = ScanResult(
                pool=req.pool,
                freq=req.freq,
                as_of=as_of.isoformat(),
                hits=hits,
                total=len(hits),
                total_scanned=done,
                total_symbols=total,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                errors=errors,
                warnings=warnings,
                params=self._params_summary(req),
            )
        finally:
            mark_scan_done()
        return result

    @staticmethod
    def _params_summary(req: ScanRequest) -> dict[str, Any]:
        return {
            "signal_types": list(req.signal_types),
            "lookback_days": req.lookback_days,
            "max_signal_age": req.max_signal_age,
            "min_divergence_hits": req.min_divergence_hits,
            "order_by": req.order_by,
            "limit": req.limit,
            "divergence": {
                "macd_area_mode": req.divergence.macd_area_mode,
                "use_dif": req.divergence.use_dif,
                "use_macd_area": req.divergence.use_macd_area,
                "use_zero_axis": req.divergence.use_zero_axis,
                "divergence_logic": req.divergence.divergence_logic,
                "trend_overlap_mode": req.divergence.trend_overlap_mode,
                "zs_pullback_base": req.divergence.zs_pullback_base,
                "zs_pullback_min_ratio": req.divergence.zs_pullback_min_ratio,
                "bs_output_mode": req.divergence.bs_output_mode,
            },
        }

    # ---------- 异步任务 ----------
    def start_task(self, req: ScanRequest) -> str:
        """启动后台扫描, 返回 task_id。"""
        req = req.normalized()
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._tasks[task_id] = {
                "status": ScanTaskStatus(task_id=task_id, status="running"),
                "request": req,
            }

        def run() -> None:
            try:
                result = self.scan(req, progress=lambda done, total, sym: self._update_progress(task_id, done, total, sym))
                status = ScanTaskStatus(
                    task_id=task_id, status="done", progress=1.0,
                    processed=result.total_scanned, total=result.total_symbols, result=result,
                )
            except Exception as exc:
                logger.exception("scan task %s failed", task_id)
                mark_scan_done()
                status = ScanTaskStatus(task_id=task_id, status="error", error=str(exc))
            with self._lock:
                self._tasks[task_id]["status"] = status
            self._persist(task_id, status)

        threading.Thread(target=run, name=f"czsc-scan-{task_id}", daemon=True).start()
        return task_id

    def _update_progress(self, task_id: str, done: int, total: int, symbol: str | None = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            status = task["status"]
            status.processed = done
            status.total = total
            status.progress = done / total if total else 0.0
            if symbol:
                status.current_symbol = symbol

    def get_task(self, task_id: str) -> ScanTaskStatus | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return task["status"] if task else None

    def _persist(self, task_id: str, status: ScanTaskStatus) -> None:
        try:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            path = self._data_dir / f"{task_id}.json"
            path.write_text(status.model_dump_json(), encoding="utf-8")
        except Exception as exc:
            logger.warning("scan task persist failed: %s", exc)

    @staticmethod
    def should_use_async(req: ScanRequest, pool_size: int) -> bool:
        return not req.symbols and pool_size > ASYNC_SCAN_THRESHOLD


# 单例 (与 AnalyzeService 同范式)
_service: ScanService | None = None
_service_lock = threading.Lock()


def get_scan_service() -> ScanService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = ScanService()
    return _service


def set_scan_service(service: ScanService | None) -> None:
    """测试注入。"""
    global _service
    _service = service  # type: ignore[assignment]
