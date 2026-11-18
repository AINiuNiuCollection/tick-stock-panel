"""上证-异动波段策略 (个人策略) — 上证指数择时信号

反推自 D:\\MyFile\\潘扬-日线级别-异动波段策略.html 的 112 笔交易数据。

核心规则 (反推近似):
- 信号源: 上证指数 (000001.SH, 写死在回测请求的 symbols 参数中)
- 入场: "异动动量" mom > buy_mom_thr (反推 p50=4.23, p10=1.56)
  mom 字段在 HTML 中是策略私有的异动指标, 精确算法未知, 此处用
  (close - EMA_period) / EMA_period * 100 近似 (指数动量百分比)。
- 出场: mom < 0 (反推 sd 当日 97% 为负) 或 收盘跌破 MA{ma_period} (反推 66% 跌破) 或
  持仓达 max_hold_days (反推 days max=30)。
- 冷却: 上次平仓后 cooldown_days 日内不再开仓 (反推 gap 中位数 11, p25=4)。

跨资产说明:
  本策略在信号源 (上证指数) 上计算买卖信号, 回测引擎在指数自身行情上执行。
  实际交易标的 (如 512100.SH 中证1000ETF) 的盈亏由前端用信号日对齐到交易标的
  K 线重算 (matching=open_t+1, 信号次日开盘成交)。后端只负责信号生成 + 指数回测。

均线天数 ma_period 参数化: 默认 5, 可配 5/10/20。
"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)

META = {
    "id": "custom_shang_zheng_anomaly_wave",
    "name": "上证-异动波段(指数择时)",
    "description": "上证指数异动动量择时信号 (反推自回测HTML, 逼近而非严格一致)",
    "tags": ["异动", "波段", "动量", "指数择时", "个人策略"],
    "asset_types": ["index"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "mom_period",
            "label": "动量EMA周期",
            "type": "int",
            "default": 5,
            "min": 3,
            "max": 20,
            "step": 1,
        },
        {
            "id": "buy_mom_thr",
            "label": "买入动量阈值(%)",
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.1,
        },
        {
            "id": "ma_period",
            "label": "卖出均线天数",
            "type": "int",
            "default": 5,
            "min": 3,
            "max": 60,
            "step": 1,
        },
        {
            "id": "use_ma_exit",
            "label": "启用跌破MA卖出",
            "type": "bool",
            "default": True,
        },
        {
            "id": "use_mom_neg_exit",
            "label": "启用动量转负卖出",
            "type": "bool",
            "default": True,
        },
        {
            "id": "max_hold_days",
            "label": "最大持仓天数",
            "type": "int",
            "default": 30,
            "min": 5,
            "max": 60,
            "step": 1,
        },
        {
            "id": "cooldown_days",
            "label": "冷却期天数",
            "type": "int",
            "default": 5,
            "min": 0,
            "max": 30,
            "step": 1,
        },
    ],
    "scoring": {"momentum_20d": 0.5, "change_pct": 0.3, "amount": 0.2},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_anomaly_breakout"]
EXIT_SIGNALS = ["signal_momentum_exit"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 30


def _calc_momentum_pct(market: MarketDataMatrix, period: int) -> np.ndarray:
    """异动动量近似: (close - EMA_period) / EMA_period * 100。

    复用 matrix_feature 的 ema{N}_bias (返回 (close-EMA)/EMA), 乘 100 转百分比。
    与 HTML 中 mom 字段语义接近: bd 当日 mom/close% p50=0.0652, p10=0.0192。
    """
    bias = matrix_feature(market, f"ema{period}_bias")
    return np.nan_to_num(bias, nan=0.0, posinf=0.0, neginf=0.0) * 100.0


class ShangZhengAnomalyWaveMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "raw_close"})

    def required_warmup_bars(self, params: dict) -> int:
        period = int(params.get("mom_period", 5))
        ma_period = int(params.get("ma_period", 5))
        cooldown = int(params.get("cooldown_days", 5))
        return max(period * 3, ma_period, 20) + cooldown

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        period = int(params.get("mom_period", 5))
        buy_thr = float(params.get("buy_mom_thr", 2.0))
        ma_period = int(params.get("ma_period", 5))
        use_ma_exit = bool(params.get("use_ma_exit", True))
        use_mom_neg_exit = bool(params.get("use_mom_neg_exit", True))

        mom_pct = _calc_momentum_pct(market, period)
        ma = matrix_feature(market, f"ma{ma_period}")

        # 入场: mom_pct > buy_thr
        entry_signal = mom_pct > buy_thr

        # 出场: mom_pct < 0 或 close < MA{ma_period}
        exit_signal = np.zeros(market.shape, dtype=bool)
        if use_mom_neg_exit:
            exit_signal |= mom_pct < 0
        if use_ma_exit:
            exit_signal |= market.close < ma

        return make_signal_matrix(
            market.shape,
            entry=entry_signal.astype(np.uint8),
            exit=exit_signal.astype(np.uint8),
            entry_signal_code=np.where(entry_signal, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_signal, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_anomaly_breakout",),
            exit_signal_ids=("signal_momentum_exit",),
        )


MATRIX_STRATEGY = ShangZhengAnomalyWaveMatrixStrategy()
