"""TdxProvider 配置模型与读取工具。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TdxConfig:
    """轻量 config shim, 让 custom loader 的 provider_has_dataset 能识别本 provider。"""

    name: str = "tdx"
    display_name: str = "通达信本地数据"
    datasets: dict = field(default_factory=lambda: {
        "daily": {}, "minute": {}, "adj_factor": {},
    })
    path: None = None
    builtin: bool = True


def get_plugin_config() -> dict:
    """从 preferences.json 读取 tdx 插件配置。

    返回 dict, 至少包含 vipdoc_dir 和 gbbq_path 两个 key。
    """
    from app.services import preferences
    cfg = preferences.get_plugin_config("tdx")
    if not cfg:
        cfg = {}
    cfg.setdefault("vipdoc_dir", "")
    cfg.setdefault("gbbq_path", "")
    return cfg


def get_vipdoc_dir() -> Path | None:
    """返回配置的 vipdoc 目录 Path, 未配置或不存在返回 None。"""
    cfg = get_plugin_config()
    vipdoc = cfg.get("vipdoc_dir", "").strip()
    if not vipdoc:
        return None
    p = Path(vipdoc)
    if not p.exists():
        return None
    return p


def get_gbbq_path(vipdoc_dir: Path | None = None) -> Path | None:
    """返回 gbbq 文件路径。

    优先使用用户显式配置的 gbbq_path;
    否则自动取 {vipdoc_dir}/../T0002/hq_cache/gbbq。
    """
    cfg = get_plugin_config()
    explicit = cfg.get("gbbq_path", "").strip()
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        return None
    if vipdoc_dir is None:
        return None
    # 自动推导: vipdoc_dir 的上级目录 / T0002 / hq_cache / gbbq
    auto_path = vipdoc_dir.parent / "T0002" / "hq_cache" "gbbq"
    # 修正: 上面拼接有误, 用正确路径
    auto_path = vipdoc_dir.parent / "T0002" / "hq_cache" / "gbbq"
    if auto_path.exists():
        return auto_path
    return None
