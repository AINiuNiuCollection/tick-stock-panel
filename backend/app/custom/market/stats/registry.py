"""注册表 — id 唯一性启动期校验, 模块元信息供 API/前端发现。"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import StatsModule

REGISTRY: dict[str, "StatsModule"] = {}


def register(module: "StatsModule | type[StatsModule]") -> "StatsModule | type[StatsModule]":
    """装饰类 → 注册为单例实例, 但返回原类 (保持被装饰名字绑定类本身)。"""
    cls_or_obj = module
    if isinstance(module, type):  # 也支持直接传实例
        module = module()
    mid = module.id
    if not mid:
        raise ValueError("StatsModule.id 不能为空")
    if mid in REGISTRY:
        raise ValueError(f"StatsModule id 冲突: {mid!r}")
    REGISTRY[mid] = module
    return cls_or_obj


def describe_modules() -> list[dict]:
    """导出注册表元信息 (id/label/参数 schema) — 供 GET /market/stats/modules。"""
    out: list[dict] = []
    for mod in REGISTRY.values():
        out.append(
            {
                "id": mod.id,
                "label": mod.label,
                "description": mod.description,
                "params": [
                    {
                        "name": p.name,
                        "label": p.label,
                        "type": p.type,
                        "default": p.default,
                        "options": list(p.options),
                        "min": p.min,
                        "max": p.max,
                        "description": p.description,
                    }
                    for p in mod.params
                ],
            }
        )
    return out
