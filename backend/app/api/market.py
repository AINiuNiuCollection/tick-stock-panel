"""大盘研究 API — 信号注册表 / 单参数组回测 / 参数网格寻优 / 政策事件库。

路由前缀: /api/market (设计文档 docs/index_tracker_design_2026-11-27.md §6.2)

端点:
  GET  /stats/modules   信号模块注册表 (id/label/参数 schema) — 前端自动渲染参数面板
  GET  /overview        总览仪表盘快照 (价格/均线/量能/缠论笔/日历, 设计 §1.1)
  POST /backtest        单参数组回测 (逐笔明细 + 资金曲线 + 信号序列, 供双K线联动)
  POST /optimize        入场×出场参数网格寻优 (train/validation 过拟合防护)
  GET  /events          政策事件库 (列表 + 效果统计 + direction×背景聚合, P3 §2.2)
  GET  /events/series   单事件迷你路径 (前5日→后60日归一化, P3 §2.3 检视/叠加层)

缠论多级别分析不在此包装 — P0-2 后 /api/czsc/analyze 已可直接分析
白名单指数 (IndexDailyKlineSource 挂链首位), 前端 Tab 2 直接调用。
K 线蜡烛数据同理复用既有 /api/kline/daily?asset_type=index|etf。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.custom.market import events as events_store
from app.custom.market.backtest import (
    BacktestResult,
    CostSpec,
    ExitSpec,
    run_backtest,
)
from app.custom.market.data import load_etf_daily, load_index_daily
from app.custom.market.bi_context import bi_directions_for, current_bi_direction
from app.custom.market.event_series import series_from_dfs
from app.custom.market.event_stats import aggregate, compute_events_stats
from app.custom.market.optimizer import optimize_grid
from app.custom.market.breadth import (
    compute_breadth as _compute_breadth,
    load_breadth as _load_breadth,
)
from app.custom.market.stats.registry import REGISTRY, describe_modules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

_WARMUP_DAYS = 550  # 信号暖机: MA250 / 量价 250 日分位等最长窗口的自然日冗余


class ExitSpecModel(BaseModel):
    mode: str = "time"
    hold_days: int = Field(default=5, ge=1, le=250)
    take_profit_pct: float = Field(default=5.0, ge=0.1, le=100.0)
    stop_loss_pct: float = Field(default=3.0, ge=0.1, le=50.0)


class CostSpecModel(BaseModel):
    commission_rate: float = Field(default=0.00025, ge=0.0, le=0.01)
    stamp_tax_rate: float = Field(default=0.0, ge=0.0, le=0.01)
    slippage_rate: float = Field(default=0.001, ge=0.0, le=0.05)


class BacktestRequest(BaseModel):
    index_symbol: str = "000001.SH"
    target_symbol: str = "510300.SH"
    module_id: str = "crash_speed"
    entry_params: dict = Field(default_factory=dict)
    exit: ExitSpecModel = Field(default_factory=ExitSpecModel)
    start: date | None = None   # 缺省=标的最早数据日
    end: date | None = None     # 缺省=最新数据日
    initial_capital: float = Field(default=100000.0, gt=0)
    position_ratio: float = Field(default=1.0, gt=0, le=1.0)
    cost: CostSpecModel = Field(default_factory=CostSpecModel)


class OptimizeRequest(BacktestRequest):
    entry_grid: dict = Field(default_factory=dict)   # {param: [values]}; 缺省用 entry_params 单值
    exit_grid: dict | None = None                    # 缺省用 optimizer 默认网格
    train_ratio: float = Field(default=0.7, gt=0.1, lt=0.95)
    sort_by: str = "validation"


def _load_pair(req: BacktestRequest):
    """加载指数/ETF 日K — 指数多取暖机段, 信号再按 start 裁剪。"""
    if req.module_id not in REGISTRY:
        raise HTTPException(400, f"未知的信号模块: {req.module_id}")
    index_df_probe = load_index_daily(req.index_symbol, date(1990, 12, 19), date(2100, 1, 1))
    if index_df_probe.is_empty():
        raise HTTPException(404, f"本地无指数 {req.index_symbol} 日K数据")
    target_df_probe = load_etf_daily(req.target_symbol, date(1990, 12, 19), date(2100, 1, 1))
    if target_df_probe.is_empty():
        raise HTTPException(404, f"本地无 ETF {req.target_symbol} 日K数据")

    start = req.start or target_df_probe["date"].min()
    end = req.end or target_df_probe["date"].max()
    index_df = load_index_daily(req.index_symbol, start - timedelta(days=_WARMUP_DAYS), end)
    target = load_etf_daily(req.target_symbol, start, end)
    if index_df.is_empty() or target.is_empty():
        raise HTTPException(404, f"指定日期区间 [{start}, {end}] 无可用数据")
    return index_df, target, start, end


def _clip_signals(module, index_df, entry_params, start):
    signals = module.to_signals(index_df, entry_params)
    return [s for s in signals if s.dt >= start]


def _bars(df) -> list[dict]:
    """OHLCV 序列化 — raw 分区深历史, 供前端双K线联动图 (enriched 分区仅近一年, 不可用)。"""
    keep = df.select(["date", "open", "high", "low", "close", "volume"]).to_dicts()
    return [
        {
            "date": r["date"].isoformat(),
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        }
        for r in keep
    ]


def _serialize(r: BacktestResult) -> dict:
    return {
        "trades": [
            {
                "entry_signal_dt": t.entry_signal_dt.isoformat(),
                "entry_dt": t.entry_dt.isoformat(),
                "entry_price": t.entry_price,
                "exit_dt": t.exit_dt.isoformat() if t.exit_dt else None,
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "shares": t.shares,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
            }
            for t in r.trades
        ],
        "metrics": {
            "n_trades": len(r.trades),
            "initial_capital": r.initial_capital,
            "final_equity": r.final_equity,
            "total_return_pct": round(r.total_return_pct, 2),
            "annual_return_pct": round(r.annual_return_pct, 2),
            "max_drawdown_pct": round(r.max_drawdown_pct, 2),
            "sharpe": None if r.sharpe in (float("inf"),) else round(r.sharpe, 3),
            "win_rate": round(r.win_rate, 2),
            "profit_loss_ratio": (
                None if r.profit_loss_ratio in (float("inf"),) else round(r.profit_loss_ratio, 3)
            ),
            "avg_hold_days": round(r.avg_hold_days, 1),
        },
        "equity_curve": [
            {"dt": d.isoformat(), "equity": e} for d, e in r.equity_curve
        ],
    }


@router.get("/stats/modules")
def list_stats_modules():
    """信号模块注册表 — 前端策略实验室的模块列表与参数面板由此驱动。"""
    return {"modules": describe_modules()}


@router.post("/backtest")
def backtest(req: BacktestRequest):
    """单参数组回测 — 返回逐笔明细 + 统计面板 + 资金曲线 + 信号序列。"""
    index_df, target, start, end = _load_pair(req)
    module = REGISTRY[req.module_id]
    signals = _clip_signals(module, index_df, req.entry_params, start)
    result = run_backtest(
        target,
        signals,
        ExitSpec(**req.exit.model_dump()),
        CostSpec(**req.cost.model_dump()),
        req.initial_capital,
        req.position_ratio,
    )
    return {
        "index_symbol": req.index_symbol,
        "target_symbol": req.target_symbol,
        "module_id": req.module_id,
        "entry_params": req.entry_params,
        "exit": req.exit.model_dump(),
        "cost": req.cost.model_dump(),  # 生效费用可溯源 (设计 §8.5 全可配)
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "signals": [
            {"dt": s.dt.isoformat(), "direction": s.direction, "note": s.note} for s in signals
        ],
        "buy_signals": [
            {"dt": s.dt.isoformat(), "note": s.note} for s in signals if s.direction > 0
        ],
        "target_bars": _bars(target),
        "index_bars": _bars(index_df.filter(pl.col("date") >= start)),
        **_serialize(result),
    }


@router.post("/optimize")
def optimize(req: OptimizeRequest):
    """参数网格寻优 — 全枚举 + train/validation 三段对照。"""
    index_df, target, start, end = _load_pair(req)
    entry_grid = req.entry_grid or {k: [v] for k, v in req.entry_params.items()}
    if not entry_grid:
        raise HTTPException(400, "entry_grid 与 entry_params 至少提供一个")
    entry_grid = {
        k: ([v] if not isinstance(v, (list, tuple)) else list(v)) for k, v in entry_grid.items()
    }
    try:
        res = optimize_grid(
            index_df,
            target,
            module_id=req.module_id,
            entry_grid=entry_grid,
            exit_grid=req.exit_grid,
            cost=CostSpec(**req.cost.model_dump()),
            initial_capital=req.initial_capital,
            position_ratio=req.position_ratio,
            train_ratio=req.train_ratio,
            sort_by=req.sort_by,
            signal_from=start,  # 暖机段信号不入场
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    res["window"] = {"start": start.isoformat(), "end": end.isoformat()}
    res["cost"] = req.cost.model_dump()
    return res


# ---------------------------------------------------------------------------
# 政策事件 (P3, 设计 §2): 统计只认 approved+major+有 source (is_countable 铁律)
# ---------------------------------------------------------------------------

_FULL_START = date(1990, 12, 19)  # 上证指数发布日
_FULL_END = date(2100, 1, 1)


def _data_root() -> Path:
    return Path(settings.data_dir)


@router.get("/events")
def list_events(
    index_symbol: str = "000001.SH",
    status: str | None = None,
    category: str | None = None,
    group_by: str = "ma20",
):
    """政策事件库 — 全量列表 (含 draft, 前端标灰) + 效果统计 + 聚合 + 固定日历。

    group_by: 聚合维度 "ma20" (默认, 20日线上/下) 或 "bi" (缠论日线笔方向, v2)。"""
    if group_by not in ("ma20", "bi"):
        raise HTTPException(400, f"未知聚合维度: {group_by} (可选 ma20 / bi)")
    root = _data_root()
    all_events = events_store.load_events(root)
    if status:
        all_events = [e for e in all_events if e.status == status]
    if category:
        all_events = [e for e in all_events if e.category == category]
    countable = [e for e in all_events if events_store.is_countable(e)]

    stats_by_id: dict = {}
    agg_rows: list[dict] = []
    kline = load_index_daily(index_symbol, _FULL_START, _FULL_END)
    if countable and not kline.is_empty():
        # 事件技术背景: 缠论日线笔方向 (v2, 设计 §2.2; czsc 缺席时优雅降级为 None)
        bi_dirs = bi_directions_for(countable, kline, index_symbol)
        sts = compute_events_stats(countable, kline, bi_dirs)
        stats_by_id = {s.event_id: s for s in sts}
        agg_rows = aggregate(countable, sts, group_by)

    return {
        "index_symbol": index_symbol,
        "group_by": group_by,
        # 全历史指数 OHLCV (raw 分区) — 事件 Tab 主图旗标定位
        "index_bars": _bars(kline) if not kline.is_empty() else [],
        "counts": {
            "total": len(all_events),
            "countable": len(countable),
            "draft": sum(1 for e in all_events if e.status == "draft"),
        },
        "events": [
            {
                **ev.to_dict(),
                "countable": events_store.is_countable(ev),
                "stats": stats_by_id[ev.id].to_dict() if ev.id in stats_by_id else None,
            }
            for ev in all_events
        ],
        "aggregate": agg_rows,
        "calendar": [c.to_dict() for c in events_store.load_fixed_calendar(root)],
    }


@router.get("/overview")
def market_overview(index_symbol: str = "000001.SH"):
    """Tab 0 总览仪表盘快照 (设计 §1.1) — 只呈现状态与统计事实, 零预测性文字。

    范围 (P4): 价格状态 / MA20 连续天数 / 量能水位 / 日线缠论笔方向 /
    未来 7 天固定日历 / 信号模块注册表。多级别缠论快照与宽度快照留后续。
    """
    kline = load_index_daily(index_symbol, _FULL_START, _FULL_END)
    if kline.is_empty():
        raise HTTPException(404, f"本地无指数 {index_symbol} 日K数据")
    as_of = kline["date"].max()
    closes = kline["close"]

    ma = {w: closes.tail(w).mean() for w in (20, 60, 250)}
    latest = closes[-1]
    prev = closes[-2] if kline.height >= 2 else None

    # MA20 上/下方连续天数 (从尾部回数)
    d = kline.with_columns(pl.col("close").rolling_mean(20).alias("ma20")).drop_nulls(
        subset=["ma20"]
    )
    streak_above = None
    if d.height:
        above = (d["close"] >= d["ma20"]).to_list()
        streak = 0
        for flag in reversed(above):
            if flag == above[-1]:
                streak += 1
            else:
                break
        streak_above = {"above": bool(above[-1]), "days": streak}

    # 量能水位: 近5日成交额均值在最近 250 个 5日均值样本中的分位
    amt = (
        kline.with_columns(pl.col("amount").rolling_mean(5).alias("amt5"))
        .drop_nulls(subset=["amt5"])
        ["amt5"]
    )
    volume = None
    if amt.len() >= 2:
        samples = amt.tail(250)
        last5 = samples[-1]
        pctile = float((samples < last5).sum()) / (samples.len() - 1)
        level = (
            "extreme_high" if pctile >= 0.9
            else "extreme_low" if pctile <= 0.1
            else "normal"
        )
        volume = {
            "last_5d_amount": round(float(last5), 2),
            "percentile_250": round(pctile, 4),
            "level": level,
        }

    # 未来 7 天固定政策日历
    today = date.today()
    horizon = today + timedelta(days=7)
    upcoming = [
        c.to_dict()
        for c in events_store.load_fixed_calendar(_data_root())
        if today <= c.date <= horizon
    ]

    # 近250日图表序列 (v3-④ 总览图表化): OHLC + MA20/60 + 5日均额 + 窗口内事件旗标
    win = kline.with_columns(
        pl.col("close").rolling_mean(20).alias("ma20"),
        pl.col("close").rolling_mean(60).alias("ma60"),
        pl.col("amount").rolling_mean(5).alias("amt5"),
    ).tail(250)
    win_dates = win["date"].to_list()
    win_start = win_dates[0]

    def _f(v) -> float | None:
        return None if v is None else round(float(v), 4)

    chart = {
        "dates": [d.isoformat() for d in win_dates],
        "ohlc": [
            [r["open"], r["close"], r["low"], r["high"]]
            for r in win.select(["open", "close", "low", "high"]).to_dicts()
        ],
        "ma20": [_f(v) for v in win["ma20"].to_list()],
        "ma60": [_f(v) for v in win["ma60"].to_list()],
        "amounts": [_f(v) for v in win["amount"].to_list()],
        "amt5": [_f(v) for v in win["amt5"].to_list()],
        "event_flags": [
            {"date": e.date.isoformat(), "title": e.title, "category": e.category}
            for e in events_store.load_events(_data_root())
            if events_store.is_countable(e) and e.date >= win_start
        ],
    }

    return {
        "index_symbol": index_symbol,
        "as_of": as_of.isoformat(),
        "price": {
            "close": float(latest),
            "prev_close": None if prev is None else float(prev),
            "pct_change_pct": (
                None if prev is None or prev == 0
                else round((latest - prev) / prev * 100, 2)
            ),
            "ma20_dev_pct": None if ma[20] is None else round((latest - ma[20]) / ma[20] * 100, 2),
            "ma60_dev_pct": None if ma[60] is None else round((latest - ma[60]) / ma[60] * 100, 2),
            "ma250_dev_pct": None if ma[250] is None else round((latest - ma[250]) / ma[250] * 100, 2),
        },
        "ma20_streak": streak_above,
        "volume": volume,
        "czsc": {
            "daily_bi_direction": current_bi_direction(kline, index_symbol, as_of),
        },
        "upcoming": upcoming,
        "modules": describe_modules(),
        "chart": chart,
    }


@router.get("/events/series")
def event_series(
    event_id: str,
    index_symbol: str = "000001.SH",
):
    """单事件迷你路径 — 前5日→后60日归一化 (基期=事件前收盘=100), 供抽屉/扇形图。"""
    ev = next(
        (e for e in events_store.load_events(_data_root()) if e.id == event_id), None
    )
    if ev is None:
        raise HTTPException(404, f"事件不存在: {event_id}")
    kline = load_index_daily(index_symbol, _FULL_START, _FULL_END)
    res = series_from_dfs(ev, kline, None)
    if res is None:
        raise HTTPException(404, f"事件 {event_id} 超出 {index_symbol} K 线数据范围")
    return {"event": ev.to_dict(), "index_symbol": index_symbol, **res}


# ---------------------------------------------------------------------------
# 市场结构 breadth (v3-⑤) — 全市场逐日宽度序列
# ---------------------------------------------------------------------------


def _breadth_rows(df: pl.DataFrame, limit: int) -> list[dict]:
    out = df.tail(limit).with_columns(
        pl.col("pct_above_ma20").round(4),
        pl.col("pct_new_high_60d").round(4),
        pl.col("amount_pctile_250").round(4),
    )
    return [
        {
            "date": r["date"].isoformat(),
            "pct_above_ma20": r["pct_above_ma20"],
            "pct_new_high_60d": r["pct_new_high_60d"],
            "total_amount": r["total_amount"],
            "amount_pctile_250": (
                None if r["amount_pctile_250"] is None or r["amount_pctile_250"] != r["amount_pctile_250"]
                else r["amount_pctile_250"]
            ),
            "amount_level": r["amount_level"],
            "sample_count": r["sample_count"],
        }
        for r in out.to_dicts()
    ]


@router.get("/breadth")
def market_breadth(limit: int = 250):
    """市场结构 — 逐日宽度序列 (近 limit 日, 默认 250)。

    数据来自 data/research/breadth_daily.parquet (指纹缓存);
    不存在或指纹过期 (enriched 分区有更新) 时返回 404, 前端提示重建。"""
    df = _load_breadth(_data_root())
    if df is None or df.is_empty():
        raise HTTPException(404, "宽度序列未计算或已过期 — 请先 POST /api/market/breadth/rebuild")
    if limit < 1 or limit > df.height:
        limit = df.height
    rows = _breadth_rows(df, limit)
    return {
        "as_of": rows[-1]["date"],
        "total_days": df.height,
        "rows": rows,
    }


@router.post("/breadth/rebuild")
def market_breadth_rebuild():
    """全量重算宽度序列 (扫 enriched 全历史, 分钟级耗时, 显式触发)。"""
    df = _compute_breadth(_data_root())
    return {"as_of": df["date"].max().isoformat(), "total_days": df.height}
