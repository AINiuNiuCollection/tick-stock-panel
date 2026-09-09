"""连板股·改进版 — 连板数2~4板追涨，跌破MA10次日确认退出

在原连板股策略基础上增加连板上限(避免5板以上高位风险)，
退出条件改为跌破10日均线且次日确认，止损增加回撤10%。
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
    "id": "custom_consecutive_limit_ups_v2",
    "name": "连板股·改进版",
    "description": "连板数2~4板追涨，跌破MA10次日确认退出，5%止损+10%回撤止损",
    "tags": ["涨停", "连板"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "price_max": 200,
        "market_cap_min": 10e8,
        "amount_min": 0.5e8,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {
            "id": "min_boards",
            "label": "最少连板数",
            "type": "int",
            "default": 2,
            "min": 1,
            "max": 10,
            "step": 1,
        },
        {
            "id": "max_boards",
            "label": "最多连板数",
            "type": "int",
            "default": 4,
            "min": 1,
            "max": 20,
            "step": 1,
        },
    ],
    "scoring": {
        "consecutive_limit_ups": 0.5,
        "change_pct": 0.3,
        "amount": 0.2,
    },
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_limit_up"]
EXIT_SIGNALS = ["signal_ma10_breakdown"]
STOP_LOSS = -0.05
TRAILING_STOP = -0.10
MAX_HOLD_DAYS = 20

RULES = """
1. 连板数在2~4之间，追涨强势连板股但避免5板以上高位风险
2. 跌破10日均线且次日仍未收回时退出
3. 止损: 买入价下跌5% 或 从最高价回撤10%
4. 最长持有20个交易日
"""


class ConsecutiveLimitUpsV2Strategy:
    """连板股·改进版矩阵策略。"""

    def required_fields(self) -> frozenset[str]:
        return frozenset({"consecutive_limit_ups", "close", "ma10"})

    def required_warmup_bars(self, params: dict) -> int:
        return 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        min_boards = int(params.get("min_boards", 2))
        max_boards = int(params.get("max_boards", 4))

        # ── 入场: 连板数在 [min, max] 区间 ──
        boards = matrix_feature(market, "consecutive_limit_ups")
        entry = (boards >= min_boards) & (boards <= max_boards)

        # ── 退出: 跌破MA10 且 前一日也低于MA10 (次日确认) ──
        ma10 = matrix_feature(market, "ma10")
        below_ma10 = market.close < ma10
        prev_below = shift(below_ma10.astype(np.float32), 1)
        exit_ = below_ma10 & (prev_below > 0.5)

        # ── 评分由引擎 MatrixStrategyPipeline 根据 META.scoring 自动计算 ──
        # 策略无需手动计算 score，返回 None 即可，引擎用 build_matrix_score 做归一化

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_limit_up",),
            exit_signal_ids=("signal_ma10_breakdown",),
        )


MATRIX_STRATEGY = ConsecutiveLimitUpsV2Strategy()
