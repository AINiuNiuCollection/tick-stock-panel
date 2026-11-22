"""线段级中枢 —— 缠师第17/18课"三个连续次级别走势类型重叠"。

分型-笔-线段-最小级别中枢-各级别中枢 (第72课懒人线路图):
    - 笔级中枢 (zs.py): 输入是笔, 是最小级别中枢的近似;
    - 线段级中枢 (本模块): 输入是线段(笔的上一级别走势类型),
      对应缠师"某级别中枢由至少三个连续次级别走势类型重叠"的严格构造。

公式完全复用第18/20课:
    [ZD, ZG] = [max(前三段低点), min(前三段高点)]
    GG = max(所有段高点), DD = min(所有段低点)
    延伸/离开判定同 zs.py 的方向性离开逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass

from .xianduan import Xianduan


@dataclass(frozen=True)
class LevelZs:
    """线段级中枢快照。"""

    sdt: object
    edt: object
    zd: float
    zg: float
    gg: float
    dd: float
    level: int
    segs: tuple[Xianduan, ...]
    valid: bool

    @property
    def direction(self) -> str:
        return self.segs[0].direction if self.segs else "unknown"


def _make(zds: list[Xianduan]) -> LevelZs | None:
    if len(zds) < 3:
        return None
    first3 = zds[:3]
    zd = max(s.low for s in first3)
    zg = min(s.high for s in first3)
    if zg <= zd:
        return None
    return LevelZs(
        sdt=first3[0].sdt,
        edt=zds[-1].edt,
        zd=zd,
        zg=zg,
        gg=max(s.high for s in zds),
        dd=min(s.low for s in zds),
        level=2,
        segs=tuple(zds),
        valid=True,
    )


def build_level_zs(segs: list[Xianduan]) -> list[LevelZs]:
    """从线段序列构造线段级中枢序列 (第18/20课公式)。

    算法与 zs.build_zs_strict 同构, 但输入单位是线段:
        1. 从 i 起取连续 3 段, [ZD,ZG]=[max(low),min(high)], 无重叠则 i+=1。
        2. 中枢方向 = 第一段方向。
        3. 第 4 段起方向性离开判定:
           - 同向段终点未越过同侧边界 -> 延伸; 越过则看下一回抽是否触及 [ZD,ZG]。
           - 反向段终点越过反向边界 -> 离开; 否则端点触及中枢 -> 延伸。
        4. 中枢结束后 i 跳到离开段处递归。
    """
    out: list[LevelZs] = []
    n = len(segs)
    i = 0
    while i + 2 < n:
        first3 = segs[i : i + 3]
        zd = max(s.low for s in first3)
        zg = min(s.high for s in first3)
        if zg <= zd:
            i += 1
            continue
        zs_dir = first3[0].direction
        if zs_dir == "unknown":
            i += 1
            continue
        grp = list(first3)
        j = i + 3
        while j < n:
            seg = segs[j]
            touch = (zd <= seg.low <= zg) or (zd <= seg.high <= zg)
            if zs_dir == "up":
                z_leave = seg.high > zg
                rev_leave = seg.low < zd
            else:
                z_leave = seg.low < zd
                rev_leave = seg.high > zg
            if seg.direction == zs_dir:
                if not z_leave:
                    grp.append(seg)
                    j += 1
                elif j + 1 < n:
                    nxt = segs[j + 1]
                    nxt_touch = (zd <= nxt.low <= zg) or (zd <= nxt.high <= zg)
                    if nxt_touch:
                        grp.append(seg)
                        grp.append(nxt)
                        j += 2
                        continue
                    break
                else:
                    break
            elif not rev_leave:
                if touch:
                    grp.append(seg)
                    j += 1
                else:
                    break
            else:
                break
        zs = _make(grp)
        if zs is not None and zs.valid:
            out.append(zs)
        i = j if j > i + 3 else i + 3
    return out
