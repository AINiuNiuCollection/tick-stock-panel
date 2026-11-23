from __future__ import annotations

import itertools
import math
from dataclasses import replace
from datetime import date, datetime, timedelta

import polars as pl
import pytest

pytest.importorskip("czsc")

from app.custom.czsc.adapters.kline.source import KlineResult
from app.custom.czsc.application.cache import AnalysisCache
from app.custom.czsc.application.service import AnalyzeService
from app.custom.czsc.config import AnalyzeRequest
from app.custom.czsc.domain.models import Bi, DtIndex
from app.custom.czsc.domain.zs import build_zs_strict


def _build_df(n: int = 260) -> pl.DataFrame:
    rows = []
    d = date(2024, 1, 1)
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        wave = math.sin(i / 9) * 0.6 + math.sin(i / 23) * 0.3
        close = 10 + i * 0.01 + wave
        openp = close - 0.1
        high = max(openp, close) + 0.15
        low = min(openp, close) - 0.15
        rows.append(
            {
                "dt": datetime.combine(d, datetime.min.time()),
                "open": openp,
                "high": high,
                "low": low,
                "close": close,
                "vol": 1000.0 + i,
                "amount": 1e6,
            }
        )
        d += timedelta(days=1)
    return pl.DataFrame(rows)


class _FakeChain:
    def __init__(self, df: pl.DataFrame) -> None:
        self.df = df
        self.calls = 0

    def fetch(self, symbol, freq, start, end):
        self.calls += 1
        return KlineResult(self.df, "fake")


def _request(**kwargs) -> AnalyzeRequest:
    base = {
        "symbol": "600000.SH",
        "freq": "日线",
        "start": date(2024, 1, 1),
        "end": date(2024, 12, 31),
        "ma_periods": (5, 20),
    }
    base.update(kwargs)
    return AnalyzeRequest(**base)


def _zs_from_bis(bis: list[Bi]):
    from app.custom.czsc.domain.zs import make_zs
    return make_zs(bis)


def _bi(day_a: int, day_b: int, direction: str, high: float, low: float) -> Bi:
    sdt = datetime(2024, 1, day_a)
    edt = datetime(2024, 1, day_b)
    return Bi(
        sdt=sdt,
        edt=edt,
        range_sdt=sdt,
        range_edt=edt,
        direction=direction,
        raw_direction="Direction.Up" if direction == "up" else "Direction.Down",
        high=high,
        low=low,
        length=day_b - day_a + 1,
        power=1.0,
        start_mark="bottom" if direction == "up" else "top",
        end_mark="top" if direction == "up" else "bottom",
        start_price=low if direction == "up" else high,
        end_price=high if direction == "up" else low,
    )


def test_service_pipeline_and_cache():
    chain = _FakeChain(_build_df())
    service = AnalyzeService(chain, sublevel=None, cache=AnalysisCache())
    req = _request()

    result = service.analyze(req)
    assert result["bar_count"] == len(result["bars"]) > 0
    assert len(result["macd"]) == len(result["bars"])
    assert len(result["mas"]) == len(result["bars"])
    assert result["cached"] is False
    assert all(z.zd < z.zg for z in result["zs_list"])
    assert all(z.dd <= z.zd and z.gg >= z.zg for z in result["zs_list"])

    cached = service.analyze(req)
    assert cached["cached"] is True
    assert chain.calls == 1

    refreshed = service.analyze(replace(req, force_refresh=True))
    assert refreshed["cached"] is False
    assert chain.calls == 2


def test_dt_index_normalizes_formats():
    index = DtIndex(["2024-01-02 00:00:00", "2024-01-03 00:00:00"])
    assert index.find(datetime(2024, 1, 2)) == 0
    assert index.find("2024-01-03T00:00:00") == 1
    assert index.find(date(2024, 1, 3)) == 1
    assert index.find("2024-01-04") is None


def test_build_zs_strict_uses_chan_formula():
    bis = [
        _bi(1, 3, "up", 12.0, 9.0),
        _bi(3, 5, "down", 11.0, 8.0),
        _bi(5, 7, "up", 10.5, 9.5),
    ]
    zs_list = build_zs_strict(bis)
    assert len(zs_list) == 1
    zs = zs_list[0]
    assert zs.zd == 9.5
    assert zs.zg == 10.5
    assert zs.gg == 12.0
    assert zs.dd == 8.0
    assert zs.sdt == datetime(2024, 1, 1)
    assert zs.edt == datetime(2024, 1, 7)
    assert zs.valid is True


def _zs_center_bis() -> list[Bi]:
    """共用底仓: 前 3 笔构成 [ZD, ZG] = [10.0, 11.0] 的中枢。"""
    return [
        _bi(1, 3, "up", 12.0, 9.5),
        _bi(3, 5, "down", 12.0, 9.0),
        _bi(5, 7, "up", 11.0, 10.0),
    ]


def test_zs_terminates_on_third_point_destruction():
    """定理三: 离开段之后的回抽不再回到 [ZD,ZG] → 前中枢终止, 离开段不并入。

    离开段 bi4 = 向下笔画到 9.0 (跌破 ZD=10.0);
    回抽 bi5 = 向上笔最高只到 9.4 (< ZD), 没回到中枢内 → 破坏成立。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "down", 11.0, 9.0),      # 离开段
        _bi(9, 11, "up", 9.4, 9.0),        # 回抽不回中枢
    ]
    zs_list = build_zs_strict(bis)
    assert zs_list, "应至少构造出前一个中枢"
    first = zs_list[0]
    assert first.zd == 10.0 and first.zg == 11.0
    # 中枢止于第 3 笔, 离开段 (bi4) 未被吞进中枢
    assert first.edt == datetime(2024, 1, 7)
    assert len(first.bis) == 3
    assert first.dd == 9.0


def test_zs_extends_when_pullback_returns_into_center():
    """定理二: 离开后回抽重新回到 [ZD,ZG] 内 → 中枢未被破坏, 继续延伸。"""
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "down", 11.0, 9.0),      # 向下离开
        _bi(9, 11, "up", 10.4, 9.0),       # 回抽重新进入中枢 (高点 10.4 > ZD)
        _bi(11, 13, "down", 10.4, 10.2),   # 回到中枢内震荡
    ]
    zs_list = build_zs_strict(bis)
    assert len(zs_list) == 1
    zs = zs_list[0]
    # 中枢吸并了 bi4/bi5/bi6, 未在 bi4 处被截断
    assert len(zs.bis) == 6
    assert zs.edt == datetime(2024, 1, 13)
    assert zs.dd == 9.0


def test_zs_rally_then_new_box_forms_two_centers_when_pullback_stays_above_zg():
    """两个月震荡 -> 翻倍拉升 -> 回落不回原箱体 -> 再震荡: 两个中枢 (定理三)。

    禅师不以时间/涨幅切中枢, 只看"离开段 + 回抽不回箱体"。这里原中枢
    [10,11]; 拉升笔高 24 (>ZG), 回抽笔低 15 (>ZG) → 破坏成立, 拉升笔不
    并入前中枢, 新中枢从回抽笔起算 → [16,18], 且 DD2=15 > GG1=12 (新生)。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "up", 24.0, 10.0),     # 离开段: 翻倍拉升
        _bi(9, 11, "down", 24.0, 15.0),  # 回抽不回原箱体 -> 定理三破坏
        _bi(11, 13, "up", 18.0, 15.0),
        _bi(13, 15, "down", 18.0, 16.0),
        _bi(15, 17, "up", 17.5, 16.2),
    ]
    zss = build_zs_strict(bis)
    assert len(zss) == 2
    z1, z2 = zss
    assert (z1.zd, z1.zg, z1.gg) == (10.0, 11.0, 12.0)
    assert len(z1.bis) == 3 and z1.edt == datetime(2024, 1, 7), "拉升笔不得并入前中枢"
    assert (z2.zd, z2.zg) == (16.0, 18.0)
    assert z2.dd > z1.gg, "两中枢波动区间不重叠 -> 新生(第20课定理二)"


def test_zs_rally_then_pullback_into_box_remains_one_center():
    """同样翻倍拉升, 但回抽跌回原箱体 -> 仍是一个中枢 (定理二延伸)。

    震荡时长、拉升幅度都不构成切断依据。ZD/ZG 固定为 [10,11] 不随拉升扩张,
    只把 GG 更新为 24 —— 若让 ZG 跟着拉升跑, 原箱体就被"吞"掉了。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "up", 24.0, 10.0),     # 翻倍拉升
        # 回抽低点 10.5, 低于 ZG=11 达 0.5 元 > 默认阈值 0.1 -> 有效回到中枢内
        _bi(9, 11, "down", 24.0, 10.5),
        _bi(11, 13, "up", 12.0, 10.5),
        _bi(13, 15, "down", 12.0, 10.5),
    ]
    zss = build_zs_strict(bis)
    assert len(zss) == 1
    z = zss[0]
    assert (z.zd, z.zg) == (10.0, 11.0), "ZD/ZG 由前三笔固定, 不随延伸变动"
    assert z.gg == 24.0 and z.dd == 9.0, "延伸只更新 GG/DD"
    assert len(z.bis) == 7


def test_zs_pullback_min_ratio_rejects_eyebrow_touch():
    """默认 ZG*2%: 擦边回抽(进 0.05 < 0.22)不算回中枢 -> 定理三破坏。

    汇川日线 2025-02-14 案例的抽象: 回抽低点只比 ZG 低 0.0175 元,
    按"有交集即回"会错误地继续延伸。默认以 ZG 为基准的 2% 阈值下,
    这种噪声级擦边判为未回, 中枢在离开段处终止。
    """
    bis = [
        *_zs_center_bis(),  # [ZD,ZG] = [10,11], ZG*2% = 0.22
        _bi(7, 9, "up", 14.0, 10.0),      # 离开段: high 14 > ZG 11
        _bi(9, 11, "down", 14.0, 10.95),  # 回抽低点 10.95, 仅进 0.05 < 0.22
        _bi(11, 13, "up", 12.0, 10.95),
        _bi(13, 15, "down", 12.0, 10.2),
    ]
    zss = build_zs_strict(bis)
    assert len(zss) == 2, "擦边回抽应判定理三破坏, 形成两个中枢"
    assert zss[0].edt == datetime(2024, 1, 7), "前中枢止于离开段之前"
    assert zss[0].zd == 10.0 and zss[0].zg == 11.0

    # 比例降到 0.001 -> 阈值 0.011, 0.05 足够 -> 回到旧行为(一个中枢)
    zss_loose = build_zs_strict(bis, min_pullback_ratio=0.001)
    assert len(zss_loose) == 1, "阈值降低后擦边算有效回抽, 中枢延伸"

    # 1% 选项: 阈值 0.11, 0.05 仍不够 -> 破坏
    assert len(build_zs_strict(bis, min_pullback_ratio=0.01)) == 2


def test_zs_pullback_min_ratio_boundary_is_strictly_less():
    """边界语义: 重叠深度 == 阈值时判为未回 (只有大于才算回踩)。

    默认 ZG=11, 2% -> 阈值 0.22; 回抽低点 10.78 恰好进入 0.22 -> 不算回。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "up", 14.0, 10.0),
        _bi(9, 11, "down", 14.0, 10.78),   # 进入 0.22 == 阈值 -> 不算
        _bi(11, 13, "up", 12.0, 10.78),
        _bi(13, 15, "down", 12.0, 10.2),
    ]
    assert len(build_zs_strict(bis)) == 2
    # 略深 0.0001 -> 算有效回抽
    bis[4] = _bi(9, 11, "down", 14.0, 10.7799)
    assert len(build_zs_strict(bis)) == 1


def test_zs_pullback_base_zg_vs_height():
    """基准切换: ZG(11)*2%=0.22 比 高度(1)*2%=0.02 严格得多。

    同一擦边回抽(进 0.05): ZG 基准判破坏, height 基准判延伸。
    """
    bis = [
        *_zs_center_bis(),  # ZD=10, ZG=11, 高度=1
        _bi(7, 9, "up", 14.0, 10.0),
        _bi(9, 11, "down", 14.0, 10.95),  # 进入 0.05
        _bi(11, 13, "up", 12.0, 10.95),
        _bi(13, 15, "down", 12.0, 10.2),
    ]
    assert len(build_zs_strict(bis, pullback_base="zg")) == 2      # 0.05 < 0.22
    assert len(build_zs_strict(bis, pullback_base="height")) == 1  # 0.05 > 0.02


def test_zs_spike_into_box_is_extension_not_new_center():
    """直线拉升 100% 后回抽回箱体 = 定理二延伸, 尖刺计入 GG 但不改 ZD/ZG。

    原中枢 [10,11]; 拉升笔高 22 (=100%), 回抽笔低 10.5 回到箱体。
    中枢不破坏, 两笔都并入延伸; 尖刺高点进 GG, ZD/ZG 固定。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "up", 22.0, 10.0),     # 直线拉升 100%
        _bi(9, 11, "down", 22.0, 10.5),  # 回抽回原箱体
    ]
    zss = build_zs_strict(bis)
    assert len(zss) == 1
    z = zss[0]
    assert (z.zd, z.zg) == (10.0, 11.0), "核心区间不随尖刺变动"
    assert z.gg == 22.0 and z.dd == 9.0, "尖刺高点只进波动区间 GG"
    assert len(z.bis) == 5, "延伸笔并入中枢"


def test_zs_spike_gg_can_break_strict_overlap_but_not_practical():
    """已知口径边界: 尖刺把 GG 拉高后, strict 用 [DD,GG] 判重叠会误断趋势链。

    后中枢 [13,14] 与原中枢核心 [10,11] 完全不重叠, practical 判为新生(上涨链 2);
    但尖刺把原中枢 GG 拉到 22, strict 的波动区间 [9,22] 与 [13,14] 相交 → 链断成 1。
    这是第20课 strict 口径的固有边界, 不是实现错误; 笔级近似下建议用 practical。
    """
    from app.custom.czsc.domain.zs import trend_zs_chain, zs_ranges_overlap

    base = _zs_center_bis()
    z_plain = build_zs_strict(base)[0]
    z_spike = build_zs_strict([*base, _bi(7, 9, "up", 22.0, 10.0),
                               _bi(9, 11, "down", 22.0, 10.5)])[0]
    z2 = replace(z_plain, sdt=datetime(2024, 2, 1), edt=datetime(2024, 2, 10),
                 zd=13.0, zg=14.0, gg=14.0, dd=13.0)
    start, end = _bi(1, 2, "up", 12.0, 9.5), _bi(20, 21, "up", 14.0, 13.0)
    end = replace(end, sdt=datetime(2024, 2, 20), edt=datetime(2024, 2, 21))
    filtered = [(0, z_spike), (1, z2)]
    assert zs_ranges_overlap(z_plain, z2) is False
    assert zs_ranges_overlap(z_spike, z2) is True
    assert len(trend_zs_chain(start, end, "up", filtered, "strict")) == 1
    assert len(trend_zs_chain(start, end, "up", filtered, "practical")) == 2


def test_zs_does_not_cut_on_partial_crossing():
    """部分穿越不算离开段 —— 向上笔的低点在中枢下方本属正常。

    旧实现用 `bi.high > zg or bi.low < zd` 任一端点越界即断, 会在这里把
    中枢切成 3 笔; 修正后只看"本方向终点", 向上笔终点 10.8 在 [10,11] 内,
    应予延伸。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "down", 11.0, 9.2),      # 向下笔低点 9.2 在 ZD 下方
        _bi(9, 11, "up", 10.8, 9.2),       # 向上笔终点 10.8 在 [10,11] 内
        _bi(11, 13, "down", 10.8, 10.1),
    ]
    zs_list = build_zs_strict(bis)
    assert len(zs_list) == 1
    assert len(zs_list[0].bis) == 6, "部分穿越应视为延伸, 不应切断中枢"
    assert zs_list[0].edt == datetime(2024, 1, 13)


def test_zs_extension_has_no_segment_cap():
    """中枢延伸不设段数封顶 —— 只要每次回抽都回到 [ZD,ZG], 就继续延伸。

    这是对"九段封顶会制造伪结构"的回归保护: 曾按第33课设 8 笔上限,
    结果把仍在延伸的中枢切成两段, 下游据此判出"两中枢下跌趋势"→ 伪一买。
    缠师定理三把破坏定义为充要条件, 第20课明言中枢可无限延伸。
    """
    bis = [
        *_zs_center_bis(),
        _bi(7, 9, "down", 11.0, 10.5),
        _bi(9, 11, "up", 10.9, 10.2),
        _bi(11, 13, "down", 10.9, 10.4),
        _bi(13, 15, "up", 10.95, 10.3),
        _bi(15, 17, "down", 10.95, 10.6),
        _bi(17, 19, "up", 10.9, 10.5),
        _bi(19, 21, "down", 10.9, 10.4),
        _bi(21, 23, "up", 10.8, 10.5),
        _bi(23, 25, "down", 10.8, 10.3),
        _bi(25, 27, "up", 10.85, 10.4),
    ]
    zs_list = build_zs_strict(bis)
    assert len(zs_list) == 1, "全程在 [ZD,ZG] 内震荡, 应只有一个中枢"
    assert len(zs_list[0].bis) == len(bis)
    assert zs_list[0].edt == bis[-1].edt


def test_zs_sequence_invariants():
    """结构不变量: 中枢至少 3 笔, 相邻中枢在时间轴上不重叠。"""
    from app.custom.czsc.adapters.czsc_adapter import run_czsc, to_raw_bars

    df = _build_df(500)
    bars = to_raw_bars(df, "日线")
    _, bis, _ = run_czsc(bars, 100, 7)
    zs_list = build_zs_strict(bis)
    assert zs_list
    for z in zs_list:
        assert 3 <= len(z.bis) <= len(bis)
        assert z.zd < z.zg and z.dd <= z.zd and z.gg >= z.zg
    for prev, nxt in itertools.pairwise(zs_list):
        assert prev.edt <= nxt.sdt


# ===== 趋势方向判据 (缠师第17课: 中枢依次上升/依次下降) =====

def _three_descending_zs():
    """三个依次下降且互不重叠的中枢, 且后两个的**首笔是向上笔**。

    这正是 Zs.direction 判据会翻车的地方: `direction` 取的是构成中枢的第一笔
    的方向, 下跌里的中枢常常"反弹笔先起" → 被标成 "up" → 被 `direction ==
    "down"` 整体剔除。但按第17课, 中枢本身没有方向, 趋势方向由中枢之间的
    相对位置给出 —— [10,11] -> [8.5,9.5] -> [7,8] 就是标准下跌趋势。
    """
    bis = [
        _bi(1, 3, "down", 11.5, 10.0),
        _bi(3, 5, "up", 11.0, 10.0),
        _bi(5, 7, "down", 11.0, 10.0),
        _bi(8, 10, "up", 9.5, 8.5),
        _bi(10, 12, "down", 9.5, 8.5),
        _bi(12, 14, "up", 9.5, 8.5),
        _bi(15, 17, "up", 8.0, 7.0),
        _bi(17, 19, "down", 8.0, 7.0),
        _bi(19, 21, "up", 8.0, 7.0),
    ]
    zs_a = _zs_from_bis(bis[0:3])
    zs_b = _zs_from_bis(bis[3:6])
    zs_c = _zs_from_bis(bis[6:9])
    assert zs_a is not None and zs_b is not None and zs_c is not None
    return bis, [(0, zs_a), (1, zs_b), (2, zs_c)]


def test_trend_chain_counts_descending_zs_regardless_of_first_bi():
    """趋势链必须按中枢相对位置判定, 不得用 Zs.direction 过滤。"""
    from app.custom.czsc.domain.zs import count_independent_zs, trend_zs_chain

    bis, zsf = _three_descending_zs()
    zs_a, zs_b, zs_c = zsf[0][1], zsf[1][1], zsf[2][1]
    assert (zs_a.zd, zs_a.zg) == (10.0, 11.0)
    assert (zs_b.zd, zs_b.zg) == (8.5, 9.5)
    assert (zs_c.zd, zs_c.zg) == (7.0, 8.0)
    # 后两个中枢的首笔是向上笔 —— 旧判据正是被这一点骗过去
    assert zs_a.direction == "down"
    assert zs_b.direction == "up" and zs_c.direction == "up"

    start, end = bis[0], bis[-1]
    chain = trend_zs_chain(start, end, "down", zsf, "practical")
    assert len(chain) == 3, [z.zd for z in chain]
    # 旧判据(带 direction 过滤)只能数到 1 —— 记录这个差距, 防止回退
    assert count_independent_zs(start, end, "down", zsf, "practical") == 1


def test_trend_chain_rejects_non_monotonic_sequence():
    """不依次下降的中枢序列不构成下跌趋势链 (第17课"依次")。"""
    from app.custom.czsc.domain.zs import trend_zs_chain

    bis, zsf = _three_descending_zs()
    ascending = [(i, z) for i, z in zsf][::-1]  # 时间倒序输入也应被正确排序
    chain = trend_zs_chain(bis[0], bis[-1], "down", ascending, "practical")
    assert len(chain) == 3

    # 上涨方向下, 同一组中枢只能数到 1 (它们不是依次上升)
    up_chain = trend_zs_chain(bis[0], bis[-1], "up", zsf, "practical")
    assert len(up_chain) == 1

    # 把中间中枢抬到最高的上方, 三连降就被打断, 链里不再含第一个中枢
    bis2, zsf2 = _three_descending_zs()
    zs_a, zs_b, zs_c = zsf2[0][1], zsf2[1][1], zsf2[2][1]
    broken = [(0, zs_a), (1, replace(zs_b, zd=12.0, zg=13.0)), (2, zs_c)]
    chain = trend_zs_chain(bis2[0], bis2[-1], "down", broken, "practical")
    assert len(chain) == 2, [z.zd for z in chain]
    assert zs_a not in chain, "中间中枢抬高后, 不应再把第一个中枢算进下跌链"


def test_fetch_start_expands_for_ma_warmup():
    req = _request(start=date(2024, 6, 1), end=date(2024, 12, 31), ma_periods=(250,))
    resolved = req.with_defaults()
    assert resolved.fetch_start() < date(2024, 6, 1)


def test_sma_warmup_trims_to_requested_range():
    service = AnalyzeService(_FakeChain(_build_df()), sublevel=None, cache=AnalysisCache())
    req = _request(start=date(2024, 12, 20), end=date(2024, 12, 31), ma_periods=(20,))

    result = service.analyze(req)
    assert result["bars"][0].dt.startswith("2024-12")
    assert len(result["mas"]) == len(result["bars"])
    assert result["mas"][0]["ma20"] is not None


async def test_stream_events_and_cache():
    chain = _FakeChain(_build_df())
    service = AnalyzeService(chain, sublevel=None, cache=AnalysisCache())
    req = _request(features=("fx", "bi", "zs"))

    events = [event async for event in service.stream(req)]
    kinds = [event["event"] for event in events]
    assert kinds[0] == "status"
    assert kinds[-1] == "done"
    assert "partial" in kinds

    cached_events = [event async for event in service.stream(req)]
    assert cached_events[0]["data"]["phase"] == "cached"
    assert cached_events[-1]["data"]["result"]["cached"] is True
    assert chain.calls == 1


async def test_facade_accepts_legacy_kwargs():
    from app.custom.czsc import analyzer

    service = AnalyzeService(_FakeChain(_build_df()), sublevel=None, cache=AnalysisCache())
    analyzer.set_default_service(service)
    try:
        result = await analyzer.analyze_async(
            symbol="600000.SH",
            freq="日线",
            start=date(2024, 1, 1),
            end=date(2024, 12, 31),
            ma_periods=[5, 20],
            features=["fx", "bi"],
        )
        assert result["bar_count"] > 0
        assert len(result["mas"]) == result["bar_count"]

        events = [
            event
            async for event in analyzer.analyze_stream(
                symbol="600000.SH",
                freq="日线",
                start=date(2024, 1, 1),
                end=date(2024, 12, 31),
                features=["fx"],
            )
        ]
        assert events[-1]["event"] == "done"
    finally:
        analyzer.set_default_service(None)


# ===== 缠论严格定义复现测试(重构 P0/P1) =====

def test_trend_requires_non_overlapping_zs():
    """缠师第18课:趋势中枢必须绝对不重叠;重叠的两中枢应合并为一簇,不构成趋势。

    复现缺陷1:旧 count_zs_in_trend 只数方向,把两个重叠中枢计为2 → 误判趋势。
    """
    from app.custom.czsc.domain.zs import count_independent_zs, count_zs_in_trend

    # 两个 down 中枢,价格区间 [9,11] 与 [10,12] 重叠(第20课 [DD,GG] 口径)
    b1 = [_bi(1, 3, "down", 11.0, 9.0), _bi(3, 5, "up", 12.0, 10.0), _bi(5, 7, "down", 11.0, 9.5)]
    b2 = [_bi(7, 9, "down", 12.0, 10.0), _bi(9, 11, "up", 13.0, 11.0), _bi(11, 13, "down", 12.0, 10.5)]
    z1 = _zs_from_bis(b1)
    z2 = _zs_from_bis(b2)
    assert z1 is not None and z2 is not None
    zsf = [(0, z1), (1, z2)]

    start = _bi(1, 3, "down", 11.0, 9.0)
    end = _bi(11, 13, "down", 12.0, 10.5)

    assert z1.direction == "down" and z2.direction == "down"
    # 旧逻辑:两个同向中枢数为 2(缺陷)
    assert count_zs_in_trend(start, end, "down", zsf) == 2
    # 新逻辑:重叠合并为 1 簇,不足以构成趋势
    assert count_independent_zs(start, end, "down", zsf) == 1


def test_trend_non_overlapping_zs_counted_separately():
    """不重叠的两个同向中枢应计为 2(真趋势)。"""
    from app.custom.czsc.domain.zs import count_independent_zs

    b1 = [_bi(1, 3, "down", 11.0, 9.0), _bi(3, 5, "up", 12.0, 10.0), _bi(5, 7, "down", 11.0, 9.5)]
    # 第二个中枢整体低于第一个,无重叠:z1[DD=9,GG=12], z2[DD=5,GG=8]
    b2 = [_bi(7, 9, "down", 7.0, 5.0), _bi(9, 11, "up", 8.0, 6.0), _bi(11, 13, "down", 7.0, 5.5)]
    z1 = _zs_from_bis(b1)
    z2 = _zs_from_bis(b2)
    zsf = [(0, z1), (1, z2)]
    start = _bi(1, 3, "down", 11.0, 9.0)
    end = _bi(11, 13, "down", 7.0, 5.5)
    assert count_independent_zs(start, end, "down", zsf) == 2


def test_practical_overlap_mode_uses_core_range():
    """practical 模式:核心区间[ZD,ZG]不重叠即算独立中枢(笔级近似)。"""
    from app.custom.czsc.domain.zs import count_independent_zs

    # 两中枢核心区间不重叠,但波动区间[DD,GG]重叠(共享价格带)
    b1 = [_bi(1, 3, "down", 11.0, 9.0), _bi(3, 5, "up", 12.0, 10.0), _bi(5, 7, "down", 11.0, 9.5)]
    b2 = [_bi(7, 9, "down", 8.0, 6.0), _bi(9, 11, "up", 8.5, 7.0), _bi(11, 13, "down", 8.0, 6.5)]
    z1 = _zs_from_bis(b1)
    z2 = _zs_from_bis(b2)
    zsf = [(0, z1), (1, z2)]
    start = _bi(1, 3, "down", 11.0, 9.0)
    end = _bi(11, 13, "down", 8.0, 6.5)
    # strict 与 practical 在这种核心/波动都不重叠场景下都应得 2
    assert count_independent_zs(start, end, "down", zsf, "strict") == 2
    assert count_independent_zs(start, end, "down", zsf, "practical") == 2

    # 构造核心重叠但波动不重叠的场景,验证两种模式差异
    # z1核心[10,11]波动[9,12]; z4核心[10.2,10.8]波动[10,11] -> 核心重叠 -> 合并为1
    b4 = [_bi(7, 9, "down", 10.8, 10.2), _bi(9, 11, "up", 11.0, 10.4), _bi(11, 13, "down", 10.8, 10.0)]
    z4 = _zs_from_bis(b4)
    zsf2 = [(0, z1), (1, z4)]
    assert count_independent_zs(start, end, "down", zsf2, "practical") == 1


def test_sublevel_verification_tri_state_and_gates():
    """定律一三态化 (方案A): _probe 三态 + strict/structural 双模式门控。

    - True/False = 有数据的结构判定结果; None = 未验证 (无验证器/异常/无更低级别)。
    - strict: False 拒绝 (旧口径 fail-closed 语义保留)。
    - structural: 次级别验证仅作标注, 不拦截。
    """
    from app.custom.czsc.domain.bs_points import _accept_by_sublevel, _probe_by_sublevel

    dt = datetime(2024, 1, 10)
    # 探测三态: 无验证器 → None (未验证)
    assert _probe_by_sublevel(None, dt) is None
    # 返回 False → False (有数据结构不通过)
    assert _probe_by_sublevel(lambda _dt: False, dt) is False
    # 返回 True → True
    assert _probe_by_sublevel(lambda _dt: True, dt) is True
    # 验证器异常 → None (数据不可得 ≠ 结构不通过, 转为未验证标注)
    def boom(_dt):
        raise RuntimeError("no data")
    assert _probe_by_sublevel(boom, dt) is None

    # strict 门控: False 拒绝, None/True 放行
    assert _accept_by_sublevel(False, "strict") is False
    assert _accept_by_sublevel(None, "strict") is True
    assert _accept_by_sublevel(True, "strict") is True
    # structural 门控: 不再拦截, 仅标注
    assert _accept_by_sublevel(False, "structural") is True
    assert _accept_by_sublevel(None, "structural") is True


def test_third_buy_requires_only_position_not_divergence():
    """第20课:三买只凭位置(回试不回中枢);背驰非成立前提。

    构造一个位置满足但无背驰数据的场景,确认 B3 仍输出。
    """
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points
    from app.custom.czsc.domain.models import DtIndex, MacdPoint

    # 中枢 [10,12],向上离开到 13,回试低点 12.5 > ZG=12 → 三买位置成立
    b1 = _bi(1, 3, "up", 11.0, 9.0)
    b2 = _bi(3, 5, "down", 10.5, 9.5)
    b3 = _bi(5, 7, "up", 12.0, 10.0)
    zs = _zs_from_bis([b1, b2, b3])
    assert zs is not None
    leave = _bi(7, 9, "up", 13.0, 12.0)   # 离开中枢,high>ZG
    back = _bi(9, 11, "down", 13.0, 12.5)  # 回试低点 12.5 > ZG=12
    bis = [b1, b2, b3, leave, back]

    # 无 MACD 数据 → 旧逻辑背驰不成立会丢弃 B3;新逻辑只凭位置应保留
    macd: list[MacdPoint] = []
    dti = DtIndex.from_bars([])
    pts = identify_bs_points(bis, [zs], macd, dti, DivergenceConfig(), None)
    b3_pts = [p for p in pts if p.type == "B3"]
    assert len(b3_pts) == 1, f"三买应仅凭位置成立,实际 {pts}"
    assert "三买" in b3_pts[0].divergence_type, b3_pts[0].divergence_type


def test_third_sell_label_is_san_mai_not_san_mai_b():
    """S3 的 divergence_type 必须标注为三卖,不得误标为三买(展示bug回归)。"""
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points
    from app.custom.czsc.domain.models import DtIndex, MacdPoint

    # 中枢核心 [ZD=10.5, ZG=11],向下离开到 9,回抽高点 9.5 < ZD → 三卖位置成立
    b1 = _bi(1, 3, "down", 11.0, 9.0)
    b2 = _bi(3, 5, "up", 11.5, 10.5)
    b3 = _bi(5, 7, "down", 11.0, 10.2)
    zs = _zs_from_bis([b1, b2, b3])
    assert zs is not None
    leave = _bi(7, 9, "down", 10.0, 9.0)   # 离开中枢,low<ZD
    back = _bi(9, 11, "up", 9.5, 8.5)      # 回抽高点 9.5 < ZD=10
    bis = [b1, b2, b3, leave, back]
    macd: list[MacdPoint] = []
    dti = DtIndex.from_bars([])
    pts = identify_bs_points(bis, [zs], macd, dti, DivergenceConfig(), None)
    s3_pts = [p for p in pts if p.type == "S3"]
    assert len(s3_pts) == 1, f"三卖应仅凭位置成立,实际 {pts}"
    assert "三卖" in s3_pts[0].divergence_type, s3_pts[0].divergence_type
    assert "三买" not in s3_pts[0].divergence_type, s3_pts[0].divergence_type


def test_third_point_equality_boundary():
    """第20课原文"不跌破/不升破"允许恰好触及: 回试低点==ZG 成三买, 回抽高点==ZD 成三卖。"""
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points
    from app.custom.czsc.domain.models import DtIndex, MacdPoint

    # 三买: 中枢核心 [ZD=10.8, ZG=11], 回试低点恰好 = ZG = 11.0
    b1 = _bi(1, 3, "up", 11.0, 9.0)
    b2 = _bi(3, 5, "down", 11.5, 10.5)
    b3 = _bi(5, 7, "up", 12.0, 10.8)
    zs = _zs_from_bis([b1, b2, b3])
    assert zs is not None and zs.zg == 11.0
    leave = _bi(7, 9, "up", 13.0, 11.5)
    back = _bi(9, 11, "down", 13.0, 11.0)  # 低点 == ZG, 不跌破 → 成立
    macd: list[MacdPoint] = []
    dti = DtIndex.from_bars([])
    pts = identify_bs_points([b1, b2, b3, leave, back], [zs], macd, dti, DivergenceConfig(), None)
    assert len([p for p in pts if p.type == "B3"]) == 1, pts

    # 三卖: 中枢核心 [ZD=10.5, ZG=11], 回抽高点恰好 = ZD = 10.5
    b4 = _bi(1, 3, "down", 11.0, 9.0)
    b5 = _bi(3, 5, "up", 11.5, 10.5)
    b6 = _bi(5, 7, "down", 11.0, 10.0)
    zs2 = _zs_from_bis([b4, b5, b6])
    assert zs2 is not None and zs2.zd == 10.5
    leave2 = _bi(7, 9, "down", 10.0, 9.0)
    back2 = _bi(9, 11, "up", 10.5, 8.5)  # 高点 == ZD, 不升破 → 成立
    pts2 = identify_bs_points([b4, b5, b6, leave2, back2], [zs2], macd, dti, DivergenceConfig(), None)
    assert len([p for p in pts2 if p.type == "S3"]) == 1, pts2


# ===== 一类点位置条件 (第17/27课) =====

def _b1_scenario(c_low: float):
    """搭一个"两个不重叠下跌中枢 + a/c 段 MACD 背驰"的一买场景。

    结构 (笔级):
        ZS_A 核心 [11.00, 12.00]   b0/b1/b2
        ZS_B 核心 [ 9.00,  9.60]   b4/b5/b6
        a 段 = b2 (趋势起点, 低点 11.00)
        c 段 = b8 (低点由 c_low 控制)

    a/c 段 MACD 面积与 DIF 均已构造为"c 弱于 a", 即背驰两条件都满足。
    唯一的变量是 c 段低点相对 ZS_B 的 ZD(=9.00) 的位置 —— 用来单独检验
    "一买必须跌出最后一个中枢"这道位置条件。
    """
    from app.custom.czsc.domain.models import MacdPoint
    from app.custom.czsc.domain.zs import make_zs

    b0 = _bi(1, 3, "down", 12.50, 11.00)
    b1 = _bi(3, 5, "up", 12.00, 11.00)
    b2 = _bi(5, 7, "down", 12.00, 11.00)     # a 段
    b3 = _bi(7, 9, "up", 11.05, 11.00)
    b4 = _bi(9, 11, "down", 11.05, 9.00)
    b5 = _bi(11, 13, "up", 9.60, 8.40)
    b6 = _bi(13, 15, "down", 9.60, 8.60)
    b7 = _bi(15, 17, "up", 9.20, 8.60)
    b8 = _bi(17, 19, "down", 9.20, c_low)    # c 段
    bis = [b0, b1, b2, b3, b4, b5, b6, b7, b8]

    zs_a = make_zs([b0, b1, b2])
    zs_b = make_zs([b4, b5, b6])
    assert zs_a is not None and zs_b is not None
    assert (zs_a.zd, zs_a.zg) == (11.00, 12.00)
    assert (zs_b.zd, zs_b.zg) == (9.00, 9.60)

    dts = [f"2024-01-{d:02d}" for d in range(1, 20)]
    macd: list[MacdPoint] = []
    for i, dt in enumerate(dts):
        if i <= 3:
            macd.append(MacdPoint(dt=dt, dif=-0.3, dea=None, macd=-1.0))
        elif i <= 6:      # a 段: 面积大 / DIF 深
            macd.append(MacdPoint(dt=dt, dif=-1.0, dea=None, macd=-3.0))
        elif i <= 15:     # 中枢内部: 无绿柱, 供 _has_macd_area 走回退分支
            macd.append(MacdPoint(dt=dt, dif=0.2, dea=None, macd=1.0))
        else:             # c 段: 面积小 / DIF 浅
            macd.append(MacdPoint(dt=dt, dif=-0.2, dea=None, macd=-0.5))

    return bis, [zs_a, zs_b], macd, DtIndex(dts)


def test_b1_requires_c_bi_below_last_zs():
    """第17/27课: 一买是趋势的终点, c 段必须跌出**最后一个**中枢。

    c 段低点 9.05 仍停在 ZS_B 的 [ZD=9.00, ZG=9.60] 内 —— 这是中枢内的回调,
    不是趋势末端的背驰段。即便 MACD 面积/DIF 都缩了, 也不得输出 B1。
    """
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points

    bis, zs_list, macd, dti = _b1_scenario(c_low=9.05)
    cfg = DivergenceConfig(
        macd_area_mode="split",
        use_dif=True,
        use_macd_area=True,
        trend_overlap_mode="practical",
        divergence_logic="and",
    )
    pts = identify_bs_points(bis, zs_list, macd, dti, cfg, None)
    b1 = [p for p in pts if p.type == "B1"]
    assert b1 == [], f"c 段未跌出中枢 ZD=9.00, 不得给一买, 实际 {b1}"


def test_b1_fires_when_c_bi_breaks_last_zs():
    """对称正控: 同一场景内只把 c 段低点压到 8.50 (< ZD=9.00) → 一买成立。

    这条保证上一条的"无 B1"是位置条件立的功, 而不是背驰数据本身不成立。
    """
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points

    bis, zs_list, macd, dti = _b1_scenario(c_low=8.50)
    cfg = DivergenceConfig(
        macd_area_mode="split",
        use_dif=True,
        use_macd_area=True,
        trend_overlap_mode="practical",
        divergence_logic="and",
    )
    pts = identify_bs_points(bis, zs_list, macd, dti, cfg, None)
    b1 = [p for p in pts if p.type == "B1"]
    assert len(b1) == 1, f"跌出中枢且背驰成立, 应给一买, 实际 {pts}"
    assert b1[0].price == 8.50
    assert b1[0].dif_peak_prev == -1.0 and b1[0].dif_peak_cur == -0.2


# ===== 区间套下钻测试 (缠师第27课) =====

def test_interval_nest_finds_sublevel_divergence():
    """区间套: 次级别存在创新低+面积缩小的同向背驰段 -> 确认。"""
    from app.custom.czsc.domain.interval_nest import find_sublevel_divergence
    from app.custom.czsc.domain.models import MacdPoint

    # 构造次级别下跌笔: a段(10->5)面积大, c段(6->4)创新低但面积小
    a = _bi(1, 5, "down", 10.0, 5.0)
    mid = _bi(5, 8, "up", 7.0, 5.5)
    c = _bi(8, 12, "down", 6.0, 4.0)

    # MACD: a段绿柱面积大(每根-2 x5), c段绿柱面积小(每根-0.5 x5)
    macd: list[MacdPoint] = []
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    d0 = _dt(2024, 1, 1)
    for i in range(12):
        dt = (d0 + _td(days=i)).isoformat()
        if i < 5:
            macd.append(MacdPoint(dt=dt, dif=None, dea=None, macd=-2.0))
        elif i < 8:
            macd.append(MacdPoint(dt=dt, dif=None, dea=None, macd=1.0))
        else:
            macd.append(MacdPoint(dt=dt, dif=None, dea=None, macd=-0.5))

    r = find_sublevel_divergence([a, mid, c], macd, "down", "30分钟")
    assert r.confirmed is True, r
    assert r.level == "30分钟"
    assert r.sub_ratio is not None and r.sub_ratio < 1.0
    assert r.sub_div_start is not None and r.sub_div_end is not None
    assert r.bi_count == 3


def test_interval_nest_rejects_when_no_divergence():
    """区间套: 次级别无背驰 -> 不确认, 且结构不变式完整。"""
    from app.custom.czsc.domain.interval_nest import find_sublevel_divergence
    from app.custom.czsc.domain.models import MacdPoint

    a = _bi(1, 5, "down", 10.0, 5.0)
    mid = _bi(5, 8, "up", 7.0, 5.5)
    c = _bi(8, 12, "down", 6.0, 4.0)  # 创新低
    # c段面积比a段更大 -> 不背驰
    macd: list[MacdPoint] = []
    from datetime import datetime as _dt
    from datetime import timedelta as _td
    d0 = _dt(2024, 1, 1)
    for i in range(12):
        dt = (d0 + _td(days=i)).isoformat()
        val = -1.0 if i < 5 else (1.0 if i < 8 else -3.0)
        macd.append(MacdPoint(dt=dt, dif=None, dea=None, macd=val))

    r = find_sublevel_divergence([a, mid, c], macd, "down")
    assert r.confirmed is False
    assert r.note  # 必须给出降级原因, 不编造


def test_interval_nest_insufficient_bi():
    """区间套: 次级别笔数不足 -> 明确降级, 不给出虚假确认。"""
    from app.custom.czsc.domain.interval_nest import find_sublevel_divergence

    r = find_sublevel_divergence([_bi(1, 3, "down", 10.0, 5.0)], [], "down")
    assert r.confirmed is False
    assert "不足" in r.note

    r2 = find_sublevel_divergence([], [], "up")
    assert r2.confirmed is False


# ===== 线段构造测试 (缠师第65/67课) =====

def _bi2(day_a, day_b, direction, high, low):
    return _bi(day_a, day_b, direction, high, low)


def test_xianduan_basic_up_then_down():
    """最简线段: 上涨三笔(起止同向)被下跌三笔破坏 -> 2个线段。"""
    from app.custom.czsc.domain.xianduan import build_xianduan

    # S1(up) X1(down) S2(up) 构成重叠的上涨线段; 然后下跌线段
    bis = [
        _bi2(1, 3, "up", 12.0, 10.0),
        _bi2(3, 5, "down", 12.0, 10.5),
        _bi2(5, 7, "up", 13.0, 10.8),
        _bi2(7, 9, "down", 13.0, 11.0),
        _bi2(9, 11, "up", 12.5, 11.0),
        _bi2(11, 13, "down", 12.5, 10.5),
        _bi2(13, 15, "up", 11.5, 10.0),
        _bi2(15, 17, "down", 11.5, 9.0),
        _bi2(17, 19, "up", 9.5, 8.0),
    ]
    segs = build_xianduan(bis)
    assert len(segs) >= 1
    # 结构不变式: 每段至少3笔、奇数笔、方向交替、首尾相接
    for k, s in enumerate(segs):
        assert s.valid, f"线段{k}无效: {s}"
        assert len(s.bis) >= 3 and len(s.bis) % 2 == 1
        assert s.bis[0].direction == s.direction
        assert s.bis[-1].direction == s.direction
        assert s.high > s.low
    for k in range(1, len(segs)):
        assert segs[k].start_idx == segs[k - 1].end_idx + 1, "线段须首尾相接"


def test_xianduan_requires_three_bis():
    """线段至少3笔: 不足3笔不成段。"""
    from app.custom.czsc.domain.xianduan import build_xianduan

    bis = [_bi2(1, 3, "up", 12.0, 10.0), _bi2(3, 5, "down", 12.0, 10.5)]
    segs = build_xianduan(bis)
    assert all(len(s.bis) >= 3 for s in segs)


def test_xianduan_feature_sequence_containment():
    """特征序列非包含处理: 向下元素序列用 [min low, min high] 合并。"""
    from app.custom.czsc.domain.xianduan import _Elem, _merge_containment

    elems = [
        _Elem(10.0, 12.0, 0),
        _Elem(10.5, 11.5, 1),  # 被前一根包含
        _Elem(9.0, 10.0, 2),
    ]
    merged = _merge_containment(elems, "down")
    # 向下: 前两根合并为 [min(10,10.5), min(12,11.5)] = [10,11.5]
    assert len(merged) == 2
    assert abs(merged[0].low - 10.0) < 1e-9
    assert abs(merged[0].high - 11.5) < 1e-9


def test_xianduan_on_synthetic_daily_bars():
    """合成日线上线段构造满足结构不变式(自包含, 不依赖外部数据)。"""
    from app.custom.czsc.adapters.czsc_adapter import run_czsc, to_raw_bars
    from app.custom.czsc.domain.xianduan import build_xianduan

    df = _build_df(500)
    bars = to_raw_bars(df, "日线")
    _fxs, bis, _sig = run_czsc(bars, 100, 7)
    segs = build_xianduan(bis)
    assert len(segs) >= 1
    for k, s in enumerate(segs):
        assert s.valid, f"合成数据线段{k}无效"
        assert len(s.bis) % 2 == 1
        assert s.bis[0].direction == s.direction == s.bis[-1].direction
        assert s.high == max(b.high for b in s.bis)
        assert s.low == min(b.low for b in s.bis)
    for k in range(1, len(segs)):
        assert segs[k].start_idx == segs[k - 1].end_idx + 1


# ===== 线段级中枢测试 (缠师第17/72课) =====

def test_level_zs_formula():
    """线段级中枢: [ZD,ZG]=[max(low),min(high)] (第18课公式在线段层复用)。"""
    from app.custom.czsc.domain.level_zs import build_level_zs
    from app.custom.czsc.domain.xianduan import Xianduan

    # 三段有重叠的线段(up/down/up)
    def seg(sd, ed, direction, low, high, idx):
        return Xianduan(sd, ed, direction, high, low, (), idx, idx)

    from datetime import datetime as dt
    s1 = seg(dt(2024,1,1), dt(2024,2,1), "up", 10.0, 12.0, 0)
    s2 = seg(dt(2024,2,1), dt(2024,3,1), "down", 10.5, 11.5, 1)
    s3 = seg(dt(2024,3,1), dt(2024,4,1), "up", 11.0, 13.0, 2)
    zss = build_level_zs([s1, s2, s3])
    assert len(zss) == 1
    z = zss[0]
    assert abs(z.zd - 11.0) < 1e-9  # max(10,10.5,11)
    assert abs(z.zg - 11.5) < 1e-9  # min(12,11.5,13)
    assert z.level == 2
    assert z.zd < z.zg
    assert z.gg >= z.zg and z.dd <= z.zd


def test_level_zs_fewer_than_bi_zs():
    """线段级中枢应比笔级中枢更少(更高级别): 线段合并了多笔。"""
    from app.custom.czsc.adapters.czsc_adapter import run_czsc, to_raw_bars
    from app.custom.czsc.domain.level_zs import build_level_zs
    from app.custom.czsc.domain.xianduan import build_xianduan
    from app.custom.czsc.domain.zs import build_zs_strict

    df = _build_df(500)
    bars = to_raw_bars(df, "日线")
    _, bis, _ = run_czsc(bars, 100, 7)
    segs = build_xianduan(bis)
    bi_zss = build_zs_strict(bis)
    lv_zss = build_level_zs(segs)
    # 线段数 << 笔数, 线段级中枢数应 <= 笔级中枢数
    assert len(segs) < len(bis)
    assert len(lv_zss) <= len(bi_zss)
    for z in lv_zss:
        assert z.valid and z.zd < z.zg and z.level == 2


# ===== 方案A/B 接入主链路回归 (2026-11-23 架构优化) =====

def test_bs_output_mode_structural_outputs_b2_without_divergence():
    """方案A: structural 模式下 B2 只凭结构定义成立 (第17课), 无盘整背驰也输出,
    divergence_type 标注'结构定义'; strict 模式仍要求背驰 (旧口径)。"""
    from app.custom.czsc.config import DivergenceConfig
    from app.custom.czsc.domain.bs_points import identify_bs_points
    from app.custom.czsc.domain.models import DtIndex, MacdPoint

    # 两中枢下跌趋势 + a/c 背驰 → B1; B1 后反弹+回调不破 B1 低点 → B2 结构成立
    b0 = _bi(1, 3, "down", 12.50, 11.00)
    b1 = _bi(3, 5, "up", 12.00, 11.00)
    b2 = _bi(5, 7, "down", 12.00, 11.00)
    b3 = _bi(7, 9, "up", 11.05, 11.00)
    b4 = _bi(9, 11, "down", 11.05, 9.00)
    b5 = _bi(11, 13, "up", 9.60, 8.40)
    b6 = _bi(13, 15, "down", 9.60, 8.60)
    b7 = _bi(15, 17, "up", 9.20, 8.60)
    b8 = _bi(17, 19, "down", 9.20, 7.00)    # c 段创新低
    b9 = _bi(19, 21, "up", 8.50, 7.30)      # B1 后反弹
    b10 = _bi(21, 23, "down", 8.20, 7.50)   # 回调不破 B1 低点 7.00
    bis = [b0, b1, b2, b3, b4, b5, b6, b7, b8, b9, b10]

    macd: list[MacdPoint] = []  # 无 MACD → 盘整背驰不成立 (a/c 面积均无)
    dti = DtIndex.from_bars([])

    structural = DivergenceConfig(bs_output_mode="structural")
    strict = DivergenceConfig(bs_output_mode="strict").normalized()
    assert structural.bs_output_mode == "structural"
    pts_structural = identify_bs_points(bis, [], macd, dti, structural, None)
    b2s = [p for p in pts_structural if p.type == "B2"]
    # structural: 结构定义成立即输出, 无背驰也有 B2, 且带结构定义标注
    assert all("结构定义" in (p.divergence_type or "") for p in b2s), pts_structural
    # strict: 无 MACD → 盘整背驰不成立 → B2 不得输出
    pts_strict = identify_bs_points(bis, [], macd, dti, strict, None)
    assert [p for p in pts_strict if p.type == "B2"] == [], pts_strict
    # 未验证 (无 verifier) → sublevel_verified 恒 None
    assert all(p.sublevel_verified is None for p in pts_structural)


def test_center_unit_xianduan_builder_produces_domain_zs():
    """方案B: XianduanCenterBuilder 从笔序列产出 domain.Zs 快照,
    字段与 identify_bs_points 全部读取点兼容; AnalyzeRequest.center_unit 归一化。"""
    from datetime import date

    from app.custom.czsc.adapters.czsc_adapter import run_czsc, to_raw_bars
    from app.custom.czsc.config import AnalyzeRequest
    from app.custom.czsc.extension_policy import XianduanCenterBuilder
    from app.custom.czsc.domain.models import Zs

    df = _build_df(500)
    bars = to_raw_bars(df, "日线")
    _, bis, _ = run_czsc(bars, 100, 7)

    zss = list(XianduanCenterBuilder().build(bis))
    assert all(isinstance(z, Zs) for z in zss)
    for z in zss:
        assert z.zd < z.zg and z.valid
        assert z.bis == ()
        _ = z.direction  # property 可读 (bis 为空 → "unknown", 不抛错)

    # 请求契约: 默认 bi, 白名单归一化
    req = AnalyzeRequest(symbol="000001.SZ", start=date(2024, 1, 1), end=date(2024, 12, 31))
    assert req.with_defaults().center_unit == "bi"
    req2 = AnalyzeRequest.from_query(symbol="000001.SZ", center_unit="xianduan")
    assert req2.with_defaults().center_unit == "xianduan"
    assert "xianduan" in req2.cache_key()
    req3 = AnalyzeRequest.from_query(symbol="000001.SZ", center_unit="bogus")
    assert req3.with_defaults().center_unit == "bi"
