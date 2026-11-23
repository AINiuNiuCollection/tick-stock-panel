"""缠论一/二/三类买卖点识别 — 严格按缠师原文 (第 15/17/18/20/24/25/27/37 课)。

    B1: 下跌趋势 a+A+b+B+c, c 创新低且 c 段 MACD 面积 < a 段 → 趋势背驰。
    S1: 上涨趋势对称。
    B2: B1 后第一次回调低点不破 B1 低点 (第17课纯结构定义)。
        strict 模式附加: a/c 段盘整背驰 + 次级别一买确认(定律一)均为必要条件。
        structural 模式: 结构条件为唯一门槛, 盘整背驰与次级别验证转为置信度标注
        (divergence_type / sublevel_verified)。
    S2: S1 后第一次反弹高点不破 S1 高点, 模式语义同 B2 对称。
    B3: 向上离开中枢后回试低点 > ZG (第20课:只凭位置, 背驰非前提)。
    S3: 向下离开中枢后回抽高点 < ZD (第20课:只凭位置, 背驰非前提)。

    重构修订 (缠师原文核对):
        - 缺陷1: B1/S1 的趋势判据改用 trend_zs_chain (第17课: 趋势 = 同级别中枢
          依次上升/依次下降, 方向由中枢相对位置给出)。旧实现用 count_independent_zs
          按 `zs.direction`(= 构成中枢的第一笔方向) 过滤, 会把"首笔向上"的下跌中枢
          整体剔除, 真实下跌趋势被数成 0 个 —— 见 zs.trend_zs_chain 注释。
        - 缺陷2: B2/S2 的次级别验证结果必须参与决策 (第17课买卖点定律一)。
        - P1: B3/S3 去掉背驰前提 (第20课三买定理只有位置条件)。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from ..config import DivergenceConfig
from .divergence import (
    check_consolidation_divergence,
    check_trend_divergence,
    slice_macd_for_bi,
)
from .interval_nest import NestResult
from .models import Bi, BsPoint, DtIndex, MacdPoint, Zs
from .zs import find_bi_overlap_zs, recent_trend_chain

logger = logging.getLogger(__name__)

SublevelVerifier = Callable[[datetime], bool | None]
# 区间套下钻回调: (dt, bs_type, direction) -> NestResult | None
NestVerifier = Callable[[str, str, str], NestResult | None]


def _probe_by_sublevel(verifier: SublevelVerifier | None, dt: datetime | str) -> bool | None:
    """探测定律一(第17课)的次级别验证结果 — 三态。

        True  = 次级别有数据且结构通过 (次级别一买/一卖确认);
        False = 次级别有数据但结构不通过;
        None  = 未验证 (无 verifier / 无更低级别 / 取数失败等数据不可得)。

    旧实现把异常 fail-closed 为 False; 结构化输出改造后, "数据不可得 ≠ 次级别
    结构不通过", 未验证不构成拒绝理由, 转为标注 (R1 边界加固)。
    """
    if verifier is None:
        return None
    try:
        state = verifier(dt)  # type: ignore[arg-type]
    except Exception as exc:
        logger.debug("sublevel verification failed at %s: %s", dt, exc)
        return None
    return True if state is True else (False if state is False else None)


def _accept_by_sublevel(state: bool | None, output_mode: str) -> bool:
    """strict 模式下次级别验证是否接受——False 一律拒绝(改动前行为保留)。

    strict: 只有 False 拒绝 (fail-closed); None/True 放行。
    structural: 次级别验证不再拦截 (仅作为 sublevel_verified 标注)。
    """
    if output_mode != "strict":
        return True
    return state is not False


def _third_point_div(
    a_bi: Bi | None,
    leave_bi: Bi,
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
    mode: str,
    use_dif: bool,
    use_macd_area: bool,
    logic: str = "and",
    label: str = "三买",
    divergence_fn: Callable[..., dict[str, Any]] = check_consolidation_divergence,
) -> dict[str, Any]:
    """三类买卖点的背驰【附加信息】——不参与成立判定。

    第20课三买/三卖定理只要求位置(回试不破ZG/回抽不过ZD)。背驰仅用于向用户
    展示力度, 故无论是否背驰,有无 a 段参照,都返回结构完整的 dict 供
    _make_bs_point 使用。label 由调用方传入("三买"/"三卖"),避免 S3 被误标为三买。
    """
    if a_bi is None:
        return {
            "macd_area_prev": None, "macd_area_cur": None,
            "dif_peak_prev": None, "dif_peak_cur": None,
            "dea_peak_prev": None, "dea_peak_cur": None,
            "divergence_pass": [], "divergence_type": f"{label}(位置成立,无进入段参照)",
        }
    div = divergence_fn(
        a_bi, leave_bi, macd_out, dt_index, mode, use_dif, use_macd_area, logic
    )
    # 语义标注:三类点的背驰只是附加力度信息,不是成立条件
    div["divergence_type"] = (
        f"{label}(位置成立;{div['divergence_type']})" if div.get("is_divergence")
        else f"{label}(位置成立;无背驰)"
    )
    return div


def _make_bs_point(
    bi: Bi,
    bs_type: str,
    direction: str,
    zs_index: int,
    div: dict[str, Any],
    macd_area_mode: str,
    definition_mode: str = "n/a",
    sublevel_verified: bool | None = None,
) -> BsPoint:
    """构造买卖点。definition_mode 标注判定口径 (strict/practical/n/a),
    避免把工程近似(practical 的 [ZD,ZG] 重叠)冒充缠师原文严格口径([DD,GG])。
    """
    return BsPoint(
        dt=str(bi.edt),
        type=bs_type,
        direction=direction,
        price=bi.end_price,
        bi_direction=bi.raw_direction,
        zs_index=zs_index,
        definition_mode=definition_mode,
        macd_area_prev=div["macd_area_prev"],
        macd_area_cur=div["macd_area_cur"],
        dif_peak_prev=div["dif_peak_prev"],
        dif_peak_cur=div["dif_peak_cur"],
        dea_peak_prev=div["dea_peak_prev"],
        dea_peak_cur=div["dea_peak_cur"],
        divergence_type=div["divergence_type"],
        divergence_pass=div["divergence_pass"],
        macd_area_mode=macd_area_mode,
        sublevel_verified=sublevel_verified,
    )


def identify_bs_points(
    bi_list: list[Bi],
    zs_list: list[Zs],
    macd_out: list[MacdPoint],
    dt_index: DtIndex,
    divergence: DivergenceConfig,
    sublevel_verifier: SublevelVerifier | None = None,
    nest_verifier: NestVerifier | None = None,
    trend_divergence: Callable[..., dict[str, Any]] | None = None,
    consolidation_divergence: Callable[..., dict[str, Any]] | None = None,
) -> list[BsPoint]:
    if not bi_list or len(bi_list) < 3:
        return []

    trend_div = trend_divergence or check_trend_divergence
    cons_div = consolidation_divergence or check_consolidation_divergence

    mode = divergence.macd_area_mode
    use_dif = divergence.use_dif
    use_macd_area = divergence.use_macd_area
    logic = divergence.divergence_logic
    overlap_mode = divergence.trend_overlap_mode
    # B2/S2 输出模式 (R1/方案A): strict=旧口径(背驰+次级别均为必要条件);
    # structural=第17课纯结构定义, 背驰与次级别验证降为置信度标注。
    output_mode = divergence.bs_output_mode
    n = len(bi_list)

    zs_filtered: list[tuple[int, Zs]] = [
        (zi, zs) for zi, zs in enumerate(zs_list) if not divergence.only_valid_zs or zs.valid
    ]

    def _bi_before(sdt: datetime, direction: str, cur_idx: int) -> Bi | None:
        """sdt 之前(含)的最后一个 direction 笔 —— 即第24课的 A 段。

        A 段是"进入趋势第一个中枢的那一段", 它的终点就在链头中枢的起点处。
        笔按时间有序, 从 cur_idx-1 往回走, 第一根 edt<=sdt 且方向相符的笔
        就是最近的一根。找不到(链头即序列起点)时由调用方退而取链头中枢
        的最后一根同向笔。
        """
        for j in range(cur_idx - 1, -1, -1):
            cand = bi_list[j]
            if cand.edt > sdt:
                continue
            if cand.direction == direction:
                return cand
        return None

    def _has_macd_area(bi: Bi) -> bool:
        sl = slice_macd_for_bi(bi, macd_out, dt_index)
        if not sl:
            return False
        for m in sl:
            if m.macd is None:
                continue
            if bi.direction == "down" and m.macd < 0:
                return True
            if bi.direction == "up" and m.macd > 0:
                return True
        return False

    bs_points: list[BsPoint] = []
    b1_bi_idx: int | None = None
    s1_bi_idx: int | None = None
    b1_candidates: list[tuple[Bi, int, dict[str, Any]]] = []
    s1_candidates: list[tuple[Bi, int, dict[str, Any]]] = []

    # ===== B1/S1 — 趋势背驰 =====
    for i in range(n - 1, 1, -1):
        bi = bi_list[i]
        if bi.direction != "down":
            continue
        # 第17课: 趋势 = 同级别中枢**依次上升/依次下降**; 第24课: A 段之前一定是
        # 和 B 同级别或更大级别的一个中枢。故先定趋势链(不依赖 a 段圈范围),
        # 再由链头反推 A 段。旧流程"先选 a 段、再在 [a.sdt, c.edt] 里数中枢":
        #   1) a 段启发式("往回找更浅的同向笔")会取到趋势内部 —— 汇川 30 分钟
        #      2026-10-15 @48.52 处 a 被取到 09-02(DIF -0.162), 而 c 的 DIF 是
        #      -0.376, 正确的 A(07-28, DIF -0.399) 才能让 DIF 判"力度衰竭";
        #   2) a 取晚了还会把链截断 —— ZS10 因此落在范围外, 三中枢下跌趋势被
        #      数成 1 个, B1 整体漏报。
        zs_completed = [(zi, z) for zi, z in zs_filtered if z.edt <= bi.sdt]
        chain = recent_trend_chain(zs_completed, "down", overlap_mode, bi.sdt)
        if len(chain) < 2:
            continue
        # A 段 = 趋势链第一中枢之前的最后一个同向段(链头即序列起点时, 退而取
        # 第一根中枢笔, 笔级近似下无法更早)
        prev_bi = _bi_before(chain[0].sdt, "down", i)
        if prev_bi is None:
            prev_bi = _bi_before(chain[0].edt, "down", i)
        if prev_bi is None:
            continue
        if bi.low >= prev_bi.low:
            continue
        if mode == "split" and not _has_macd_area(prev_bi):
            k = bi_list.index(prev_bi) - 2
            while k >= 0:
                cand = bi_list[k]
                if cand.direction == "down" and _has_macd_area(cand):
                    prev_bi = cand
                    break
                k -= 2
        # 一买位置条件: c 段必须跌出趋势的最后一个中枢 (c.low < 最后中枢 ZD)
        last_zs = chain[-1]
        if bi.low >= last_zs.zd:
            continue
        zs_idx = find_bi_overlap_zs(prev_bi, zs_filtered)
        div = trend_div(prev_bi, bi, macd_out, dt_index, mode, use_dif, use_macd_area, logic)
        if div["is_divergence"]:
            b1_candidates.append((bi, zs_idx, div))

    # 一买是趋势背驰点 = 趋势的**最低点**。同一趋势里, 底部构筑期的多根同向笔
    # 都可能通过三条件(如汇川 10-15 @48.52 与 10-23 @48.99), 旧实现"从后往前
    # 命中即 break"会取到更晚的更高低点, 把真底顶掉 —— 这正是此前记录过的
    # "缺陷B"。故收集全部候选取 low 最低者。
    if b1_candidates:
        bi, zs_idx, div = min(b1_candidates, key=lambda t: t[0].low)
        b1_bi_idx = bi_list.index(bi)
        bs_points.append(_make_bs_point(bi, "B1", "买", zs_idx, div, mode, overlap_mode))

    for i in range(n - 1, 1, -1):
        bi = bi_list[i]
        if bi.direction != "up":
            continue
        # 缠师第17课: 上涨趋势 = 同级别中枢依次上升 (见 B1 分支注释)。
        zs_completed = [(zi, z) for zi, z in zs_filtered if z.edt <= bi.sdt]
        chain = recent_trend_chain(zs_completed, "up", overlap_mode, bi.sdt)
        if len(chain) < 2:
            continue
        prev_bi = _bi_before(chain[0].sdt, "up", i)
        if prev_bi is None:
            prev_bi = _bi_before(chain[0].edt, "up", i)
        if prev_bi is None:
            continue
        if bi.high <= prev_bi.high:
            continue
        if mode == "split" and not _has_macd_area(prev_bi):
            k = bi_list.index(prev_bi) - 2
            while k >= 0:
                cand = bi_list[k]
                if cand.direction == "up" and _has_macd_area(cand):
                    prev_bi = cand
                    break
                k -= 2
        # 一卖位置条件: c 段必须涨出趋势的最后一个中枢 (c.high > 最后中枢 ZG)
        last_zs = chain[-1]
        if bi.high <= last_zs.zg:
            continue
        zs_idx = find_bi_overlap_zs(prev_bi, zs_filtered)
        div = trend_div(prev_bi, bi, macd_out, dt_index, mode, use_dif, use_macd_area, logic)
        if div["is_divergence"]:
            s1_candidates.append((bi, zs_idx, div))

    # 一卖对称: 取 high 最高者 (见 B1 候选收集的注释)
    if s1_candidates:
        bi, zs_idx, div = max(s1_candidates, key=lambda t: t[0].high)
        s1_bi_idx = bi_list.index(bi)
        bs_points.append(_make_bs_point(bi, "S1", "卖", zs_idx, div, mode, overlap_mode))

    # ===== B2/S2 — 盘整背驰 =====
    if b1_bi_idx is not None and b1_bi_idx + 2 < n:
        b1_bi = bi_list[b1_bi_idx]
        anchor = bi_list[b1_bi_idx - 2] if b1_bi_idx >= 2 else b1_bi
        zs_idx_b1 = find_bi_overlap_zs(anchor, zs_filtered)
        rebound_up = bi_list[b1_bi_idx + 1] if bi_list[b1_bi_idx + 1].direction == "up" else None
        fallback_down = (
            bi_list[b1_bi_idx + 2]
            if rebound_up is not None and bi_list[b1_bi_idx + 2].direction == "down"
            else None
        )
        a_bi_b2 = (
            bi_list[b1_bi_idx - 2]
            if b1_bi_idx - 2 >= 0 and bi_list[b1_bi_idx - 2].direction == "down"
            else None
        )
        if (
            rebound_up is not None
            and fallback_down is not None
            and fallback_down.low > b1_bi.low
        ):
            if output_mode == "strict" and a_bi_b2 is None:
                pass  # strict 模式需 a 段做盘整背驰比较, 无参照则不成立
            else:
                div = (
                    cons_div(
                        a_bi_b2, fallback_down, macd_out, dt_index, mode, use_dif, use_macd_area, logic
                    )
                    if a_bi_b2 is not None
                    else {
                        "macd_area_prev": None, "macd_area_cur": None,
                        "dif_peak_prev": None, "dif_peak_cur": None,
                        "dea_peak_prev": None, "dea_peak_cur": None,
                        "is_divergence": False, "divergence_pass": [],
                        "divergence_type": "B2(结构定义;无进入段参照)",
                    }
                )
                sub_state = _probe_by_sublevel(sublevel_verifier, fallback_down.edt)
                if (
                    (output_mode == "strict" and div["is_divergence"])
                    or output_mode != "strict"
                ) and _accept_by_sublevel(sub_state, output_mode):
                    if output_mode != "strict" and not div["is_divergence"]:
                        div = {**div, "divergence_type": "B2(结构定义;无盘整背驰)"}
                    bs_points.append(
                        _make_bs_point(
                            fallback_down, "B2", "买", zs_idx_b1, div, mode, overlap_mode,
                            sublevel_verified=sub_state,
                        )
                    )

    if s1_bi_idx is not None and s1_bi_idx + 2 < n:
        s1_bi = bi_list[s1_bi_idx]
        anchor = bi_list[s1_bi_idx - 2] if s1_bi_idx >= 2 else s1_bi
        zs_idx_s1 = find_bi_overlap_zs(anchor, zs_filtered)
        fallback_down = (
            bi_list[s1_bi_idx + 1] if bi_list[s1_bi_idx + 1].direction == "down" else None
        )
        rebound_up = (
            bi_list[s1_bi_idx + 2]
            if fallback_down is not None and bi_list[s1_bi_idx + 2].direction == "up"
            else None
        )
        a_bi_s2 = (
            bi_list[s1_bi_idx - 2]
            if s1_bi_idx - 2 >= 0 and bi_list[s1_bi_idx - 2].direction == "up"
            else None
        )
        if (
            fallback_down is not None
            and rebound_up is not None
            and rebound_up.high < s1_bi.high
        ):
            if output_mode == "strict" and a_bi_s2 is None:
                pass  # strict 模式需 a 段做盘整背驰比较, 无参照则不成立
            else:
                div = (
                    cons_div(
                        a_bi_s2, rebound_up, macd_out, dt_index, mode, use_dif, use_macd_area, logic
                    )
                    if a_bi_s2 is not None
                    else {
                        "macd_area_prev": None, "macd_area_cur": None,
                        "dif_peak_prev": None, "dif_peak_cur": None,
                        "dea_peak_prev": None, "dea_peak_cur": None,
                        "is_divergence": False, "divergence_pass": [],
                        "divergence_type": "S2(结构定义;无进入段参照)",
                    }
                )
                sub_state = _probe_by_sublevel(sublevel_verifier, rebound_up.edt)
                if (
                    (output_mode == "strict" and div["is_divergence"])
                    or output_mode != "strict"
                ) and _accept_by_sublevel(sub_state, output_mode):
                    if output_mode != "strict" and not div["is_divergence"]:
                        div = {**div, "divergence_type": "S2(结构定义;无盘整背驰)"}
                    bs_points.append(
                        _make_bs_point(
                            rebound_up, "S2", "卖", zs_idx_s1, div, mode, overlap_mode,
                            sublevel_verified=sub_state,
                        )
                    )

    # ===== B3/S3 — 盘整背驰 =====
    for zi, zs in zs_filtered:
        zg = zs.zg
        zd = zs.zd
        last_zs_bi_idx = -1
        for k, bi in enumerate(bi_list):
            if bi.edt == zs.edt:
                last_zs_bi_idx = k
                break
        if last_zs_bi_idx < 0 or last_zs_bi_idx + 2 >= n:
            continue
        leave_bi = bi_list[last_zs_bi_idx + 1]
        back_bi = bi_list[last_zs_bi_idx + 2]
        leave_dir = leave_bi.direction
        back_dir = back_bi.direction
        if leave_dir == "unknown" or back_dir == "unknown" or leave_dir == back_dir:
            continue

        a_bi_b3: Bi | None = None
        for k in range(last_zs_bi_idx, -1, -1):
            cand = bi_list[k]
            if cand.direction == leave_dir and cand.edt <= zs.sdt:
                a_bi_b3 = cand
                break

        # 缠师第20课 third-buy 定理原文:"一个次级别走势类型向上离开缠中说禅走势中枢,
        # 然后以一个次级别走势类型回试, 其低点【不跌破】ZG, 则构成第三类买点;
        # 向下离开...回抽, 其高点【不升破】ZD, 则构成第三类卖点。"
        # "不跌破/不升破" = 允许恰好触及(>=/<=), 非严格大于/小于。
        # 成立条件【只有位置】, 背驰是可选强度信息; "必须是第一次"由构造保证
        # (离开/回试取中枢结束后的第一个次级移动对, 中枢延伸期间产生的
        # 回拉已按中心定理一并入延伸)。
        # 笔级近似: 原文的"次级别走势类型"在线段/走势层面, 本引擎以笔近似,
        # 为缠论工程实现的通行口径 (与 czsc 库一致)。
        if leave_dir == "up" and leave_bi.high > zg and back_dir == "down" and back_bi.low >= zg:
            div = _third_point_div(
                a_bi_b3, leave_bi, macd_out, dt_index, mode, use_dif, use_macd_area, logic,
                divergence_fn=cons_div,
            )
            bs_points.append(_make_bs_point(back_bi, "B3", "买", zi, div, mode))

        if leave_dir == "down" and leave_bi.low < zd and back_dir == "up" and back_bi.high <= zd:
            div = _third_point_div(
                a_bi_b3, leave_bi, macd_out, dt_index, mode, use_dif, use_macd_area, logic,
                label="三卖", divergence_fn=cons_div,
            )
            bs_points.append(_make_bs_point(back_bi, "S3", "卖", zi, div, mode))

    seen: set[tuple[str, str]] = set()
    deduped: list[BsPoint] = []
    for bp in bs_points:
        key = (bp.dt, bp.type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(bp)
    deduped.sort(key=lambda x: (x.dt, x.type))

    # 区间套下钻 (缠师第27课): 对每个买卖点标注次级别背驰确认信息。
    # 无 nest_verifier / 次级别数据不可用时保持 None, 不影响主信号。
    if nest_verifier is not None:
        annotated: list[BsPoint] = []
        for bp in deduped:
            direction = "down" if bp.direction == "买" else "up"
            try:
                nr = nest_verifier(bp.dt, bp.type, direction)
            except Exception as exc:
                logger.debug("nest verify failed at %s %s: %s", bp.dt, bp.type, exc)
                nr = None
            if nr is None:
                annotated.append(bp)
                continue
            annotated.append(
                replace(
                    bp,
                    level="日线+次级别",
                    nest_confirmed=nr.confirmed,
                    nest_level=nr.level,
                    nest_ratio=nr.sub_ratio,
                    nest_note=nr.note,
                )
            )
        return annotated
    return deduped
