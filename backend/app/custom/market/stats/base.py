"""统计/信号模块协议 — 声明式参数 schema + to_signals 同源口径。

StatsModule 是研究 (统计表) 与执行 (回测信号) 的共同口径来源:
    - params: 声明式参数 schema, 前端据此自动渲染参数面板;
    - to_signals(): 把参数化的统计条件转成带方向的信号序列,
      统计页看到的规律与回测页买入的信号由同一函数产出, 杜绝口径漂移。

方向约定: +1 = 做多入场信号; -1 = 反向 (平仓/离场参照) 信号。
只做多 (设计 §8 裁定): 引擎只用 +1 开仓, -1 仅用于反向离场。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ParamSpec:
    """单个模块参数的声明 — 驱动前端自动渲染与启动期校验。"""

    name: str
    label: str
    type: str  # "int" | "float" | "select" | "bool"
    default: Any
    options: tuple[str, ...] = ()   # type=select 时必填
    min: float | None = None        # 数值型可选钳制
    max: float | None = None
    description: str = ""


@dataclass(frozen=True)
class Signal:
    """一条带方向的信号。dt 为信号成立的日K日期 (T 日收盘确认)。"""

    dt: date
    direction: int  # +1 做多 / -1 反向
    note: str = ""


class StatsModule:
    """模块基类 — 子类声明 id/label/params 并实现 to_signals。"""

    id: str = ""
    label: str = ""
    description: str = ""
    params: tuple[ParamSpec, ...] = ()

    def to_signals(self, df: pl.DataFrame, params: dict[str, Any]) -> list[Signal]:
        """df: 指数日K (date/open/high/low/close/volume/amount), 升序。"""
        raise NotImplementedError

    # ---- 参数辅助 -------------------------------------------------------
    def resolve_params(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        resolved = {p.name: p.default for p in self.params}
        for k, v in (overrides or {}).items():
            if k not in resolved:
                raise ValueError(f"unknown param {k!r} for module {self.id!r}")
            resolved[k] = v
        return resolved
