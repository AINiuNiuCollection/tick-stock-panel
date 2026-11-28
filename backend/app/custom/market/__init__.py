"""大盘研究模块 — 上证指数信号/回测/寻优引擎。

设计文档: docs/index_tracker_design_2026-11-27.md
分层 (与缠论模块解耦, 只读 raw 分区):
    data.py     — raw 分区读取 (kline_index_daily / kline_etf_daily 深历史)
    stats/      — 信号注册表 (M1/M2/M3, 统计口径与回测口径同源)
    backtest.py — 回测引擎 (T+1 开盘成交 / 停牌顺延 / 一字板不追 / 费用滑点)
    optimizer.py — 参数网格寻优 (train 70% / validation 30% 过拟合防护)

扩展约定: app/custom/ 下包由扩展加载器扫描, 需声明 EXTENSION_ID。本模块的
HTTP 层按设计 §6.2 固定挂载于 app/api/market.py (main.py include_router),
不经 BackendExtensionRegistrar 动态注册 — setup 为空实现仅满足加载契约。
"""
from __future__ import annotations

from app.extensions import BACKEND_EXTENSION_API_VERSION, BackendExtensionRegistrar

EXTENSION_ID = "tsp.market"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    """无动态注册 — 路由固定于 app/api/market.py (设计 §6.2), 此处仅满足扩展加载契约。"""
