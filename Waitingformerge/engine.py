@dataclass
class MatcherConfig:
    # matching 为向后兼容入口: 仅传 matching 时, entry_fill/exit_fill 都取 matching 的值。
    # 显式传入 entry_fill/exit_fill 时以二者为准 (允许建仓/清仓口径不同)。
    matching: Literal["close_t", "open_t+1"] = "close_t"
    entry_fill: Literal["close_t", "open_t+1"] | None = None
    exit_fill: Literal["close_t", "open_t+1", "signal_next_minute"] | None = None
    # 成本模型: 优先使用拆分口径 (佣金双边 + 印花税仅卖出 + 滑点双边)。
    # 未设 commission_pct 时回退到 fees_pct 作为双边佣金 (向后兼容, 无印花税)。
    fees_pct: float = 0.0002
    commission_pct: float | None = None
    stamp_tax_pct: float | None = None
    slippage_bps: float = 5.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None
    trailing_take_profit_activate_pct: float | None = None
    trailing_take_profit_drawdown_pct: float | None = None
    max_hold_days: int | None = None
    # 连亏冷却: 连续亏损 N 笔后暂停开仓 X 个交易日
    cooldown_loss_streak: int | None = None
    cooldown_days: int | None = None
    max_positions: int = 10
    max_exposure_pct: float = 1.0
    score_min: float | None = None
    score_max: float | None = None
    initial_capital: float = 1_000_000.0
    position_sizing: Literal["equal", "score_weight"] = "equal"
    # 分钟K精确成交: 开启后, 信号触发日的成交价用当日分钟K优化
    # (有参考线→穿越价, 无参考线→VWAP)。数据缺失时降级为日K口径。
    minute_fill: bool = False

    def __post_init__(self) -> None:
        # 解析最终口径: 优先 entry_fill/exit_fill, 否则回退到 matching (向后兼容)。
        if self.entry_fill is None:
            self.entry_fill = self.matching
        if self.exit_fill is None:
            self.exit_fill = self.matching

    def _commission_pct(self) -> float:
        # commission_pct 显式给出时优先, 否则回退 fees_pct (向后兼容双边佣金)。
        return self.commission_pct if self.commission_pct is not None else self.fees_pct

    def buy_cost_pct(self) -> float:
        # 买入腿: 佣金 + 滑点。
        return self._commission_pct() + self.slippage_bps / 10000.0

    def sell_cost_pct(self) -> float:
        # 卖出腿: 佣金 + 印花税 + 滑点。印花税未设时为 0 (向后兼容)。
        stamp = self.stamp_tax_pct if self.stamp_tax_pct is not None else 0.0
        return self._commission_pct() + stamp + self.slippage_bps / 10000.0




















nl_amount < 0:
                    consec_losses += 1
                    if consec_losses >= config.cooldown_loss_streak:
                        cooldown_until = time_id + 1 + config.cooldown_days
                        consec_losses = 0
                else:
                    consec_losses = 0

        def _try_sell(
            time_id: int,
            asset_id: int,
            reason: str,
            signal_date: str,
            sold_today: set[int],
            override: float | None = None,
        ) -> bool:
            signal_id = (
                _signal_id(int(matrix.exit_signal_code[time_id, asset_id]), matrix.exit_signal_ids)
                if reason == "signal" else None
            )
            minute_trigger = config.exit_fill == "signal_next_minute" and reason == "signal"
            if minute_trigger and override is None:
                pos = positions[asset_id]
                if pos.get("pending_exit_next_open"):
                    override = float(matrix.open[time_id, asset_id])
                else:
                    override = _minute_trigger_price(time_id, asset_id)
                    if override is None:
                        _mark_pending(asset_id, reason, signal_date, signal_id, next_open=True)
                        _count("sell_minute_trigger_fallback")
                        return False
            ok, blocked = _can_sell(time_id, asset_id, override)
            if not ok:
                _mark_pending(
                    asset_id,
                    reason,
                    signal_date,
                    signal_id,
                    next_open=minute_trigger,
                )
                _count(blocked)
                return False
            _sell(time_id, asset_id, reason, signal_date, sold_today, override)
            return True

        for time_id, date_label in enumerate(matrix.timestamp_labels):
            date_text = date_label[:10]
            if time_id % 20 == 0:
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("回测被用户取消 (第 %d/%d 天)", time_id, time_count)
                    break
                if progress_cb is not None:
                    try:
                        progress_cb({
                            "day": time_id + 1,
                            "total": time_count,
                            "date": date_text,
                            "equity": round(cash + _market_value(), 2),
                        })
                    except Exception:
                        pass

            sold_today: set[int] = set()
            for pos in positions.values():
                pos["hold_days"] += 1

            for asset_id in list(positions):
                pos = positions.get(asset_id)
                if pos is None or pos.get("pending_exit_reason") or pos["entry_date"] == date_text:
                    continue
                if not matrix.tradable[time_id, asset_id] or pos["entry_price"] <= 0:
                    continue
                open_price = float(matrix.open[time_id, asset_id])
                low_price = float(matrix.low[time_id, asset_id])
                high_price = float(matrix.high[time_id, asset_id])
                entry_price = float(pos["entry_price"])
                peak_price = float(pos["max_high"])
                risk_lines: list[tuple[float, str]] = []
                if config.stop_loss_pct is not None:
                    risk_lines.append((entry_price * (1 - abs(config.stop_loss_pct)), "stop_loss"))
                if config.trailing_stop_pct is not None:
                    risk_lines.append((peak_price * (1 - abs(config.trailing_stop_pct)), "trailing_stop"))
                activate = config.trailing_take_profit_activate_pct
                drawdown = config.trailing_take_profit_drawdown_pct
                if activate is not None and drawdown is not None and peak_price > entry_price:
                    if peak_price / entry_price - 1 >= abs(float(activate)):
                        risk_lines.append((peak_price * (1 - abs(float(drawdown))), "trailing_take_profit"))
                valid_lines = [(line, reason) for line, reason in risk_lines if _valid_price(line)]
                if valid_lines:
                    stop_price, reason = max(valid_lines, key=lambda item: item[0])
                    override = None
                    if _valid_price(open_price) and open_price <= stop_price:
                        override = open_price
                    elif _valid_price(low_price) and low_price <= stop_price:
                        override = stop_price
                    if override is not None:
                        _try_sell(time_id, asset_id, reason, date_text, sold_today, override)
                        continue
                if config.take_profit_pct is not None:
                    take_profit = entry_price * (1 + abs(float(config.take_profit_pct)))
                    if _valid_price(open_price) and open_price >= take_profit:
                        _try_sell(time_id, asset_id, "take_profit", date_text, sold_today, open_price)
                    elif _valid_price(high_price) and high_price >= take_profit:
                        _try_sell(time_id, asset_id, "take_profit", date_text, sold_today, take_profit)

            for asset_id in list(positions):
                pos = positions.get(asset_id)
                if pos is None:
                    continue
                reason = ""
                signal_date = date_text
                if pos.get("pending_exit_reason"):
                    reason = str(pos["pending_exit_reason"])
                    signal_date = str(pos.get("pending_exit_signal_date") or date_text)
                elif matrix.exit[time_id, asset_id]:
                    reason = "signal"
                    signal_date = _signal_date(int(matrix.exit_signal_time[time_id, asset_id]), date_text)
                elif config.max_hold_days is not None and pos["hold_days"] >= config.max_hold_days:
                    reason = "max_hold"
                elif time_id == time_count - 1:
                    reason = "end"
                if reason:
                    _try_sell(time_id, asset_id, reason, signal_date, sold_today)

            if time_id < time_count - 1 and max_positions > 0:
                # ── 连亏冷却: 冷却期内禁止开仓 ──
                if config.cooldown_loss_streak is not None and config.cooldown_loss_streak > 0 and config.cooldown_days is not None and time_id < cooldown_until:
                    for _ in np.flatnonzero(matrix.entry[time_id]):
                        _count("buy_cooldown")
                else:
                    candidates: list[tuple[int, float]] = []
                    for asset_id in np.flatnonzero(matrix.entry[time_id]):
                        asset = int(asset_id)
                        if asset in positions:
                            continue
                        if asset in sold_today:
                            _count("buy_same_day_reentry")
                            continue
                        ok, blocked = _can_buy(time_id, asset)
                        if not ok:
                            _count(blocked)
                            continue
                        score = _matrix_entry_score(matrix, time_id, asset)
                        if config.score_min is not None and score < config.score_min:
                            _count("buy_score_filter")
                            continue
                        if config.score_max is not None and score > config.score_max:
                            _count("buy_score_filter")
                            continue
                        candidates.append((asset, score))
                    candidates.sort(key=lambda item: item[1], reverse=True)
                    slots = max_positions - len(positions)
                    if slots <= 0:
                        execution_stats["buy_no_slot"] += len(candidates)
                    elif candidates:
                        selected = candidates[:slots]
                        market_value_before = _market_value()
                        equity_before = cash + market_value_before
                        target_value = equity_before * max_exposure_pct / max_positions
                        exposure_capacity = equity_before * max_exposure_pct - market_value_before
                        if equity_before <= 0 or exposure_capacity <= 0 or max_exposure_pct <= 0:
                            execution_stats["buy_exposure"] += len(selected)
                        else:
                            weights = np.repeat(1 / len(selected), len(selected))
                            if config.position_sizing == "score_weight":
                                raw_weights = np.array([max(item[1], 0.0) for item in selected])
                                if raw_weights.sum() > 0:
                                    weights = raw_weights / raw_weights.sum()
                            total_budget = min(cash, exposure_capacity, target_value * len(selected))
                            for (asset_id, entry_score), weight in zip(selected, weights):
                                if len(positions) >= max_positions:
                                    _count("buy_no_slot")
                                    break
                                market_value = _market_value()
                                equity = cash + market_value
                                capacity = equity * max_exposure_pct - market_value
                                allocation = min(total_budget * float(weight), target_value, cash, capacity)
                                if allocation <= 0:
                                    _count("buy_exposure")
                                    continue
                                entry_price = _refill_price(
                                    time_id, asset_id, "buy", float(entry_prices[time_id, asset_id])
                                )
                                shares = np.floor(allocation / (entry_price * (1 + buy_cost_pct)) / 100) * 100
                                entry_value = shares * entry_price * (1 + buy_cost_pct)
                                if shares <= 0:
                                    _count("buy_lot_size")
                                    continue
                                if entry_value > cash + 1e-6:
                                    _count("buy_cash")
                                    continue
                                if entry_value > capacity + 1e-6:
                                    _count("buy_exposure")
                                    continue
                                cash -= entry_value
                                positions[asset_id] = {
                                    "entry_date": date_text,
                                    "entry_signal_date": _signal_date(
                                        int(matrix.entry_signal_time[time_id, asset_id]), date_text
                                    ),
                                    "entry_signal_id": _signal_id(
                                        int(matrix.entry_signal_code[time_id, asset_id]), matrix.entry_signal_ids
                                    ),
                                    "entry_price": entry_price,
                                    "entry_value": entry_value,
                                    "shares": shares,
                                    "lots": shares / 100,
                                    "position_pct": entry_value / equity_before if equity_before > 0 else 0.0,
                                    "entry_score": entry_score,
                                    "max_high": entry_price,
                                    "hold_days": 0,
                                    "pending_exit_reason": None,
                                    "pending_exit_signal_date": None,
                                    "pending_exit_signal_id": None,
                                    "pending_exit_next_open": False,
                                    "blocked_exit_days": 0,
                                }












