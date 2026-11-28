"""基础过滤 null 率告警测试 (Fix C, 2026-11-24 零命中回归)。

背景: instruments 残缺快照 (TickFlow SZ/BJ 503) 导致深市
float_shares/turnover_rate 全 null, 换手率过滤把 null 行静默排除 —
列存在所以缺列检测不触发, 用户毫无提示。守卫语义:
  - 过滤引用列 null 率 > 50% → 生成中文告警
  - 少量 null / 列缺失 (走原有缺列告警) / 条件未启用 → 不触发 null 告警
"""
from __future__ import annotations

import polars as pl

from app.strategy.engine import StrategyEngine


def _df(n: int, null_turnover: int) -> pl.DataFrame:
    """n 行横截面, 前 null_turnover 行 turnover_rate 为 null。"""
    return pl.DataFrame({
        "symbol": [f"60000{i}.SH" for i in range(n)],
        "close": [10.0] * n,
        "turnover_rate": [None] * null_turnover + [5.0] * (n - null_turnover),
        "float_shares": [8e8] * n,
        "name": ["测试"] * n,
    })


BF = {"turnover_min": 1, "turnover_max": 10, "float_cap_min": 5e9}


def test_null_ratio_above_threshold_warns():
    """换手率 100% null (深市残缺快照场景) → 告警。"""
    warns = StrategyEngine._basic_filter_missing_columns(_df(100, 100), BF)
    assert any("换手率" in w and "误杀" in w for w in warns)


def test_null_ratio_just_above_half_warns():
    """51% null → 告警 (阈值 > 50%)。"""
    warns = StrategyEngine._basic_filter_missing_columns(_df(100, 51), BF)
    assert any("换手率" in w for w in warns)


def test_low_null_ratio_no_warning():
    """10% null (正常缺失) → 不触发 null 告警。"""
    warns = StrategyEngine._basic_filter_missing_columns(_df(100, 10), BF)
    assert not any("误杀" in w for w in warns)


def test_null_check_only_for_enabled_conditions():
    """未启用换手过滤时, turnover_rate 全 null 也不告警。"""
    bf = {"float_cap_min": 5e9}  # 无换手条件
    warns = StrategyEngine._basic_filter_missing_columns(_df(10, 10), bf)
    assert not any("换手率" in w for w in warns)


def test_float_shares_null_warns_for_float_cap():
    """流通市值过滤启用且 float_shares 大面积 null → 告警。"""
    df = _df(10, 0).drop("float_shares").with_columns(
        pl.lit(None, dtype=pl.Float64).alias("float_shares")
    )
    warns = StrategyEngine._basic_filter_missing_columns(df, {"float_cap_min": 5e9})
    assert any("流通市值" in w and "误杀" in w for w in warns)


def test_empty_df_no_crash():
    """空帧不崩溃, 返回原缺列结果。"""
    warns = StrategyEngine._basic_filter_missing_columns(_df(0, 0), BF)
    assert warns == []
