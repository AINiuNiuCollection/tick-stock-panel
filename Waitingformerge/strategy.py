"D:\Code\githubProject\tick-stock-panel\backend\app\backtest\strategy.py"

 

@dataclass
class StrategyBacktestConfig:
    strategy_id: str
    symbols: list[str] | None
    start: date
    end: date
    params: dict | None = None
    overrides: dict | None = None
    # matching 为向后兼容入口; 显式传 entry_fill/exit_fill 时以二者为准。
    matching: Literal["close_t", "open_t+1"] = "open_t+1"
    entry_fill: Literal["close_t", "open_t+1"] | None = None
    exit_fill: Literal["close_t", "open_t+1", "signal_next_minute"] | None = None
    fees_pct: float = 0.0002
    commission_pct: float | None = None
    stamp_tax_pct: float | None = None
    slippage_bps: float = 5.0
    max_positions: int = 10
    max_exposure_pct: float = 1.0
    initial_capital: float = 1_000_000.0
    position_sizing: Literal["equal", "score_weight"] = "equal"
    mode: Literal["position", "full"] = "position"
    asset_type: str = "stock"
    holding_days: int = 5
    # 分钟K精确成交: 开启后用当日分钟K确定穿越价/VWAP (需 Pro+ 分钟K能力)
    minute_fill: bool = False
    # 同日买卖执行顺序: "auto"=按 entry_fill/exit_fill 时序自动判断,
    # "sell_first"=强制先卖后买(向后兼容), "buy_first"=强制先买后卖。
    fill_order: Literal["auto", "sell_first", "buy_first"] = "auto"
    # 市场环境过滤: {"states": ["strong",...], "min_score": 60}。
    # 强制 T-1: regime[T-1] 决定 entry[T](防未来函数)。None=不过滤。
    regime_filter: dict | None = None



******************************************************************************************************************************************************************
            # 环境过滤下正式起点=面板首日时顺延 (首日让渡为预热)
            if config.regime_filter:
                date_labels = tuple(
                    str(value)[:10]
                    for value in panel.get_column("date").unique().sort().to_list()
                )
                config = self._clamp_regime_formal_start(config, date_labels)
            formal_range = self._date_range_mask(panel, config.start, config.end)
            if not formal_range.any():
                return _err("正式回测区间内无数据")
            feature_width = int(panel.width)

        matcher_config = MatcherConfig(
            matching=config.matching,
            entry_fill=config.entry_fill,
            exit_fill=config.exit_fill,
            fees_pct=config.fees_pct,
            commission_pct=config.commission_pct,
            stamp_tax_pct=config.stamp_tax_pct,
            slippage_bps=config.slippage_bps,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            trailing_stop_pct=trailing_stop,
            trailing_take_profit_activate_pct=trailing_take_profit_activate,
            trailing_take_profit_drawdown_pct=trailing_take_profit_drawdown,
            max_hold_days=max_hold_days,
            max_positions=config.max_positions,
            max_exposure_pct=config.max_exposure_pct,
            score_min=score_min,
            score_max=score_max,
            initial_capital=config.initial_capital,
            position_sizing=config.position_sizing,
            minute_fill=config.minute_fill,
            cooldown_loss_streak=cooldown_loss_streak,
            cooldown_days=cooldown_days,
            fill_order=config.fill_order,
        )






******************************************************************************************************************************************************************

        matcher_config = MatcherConfig(
            matching=config.matching,
            entry_fill="close_t",
            exit_fill=config.exit_fill,
            fees_pct=config.fees_pct,
            commission_pct=config.commission_pct,
            stamp_tax_pct=config.stamp_tax_pct,
            slippage_bps=config.slippage_bps,
            stop_loss_pct=stop_loss,
            take_profit_pct=take_profit,
            trailing_stop_pct=trailing_stop,
            trailing_take_profit_activate_pct=trailing_take_profit_activate,
            trailing_take_profit_drawdown_pct=trailing_take_profit_drawdown,
            max_hold_days=max_hold_days,
            max_positions=config.max_positions,
            max_exposure_pct=config.max_exposure_pct,
            score_min=score_min,
            score_max=score_max,
            initial_capital=config.initial_capital,
            position_sizing=config.position_sizing,
            # 分钟策略的成交价由 entry_price_override 提供 (触发分钟收盘),
            # 不再叠加日线口径的分钟成交细化。
            minute_fill=False,
            cooldown_loss_streak=cooldown_loss_streak,
            cooldown_days=cooldown_days,
            fill_order=config.fill_order,
        )

