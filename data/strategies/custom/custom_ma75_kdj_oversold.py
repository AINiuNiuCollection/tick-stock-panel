"""MA75+KDJ超卖 — 中期趋势上方 KDJ 超卖低吸

收盘价站上 MA75 (中期多头) + KDJ 的 J 值 < 25 (短期超卖) + 当日涨跌幅在 ±3.5% 以内 (非涨停非暴跌) + 总市值 > 30 亿
+ 过去10个交易日内至少有一天单日涨幅 > 8% (有爆发力)。
逻辑: 在中期上升趋势中, 利用 KDJ 超卖信号捕捉短线低吸机会, 且要求近期出现过单日大涨(有资金关注)。
"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "custom_ma75_kdj_oversold",
    "name": "MA75+KDJ超卖",
    "description": "收盘价站上MA75 + KDJ的J值<25 + 涨跌幅±3.5%以内 + 总市值>30亿 + 近10日有过单日涨幅>8%, 中期趋势上方超卖低吸",
    "tags": ["超卖", "KDJ", "均线", "低吸"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "price_max": 200,
        "market_cap_min": 30e8,
        "amount_min": 0.5e8,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {
            "id": "ma_period",
            "label": "均线周期",
            "type": "int",
            "default": 75,
            "min": 20,
            "max": 250,
            "step": 5,
        },
        {
            "id": "kdj_j_max",
            "label": "KDJ J值上限",
            "type": "float",
            "default": 25.0,
            "min": 0.0,
            "max": 50.0,
            "step": 1.0,
        },
        {
            "id": "change_pct_abs_max",
            "label": "涨跌幅绝对值上限(%)",
            "type": "float",
            "default": 3.5,
            "min": 1.0,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "surge_pct_min",
            "label": "近10日单日涨幅下限(%)",
            "type": "float",
            "default": 8.0,
            "min": 3.0,
            "max": 20.0,
            "step": 0.5,
        },
        {
            "id": "surge_lookback_days",
            "label": "涨幅回看天数",
            "type": "int",
            "default": 10,
            "min": 3,
            "max": 30,
            "step": 1,
        },
    ],
    "scoring": {
        "kdj_j": 0.4,
        "change_pct": 0.3,
        "vol_ratio_5d": 0.3,
    },
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = []
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.05
TRAILING_STOP = -0.10
MAX_HOLD_DAYS = 15
COOLDOWN_LOSS_STREAK = 2
COOLDOWN_DAYS = 3

RULES = """
1. 收盘价站上MA75, 确认中期多头趋势
2. KDJ的J值小于25, 短期超卖低吸信号
3. 当日涨跌幅在 ±3.5% 以内, 排除涨停追高和暴跌接刀
4. 总市值大于30亿元, 排除小盘垃圾股
5. 过去10个交易日内至少有一天单日涨幅超过8%, 确保近期有资金爆发力
6. 止损: 买入价下跌5% 或 从最高价回撤10%
7. 最长持有15个交易日
"""


class Ma75KdjOversoldStrategy:
    """MA75+KDJ超卖矩阵策略。"""

    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "kdj_j"})

    def required_warmup_bars(self, params: dict) -> int:
        ma_period = int(params.get("ma_period", 75))
        lookback = int(params.get("surge_lookback_days", 10))
        return max(ma_period + 10, 80 + lookback)

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma_period = int(params.get("ma_period", 75))
        j_max = float(params.get("kdj_j_max", 25.0))
        change_abs = float(params.get("change_pct_abs_max", 3.5)) / 100.0
        surge_threshold = float(params.get("surge_pct_min", 8.0)) / 100.0
        lookback = int(params.get("surge_lookback_days", 10))

        # ── 入场条件 ──
        # 1. 收盘价 > MA75 (中期多头)
        ma = matrix_feature(market, f"ma{ma_period}")
        entry = market.close > ma

        # 2. KDJ J值 < j_max (短期超卖)
        kdj_j = matrix_feature(market, "kdj_j")
        entry &= kdj_j < j_max

        # 3. 涨跌幅在 ±change_abs 以内
        change_pct = matrix_feature(market, "change_pct")
        entry &= (change_pct > -change_abs) & (change_pct < change_abs)

        # 4. 过去 lookback 个交易日内至少有一天单日涨幅 > surge_threshold
        has_surge = np.zeros(market.shape, dtype=bool)
        for d in range(1, lookback + 1):
            has_surge |= shift(change_pct, d) > surge_threshold
        entry &= has_surge

        # ── 退出条件: 跌破MA20 ──
        ma20 = matrix_feature(market, "ma20")
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = Ma75KdjOversoldStrategy()
