"""M4 均线异动波段 (ma_anomaly_wave) 单元测试 — 潘扬异动波段口径。"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from app.custom.market.stats.anomaly_wave import AnomalyWaveModule


def _mk_df(closes: list[float], start: date = date(2026, 1, 5)) -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame(
        {
            "date": [start + timedelta(days=i) for i in range(n)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000.0] * n,
            "amount": [1000.0] * n,
        }
    )


D = AnomalyWaveModule()


def test_registry_id():
    assert D.id == "ma_anomaly_wave"
    # 参数默认值与潘扬反推口径一致
    p = D.resolve_params(None)
    assert p["mom_period"] == 5
    assert p["buy_mom_thr"] == 2.0
    assert p["ma_period"] == 5
    assert p["cooldown_days"] == 5


def test_breakout_entry_signal():
    # 平稳 100 → 跳涨 110: 乖离率远超 2%, 应产出 +1
    closes = [100.0] * 10 + [110.0]
    signals = D.to_signals(_mk_df(closes), {})
    entries = [s for s in signals if s.direction == 1]
    assert len(entries) == 1
    assert entries[0].dt == date(2026, 1, 15)
    # 手工核算 EMA(5, 首值种子): 跳涨当根 EMA=110*(2/6)+100*(4/6)=103.33
    # mom=(110-103.33)/103.33*100≈6.45% > 2%
    assert "6.45%" in entries[0].note


def test_momentum_negative_exit_signal():
    # 先涨后回落跌破 EMA → mom_pct < 0 → -1
    closes = [100.0 + i * 1.0 for i in range(10)] + [104.0, 103.0]
    signals = D.to_signals(_mk_df(closes), {})
    exits = [s for s in signals if s.direction == -1]
    assert any("动量转负" in s.note for s in exits)


def test_ma_break_exit_signal():
    # 长期高位横盘后跳水下穿 MA5 → -1 跌破MA
    closes = [100.0] * 20 + [90.0]
    signals = D.to_signals(_mk_df(closes), {})
    exits = [s for s in signals if s.direction == -1]
    assert any("跌破MA5" in s.note for s in exits)


def test_cooldown_suppresses_repeated_entries():
    # 连续异动上涨: 冷却期 5 内第二个 +1 被抑制
    closes = [100.0] * 5 + [110.0] * 2 + [121.0, 133.0]
    signals = D.to_signals(_mk_df(closes), {})
    entries = [s for s in signals if s.direction == 1]
    assert len(entries) == 1
    # 冷却期设 0 后, 每根异动 K 都可触发
    signals2 = D.to_signals(_mk_df(closes), {"cooldown_days": 0})
    entries2 = [s for s in signals2 if s.direction == 1]
    assert len(entries2) >= 2


def test_insufficient_data_returns_empty():
    assert D.to_signals(_mk_df([100.0, 101.0]), {}) == []


def test_unknown_param_rejected():
    try:
        D.resolve_params({"nope": 1})
        raise AssertionError("should reject unknown param")
    except ValueError:
        pass
