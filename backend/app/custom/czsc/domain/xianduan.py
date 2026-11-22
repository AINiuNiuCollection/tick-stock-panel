"""线段构造 —— 缠师第65/67/71/77/78 课特征序列分型法。

原文锚点:
    第72课懒人线路图: "分型-笔-线段-最小级别中枢-各级别中枢、走势类型"。
    第67课: 向上笔开始的线段 S1X1S2X2..., 特征序列 = 向下笔序列 X1X2...;
            向下笔开始的线段, 特征序列 = 向上笔序列 S1S2...。
            特征序列两元素无重合 = 缺口。特征序列做非包含处理 = 标准特征序列。
            向上线段特征序列只考察顶分型; 向下线段只考察底分型。
            第一种情况: 分型第1、2元素无缺口 -> 线段在分型极值处结束。
            第二种情况: 分型第1、2元素有缺口 -> 需后一特征序列出现(反向)分型确认。
    第65课: 线段至少三笔且前三笔必须重叠; 奇数笔; 方向交替;
            顶高于底; 线段必须被线段(反方向)破坏。
    第78课: 标准化后向上线段从最低到最高, 向下从最高到最低。

已知局限(诚实标注):
    - 第二种情况的后序列分型, 对"分界点两边包含处理"的差异(第78课)采用简化:
      第二种情况的后序列正常做包含处理, 不对分界点做特殊豁免。
    - 缺口"封闭"的严格判定在极少数强缺口场景可能与原文有细微差异。
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Bi


@dataclass(frozen=True)
class Xianduan:
    """线段快照 (第65/78课)。"""

    sdt: object  # datetime
    edt: object
    direction: str  # "up" / "down"
    high: float
    low: float
    bis: tuple[Bi, ...]
    start_idx: int  # 在 bi_list 中的起始下标
    end_idx: int  # 在 bi_list 中的结束下标(含)

    @property
    def valid(self) -> bool:
        return (
            len(self.bis) >= 3
            and len(self.bis) % 2 == 1
            and self.direction in ("up", "down")
            and self.high > self.low
        )


@dataclass(frozen=True)
class _Elem:
    """特征序列元素 = 一根与线段方向相反的笔的 [low, high]。"""

    low: float
    high: float
    bi_idx: int


def _bi_dir(bi: Bi) -> str:
    return bi.direction if bi.direction in ("up", "down") else "unknown"


def _has_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return not (a_high < b_low or b_high < a_low)


def _merge_containment(elems: list[_Elem], direction: str) -> list[_Elem]:
    """特征序列非包含处理 (第67课)。

    把每个元素当成一根 K 线, 按 K 线包含处理规则合并。
    特征序列元素方向 = 对应笔方向 = 与线段方向相反。
    direction 传特征序列元素的方向(向上笔序列=up, 向下笔序列=down)。
    向上时取高高/低高 [max low, max high]; 向下时取低低/低高 [min low, min high]。
    按第65课顺序原则向后传播 (while 而非 if)。
    """
    if not elems:
        return []
    out: list[_Elem] = [elems[0]]
    for e in elems[1:]:
        cur = out[-1]
        contained = (cur.low <= e.low and e.high <= cur.high) or (
            e.low <= cur.low and cur.high <= e.high
        )
        if contained:
            if direction == "up":
                new_low, new_high = max(cur.low, e.low), max(cur.high, e.high)
            else:
                new_low, new_high = min(cur.low, e.low), min(cur.high, e.high)
            out[-1] = _Elem(new_low, new_high, cur.bi_idx)
        else:
            out.append(e)
    return out


def _is_fractal(elems: list[_Elem], k: int, top: bool) -> bool:
    """标准特征序列在 k 处是否构成顶/底分型 (第67课, 参照 K 线分型)。

    顶分型: 中间元素 high 同时高于左右; 底分型: 中间元素 low 同时低于左右。
    """
    if k <= 0 or k >= len(elems) - 1:
        return False
    a, b, c = elems[k - 1], elems[k], elems[k + 1]
    if top:
        return b.high > a.high and b.high > c.high and b.low > a.low and b.low > c.low
    return b.low < a.low and b.low < c.low and b.high < a.high and b.high < c.high


def _gap_between(a: _Elem, b: _Elem) -> bool:
    """特征序列相邻两元素是否有缺口 (无重合)。"""
    return not _has_overlap(a.low, a.high, b.low, b.high)


def build_xianduan(bi_list: list[Bi]) -> list[Xianduan]:
    """从笔序列构造线段序列 —— 严格特征序列分型法。

    算法 (逐段推进):
        1. 以 bi_list[i] 起, 方向 dir = 该笔方向。
        2. 收集从 i 起所有与 dir 同向的笔作为特征序列元素(elems), 每个元素携带其笔下标。
           向上线段的特征序列 = 向下笔; 向下线段的特征序列 = 向上笔。
        3. 非包含处理 -> 标准特征序列。
        4. 向上线段考察顶分型, 向下线段考察底分型。
        5. 找到第一个分型(k):
           - 无缺口(第一种): 线段终点 = 分型元素对应笔的 edt, 结束。
           - 有缺口(第二种): 从分型极值笔起考察后一特征序列;
             若后出现反向分型, 确认结束; 否则本段延续, 继续收集后续元素。
        6. 线段结束下标 j: 取分型元素所在笔之前最后一根与 dir 同向笔(奇数笔约束)。
        7. i 推进到 j+1 (线段首尾相接)。

    边界: 未出现分型时, 余下笔整体成段(若>=3且奇数); 不足3笔不成段。
    """
    out: list[Xianduan] = []
    n = len(bi_list)
    i = 0
    while i < n:
        start_dir = _bi_dir(bi_list[i])
        if start_dir == "unknown":
            i += 1
            continue
        # 特征序列方向 = 与线段方向相反
        feat_dir = "down" if start_dir == "up" else "up"
        # 特征序列 = 从 i 起所有 feat_dir 方向的笔
        raw_elems: list[_Elem] = []
        for k in range(i, n):
            b = bi_list[k]
            if _bi_dir(b) == feat_dir:
                raw_elems.append(_Elem(b.low, b.high, k))
        if len(raw_elems) < 2:
            # 无足够特征元素, 余下不足成段
            break

        std = _merge_containment(raw_elems, feat_dir)
        top = start_dir == "up"  # 向上线段看顶分型
        end_elem_idx: int | None = None
        for k in range(1, len(std) - 1):
            if not _is_fractal(std, k, top):
                continue
            if k >= 1 and _gap_between(std[k - 1], std[k]):
                # 第二种情况: 从分型极值笔起, 考察后一特征序列反向分型
                if _confirm_second_case(bi_list, std[k].bi_idx, feat_dir):
                    end_elem_idx = k
                    break
                # 未确认, 本段延续, 继续找后续分型
                continue
            end_elem_idx = k  # 第一种情况
            break

        if end_elem_idx is not None:
            fbi = std[end_elem_idx].bi_idx
            # 线段终点笔: 分型元素对应笔之前最后一根与 start_dir 同向的笔
            j = fbi - 1
            while j > i and _bi_dir(bi_list[j]) != start_dir:
                j -= 1
        else:
            # 无分型: 取到最后一根与 start_dir 同向的笔
            j = n - 1
            while j > i and _bi_dir(bi_list[j]) != start_dir:
                j -= 1

        seg_bis = bi_list[i : j + 1]
        # 奇数笔约束: 若偶数笔, 去掉最后一根反向笔(线段须起止同向)
        if len(seg_bis) >= 2 and len(seg_bis) % 2 == 0:
            seg_bis = seg_bis[:-1]
            j -= 1
        if len(seg_bis) >= 3:
            lo = min(b.low for b in seg_bis)
            hi = max(b.high for b in seg_bis)
            seg = Xianduan(
                sdt=seg_bis[0].sdt, edt=seg_bis[-1].edt,
                direction=start_dir, high=hi, low=lo,
                bis=tuple(seg_bis), start_idx=i, end_idx=j,
            )
            if seg.valid:
                out.append(seg)
        i = j + 1 if j >= i else i + 1
    return out


def _confirm_second_case(bi_list: list[Bi], fractal_bi_idx: int, prev_feat_dir: str) -> bool:
    """第二种情况确认(第67课): 从分型极值笔起, 后一特征序列出现(反向)分型。

    prev_feat_dir 是旧线段的特征序列方向(与旧线段方向相反)。
    新线段方向 = prev_feat_dir(因为旧特征序列元素方向=新线段方向),
    新特征序列方向 = 与 prev_feat_dir 相反 = 旧线段方向。
    新特征序列只考察底/顶分型(按新线段方向), 不分第一二种情况, 有分型即可。
    """
    new_line_dir = prev_feat_dir
    new_feat_dir = "down" if new_line_dir == "up" else "up"
    elems: list[_Elem] = []
    for k in range(fractal_bi_idx, len(bi_list)):
        b = bi_list[k]
        if _bi_dir(b) == new_feat_dir:
            elems.append(_Elem(b.low, b.high, k))
    if len(elems) < 3:
        return False
    std = _merge_containment(elems, new_feat_dir)
    top = new_line_dir == "up"
    return any(_is_fractal(std, k, top) for k in range(1, len(std) - 1))
