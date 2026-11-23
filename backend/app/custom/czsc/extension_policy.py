"""czsc 默认扩展实现 — 把现有严格算法接到公共扩展点上。

注册后, 其他二开模块可按 order 覆盖中枢构造或背驰判定; 未注册时
``AnalyzeService`` 仍直接使用本模块的严格实现, 行为与旧版一致。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.extensions.contracts import (
    BACKEND_EXTENSION_API_VERSION,
    CenterBuilder,
    DivergencePolicy,
)

from .domain.divergence import (
    check_consolidation_divergence,
    check_trend_divergence,
)
from .domain.zs import build_zs_strict


class StrictCenterBuilder(CenterBuilder):
    """当前严格版中枢构造 (第 18/20 课定理一/二/三)。"""

    api_version = BACKEND_EXTENSION_API_VERSION

    def build(self, bis: Sequence[Any], /, **options: Any) -> Sequence[Any]:
        return build_zs_strict(list(bis), **options)


class XianduanCenterBuilder(CenterBuilder):
    """线段级中枢 (第83课: 笔作最小构件稳定性差; R3/方案B)。

    笔 → 线段 (第65/67/71/77/78课特征序列法) → 线段级中枢 (第18/20课公式)。
    返回 domain.Zs 快照 (bis 为空元组), 字段与 identify_bs_points 全部读取点
    兼容 (zd/zg/gg/dd/sdt/edt/valid/direction)。

    注意: 笔级中枢的回抽最小进入深度阈值 (zs_pullback_*) 在线段级构造中
    不适用 —— build_level_zs 的延伸判定是"端点触及 [ZD,ZG] 即延伸",
    传入的 pullback options 被忽略。
    """

    api_version = BACKEND_EXTENSION_API_VERSION
    name = "xianduan"

    def build(self, bis: Sequence[Any], /, **options: Any) -> Sequence[Any]:
        from .domain.level_zs import build_level_zs
        from .domain.models import Zs
        from .domain.xianduan import build_xianduan

        segs = build_xianduan(list(bis))
        return [
            Zs(
                sdt=z.sdt,
                edt=z.edt,
                zd=z.zd,
                zg=z.zg,
                gg=z.gg,
                dd=z.dd,
                valid=z.valid,
                bis=(),
            )
            for z in build_level_zs(segs)
        ]


class StrictDivergencePolicy(DivergencePolicy):
    """当前严格版背驰判定 (默认 and 口径)。"""

    api_version = BACKEND_EXTENSION_API_VERSION

    def check_trend_divergence(
        self,
        a_bi: Any,
        c_bi: Any,
        macd_out: Sequence[Any],
        dt_index: Any,
        macd_area_mode: str,
        use_dif: bool,
        use_macd_area: bool,
        logic: str = "and",
    ) -> dict[str, Any]:
        return check_trend_divergence(
            a_bi,
            c_bi,
            list(macd_out),
            dt_index,
            macd_area_mode,
            use_dif,
            use_macd_area,
            logic,
        )

    def check_consolidation_divergence(
        self,
        a_bi: Any,
        c_bi: Any,
        macd_out: Sequence[Any],
        dt_index: Any,
        macd_area_mode: str,
        use_dif: bool,
        use_macd_area: bool,
        logic: str = "and",
    ) -> dict[str, Any]:
        return check_consolidation_divergence(
            a_bi,
            c_bi,
            list(macd_out),
            dt_index,
            macd_area_mode,
            use_dif,
            use_macd_area,
            logic,
        )
