"""真实样本黄金快照回归 — 锁死 domain 层判定口径, 防止重构回退。

背景: "趋势方向判据"、"A 段选取"、"MACD 切片口径" 三类 bug 都是被真实行情数据
暴露的, 手工构造笔的单测 (range=sdt 的理想笔) 咬不住适配层问题。本文件把两个
真实样本 (经 service 全链路录制 identify_bs_points 的真实入参) 固化为快照,
无网络依赖地重放判定, 逐点断言输出。

快照里的黄金点都是按禅师原文手工分解核对过的:
- 汇川 300124.SZ 30分钟 2025-11-20~2026-11-21:
  三中枢下跌趋势 ZS10→ZS11→ZS12, 真底 48.52(10-15) 处 c 跌破 ZD 48.85 且
  面积 5.01→0.93/DIF -0.399→-0.376 → B1; 10-23 回调 48.99 盘整背驰 → B2。
  历史教训: 旧切片口径用分型 raw_bars 窗口, 把 10-09 14:30 (48.85 下跌腿残留,
  DIF -0.548) 卷进 c 段, 背驰被误杀; 切片已改笔本体 sdt~edt。
- 分众 002027.SZ 30分钟 同窗口: 4.4142(06-29) 与 4.63(09-30) 都是中枢 DD 内的
  盘整背驰低点 (A/C 只隔一笔), 不满足第 24 课趋势背驰前提 → 必须无 B1/S1/B2/S2;
  真实买点是三买 07-17 @4.9085 / 10-29 @5.12 (第 20 课位置条件)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.custom.czsc.config import DivergenceConfig
from app.custom.czsc.domain.bs_points import identify_bs_points
from app.custom.czsc.domain.models import Bi, DtIndex, MacdPoint, Zs

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _replay(snapshot: dict):
    bis = [
        Bi(
            sdt=datetime.fromisoformat(b["sdt"]),
            edt=datetime.fromisoformat(b["edt"]),
            range_sdt=datetime.fromisoformat(b["range_sdt"]),
            range_edt=datetime.fromisoformat(b["range_edt"]),
            direction=b["direction"],
            raw_direction=b["raw_direction"],
            high=b["high"],
            low=b["low"],
            length=b["length"],
            power=b["power"],
            start_mark=b["start_mark"],
            end_mark=b["end_mark"],
            start_price=b["start_price"],
            end_price=b["end_price"],
        )
        for b in snapshot["bis"]
    ]
    zs_list = [
        Zs(
            sdt=datetime.fromisoformat(z["sdt"]),
            edt=datetime.fromisoformat(z["edt"]),
            zd=z["zd"],
            zg=z["zg"],
            gg=z["gg"],
            dd=z["dd"],
            valid=z["valid"],
            bis=(),
        )
        for z in snapshot["zs"]
    ]
    macd_out = [
        MacdPoint(dt=m["dt"], dif=m["dif"], dea=m["dea"], macd=m["macd"])
        for m in snapshot["macd"]
    ]
    dt_index = DtIndex(snapshot["bar_dts"])
    cfg = DivergenceConfig(**snapshot["divergence"])
    return identify_bs_points(bis, zs_list, macd_out, dt_index, cfg)


@pytest.mark.parametrize(
    ("fixture", "case"),
    [
        pytest.param(
            "czsc_golden_hc30.json",
            [("2026-10-15", "B1", "买", 48.52), ("2026-10-23", "B2", "买", 48.99)],
            id="huichuan30-b1-b2-trend-divergence",
        ),
        pytest.param(
            "czsc_golden_fz30.json",
            [("2026-07-17", "B3", "买", 4.9085), ("2026-10-29", "B3", "买", 5.12)],
            id="fenzi30-no-first-second-buy",
        ),
        pytest.param(
            "czsc_golden_syzb.json",
            [("2026-06-05", "S1", "卖", 22.38)],
            id="shengyuan-up-bi-below-zero-axis-still-fires-s1",
        ),
    ],
)
def test_golden_snapshot_contains_hand_checked_points(fixture: str, case: list[tuple]):
    """黄金点逐个核对 (时间/类型/方向/价格), 且输出点集与录制时完全一致。"""
    snapshot = _load(fixture)
    got = [(p.dt[:10], p.type, p.direction, round(p.price, 4)) for p in _replay(snapshot)]
    golden = [
        (g["dt"][:10], g["type"], g["direction"], round(g["price"], 4))
        for g in snapshot["golden"]
    ]
    assert got == golden, f"输出点集与黄金快照不一致:\n got={got}\n golden={golden}"
    for dt_prefix, bs_type, direction, price in case:
        assert (dt_prefix, bs_type, direction, price) in got, (
            f"手工核对过的黄金点缺失: {dt_prefix} {bs_type} {direction} {price}"
        )


def test_golden_syzb_up_bi_below_zero_axis_has_zero_area():
    """上涨笔全程 MACD 绿柱(零轴下反弹): 红柱面积=0 是真实值, 不得用 abs 兜底。

    圣元环保 300867 2026-06-05 的 S1: C 笔 5 根柱全负, split 模式下红柱面积
    应为 0.0 (小于 A 段面积 -> 背驰成立)。早期 bug 把 area=None 当数据不足,
    用 total_abs 得 2.342 > 1.165, 反向柱冒充同向柱, 压掉 S1。
    """
    snapshot = _load("czsc_golden_syzb.json")
    pts = _replay(snapshot)
    s1 = [p for p in pts if p.dt.startswith("2026-06-05") and p.type == "S1"]
    assert len(s1) == 1, "零轴下反弹的顶背驰应报出 S1"
    assert s1[0].macd_area_cur == 0.0, "红柱面积应为 0, 不是反向柱绝对值"
    assert s1[0].macd_area_cur < s1[0].macd_area_prev
    assert "macd_area" in s1[0].divergence_pass


def test_definition_mode_labels_engineering_approximation():
    """口径标注: 一/二类点按所用重叠口径标注, 三类点(只凭位置)标 n/a。"""
    for fixture, expected in [
        ("czsc_golden_hc30.json", {"B1": "practical", "B2": "practical", "B3": "n/a", "S3": "n/a"}),
        ("czsc_golden_syzb.json", {"S1": "practical"}),
    ]:
        snapshot = _load(fixture)
        for p in _replay(snapshot):
            if p.type in expected:
                assert p.definition_mode == expected[p.type], (
                    f"{fixture} {p.type} 口径标注错误: {p.definition_mode}"
                )


def test_golden_fz30_has_no_trend_or_second_points():
    """分众窗口: 两个底都在中枢 DD 内, 严格第 24 课口径下不允许出现一/二类点。"""
    snapshot = _load("czsc_golden_fz30.json")
    got = _replay(snapshot)
    bad = [p for p in got if p.type in ("B1", "S1", "B2", "S2")]
    assert bad == [], f"盘整背驰低点被误判为一/二类点: {[(p.dt, p.type) for p in bad]}"
