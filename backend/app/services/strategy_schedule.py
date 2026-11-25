"""策略每日定时筛选调度 — 用户为选入面板的策略设置执行时间。

设计:
    - 持久化: data_dir/user_data/strategy_schedules.json
      {strategy_id: {enabled, hour, minute, last_run: {date, total, error, at}}}
    - 调度: 复用全局 AsyncIOScheduler (daily_pipeline.start_scheduler 创建),
      CronTrigger mon-fri Asia/Shanghai, job id 前缀 strategy_schedule_
    - 执行: 复用 run_preset 同款链路 (engine.run + build_strategy_context),
      结果写入 strategy_cache (按 as_of 天存储 → 前端 cached-summary 秒加载
      路径自动生效, 结果天然按天展示)
    - 适用范围: 仅 timeframes 含 '1d' 的策略 (strategy_cache 是日线语义,
      分钟策略结果写入会污染页面秒加载路径 — 与 screener.py 注释口径一致)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.strategy.engine import release_strategy_run, try_acquire_strategy_run

logger = logging.getLogger(__name__)

_SCHEDULES_PATH = Path(settings.data_dir) / "user_data" / "strategy_schedules.json"
_JOB_PREFIX = "strategy_schedule_"

_lock = threading.Lock()
# lifespan 早期 main.py 调 set_app_state(app.state) 注入, 供 job 执行体访问
_app_state: Any = None


def set_app_state(state: Any) -> None:
    global _app_state
    _app_state = state


def _get_app_state() -> Any:
    return _app_state


# ---------- 持久化 ----------

def load_schedules() -> dict[str, dict[str, Any]]:
    """读取全部定时设置。返回 {strategy_id: {enabled, hour, minute, last_run}}。"""
    with _lock:
        try:
            if _SCHEDULES_PATH.exists():
                return json.loads(_SCHEDULES_PATH.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("strategy schedules read failed: %s", exc)
    return {}


def _save_schedules(schedules: dict[str, dict[str, Any]]) -> None:
    _SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULES_PATH.write_text(
        json.dumps(schedules, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_schedule(strategy_id: str) -> dict[str, Any] | None:
    with _lock:
        try:
            if _SCHEDULES_PATH.exists():
                data = json.loads(_SCHEDULES_PATH.read_text(encoding="utf-8"))
                return data.get(strategy_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("strategy schedule read failed: %s", exc)
    return None


def set_schedule(strategy_id: str, *, enabled: bool, hour: int, minute: int) -> dict[str, Any]:
    """保存定时设置 (不注册 job — 注册由调用方拿 scheduler 完成)。"""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("hour/minute out of range")
    entry = {"enabled": bool(enabled), "hour": int(hour), "minute": int(minute)}
    with _lock:
        schedules = _read_unlocked()
        prev = schedules.get(strategy_id) or {}
        entry["last_run"] = prev.get("last_run")
        schedules[strategy_id] = entry
        _save_schedules(schedules)
    return entry


def _read_unlocked() -> dict[str, dict[str, Any]]:
    if _SCHEDULES_PATH.exists():
        try:
            return json.loads(_SCHEDULES_PATH.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    return {}


def record_run(strategy_id: str, *, ok: bool, total: int | None = None, error: str | None = None) -> None:
    """job 执行后回写最近一次运行结果 (供 UI 展示)。"""
    with _lock:
        schedules = _read_unlocked()
        entry = schedules.get(strategy_id)
        if not entry:
            return
        entry["last_run"] = {
            "date": date.today().isoformat(),
            "ok": ok,
            "total": total,
            "error": error,
            "at": datetime.now().strftime("%H:%M"),
        }
        _save_schedules(schedules)


# ---------- 调度注册 ----------

def register_job(scheduler: Any, strategy_id: str, *, hour: int, minute: int) -> None:
    """注册/更新单个策略的定时 job (replace_existing, 改时间后重复注册只更新 trigger)。"""
    from apscheduler.triggers.cron import CronTrigger

    scheduler.add_job(
        run_scheduled_strategy,
        args=[strategy_id],
        trigger=CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute,
                            timezone="Asia/Shanghai"),
        id=_JOB_PREFIX + strategy_id,
        name=f"策略定时筛选 {strategy_id}",
        misfire_grace_time=3600,  # 盘后数据就绪窗口内允许补跑
        replace_existing=True,
    )


def remove_job(scheduler: Any, strategy_id: str) -> None:
    try:
        scheduler.remove_job(_JOB_PREFIX + strategy_id)
    except Exception:  # noqa: BLE001 — job 不存在时静默
        pass


def sync_job(scheduler: Any, strategy_id: str) -> None:
    """按当前持久化设置对齐 job 状态 (存在且 enabled → 注册, 否则移除)。"""
    entry = get_schedule(strategy_id)
    if entry and entry.get("enabled"):
        register_job(scheduler, strategy_id, hour=entry["hour"], minute=entry["minute"])
    else:
        remove_job(scheduler, strategy_id)


def restore_scheduled_jobs(scheduler: Any) -> int:
    """启动时恢复全部已启用的定时任务 (daily_pipeline.start_scheduler 调用)。"""
    n = 0
    for sid, entry in load_schedules().items():
        if entry.get("enabled"):
            try:
                register_job(scheduler, sid, hour=entry["hour"], minute=entry["minute"])
                n += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("restore strategy schedule %s failed: %s", sid, exc)
    if n:
        logger.info("restored %d strategy schedule jobs", n)
    return n


# ---------- 执行体 ----------

def run_scheduled_strategy(strategy_id: str) -> dict[str, Any]:
    """定时触发的单策略执行 — 复用 run_preset 同款链路并写入盘后缓存。

    并发互斥 (需求C, 2026-11-23): 同策略已在运行 (手动 run_preset / 批量
    run_all / 另一定时触发) 时跳过本次 — engine.run 维护进程级运行计数,
    这里原子检查并预登记, 避免 context 构建期间被手动运行插队。
    跳过不算失败, 不回写 last_run。
    单策略异常只回写 last_run.error, 不向外抛 (APScheduler 会记 job 失败)。
    """
    state = _get_app_state()
    if state is None:
        logger.warning("strategy schedule %s skipped: app state unavailable", strategy_id)
        return {"ok": False, "error": "app state unavailable"}
    engine = getattr(state, "strategy_engine", None)
    if not engine or not engine.has(strategy_id):
        record_run(strategy_id, ok=False, error="strategy not found")
        return {"ok": False, "error": "strategy not found"}
    if not try_acquire_strategy_run(strategy_id):
        logger.info("scheduled strategy %s skipped: already running", strategy_id)
        return {"ok": False, "skipped": True, "error": "already running"}
    try:
        repo = state.repo

        from app.api.screener import ScreenerService
        from app.services import strategy_cache
        # strategy_config 已迁至 app.strategy.config (app.services 不再导出)
        from app.strategy import config as strategy_config

        data_dir = repo.store.data_dir
        svc = ScreenerService(repo, asset_type="stock")
        as_of = svc.latest_date()
        if not as_of:
            record_run(strategy_id, ok=False, error="无可用数据日期")
            return {"ok": False, "error": "无可用数据日期"}

        overrides = strategy_config.load_override(data_dir, strategy_id)
        params = dict(overrides.get("params") or {})
        context = svc.build_strategy_context(
            engine, as_of, [strategy_id],
            timeframe="1d",
            params_map={strategy_id: params},
            overrides_map={strategy_id: overrides or {}},
        )
        result = engine.run(
            strategy_id, context, pool=None, params=params, overrides=overrides or None,
        )
        from dataclasses import asdict
        # 直接写缓存: _update_cache_strategy 只在缓存 as_of 已是当天时写入,
        # 定时任务先于 run_all 执行时结果会被丢弃; 这里无条件以本次结果为准
        # (定时跑出的更新数据优先, run_all 稍后到达时整体刷新)。
        cached = strategy_cache.read_cache(data_dir)
        results: dict[str, Any] = {}
        if cached and cached.get("as_of") == str(as_of):
            results = dict(cached.get("results") or {})
        results[strategy_id] = {
            "total": result.total,
            "as_of": str(as_of),
            "rows": asdict(result).get("rows", []),
        }
        strategy_cache.write_cache(data_dir, str(as_of), results)
        record_run(strategy_id, ok=True, total=result.total)
        logger.info("scheduled strategy %s done: as_of=%s total=%d", strategy_id, as_of, result.total)
        return {"ok": True, "as_of": str(as_of), "total": result.total}
    except Exception as exc:  # noqa: BLE001
        logger.warning("scheduled strategy %s failed: %s", strategy_id, exc, exc_info=True)
        record_run(strategy_id, ok=False, error=str(exc))
        return {"ok": False, "error": str(exc)}
    finally:
        release_strategy_run(strategy_id)
