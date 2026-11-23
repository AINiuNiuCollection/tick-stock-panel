"""背驰判定 — 缠师第 15/24/27/37 课口径。

两条件 AND (可配置关闭):
    1. MACD 面积: c 段面积 < a 段面积 (split/total_abs/dif_dea)
    2. DIF 极值: 上涨 c.max < a.max; 下跌 c.min > a.min
可选第 3 条件 (use_zero_axis, 默认关闭, 第24课):
    3. 0 轴回抽: a/c 两段之间 DIF 回拉触及 0 轴 (过滤零轴下弱势反弹的假背驰)
DEA 已废弃 (缠师原文未要求), 恒 None。
"""
from __future__ import annotations

from typing import Any

from .models import Bi, DtIndex, MacdPoint


def slice_macd_for_bi(bi: Bi, macd_out: list[MacdPoint], dt_index: DtIndex) -> list[MacdPoint]:
    """取笔本体 (sdt ~ edt, 即起点分型极值 bar 到终点分型极值 bar) 的 MACD 子序列。

    为什么不用 range_sdt/range_edt (fx_a.raw_bars[0] ~ fx_b.raw_bars[-1]):
        分型的 raw_bars 因 K 线包含处理会向前/向后链到**前一段走势**的 bar。
        实例 (汇川技术 30 分钟 2026-10-15 @48.52): 下跌笔 sdt=10-12 10:00,
        但起点顶分型的 raw_bars[0] 被包含链合并到 10-09 14:30 —— 那是 10-09
        48.85 低点之后反弹区的 bar, 其 DIF=-0.548 是 10-09 下跌腿的残留。
        用 range 切片会把这根 bar 卷进 c 段, DIF 峰值 -0.548 < A 段 -0.418,
        背驰被误判为不成立; 按笔本体切片 DIF 峰值 -0.376 > -0.418, 判据正确。
        相邻笔的 range 窗口还会互相重叠, 使盘整背驰 a/c 面积重复计数。
    """
    sdt_idx = dt_index.find(bi.sdt)
    edt_idx = dt_index.find(bi.edt)
    if sdt_idx is None or edt_idx is None or sdt_idx > edt_idx:
        return []
    return macd_out[sdt_idx : edt_idx + 1]


def calc_bi_macd_area(bi: Bi, macd_slice: list[MacdPoint], mode: str) -> float | None:
    """计算笔区间 MACD 面积。

    缠师第24课原文口径: "比较下方对应的绿柱子和黄白线围成的面积" --
    底背驰看绿柱、顶背驰看红柱, 面积的定义本身是**分方向**的。故 split 模式下
    下跌笔只取绿柱、上涨笔只取红柱; 若某段全程无同向柱 (典型: 零轴下方的反弹,
    上涨笔全程绿柱), 同向柱面积 = 0.0 是**真实测量值**, 不是数据缺失, 不得用
    反向柱的绝对值冒充 (否则等于拿空头力度去比较多头力度, 判定方向被颠倒)。

    None 只用于"数据本身无效": 空切片, 或全部柱值为 None (暖机未完成)。
    由 has_data 标志区分: True 且有值则正常返回 (含 0.0), False 才交给上层兜底。
    """
    if not macd_slice:
        return None
    total = 0.0
    has_data = False  # 至少有一根有效 MACD 柱值
    if mode == "dif_dea":
        for m in macd_slice:
            if m.dif is None or m.dea is None:
                continue
            total += abs(m.dif - m.dea)
            has_data = True
    elif mode == "total_abs":
        for m in macd_slice:
            if m.macd is None:
                continue
            total += abs(m.macd)
            has_data = True
    else:  # split
        for m in macd_slice:
            if m.macd is None:
                continue
            has_data = True
            if bi.direction == "down" and m.macd < 0:
                total += abs(m.macd)
            elif bi.direction == "up" and m.macd > 0:
                total += m.macd
    if not has_data:
        return None  # 数据缺失 -> 由上层 total_abs 兜底
    # 有有效柱但没有同向柱 -> 面积为 0, 是真实值, 不兜底
    return round(total, 6)


def calc_bi_peak(macd_slice: list[MacdPoint], field: str, direction: str) -> float | None:
    """笔区间内 DIF/DEA 极值: 上涨取 max, 下跌取 min。"""
    vals = [getattr(m, field) for m in macd_slice if getattr(m, field) is not None]
    if not vals:
        return None
    if direction == "up":
        return max(vals)
    if direction == "down":
        return min(vals)
    return None


def compute_macd_metrics(
    a_bi: Bi,
    c_bi: Bi,
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
    macd_area_mode: str,
) -> dict[str, Any]:
    a_slice = slice_macd_for_bi(a_bi, macd_out, dt_index)
    c_slice = slice_macd_for_bi(c_bi, macd_out, dt_index)
    return {
        "area_a": calc_bi_macd_area(a_bi, a_slice, macd_area_mode),
        "area_c": calc_bi_macd_area(c_bi, c_slice, macd_area_mode),
        "dif_a": calc_bi_peak(a_slice, "dif", a_bi.direction),
        "dif_c": calc_bi_peak(c_slice, "dif", c_bi.direction),
    }


def empty_divergence(label: str = "背驰") -> dict[str, Any]:
    return {
        "is_divergence": False,
        "macd_area_prev": None,
        "macd_area_cur": None,
        "dif_peak_prev": None,
        "dif_peak_cur": None,
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": [],
        "divergence_type": f"数据不足({label})",
    }


def zero_axis_pullback(
    a_bi: Bi,
    c_bi: Bi,
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
) -> bool | None:
    """第24课 0 轴回抽判定: a/c 两段之间黄白线(DIF)要回拉过 0 轴。

    底背驰(下跌): 回抽窗口内 DIF 峰值须 >= 0 (回拉到 0 轴上方);
    顶背驰(上涨): 回抽窗口内 DIF 谷值须 <= 0 (回拉到 0 轴下方)。

    回抽窗口 = a_bi.edt 之后到 c_bi.sdt 之前的 bar (即两段之间的中枢震荡区)。
    窗口为空 (a/c 相邻, 无中间段) 时退化为 a.sdt ~ c.edt 全窗口。
    返回 None 表示窗口内无有效 DIF 数据 (暖机未完成), 由调用方 fail-open。
    """
    if a_bi.direction not in ("up", "down"):
        return None
    a_end = dt_index.find(a_bi.edt)
    c_start = dt_index.find(c_bi.sdt)
    if a_end is None or c_start is None:
        return None
    lo, hi = a_end + 1, c_start - 1
    if lo > hi:  # 无中间段 -> 退化为全窗口
        a_start = dt_index.find(a_bi.sdt)
        c_end = dt_index.find(c_bi.edt)
        if a_start is None or c_end is None or a_start > c_end:
            return None
        lo, hi = a_start, c_end
    difs = [m.dif for m in macd_out[lo : hi + 1] if m.dif is not None]
    if not difs:
        return None
    if a_bi.direction == "down":
        return max(difs) >= 0
    return min(difs) <= 0


def check_trend_divergence(
    a_bi: Bi,
    c_bi: Bi,
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
    macd_area_mode: str,
    use_dif: bool,
    use_macd_area: bool,
    logic: str = "and",
    use_zero_axis: bool = False,
) -> dict[str, Any]:
    """趋势背驰判定 (B1/S1)。

    logic: "and"=面积与DIF同时满足(默认,严格); "or"=任一满足(第27课口径)。
    use_zero_axis: 开启后追加第24课 0 轴回抽条件 (a/c 之间 DIF 须回拉过 0 轴)。
    """
    if a_bi.direction != c_bi.direction or a_bi.direction == "unknown":
        return empty_divergence("趋势背驰")

    m = compute_macd_metrics(a_bi, c_bi, macd_out, dt_index, macd_area_mode)

    # 数据缺失兜底(与 check_consolidation_divergence 保持一致): 仅当柱值本身
    # 全为 None (暖机未完成 / 数据空洞) 时, calc_bi_macd_area 才返回 None,
    # 此处用 total_abs 重算。注意"有柱值但没有同向柱"(如上涨笔全程绿柱)现在
    # 返回 0.0, 是第24课分方向面积的真实测量值, 不触发兜底 — 早期版本把这种
    # 情形当"数据不足"用反向柱绝对值重算, 等于拿空头力度冒充多头力度,
    # 会把零轴下反弹的顶背驰压掉 (圣元环保 300867 S1@2026-06-05 案例)。
    area_mode_used = macd_area_mode
    if macd_area_mode == "split" and use_macd_area and (m["area_a"] is None or m["area_c"] is None):
        m_fallback = compute_macd_metrics(a_bi, c_bi, macd_out, dt_index, "total_abs")
        if m["area_a"] is None:
            m["area_a"] = m_fallback["area_a"]
        if m["area_c"] is None:
            m["area_c"] = m_fallback["area_c"]
        area_mode_used = f"{macd_area_mode}→total_abs(暖机兜底)"

    pass_list: list[str] = []

    if (
        use_macd_area
        and m["area_a"] is not None
        and m["area_c"] is not None
        and m["area_c"] < m["area_a"]
    ):
        pass_list.append("macd_area")

    if (
        use_dif
        and m["dif_a"] is not None
        and m["dif_c"] is not None
        and (
            (a_bi.direction == "up" and m["dif_c"] < m["dif_a"])
            or (a_bi.direction == "down" and m["dif_c"] > m["dif_a"])
        )
    ):
        pass_list.append("dif")

    # 第24课 0 轴回抽: True=通过计入; False=未回抽, 条件不通过;
    # None=回抽窗口无有效 DIF 数据, fail-open (缺数据不等于条件不通过)。
    z_state = zero_axis_pullback(a_bi, c_bi, macd_out, dt_index) if use_zero_axis else False
    if use_zero_axis and z_state is True:
        pass_list.append("zero_axis")

    enabled = [
        c
        for c, on in (
            ("macd_area", use_macd_area),
            ("dif", use_dif),
            ("zero_axis", use_zero_axis and z_state is not None),
        )
        if on
    ]
    # 第24课标准背驰要求两条件同时成立(and); 第27课"只要其中一个符合就可以是
    # 一个背弛的信号"对应 or。默认 and 保持严格口径, or 为可选宽松口径。
    is_div = (
        (len(pass_list) >= 1 and len(enabled) > 0)
        if logic == "or"
        else (len(pass_list) == len(enabled) and len(enabled) > 0)
    )

    return {
        "is_divergence": is_div,
        "macd_area_prev": m["area_a"],
        "macd_area_cur": m["area_c"],
        "dif_peak_prev": m["dif_a"],
        "dif_peak_cur": m["dif_c"],
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": pass_list,
        "divergence_logic": logic,
        "macd_area_mode_used": area_mode_used,
        "divergence_type": f"趋势背驰:{'+'.join(pass_list)}" if is_div else "未构成趋势背驰",
    }


def check_consolidation_divergence(
    a_bi: Bi,
    c_bi: Bi,
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
    macd_area_mode: str,
    use_dif: bool,
    use_macd_area: bool,
    logic: str = "and",
    use_zero_axis: bool = False,
) -> dict[str, Any]:
    """盘整背驰判定 (B2/S2/B3/S3)。

    logic: "and"=两条件同时满足(默认); "or"=任一满足(第27课口径)。

    数据缺失兜底: 仅当柱值本身全为 None 时 area 才是 None, 此时用
    total_abs 重算。"有柱值但无同向柱"面积为 0.0, 是分方向面积的真实值,
    不触发兜底 (与 check_trend_divergence 口径一致)。
    """
    if a_bi.direction != c_bi.direction or a_bi.direction == "unknown":
        return empty_divergence("盘整背驰")

    m = compute_macd_metrics(a_bi, c_bi, macd_out, dt_index, macd_area_mode)

    area_mode_used = macd_area_mode
    if macd_area_mode == "split" and use_macd_area and (m["area_a"] is None or m["area_c"] is None):
        m_fallback = compute_macd_metrics(a_bi, c_bi, macd_out, dt_index, "total_abs")
        if m["area_a"] is None:
            m["area_a"] = m_fallback["area_a"]
        if m["area_c"] is None:
            m["area_c"] = m_fallback["area_c"]
        area_mode_used = f"{macd_area_mode}→total_abs(暖机兜底)"

    pass_list: list[str] = []
    if (
        use_macd_area
        and m["area_a"] is not None
        and m["area_c"] is not None
        and m["area_c"] < m["area_a"]
    ):
        pass_list.append("macd_area")

    if (
        use_dif
        and m["dif_a"] is not None
        and m["dif_c"] is not None
        and (
            (a_bi.direction == "up" and m["dif_c"] < m["dif_a"])
            or (a_bi.direction == "down" and m["dif_c"] > m["dif_a"])
        )
    ):
        pass_list.append("dif")

    # 第24课 0 轴回抽 (与 check_trend_divergence 同口径):
    # True=通过计入; False=未回抽, 条件不通过; None=无有效 DIF 数据, fail-open。
    z_state = zero_axis_pullback(a_bi, c_bi, macd_out, dt_index) if use_zero_axis else False
    if use_zero_axis and z_state is True:
        pass_list.append("zero_axis")

    enabled = [
        c
        for c, on in (
            ("macd_area", use_macd_area),
            ("dif", use_dif),
            ("zero_axis", use_zero_axis and z_state is not None),
        )
        if on
    ]
    is_div = (
        (len(pass_list) >= 1 and len(enabled) > 0)
        if logic == "or"
        else (len(pass_list) == len(enabled) and len(enabled) > 0)
    )

    return {
        "is_divergence": is_div,
        "macd_area_prev": m["area_a"],
        "macd_area_cur": m["area_c"],
        "dif_peak_prev": m["dif_a"],
        "dif_peak_cur": m["dif_c"],
        "dea_peak_prev": None,
        "dea_peak_cur": None,
        "divergence_pass": pass_list,
        "divergence_logic": logic,
        "divergence_type": f"盘整背驰:{'+'.join(pass_list)}" if is_div else "未构成盘整背驰",
        "macd_area_mode_used": area_mode_used,
    }
