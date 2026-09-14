    def _simulate_portfolio_matrix(
        self,
        matrix: MarketMatrix,
        config: MatcherConfig,
        progress_cb: "Callable[[dict], None] | None",
        cancel_event: "threading.Event | None",
        options: SimulationOptions | None = None,
    ) -> SimResult:
        options = options or SimulationOptions()
        time_count, asset_count = matrix.shape
        entry_prices = self._resolve_entry_prices(matrix, config)
        exit_prices = matrix.open if config.exit_fill == "open_t+1" else matrix.close
        buy_cost_pct = config.buy_cost_pct()
        sell_cost_pct = config.sell_cost_pct()
        cash = float(config.initial_capital)
        peak = cash
        max_positions = max(int(config.max_positions), 0)
        max_exposure_pct = min(max(float(config.max_exposure_pct), 0.0), 1.0)
        positions: dict[int, dict] = {}
        last_close = np.full(asset_count, np.nan, dtype=np.float64)
        trades: list[TradeRecord] = []
        equity_curve: list[dict] = []
        drawdown_curve: list[dict] = []
        equity_values: list[float] = []
        exposure_values: list[float] = []
        execution_stats = {
            "buy_invalid_price": 0,
            "buy_suspended": 0,
            "buy_limit_up": 0,
            "buy_no_slot": 0,
            "buy_cash": 0,
            "buy_lot_size": 0,
            "buy_same_day_reentry": 0,
            "buy_exposure": 0,
            "buy_score_filter": 0,
            # ── 连亏冷却: 买入被冷却拦截的次数 (诊断指标) ──
            "buy_cooldown": 0,
            "sell_invalid_price": 0,
            "sell_suspended": 0,
            "sell_limit_down": 0,
            "pending_exit": 0,
        }

        # ── 连亏冷却状态 ──
        # consec_losses: 连续亏损笔数, 达到阈值后触发冷却期
        # cooldown_until: 冷却截止 time_id, time_id < cooldown_until 时禁止开仓
        # 初始化在主循环前 (与原始代码在 _try_sell 后初始化等价, 因 nonlocal 闭包捕获)
        consec_losses = 0
        cooldown_until = -1

        minute_cache: dict = {}
        if config.minute_fill:
            trigger_times, trigger_assets = np.nonzero(matrix.entry | matrix.exit)
            trigger_dates = {matrix.timestamp_labels[int(t)][:10] for t in trigger_times}
            trigger_symbols = {matrix.symbols[int(a)] for a in trigger_assets}
            if trigger_dates and trigger_symbols:
                asset_type = "etf" if all(
                    symbol.endswith(".SH") and symbol.startswith("5")
                    for symbol in list(trigger_symbols)[:5]
                ) else "stock"
                loaded = self._load_minute_for_fills(
                    self.repo, list(trigger_symbols), trigger_dates, asset_type,
                )
                minute_cache = {key: value for key, value in loaded.items() if value is not None and len(value) > 0}

        def _count(key: str) -> None:
            execution_stats[key] = execution_stats.get(key, 0) + 1

        def _valid_price(value) -> bool:
            return bool(np.isfinite(value) and value > 0)

        def _signal_id(code: int, signal_ids: tuple[str, ...]) -> str | None:
            return signal_ids[code] if 0 <= code < len(signal_ids) else None

        def _signal_date(signal_time: int, fallback: str) -> str:
            return matrix.timestamp_labels[signal_time][:10] if signal_time >= 0 else fallback

        def _market_value() -> float:
            total = 0.0
            for asset, pos in positions.items():
                mark = last_close[asset]
                if not _valid_price(mark):
                    mark = pos["entry_price"]
                total += pos["shares"] * mark
            return total

        def _refill_price(time_id: int, asset_id: int, side: str, daily_price: float) -> float:
            if not config.minute_fill or not minute_cache:
                return daily_price
            key = (matrix.symbols[asset_id], matrix.timestamp_labels[time_id][:10])
            minute_rows = minute_cache.get(key)
            if minute_rows is None:
                return daily_price
            reference = float(matrix.reference_price[time_id, asset_id])
            precise = self._resolve_minute_fill(
                minute_rows,
                reference if _valid_price(reference) else None,
                side,
            )
            return precise if precise is not None else daily_price

        def _minute_trigger_price(time_id: int, asset_id: int) -> float | None:
            if not config.minute_fill or not minute_cache:
                return None
            key = (matrix.symbols[asset_id], matrix.timestamp_labels[time_id][:10])
            minute_rows = minute_cache.get(key)
            if minute_rows is None:
                return None
            reference = float(matrix.reference_price[time_id, asset_id])
            return self._resolve_minute_exit_trigger(
                minute_rows,
                reference if _valid_price(reference) else None,
            )

        def _one_price_limit(time_id: int, asset_id: int, direction: str) -> bool:
            if not matrix.tradable[time_id, asset_id]:
                return False
            prices = (
                float(matrix.open[time_id, asset_id]),
                float(matrix.high[time_id, asset_id]),
                float(matrix.low[time_id, asset_id]),
                float(matrix.close[time_id, asset_id]),
            )
            if not all(_valid_price(value) for value in prices):
                return False
            same_price = max(prices) - min(prices) <= max(abs(prices[3]) * 1e-4, 0.01)
            flag = matrix.limit_up_locked if direction == "up" else matrix.limit_down_locked
            return bool(flag[time_id, asset_id]) and same_price

        def _can_buy(time_id: int, asset_id: int) -> tuple[bool, str]:
            if not matrix.tradable[time_id, asset_id]:
                return False, "buy_suspended"
            if not _valid_price(entry_prices[time_id, asset_id]):
                return False, "buy_invalid_price"
            if _one_price_limit(time_id, asset_id, "up"):
                return False, "buy_limit_up"
            return True, ""

        def _can_sell(time_id: int, asset_id: int, override: float | None = None) -> tuple[bool, str]:
            if not matrix.tradable[time_id, asset_id]:
                return False, "sell_suspended"
            price = override if override is not None else exit_prices[time_id, asset_id]
            if not _valid_price(price):
                return False, "sell_invalid_price"
            if _one_price_limit(time_id, asset_id, "down"):
                return False, "sell_limit_down"
            return True, ""

        def _mark_pending(
            asset_id: int,
            reason: str,
            signal_date: str,
            signal_id: str | None = None,
            next_open: bool = False,
        ) -> None:
            pos = positions[asset_id]
            if not pos.get("pending_exit_reason"):
                pos["pending_exit_reason"] = reason
                pos["pending_exit_signal_date"] = signal_date
                pos["pending_exit_signal_id"] = signal_id
                _count("pending_exit")
            if next_open:
                pos["pending_exit_next_open"] = True
            pos["blocked_exit_days"] += 1

        def _sell(
            time_id: int,
            asset_id: int,
            reason: str,
            signal_date: str,
            sold_today: set[int],
            override: float | None = None,
        ) -> None:
            nonlocal cash, consec_losses, cooldown_until
            pos = positions.pop(asset_id)
            exit_price = float(override) if override is not None else _refill_price(
                time_id, asset_id, "sell", float(exit_prices[time_id, asset_id])
            )
            exit_value = pos["shares"] * exit_price * (1 - sell_cost_pct)
            cash += exit_value
            pnl_amount = exit_value - pos["entry_value"]
            pnl_pct = pnl_amount / pos["entry_value"] if pos["entry_value"] > 0 else 0.0
            sold_today.add(asset_id)
            trades.append(TradeRecord(
                symbol=matrix.symbols[asset_id],
                name=matrix.names[asset_id],
                entry_date=pos["entry_date"],
                exit_date=matrix.timestamp_labels[time_id][:10],
                entry_price=round(float(pos["entry_price"]), 4),
                exit_price=round(exit_price, 4),
                pnl_pct=round(float(pnl_pct), 6),
                duration=int(pos["hold_days"]),
                exit_reason=reason,
                shares=round(float(pos["shares"]), 4),
                lots=round(float(pos["lots"]), 2),
                position_pct=round(float(pos["position_pct"]), 6),
                entry_value=round(float(pos["entry_value"]), 2),
                exit_value=round(float(exit_value), 2),
                pnl_amount=round(float(pnl_amount), 2),
                entry_score=round(float(pos["entry_score"]), 2),
                entry_signal_date=pos["entry_signal_date"],
                exit_signal_date=signal_date,
                blocked_exit_days=int(pos["blocked_exit_days"]),
                entry_signal_id=pos["entry_signal_id"],
                exit_signal_id=(
                    pos.get("pending_exit_signal_id")
                    or _signal_id(int(matrix.exit_signal_code[time_id, asset_id]), matrix.exit_signal_ids)
                ) if reason == "signal" else None,
            ))
            # ── 连亏冷却: 平仓后更新连亏计数 ──
            # cooldown_loss_streak > 0 守卫: 当用户设为 0 时表示禁用冷却,
            # 原始代码缺少此守卫, 0 >= 0 恒成立 → 首次亏损即触发冷却 (bug)
            if config.cooldown_loss_streak is not None and config.cooldown_loss_streak > 0 and config.cooldown_days is not None:
                if pnl_amount < 0:
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

            for asset_id, pos in positions.items():
                high_price = float(matrix.high[time_id, asset_id])
                if _valid_price(high_price):
                    pos["max_high"] = max(float(pos["max_high"]), high_price)
            valid_closes = np.isfinite(matrix.close[time_id]) & (matrix.close[time_id] > 0)
            last_close[valid_closes] = matrix.close[time_id, valid_closes]

            market_value = _market_value()
            equity = cash + market_value
            peak = max(peak, equity)
            drawdown = (equity - peak) / peak if peak > 0 else 0.0
            exposure = market_value / equity if equity > 0 else 0.0
            equity_value = round(float(equity), 2)
            exposure_value = round(float(exposure), 4)
            equity_values.append(equity_value)
            exposure_values.append(exposure_value)
            if options.include_curves:
                equity_curve.append({
                    "date": date_text,
                    "value": equity_value,
                    "cash": round(float(cash), 2),
                    "positions": len(positions),
                    "exposure": exposure_value,
                })
                drawdown_curve.append({
                    "date": date_text,
                    "value": round(float(drawdown), 4),
                })

        statistics_started = time.perf_counter()
        stats = self._calc_portfolio_stats_from_values(
            equity_values,
            exposure_values,
            trades,
            config.initial_capital,
            include_monte_carlo=options.include_monte_carlo,
        )
        stats["statistics_ms"] = round(
            (time.perf_counter() - statistics_started) * 1000,
            1,
        )
        stats["execution"] = execution_stats
        stats["pending_exit_positions"] = sum(1 for pos in positions.values() if pos.get("pending_exit_reason"))
        stats["market_matrix_shape"] = [time_count, asset_count]
        stats["market_matrix_bytes"] = matrix.nbytes
        return SimResult(
            equity_curve=equity_curve if options.include_curves else [],
            drawdown_curve=drawdown_curve if options.include_curves else [],
            trades=trades if options.include_trades else [],
            per_symbol_stats=(
                self._calc_per_symbol(trades)
                if options.include_per_symbol_stats
                else []
            ),
            stats=stats,
        )

    def simulate_portfolio_legacy(


