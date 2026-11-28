"""信号统计注册表子包 — 新规律 = 新文件 + @register, 零前端改动扩展。

导入即注册: 这里显式 import 各模块文件, 注册表在首次 import 时填充。
"""
from .base import ParamSpec, Signal, StatsModule
from .registry import REGISTRY, register

# 首批 M1/M2/M3 (与回测信号同源, 见设计文档 §4.4/§8.2)
from . import ma_state  # noqa: F401
from . import crash_speed  # noqa: F401
from . import volume_price  # noqa: F401
from . import anomaly_wave  # noqa: F401

__all__ = ["REGISTRY", "ParamSpec", "Signal", "StatsModule", "register"]
