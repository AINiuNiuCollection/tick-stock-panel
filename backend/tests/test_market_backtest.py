"""大盘研究模块测试 — 信号引擎 / 回测引擎 / 参数寻优。

验收口径 (任务 #189): 回测逐笔可手工核算 — 零费率零滑点下
pnl = shares × (出场价 − 入场价) 必须逐一成立。
"""
from datetime import date

import polars as pl
import pytest

from app.custom.market.backtest import (
    BacktestResult,
    CostSpec,
    ExitSpec,
    run_backtest,
)
from app.custom.market.optimizer import optimize_grid
from app.custom.market.stats import REGISTRY
from app.custom.market.stats.base import Signal
from app.custom.market.stats.crash_speed import CrashSpeedModule
from app.custom.market.stats.ma_state import MaStateModule
from app.custom.market.stats.volume_price import VolumePriceModule

ZERO_COST = CostSpec(commission_rate=0.0, stamp_tax_rate=0.0, slippage_rate=0.0)


def _mk_target(rows: list[tuple]) -> pl.DataFrame:
    """rows: (date, open, high, low, close)。"""
    return pl.DataFrame(
        {
            "date": [r[0] for r in rows],
            "open": [float(r[1]) for r in rows],
            "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows],
            "close": [float(r[4]) for r in rows],
        }
    )


# ---------------------------------------------------------------------------
# M1 均线状态机信号
# ---------------------------------------------------------------------------
class TestMaState:
    def test_cross_up_and_down(self):
        d = [date(2024, 1, i) for i in range(1, 31)]
        # 前 5 日 10 → MA5=10; 第 6 日拉升上穿; 第 12 日回落跌破
        closes = [10.0] * 5 + [11.0, 12, 12, 12, 12, 12, 9.0] + [9.0] * 18
        df = pl.DataFrame(
            {"date": d, "open": closes, "high": closes, "low": closes, "close": closes}
        )
        sigs = MaStateModule().to_signals(df, {"ma_period": 5})
        up = [s for s in sigs if s.direction > 0]
        down = [s for s in sigs if s.direction < 0]
        assert [s.dt for s in up] == [date(2024, 1, 6)]
        assert [s.dt for s in down] == [date(2024, 1, 12)]

    def test_unknown_param_rejected(self):
        df = pl.DataFrame(
            {"date": [date(2024, 1, 1)], "close": [1.0]}
        )
        with pytest.raises(ValueError):
            MaStateModule().to_signals(df, {"foo": 1})


# ---------------------------------------------------------------------------
# M2 急跌急涨
# ---------------------------------------------------------------------------
class TestCrashSpeed:
    def test_single_day_drop_and_rally(self):
        d = [date(2024, 1, i) for i in range(1, 11)]
        closes = [10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 9.0, 9.0, 10.5]
        df = pl.DataFrame(
            {"date": d, "open": closes, "high": closes, "low": closes, "close": closes}
        )
        sigs = CrashSpeedModule().to_signals(df, {"threshold_pct": 5.0})
        ups = [s for s in sigs if s.direction > 0]
        downs = [s for s in sigs if s.direction < 0]
        assert [s.dt for s in ups] == [date(2024, 1, 5)]  # 10→9 跌 10% ≥5%
        assert [s.dt for s in downs] == [date(2024, 1, 10)]  # 9→10.5 涨 ~16.7%

    def test_cumulative_kind(self):
        d = [date(2024, 1, i) for i in range(1, 8)]
        closes = [10.0, 9.8, 9.6, 9.4, 9.2, 9.0, 9.0]  # 5 日累计 -10%
        df = pl.DataFrame(
            {"date": d, "open": closes, "high": closes, "low": closes, "close": closes}
        )
        sigs = CrashSpeedModule().to_signals(
            df, {"threshold_pct": 5.0, "kind": "cumulative", "cum_days": 5}
        )
        ups = [s for s in sigs if s.direction > 0]
        assert date(2024, 1, 6) in [s.dt for s in ups]


# ---------------------------------------------------------------------------
# M3 量价 (地量/放量)
# ---------------------------------------------------------------------------
class TestVolumePrice:
    def test_low_and_high_quantile_signals(self):
        n = 30
        d = [date(2024, 1, 1 + i) for i in range(n)]
        amounts = [100.0] * 20 + [1.0] * 5 + [500.0] * 5
        closes = [10.0] * n
        df = pl.DataFrame(
            {
                "date": d,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "amount": amounts,
            }
        )
        sigs = VolumePriceModule().to_signals(
            df, {"window": 20, "low_q": 0.1, "high_q": 0.9}
        )
        ups = [s for s in sigs if s.direction > 0]
        downs = [s for s in sigs if s.direction < 0]
        assert all(s.dt >= d[20] for s in sigs)  # 前 window 日暖机无信号
        assert len(ups) > 0 and all(s.dt <= d[24] for s in ups)  # 地量期
        assert len(downs) > 0 and all(s.dt >= d[25] for s in downs)  # 放量期


# ---------------------------------------------------------------------------
# 回测引擎 — 手工核算
# ---------------------------------------------------------------------------
class TestBacktest:
    def _target5(self):
        return _mk_target(
            [
                (date(2024, 1, 1), 10.0, 10.5, 9.8, 10.2),
                (date(2024, 1, 2), 10.0, 10.8, 9.9, 10.5),
                (date(2024, 1, 3), 10.5, 11.0, 10.2, 10.8),
                (date(2024, 1, 4), 11.0, 11.5, 10.5, 11.2),
                (date(2024, 1, 5), 11.0, 11.2, 10.5, 10.8),
            ]
        )

    def test_time_exit_hand_calc_zero_cost(self):
        """信号 1/1, T+1 (1/2) 开盘 10 买入; 持有 2 交易日 → 1/4 开盘 11 卖出。

        手工: shares=floor(100000/10)=10000; pnl=10000×(11−10)=10000;
        equity=110000; 总收益 10%。
        """
        target = self._target5()
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        r = run_backtest(
            target, sigs, ExitSpec(mode="time", hold_days=2), ZERO_COST
        )
        assert len(r.trades) == 1
        t = r.trades[0]
        assert t.entry_dt == date(2024, 1, 2) and t.entry_price == 10.0
        assert t.exit_dt == date(2024, 1, 4) and t.exit_price == 11.0
        assert t.exit_reason == "time"
        assert t.shares == 10000
        assert t.pnl == pytest.approx(10000.0, abs=0.01)
        assert r.final_equity == pytest.approx(110000.0, abs=0.01)
        assert r.total_return_pct == pytest.approx(10.0, abs=0.01)
        assert r.win_rate == 100.0
        assert r.avg_hold_days == 2.0  # 1/2 → 1/4 自然日

    def test_slippage_and_commission_hand_calc(self):
        """默认费率下手工核算: 入场 10×1.001, 出场 11×0.999, 佣金万2.5 双边。

        shares=floor(100000/10.01)=9989; entry=99989.89-... 逐项验 pnl。
        """
        target = self._target5()
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        cost = CostSpec()  # 佣金 0.00025, 滑点 0.001
        r = run_backtest(target, sigs, ExitSpec(mode="time", hold_days=2), cost)
        t = r.trades[0]
        entry = 10.0 * 1.001
        exit_ = 11.0 * 0.999
        shares = int(100000 / entry)
        assert t.shares == shares
        assert t.entry_price == pytest.approx(entry, abs=1e-6)
        assert t.exit_price == pytest.approx(exit_, abs=1e-6)
        expect_pnl = (
            shares * exit_
            - shares * entry
            - shares * entry * 0.00025
            - shares * exit_ * 0.00025
        )
        assert t.pnl == pytest.approx(expect_pnl, abs=0.05)

    def test_one_word_board_deferred(self):
        """1/2 一字涨停 (open==high) 不追买, 顺延 1/3 开盘 10.5 成交。"""
        target = _mk_target(
            [
                (date(2024, 1, 1), 10.0, 10.5, 9.8, 10.2),
                (date(2024, 1, 2), 10.0, 10.0, 10.0, 10.0),  # 一字板
                (date(2024, 1, 3), 10.5, 11.0, 10.2, 10.8),
                (date(2024, 1, 4), 11.0, 11.5, 10.5, 11.2),
                (date(2024, 1, 5), 11.0, 11.2, 10.5, 10.8),
            ]
        )
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        r = run_backtest(target, sigs, ExitSpec(mode="time", hold_days=1), ZERO_COST)
        t = r.trades[0]
        assert t.entry_dt == date(2024, 1, 3) and t.entry_price == 10.5

    def test_reverse_exit(self):
        """1/1 买, 1/3 出现反向信号 → 1/4 开盘卖出。"""
        target = self._target5()
        sigs = [
            Signal(dt=date(2024, 1, 1), direction=1),
            Signal(dt=date(2024, 1, 3), direction=-1),
        ]
        r = run_backtest(target, sigs, ExitSpec(mode="reverse"), ZERO_COST)
        t = r.trades[0]
        assert t.exit_dt == date(2024, 1, 4) and t.exit_reason == "reverse"

    def test_profit_stop_intraday(self):
        """1/2 开盘 10 买入; 止盈 5% → 触发价 10.5; 1/2 high 10.4 未触, 1/3 high 11.0 盘中触达以 10.5 成交。"""
        target = _mk_target(
            [
                (date(2024, 1, 1), 10.0, 10.5, 9.8, 10.2),
                (date(2024, 1, 2), 10.0, 10.4, 9.9, 10.3),
                (date(2024, 1, 3), 10.5, 11.0, 10.2, 10.8),
                (date(2024, 1, 4), 11.0, 11.5, 10.5, 11.2),
                (date(2024, 1, 5), 11.0, 11.2, 10.5, 10.8),
            ]
        )
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        r = run_backtest(
            target,
            sigs,
            ExitSpec(mode="profit_stop", take_profit_pct=5.0, stop_loss_pct=3.0, hold_days=5),
            ZERO_COST,
        )
        t = r.trades[0]
        assert t.exit_reason == "take_profit"
        assert t.exit_dt == date(2024, 1, 3)
        assert t.exit_price == pytest.approx(10.5, abs=1e-6)

    def test_profit_stop_loss_priority_same_day(self):
        """同日高低点双触 → 保守按止损优先。"""
        target = _mk_target(
            [
                (date(2024, 1, 1), 10.0, 10.5, 9.8, 10.2),
                (date(2024, 1, 2), 10.0, 11.0, 9.5, 10.5),  # 买点当天巨震
                (date(2024, 1, 3), 10.5, 11.0, 10.2, 10.8),
                (date(2024, 1, 4), 11.0, 11.5, 10.5, 11.2),
            ]
        )
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        r = run_backtest(
            target,
            sigs,
            ExitSpec(mode="profit_stop", take_profit_pct=5.0, stop_loss_pct=5.0, hold_days=5),
            ZERO_COST,
        )
        t = r.trades[0]
        assert t.exit_reason == "stop_loss"
        assert t.exit_price == pytest.approx(9.5, abs=1e-6)  # 10×0.95

    def test_no_overlap_positions(self):
        """持仓中不重复开仓: 两个信号只做第一笔 (time 持有 3 天)。"""
        target = self._target5()
        sigs = [Signal(dt=date(2024, 1, 1), direction=1), Signal(dt=date(2024, 1, 2), direction=1)]
        r = run_backtest(target, sigs, ExitSpec(mode="time", hold_days=3), ZERO_COST)
        assert len(r.trades) == 1
        assert r.trades[0].entry_dt == date(2024, 1, 2)

    def test_position_ratio(self):
        target = self._target5()
        sigs = [Signal(dt=date(2024, 1, 1), direction=1)]
        r = run_backtest(
            target, sigs, ExitSpec(mode="time", hold_days=2), ZERO_COST, position_ratio=0.5
        )
        t = r.trades[0]
        # 半仓 50000 → 5000 股, pnl=5000×1=5000
        assert t.shares == 5000
        assert t.pnl == pytest.approx(5000.0, abs=0.01)

    def test_empty_target(self):
        r = run_backtest(pl.DataFrame(), [Signal(dt=date(2024, 1, 1), direction=1)])
        assert r.trades == [] and r.final_equity == 100000.0


# ---------------------------------------------------------------------------
# 网格寻优
# ---------------------------------------------------------------------------
class TestOptimizer:
    def test_grid_enumeration_and_split(self):
        index_df = pl.DataFrame(
            {
                "date": [date(2024, 1, i) for i in range(1, 11)],
                "open": [10.0] * 10,
                "high": [10.0] * 10,
                "low": [10.0] * 10,
                # 两次 -10% 急跌: 1/5 (train 段) 与 1/8 (validation 段)
                "close": [10.0, 10, 10, 10, 9.0, 10, 10, 9.0, 10, 10],
                "amount": [100.0] * 10,
            }
        )
        target = _mk_target(
            [
                (date(2024, 1, i), 10.0 + i * 0.1, 10.5 + i * 0.1, 9.8 + i * 0.1, 10.2 + i * 0.1)
                for i in range(1, 11)
            ]
        )
        res = optimize_grid(
            index_df,
            target,
            module_id="crash_speed",
            entry_grid={"threshold_pct": [5.0, 10.0]},
            exit_grid={"mode": ["time"], "hold_days": [1, 3]},
            cost=ZERO_COST,
            train_ratio=0.7,
        )
        # 2 入场 × 2 出场 = 4 组
        assert res["n_combos"] == 4
        # 排序按 validation 收益降序
        vals = [r["validation"]["total_return_pct"] for r in res["rows"]]
        assert vals == sorted(vals, reverse=True)
        # split 边界: 10 日 × 0.7 → idx=7 → split=1/8; 跌 1/5 归 train, 跌 1/8 归 validation
        assert res["split_date"] == date(2024, 1, 8).isoformat()
        for row in res["rows"]:
            assert row["train"]["n_trades"] + row["validation"]["n_trades"] >= row["full"]["n_trades"]
            assert row["overfit_flag"] is False  # train/validation 均为正收益不标红

    def test_overfit_flag(self):
        """train 赚 validation 崩塌 → 标红。"""
        index_df = pl.DataFrame(
            {
                "date": [date(2024, 1, i) for i in range(1, 11)],
                "open": [10.0] * 10,
                "high": [10.0] * 10,
                "low": [10.0] * 10,
                "close": [10.0, 10, 10, 10, 9.0, 10, 10, 9.0, 10, 10],
                "amount": [100.0] * 10,
            }
        )
        # 目标: 前 8 天稳步上涨 (train 跌后做多赚钱), 最后两天跳水 (validation 跌后做多亏钱)
        opens = [10.5 + 0.5 * i for i in range(1, 9)] + [15.5, 12.0]
        target = _mk_target(
            [
                (date(2024, 1, i), opens[i - 1], opens[i - 1] + 0.2, opens[i - 1] - 0.2,
                 opens[i - 1] + 0.1)
                for i in range(1, 11)
            ]
        )
        res = optimize_grid(
            index_df,
            target,
            module_id="crash_speed",
            entry_grid={"threshold_pct": [5.0]},
            exit_grid={"mode": ["time"], "hold_days": [1, 3]},
            cost=ZERO_COST,
            train_ratio=0.7,
        )
        flagged = [r for r in res["rows"] if r["overfit_flag"]]
        assert flagged, "train 赚 validation 亏的组合应被标红"
        for r in flagged:
            assert r["train"]["total_return_pct"] > 0
            assert r["validation"]["total_return_pct"] <= 0

    def test_unknown_module_raises(self):
        with pytest.raises(ValueError):
            optimize_grid(
                pl.DataFrame(), pl.DataFrame(), module_id="nope", entry_grid={}
            )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------
class TestRegistry:
    def test_builtins_registered(self):
        assert {"ma_state", "crash_speed", "volume_price"} <= set(REGISTRY)

    def test_duplicate_id_rejected(self):
        from app.custom.market.stats.registry import register

        class Dummy(MaStateModule):
            pass

        with pytest.raises(ValueError):
            register(Dummy())  # id 冲突 ma_state

    def test_unknown_exit_mode_in_grid(self):
        with pytest.raises(ValueError):
            optimize_grid(
                pl.DataFrame(
                    {"date": [date(2024, 1, 1)], "close": [1.0], "open": [1.0],
                     "high": [1.0], "low": [1.0], "amount": [1.0]}
                ),
                _mk_target([(date(2024, 1, 1), 1.0, 1.0, 1.0, 1.0)]),
                module_id="ma_state",
                entry_grid={"ma_period": [5]},
                exit_grid={"mode": ["nonsense"]},
            )
