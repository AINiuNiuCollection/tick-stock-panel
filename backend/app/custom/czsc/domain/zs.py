"""中枢构造 — 严格按缠师第 18/20 课定理一/二/三。

与 czsc 库 `get_zs_seq` 的差异:
    - 库的延伸判定较宽松 (笔端点回到中枢即算延伸), 导致中枢被无限拉长。
    - 本实现用"离开—回抽确认"做硬切断 (定理三), 这是本级别唯一的终止条件;
      不用时间、不用段数、也不用简单重叠去切中枢。
"""
from __future__ import annotations

from .models import Bi, Zs


def make_zs(bis: list[Bi]) -> Zs | None:
    """用 [ZD, ZG] = [max(前三笔低点), min(前三笔高点)] 构造中枢。"""
    if len(bis) < 3:
        return None
    first3 = bis[:3]
    zd = max(b.low for b in first3)
    zg = min(b.high for b in first3)
    if zg <= zd:
        return None
    return Zs(
        sdt=bis[0].sdt,
        edt=bis[-1].edt,
        zd=zd,
        zg=zg,
        gg=max(b.high for b in bis),
        dd=min(b.low for b in bis),
        valid=len(bis) >= 3 and zg > zd,
        bis=tuple(bis),
    )


def build_zs_strict(
    bi_list: list[Bi],
    min_pullback_depth: float = 0.0,
    min_pullback_ratio: float = 0.02,
    pullback_base: str = "zg",
) -> list[Zs]:
    """从笔序列构造中枢序列 — 严格按第 18/20 课的中枢延伸与终止规则。

    原文依据:
        定理一(延伸): "走势中枢的延伸等价于任意区间[dn,gn]与[ZD,ZG]有重叠。
                       换言之, 若有Zn, 使得dn>ZG 或 gn<ZD, 则必然产生高级别的
                       走势中枢或趋势及延续。"
        定理二(维持): 盘整中"离开—回抽"的走势必须是次级别或以下级别的走势类型,
                       即离开后重新回到 [ZD,ZG] 内 → 中枢未被破坏, 继续延伸。
        定理三(破坏): "某级别缠中说禅走势中枢的破坏, 当且仅当一个次级别走势离开
                       该中枢后, 其后的次级别回抽走势不重新回到该中枢内。"
        第20课: "盘整结束的标志就是第三类买卖点"; 两个同级别中枢的波动区间重叠
                 → 形成更大级别中枢 (级别延续定理二)。

    终止条件只有一条 —— 定理三破坏。扩展/升级 (级别延续定理二) 不在这里判,
    由下游 zs_ranges_overlap()/count_independent_zs() 统一处理。

    【为什么不再用"九段封顶"终止】
        曾按第33课"延伸不超过5段"设 MAX_ZS_BIS=8, 第 9 笔强行切出新中枢。
        实测该规则会**制造结构**: 分众 30 分钟 2025-11~2026-11 样本中, 一个
        仍在延伸的中枢被切在 2026-08-19, 后半段独立成另一个中枢; 两个中枢
        高低不重叠 → 被下游判成"两中枢下跌趋势" → 在一段下跌的两个子段之间
        做 a/c 背驰比较, 得出伪一买 (2026-08-31 @4.81), 而真正的趋势底
        (2026-07-10 @4.58) 因为 B1 只取"最近一个"被顶替掉。
        第33课的"5段"是**消除分解多义性**的口径 (同一图形有多种合法分解时择一),
        不是走势本身的终止条件; 缠师在定理三里把破坏定义为充要条件, 且第20课
        明言中枢"可以不断延伸下去直到无穷"。故此处回归"只按定理三终止"。

    算法:
        1. 从位置 i 取连续 3 笔算 [ZD,ZG]; zg <= zd 则 i += 1 重试。
           [ZD,ZG] 一经确定, 在本中枢生命周期内不再变动 (第20课: ZG/ZD 只由
           形成中枢的前三段决定; 其 ZG=min(g1,g2)/ZD=max(d1,d2) 在笔端点衔接
           的条件下与本式等价)。
        2. 延伸循环逐笔判"潜在离开段":
               离开 = 笔**在当前方向上的终点**越出中枢
                      (向上笔 high > ZG / 向下笔 low < ZD)。
               仅"另一端极值越界"不算离开 —— 盘整内向上笔的低点本来就在中枢下方。
        3. 潜在离开段交由**回抽确认** (定理三):
               - 下一笔重新回到 [ZD,ZG] 内 → 定理二: 中枢未被破坏,
                 该笔并入延伸 (只更新 GG/DD), 继续循环;
               - 下一笔不回到中枢内    → 定理三破坏成立, 该笔是真离开段,
                 **不并入**中枢 (否则拉升/断头铡刀段会被吞进方框),
                 前中枢在此刻正式终止, 新中枢从回抽笔起重新扫描。
           "重新回到中枢内"需满足**最小进入深度**, 而非任意擦边: 回抽笔与本
           中枢 [ZD,ZG] 的重叠长度必须 **> threshold** (等于也不算, 严格大于)。
           threshold =
           max(min_pullback_depth, min_pullback_ratio * base_value), 其中
           base_value = ZG (pullback_base='zg', 默认) 或 (ZG - ZD) ('height')。
           默认 ZG * 2%: 缠师第20课三买以 ZG 为锚("回试不破 ZG"), 破坏是
           其对称面("回抽有效跌破 ZG"), 故以 ZG 为基准; 且跨标的语义一致
           (2% 就是价格回撤 2%), 避免中枢高度宽窄不一导致阈值漂移。
           缘起: 汇川日线 2025-02-14 回抽低点 63.8495, ZG=63.866986,
           只进入 0.0175 元 —— 肉眼几乎贴着 ZG, 按"有交集即回"会被当成
           中枢继续延伸, 实为噪声级擦边。默认阈值 1.277 元将其判为未回。

    被修正的缺陷 (上一轮):
        旧实现的条件是 `bi.high > zg or bi.low < zd` —— **任一端点越界即断**。
        日线样本上 100%、30 分钟样本上 92% 的中枢切断属于"部分穿越"
        (笔的区间仍与 [ZD,ZG] 相交, 根本没有离开段), 等于靠"第 4 笔戳破一边"
        切中枢, 而非靠定理三的离开—回抽。后果: 中枢被切得过碎
        (分众 30 分钟 100 笔切出 26 个中枢, 平均不足 4 笔),
        三类买卖点随之虚增、且大量出现在回抽其实已回到中枢的位置上。
    """
    out: list[Zs] = []
    n = len(bi_list)
    i = 0
    while i + 2 < n:
        first3 = bi_list[i : i + 3]
        zd = max(b.low for b in first3)
        zg = min(b.high for b in first3)
        if zg <= zd:
            i += 1
            continue

        zs_bis = list(first3)
        base_value = zg if pullback_base == "zg" else (zg - zd)
        # round 消除浮点尾差 (如 11*0.02=0.22000000000000003), 保证"恰好等于阈值"
        # 稳定判为未回 (只有 overlap > threshold 才算回到中枢)
        threshold = round(max(min_pullback_depth, min_pullback_ratio * base_value), 10)
        j = i + 3
        leave_idx: int | None = None
        while j < n:
            bi = bi_list[j]
            # 潜在离开段: 只看笔在本方向上的终点是否越出中枢。
            # 反向极值越界不算离开 —— 盘整内向上笔的低点本来就在中枢下方。
            exits = bi.high > zg if bi.direction == "up" else bi.low < zd
            if exits:
                nxt = bi_list[j + 1] if j + 1 < n else None
                if nxt is None:
                    leave_idx = j          # 数据末端, 离开未能确认
                    break
                # 定理三回抽确认: 回抽笔与 [ZD,ZG] 的重叠长度 >= threshold
                # 才算"重新回到中枢内" (定理二维持)。擦边 (重叠极浅) 视为未回,
                # 判定理三破坏 —— 这是噪声过滤, 不改变定理本身。
                overlap = round(min(nxt.high, zg) - max(nxt.low, zd), 10)
                if overlap <= threshold:
                    leave_idx = j
                    break
            zs_bis.append(bi)
            j += 1

        zs = make_zs(zs_bis)
        if zs is not None and zs.valid:
            out.append(zs)

        # 破坏成立 → 新中枢从回抽笔起; 数据耗尽 → 从当前笔起继续扫描
        i = j if leave_idx is None else j + 1
    return out


def find_bi_overlap_zs(bi: Bi, zs_filtered: list[tuple[int, Zs]]) -> int:
    """找与笔时间区间重叠的最后一个 valid 中枢, 返回其原始下标; 无则 -1。"""
    found = -1
    for zi, zs in zs_filtered:
        if bi.sdt <= zs.edt and bi.edt >= zs.sdt:
            found = zi
    return found


def count_zs_in_trend(
    start_bi: Bi,
    end_bi: Bi,
    direction: str,
    zs_filtered: list[tuple[int, Zs]],
) -> int:
    """统计 [start_bi, end_bi] 区间内与趋势方向一致的中枢数 (缠师第 17/27 课)。

    注意:这是"计数"口径,不含不重叠判定。趋势背驰判定必须用
    count_independent_zs()——缠师第18课要求趋势中枢绝对不重叠。
    """
    return len(_pick_directional_zs(start_bi, end_bi, direction, zs_filtered))


def zs_ranges_overlap(a: Zs, b: Zs) -> bool:
    """缠师第20课:中枢波动区间 [DD, GG] 有交集即重叠(含瞬间波动)。

    第20课级别延续定理二:两个同级别中枢的波动区间重叠 → 形成更大级别中枢,
    而非新的同向趋势中枢。故重叠的中枢必须合并计数。
    """
    return not (a.gg < b.dd or a.dd > b.gg)


def _pick_directional_zs(
    start_bi: Bi,
    end_bi: Bi,
    direction: str,
    zs_filtered: list[tuple[int, Zs]],
) -> list[tuple[int, Zs]]:
    """挑出区间内方向一致的中枢,按时间升序。"""
    t_start, t_end = start_bi.sdt, end_bi.edt
    picked = [
        (zi, zs)
        for zi, zs in zs_filtered
        if not (zs.sdt > t_end or zs.edt < t_start) and zs.direction == direction
    ]
    picked.sort(key=lambda pair: pair[1].sdt)
    return picked


def trend_zs_chain(
    start_bi: Bi,
    end_bi: Bi,
    direction: str,
    zs_filtered: list[tuple[int, Zs]],
    overlap_mode: str = "strict",
) -> list[Zs]:
    """构造区间内的"同向趋势中枢链" — 第17课「依次上升、依次下降」。

    【为什么不能用 zs.direction 判趋势方向】
        中枢本身没有方向。`Zs.direction` 只是"构成中枢的第一笔的方向"
        (models.py 里 `self.bis[0].direction`), 它由中枢从哪一笔起算决定,
        与走势方向无关: 一段下跌里, 中枢常常是"反弹笔先起", 于是被标成 "up",
        再被 `direction == "down"` 过滤掉 — 真实的下跌趋势就此数成 0 个。
        实测分众 30 分钟 2026-07-16~10-22: ZS8 [4.9778,5.0669] ->
        ZS9 [4.8096,4.9481] -> ZS10 [4.64,4.79] 三个中枢依次下降且互不重叠,
        是标准的下跌趋势; 但 ZS9/ZS10 的首笔都是向上笔, 被旧判据全部剔除。

    第17课原文: 「趋势, 就是至少两个以上同级别中枢的依次上升或依次下降」--
    方向由**相邻中枢的相对位置**给出, 故此处只按位置判定:
        下跌: 后一中枢整体在前一中枢下方 (`nxt.hi < prev.lo`)
        上涨: 后一中枢整体在前一中枢上方 (`nxt.lo > prev.hi`)
    并要求"依次" — 只取**时间上连续**的一段, 不允许跳过中间中枢凑数。

    overlap_mode 与 count_independent_zs 一致:
        "strict"    -> 用 [DD,GG] 波动区间 (第20课口径, 笔级下趋势很稀少)
        "practical" -> 用 [ZD,ZG] 核心区间 (笔级近似, 默认)

    返回最长的那条连续链; 不足 2 个中枢即不构成趋势 (返回长度 0/1)。
    """
    t_start, t_end = start_bi.sdt, end_bi.edt
    picked = [
        zs for _zi, zs in zs_filtered if not (zs.sdt > t_end or zs.edt < t_start)
    ]
    if len(picked) < 2:
        return []
    picked.sort(key=lambda z: z.sdt)
    use_core = overlap_mode == "practical"
    bounds = [(z.zd, z.zg) if use_core else (z.dd, z.gg) for z in picked]

    best: list[Zs] = []
    run: list[Zs] = [picked[0]]
    for k in range(1, len(picked)):
        (plo, phi), (clo, chi) = bounds[k - 1], bounds[k]
        if direction == "down":
            continues = chi < plo
        elif direction == "up":
            continues = clo > phi
        else:
            continues = False
        if continues:
            run.append(picked[k])
        else:
            # 等长时保留**更近**的一段 — 判断买点时, 起作用的总是离 c 段
            # 最近的那条趋势链, 而不是整张图上最古老的一条等长链。
            if len(run) >= len(best):
                best = run
            run = [picked[k]]
    return run if len(run) >= len(best) else best


def recent_trend_chain(
    zs_filtered: list[tuple[int, Zs]],
    direction: str,
    overlap_mode: str = "strict",
    before_dt=None,
) -> list[Zs]:
    """取"包含 before_dt 之前最后一个中枢"的那条连续同向趋势链。

    与 trend_zs_chain 的差别: 不由 a 段圈定时间范围。旧流程是"先选 a 段、
    再在 [a.sdt, c.edt] 里数中枢", 一旦 a 段取晚了, 链就被截断 —— 汇川技术
    30 分钟 2026-10-15 @48.52 处, a 段被启发式取到 09-02, ZS10(08-03~08-26)
    因此落在范围外, 三中枢下跌趋势被数成 1 个, B1 直接漏报。
    判断 c 段背驰时, 起作用的总是**离 c 最近的那条趋势**, 所以这里先取所有
    在 before_dt 前走完的中枢, 再返回包含最后一个中枢的那条连续链。
    """
    picked = [
        z for _zi, z in zs_filtered if before_dt is None or z.edt <= before_dt
    ]
    if len(picked) < 2:
        return []
    picked.sort(key=lambda z: z.sdt)
    use_core = overlap_mode == "practical"
    bounds = [(z.zd, z.zg) if use_core else (z.dd, z.gg) for z in picked]

    runs: list[list[Zs]] = []
    run: list[Zs] = [picked[0]]
    for k in range(1, len(picked)):
        (plo, phi), (clo, chi) = bounds[k - 1], bounds[k]
        if direction == "down":
            continues = chi < plo
        elif direction == "up":
            continues = clo > phi
        else:
            continues = False
        if continues:
            run.append(picked[k])
        else:
            runs.append(run)
            run = [picked[k]]
    runs.append(run)

    last = picked[-1]
    for r in runs:
        if last in r:
            return r
    return []


def count_independent_zs(
    start_bi: Bi,
    end_bi: Bi,
    direction: str,
    zs_filtered: list[tuple[int, Zs]],
    overlap_mode: str = "strict",
) -> int:
    """统计区间内"相互不重叠"的同向中枢数——缠师第18/20课趋势判据。

    缠师第18课:"趋势中的缠中说禅走势中枢之间必须绝对不存在重叠";
    第20课:"这包括任何围绕走势中枢产生的任何瞬间波动之间的重叠"。

    overlap_mode:
        - "strict"(默认): 用波动区间 [DD,GG] 判重叠, 完全对齐缠师第20课。
          笔级近似下, 同向中枢常因共享价格带而重叠 -> 趋势稀少。
        - "practical": 用核心区间 [ZD,ZG] 判重叠(笔级合理近似);
          只要中枢核心区间不重叠即视为独立趋势中枢。

    重叠的中枢合并为一簇(等价于扩展成更大级别中枢), 返回簇数。
    簇数 < 2 时按缠师定义不构成趋势, 趋势背驰不成立。
    这是缺陷1的修复: 旧实现只数方向, 重叠中枢被误计为多个独立趋势中枢。
    """
    picked = _pick_directional_zs(start_bi, end_bi, direction, zs_filtered)
    if not picked:
        return 0
    use_core = overlap_mode == "practical"
    # 贪心合并: 重叠区间合并为一簇(区间并集)
    clusters: list[list[float]] = []
    for _zi, zs in picked:
        lo, hi = (zs.zd, zs.zg) if use_core else (zs.dd, zs.gg)
        placed = False
        for cl in clusters:
            if not (cl[1] < lo or cl[0] > hi):
                cl[0] = min(cl[0], lo)
                cl[1] = max(cl[1], hi)
                placed = True
                break
        if not placed:
            clusters.append([lo, hi])
    return len(clusters)
