"""czsc 缠论分析扩展 — 后端集成入口。

L2 二开模块: 通过 BackendExtensionRegistrar 注册路由, 不修改 main.py / routes.py。
loader 自动发现 app.custom 下的包/模块, 按 EXTENSION_ID 注册。

职责:
    1. 直接调用 czsc 库 (作为 [czsc] optional-dependency) 完成缠论分析
    2. 数据获取: 主工程 MarketDataProvider 优先, EastmoneyFetcher 兜底
    3. CPU 密集运算通过线程池 run_in_executor 隔离, 不阻塞事件循环
    4. czsc 未安装时返回 503 + 安装提示, 不影响主功能
    5. 契约版本头 X-Czsc-Api-Version: 1

不修改主工程核心路由/Layout/data_providers, 全部代码隔离在 app/custom/czsc/ 下。
"""
from __future__ import annotations

import logging

from app.extensions import (
    BACKEND_EXTENSION_API_VERSION,
    BackendExtensionRegistrar,
    ExtensionContext,
)

logger = logging.getLogger(__name__)

EXTENSION_ID = "tsp.czsc"
EXTENSION_API_VERSION = BACKEND_EXTENSION_API_VERSION


def setup(registrar: BackendExtensionRegistrar) -> None:
    """注册 czsc 路由。模块加载阶段不导入 czsc, 运行时按需 import。"""
    from .routes import build_router

    registrar.include_router(build_router())


def startup(context: ExtensionContext) -> None:
    """启动钩子 — 仅日志, 不做重活。czsc import 延迟到首次请求。"""
    from app.config import settings

    logger.info(
        "czsc extension startup, enabled=%s, eastmoney_fallback=%s",
        settings.czsc_enabled, settings.czsc_eastmoney_fallback,
    )
