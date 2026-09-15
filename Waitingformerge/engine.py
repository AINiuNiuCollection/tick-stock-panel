backend/app/backtest/engine.py

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
        # cooldown_trigger_day: 冷却触发日, 当天卖出后不应阻止当天买入 (卖出先于买入执行)
        # 初始化在主循环前 (与原始代码在 _try_sell 后初始化等价, 因 nonlocal 闭包捕获)
        consec_losses = 0
        cooldown_until = -1
        cooldown_trigger_day = -1

        # ── 选股过程日志 ──
        # 记录每个有 entry 信号日的完整选股过程: 候选股票、评分、排名、
        # 选中/淘汰状态及淘汰原因。供前端"选股过程"Tab 展示。
        # 仅记录至少有 1 个候选进入候选池的日子 (纯冷却期/无信号日不记录)。
        selection_log: list[dict] = []

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
            nonlocal cash, consec_losses, cooldown_until, cooldown_trigger_day
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
            # cooldown_until = time_id + 1 + cooldown_days: +1 跳过当天(卖出日),
            #   使冷却从次日开始持续 cooldown_days 个交易日。
            #   但 _sell 在买入逻辑之前执行, 当天买入检查也会命中 time_id < cooldown_until,
            #   因此额外记录 cooldown_trigger_day, 买入检查时排除触发当天。
            if config.cooldown_loss_streak is not None and config.cooldown_loss_streak > 0 and config.cooldown_days is not None:
                if pnl_amount < 0:
                    consec_losses += 1
                    if consec_losses >= config.cooldown_loss_streak:
                        cooldown_until = time_id + 1 + config.cooldown_days
                        cooldown_trigger_day = time_id
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
                # time_id > cooldown_trigger_day: 排除触发当天 (卖出先于买入, 当天不应被自己触发的冷却阻止)
                if config.cooldown_loss_streak is not None and config.cooldown_loss_streak > 0 and config.cooldown_days is not None and time_id < cooldown_until and time_id > cooldown_trigger_day:
                    _cooldown_signals = np.flatnonzero(matrix.entry[time_id])
                    for _ in _cooldown_signals:
                        _count("buy_cooldown")
                    # ── 选股日志: 冷却期所有信号被拦截 ──
                    if len(_cooldown_signals) > 0:
                        _day_sel: list[dict] = []
                        for asset_id in _cooldown_signals:
                            _a = int(asset_id)
                            _sym = str(matrix.symbols[_a])
                            _nm = str(matrix.names[_a]) if matrix.names is not None else _sym
                            _day_sel.append({"symbol": _sym, "name": _nm, "score": None, "rank": None, "status": "rejected", "reason": "cooldown"})
                        selection_log.append({
                            "date": date_text,
                            "signal_count": len(_day_sel),
                            "slots_available": max_positions - len(positions),
                            "candidates": _day_sel,
                        })
                else:
                    candidates: list[tuple[int, float]] = []
                    # ── 选股过程日志: 逐个记录当日信号股票的处置结果 ──
                    # status 流转: rejected(预过滤淘汰) → candidate(进入候选池) →
                    #              selected(成功买入) / rejected(执行阶段淘汰)
                    day_selection: list[dict] = []
                    sel_map: dict[str, dict] = {}
                    for asset_id in np.flatnonzero(matrix.entry[time_id]):
                        asset = int(asset_id)
                        sym = str(matrix.symbols[asset])
                        nm = str(matrix.names[asset]) if matrix.names is not None else sym
                        if asset in positions:
                            _e = {"symbol": sym, "name": nm, "score": None, "rank": None, "status": "rejected", "reason": "already_held"}
                            day_selection.append(_e); sel_map[sym] = _e
                            continue
                        if asset in sold_today:
                            _count("buy_same_day_reentry")
                            _e = {"symbol": sym, "name": nm, "score": None, "rank": None, "status": "rejected", "reason": "same_day_reentry"}
                            day_selection.append(_e); sel_map[sym] = _e
                            continue
                        score = _matrix_entry_score(matrix, time_id, asset)
                        ok, blocked = _can_buy(time_id, asset)
                        if not ok:
                            _count(blocked)
                            _e = {"symbol": sym, "name": nm, "score": round(float(score), 4), "rank": None, "status": "rejected", "reason": blocked}
                            day_selection.append(_e); sel_map[sym] = _e
                            continue
                        if config.score_min is not None and score < config.score_min:
                            _count("buy_score_filter")
                            _e = {"symbol": sym, "name": nm, "score": round(float(score), 4), "rank": None, "status": "rejected", "reason": "score_filter"}
                            day_selection.append(_e); sel_map[sym] = _e
                            continue
                        if config.score_max is not None and score > config.score_max:
                            _count("buy_score_filter")
                            _e = {"symbol": sym, "name": nm, "score": round(float(score), 4), "rank": None, "status": "rejected", "reason": "score_filter"}
                            day_selection.append(_e); sel_map[sym] = _e
                            continue
                        candidates.append((asset, score))
                        _e = {"symbol": sym, "name": nm, "score": round(float(score), 4), "rank": None, "status": "candidate", "reason": None}
                        day_selection.append(_e); sel_map[sym] = _e
                    candidates.sort(key=lambda item: item[1], reverse=True)
                    # 按评分降序分配名次
                    for _rank_idx, (_asset, _score) in enumerate(candidates):
                        _sym = str(matrix.symbols[_asset])
                        _item = sel_map.get(_sym)
                        if _item is not None:
                            _item["rank"] = _rank_idx + 1
                    slots = max_positions - len(positions)
                    if slots <= 0:
                        execution_stats["buy_no_slot"] += len(candidates)
                        for _item in day_selection:
                            if _item["status"] == "candidate":
                                _item["status"] = "rejected"
                                _item["reason"] = "no_slot"
                    elif candidates:
                        selected = candidates[:slots]
                        _selected_syms = {str(matrix.symbols[_a]) for _a, _ in selected}
                        # 未选中的候选 → no_slot
                        for _item in day_selection:
                            if _item["status"] == "candidate" and _item["symbol"] not in _selected_syms:
                                _item["status"] = "rejected"
                                _item["reason"] = "no_slot"
                        market_value_before = _market_value()
                        equity_before = cash + market_value_before
                        target_value = equity_before * max_exposure_pct / max_positions
                        exposure_capacity = equity_before * max_exposure_pct - market_value_before
                        if equity_before <= 0 or exposure_capacity <= 0 or max_exposure_pct <= 0:
                            execution_stats["buy_exposure"] += len(selected)
                            for _item in day_selection:
                                if _item["status"] == "candidate":
                                    _item["status"] = "rejected"
                                    _item["reason"] = "exposure"
                        else:
                            weights = np.repeat(1 / len(selected), len(selected))
                            if config.position_sizing == "score_weight":
                                raw_weights = np.array([max(item[1], 0.0) for item in selected])
                                if raw_weights.sum() > 0:
                                    weights = raw_weights / raw_weights.sum()
                            total_budget = min(cash, exposure_capacity, target_value * len(selected))
                            for (asset_id, entry_score), weight in zip(selected, weights):
                                _sym = str(matrix.symbols[asset_id])
                                if len(positions) >= max_positions:
                                    _count("buy_no_slot")
                                    _item = sel_map.get(_sym)
                                    if _item and _item["status"] == "candidate":
                                        _item["status"] = "rejected"; _item["reason"] = "no_slot"
                                    break
                                market_value = _market_value()
                                equity = cash + market_value
                                capacity = equity * max_exposure_pct - market_value
                                allocation = min(total_budget * float(weight), target_value, cash, capacity)
                                if allocation <= 0:
                                    _count("buy_exposure")
                                    _item = sel_map.get(_sym)
                                    if _item and _item["status"] == "candidate":
                                        _item["status"] = "rejected"; _item["reason"] = "exposure"
                                    continue
                                entry_price = _refill_price(
                                    time_id, asset_id, "buy", float(entry_prices[time_id, asset_id])
                                )
                                shares = np.floor(allocation / (entry_price * (1 + buy_cost_pct)) / 100) * 100
                                entry_value = shares * entry_price * (1 + buy_cost_pct)
                                if shares <= 0:
                                    _count("buy_lot_size")
                                    _item = sel_map.get(_sym)
                                    if _item and _item["status"] == "candidate":
                                        _item["status"] = "rejected"; _item["reason"] = "lot_size"
                                    continue
                                if entry_value > cash + 1e-6:
                                    _count("buy_cash")
                                    _item = sel_map.get(_sym)
                                    if _item and _item["status"] == "candidate":
                                        _item["status"] = "rejected"; _item["reason"] = "cash"
                                    continue
                                if entry_value > capacity + 1e-6:
                                    _count("buy_exposure")
                                    _item = sel_map.get(_sym)
                                    if _item and _item["status"] == "candidate":
                                        _item["status"] = "rejected"; _item["reason"] = "exposure"
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
                                _item = sel_map.get(_sym)
                                if _item and _item["status"] == "candidate":
                                    _item["status"] = "selected"
                    # ── 写入选股日志 (所有有信号的天都记录) ──
                    if day_selection:
                        selection_log.append({
                            "date": date_text,
                            "signal_count": len(day_selection),
                            "slots_available": slots,
                            "candidates": day_selection,
                        })

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
        stats["selection_log"] = selection_log
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




















***************************************************************************************
        # ── 选股过程日志 (与 matrix 模式结构一致) ──
        selection_log: list[dict] = []

        def _count(key: str) -> None:
            execution_stats[key] = execution_stats.get(key, 0) + 1

        def _valid_price(value) -> bool:
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False
            return v > 0 and np.isfinite(v)

        def _market_value() -> float:
            value = 0.0
            for pos in positions.values():
                mark = last_close.get(pos["symbol"], pos["entry_price"])
                value += pos["shares"] * mark
            return value








********************************************************************************************
        def _process_entries(
            d_str: str,
            idxs: list[int],
            sold_today: set[str],
        ) -> None:
            nonlocal cash
            if max_positions <= 0:
                return
            candidates: list[tuple[int, str, float]] = []
            # ── 选股过程日志 ──
            day_selection: list[dict] = []
            sel_map: dict[str, dict] = {}
            for idx in idxs:
                if not ent[idx]:
                    continue
                sym = str(panel_symbols[idx])
                nm = str(names[idx] or sym)
                if sym in positions:
                    _e = {"symbol": sym, "name": nm, "score": None, "rank": None, "status": "rejected", "reason": "already_held"}
                    day_selection.append(_e); sel_map[sym] = _e
                    continue
                if sym in sold_today:
                    _count("buy_same_day_reentry")
                    _e = {"symbol": sym, "name": nm, "score": None, "rank": None, "status": "rejected", "reason": "same_day_reentry"}
                    day_selection.append(_e); sel_map[sym] = _e
                    continue
                score = float(trade_scores[idx] or 0.0)
                ok, block_reason = _can_buy(idx)
                if not ok:
                    _count(block_reason)
                    _e = {"symbol": sym, "name": nm, "score": round(score, 4), "rank": None, "status": "rejected", "reason": block_reason}
                    day_selection.append(_e); sel_map[sym] = _e
                    continue
                if score_min is not None and score < score_min:
                    _count("buy_score_filter")
                    _e = {"symbol": sym, "name": nm, "score": round(score, 4), "rank": None, "status": "rejected", "reason": "score_filter"}
                    day_selection.append(_e); sel_map[sym] = _e
                    continue
                if score_max is not None and score > score_max:
                    _count("buy_score_filter")
                    _e = {"symbol": sym, "name": nm, "score": round(score, 4), "rank": None, "status": "rejected", "reason": "score_filter"}
                    day_selection.append(_e); sel_map[sym] = _e
                    continue
                candidates.append((idx, sym, score))
                _e = {"symbol": sym, "name": nm, "score": round(score, 4), "rank": None, "status": "candidate", "reason": None}
                day_selection.append(_e); sel_map[sym] = _e
            if not candidates:
                # 仍有信号但全部被预过滤淘汰 → 记录日志
                if day_selection:
                    selection_log.append({
                        "date": str(d_str)[:10],
                        "signal_count": len(day_selection),
                        "slots_available": max_positions - len(positions),
                        "candidates": day_selection,
                    })
                return
            candidates.sort(key=lambda x: x[2], reverse=True)
            for _rank_idx, (_idx, _sym, _score) in enumerate(candidates):
                _item = sel_map.get(_sym)
                if _item is not None:
                    _item["rank"] = _rank_idx + 1

            slots = max_positions - len(positions)
            if slots <= 0:
                execution_stats["buy_no_slot"] += len(candidates)
                for _item in day_selection:
                    if _item["status"] == "candidate":
                        _item["status"] = "rejected"
                        _item["reason"] = "no_slot"
                selection_log.append({
                    "date": str(d_str)[:10],
                    "signal_count": len(day_selection),
                    "slots_available": slots,
                    "candidates": day_selection,
                })
                return

            selected = candidates[:slots]
            _selected_syms = {_sym for _, _sym, _ in selected}
            for _item in day_selection:
                if _item["status"] == "candidate" and _item["symbol"] not in _selected_syms:
                    _item["status"] = "rejected"
                    _item["reason"] = "no_slot"
            market_value_before = _market_value()
            account_equity_before_buy = cash + market_value_before
            if account_equity_before_buy <= 0 or max_exposure_pct <= 0:
                execution_stats["buy_exposure"] += len(selected)
                for _item in day_selection:
                    if _item["status"] == "candidate":
                        _item["status"] = "rejected"
                        _item["reason"] = "exposure"
                selection_log.append({
                    "date": str(d_str)[:10],
                    "signal_count": len(day_selection),
                    "slots_available": slots,
                    "candidates": day_selection,
                })
                return
            target_position_value = account_equity_before_buy * max_exposure_pct / max_positions
            max_exposure_value = account_equity_before_buy * max_exposure_pct
            exposure_capacity = max_exposure_value - market_value_before
            if exposure_capacity <= 0:
                execution_stats["buy_exposure"] += len(selected)
                for _item in day_selection:
                    if _item["status"] == "candidate":
                        _item["status"] = "rejected"
                        _item["reason"] = "exposure"
                selection_log.append({
                    "date": str(d_str)[:10],
                    "signal_count": len(day_selection),
                    "slots_available": slots,
                    "candidates": day_selection,
                })
                return

            weights = np.repeat(1 / len(selected), len(selected))
            if config.position_sizing == "score_weight":
                raw = np.array([max(x[2], 0.0) for x in selected], dtype=float)
                if raw.sum() > 0:
                    weights = raw / raw.sum()
            total_budget = min(cash, exposure_capacity, target_position_value * len(selected))

            for (idx, sym, _score), weight in zip(selected, weights):
                if len(positions) >= max_positions:
                    _count("buy_no_slot")
                    _item = sel_map.get(sym)
                    if _item and _item["status"] == "candidate":
                        _item["status"] = "rejected"; _item["reason"] = "no_slot"
                    break
                current_market_value = _market_value()
                current_equity = cash + current_market_value
                current_exposure_capacity = current_equity * max_exposure_pct - current_market_value
                allocation = min(total_budget * float(weight), target_position_value, cash, current_exposure_capacity)
                if allocation <= 0:
                    _count("buy_exposure")
                    _item = sel_map.get(sym)
                    if _item and _item["status"] == "candidate":
                        _item["status"] = "rejected"; _item["reason"] = "exposure"
                    continue
                entry_price = _refill_price(idx, "buy", float(entry_prices[idx]))
                shares = np.floor(allocation / (entry_price * (1 + buy_cost_pct)) / 100) * 100
                entry_value = shares * entry_price * (1 + buy_cost_pct)
                if shares <= 0:
                    _count("buy_lot_size")
                    _item = sel_map.get(sym)
                    if _item and _item["status"] == "candidate":
                        _item["status"] = "rejected"; _item["reason"] = "lot_size"
                    continue
                if entry_value > cash + 1e-6:
                    _count("buy_cash")
                    _item = sel_map.get(sym)
                    if _item and _item["status"] == "candidate":
                        _item["status"] = "rejected"; _item["reason"] = "cash"
                    continue
                if entry_value > current_exposure_capacity + 1e-6:
                    _count("buy_exposure")
                    _item = sel_map.get(sym)
                    if _item and _item["status"] == "candidate":
                        _item["status"] = "rejected"; _item["reason"] = "exposure"
                    continue
                cash -= entry_value
                positions[sym] = {
                    "symbol": sym,
                    "name": str(names[idx] or ""),
                    "entry_date": self._date_str(panel_dates[idx]),
                    "entry_signal_date": entry_signal_dates[idx] or self._date_str(panel_dates[idx]),
                    "entry_signal_id": _resolve_signal_id(panel, idx, entry_signal_ids),
                    "entry_price": entry_price,
                    "entry_value": entry_value,
                    "shares": shares,
                    "lots": shares / 100,
                    "position_pct": entry_value / account_equity_before_buy if account_equity_before_buy > 0 else 0.0,
                    "entry_score": _score,
                    "max_high": entry_price,
                    "hold_days": 0,
                    "pending_exit_reason": None,
                    "pending_exit_signal_date": None,
                    "blocked_exit_days": 0,
                }
                _item = sel_map.get(sym)
                if _item and _item["status"] == "candidate":
                    _item["status"] = "selected"
            # ── 写入选股日志 ──
            selection_log.append({
                "date": str(d_str)[:10],
                "signal_count": len(day_selection),
                "slots_available": slots,
                "candidates": day_selection,
            })

        for d_idx, d_str in enumerate(all_dates):
            if d_idx % 20 == 0:
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("回测被用户取消 (第 %d/%d 天)", d_idx, len(all_dates))
                    break
                if progress_cb is not None:
                    try:
                        progress_cb({
                            "day": d_idx + 1,
                            "total": len(all_dates),
                            "date": str(d_str)[:10],
                            "equity": round(cash + _market_value(), 2),
                        })
                    except Exception:
                        pass

            idxs = date_to_indices[d_str]
            row_by_symbol = {str(panel_symbols[i]): i for i in idxs}
            sold_today: set[str] = set()

            for pos in positions.values():
                pos["hold_days"] += 1

            # 统一执行顺序 (不分口径): 风控(止损/移动止损/止盈) → 计划出场(signal/max_hold/end) → 建仓。
            # 风控是保护性离场, 必须最先; 计划出场次之; 建仓最后 (卖出释放的现金/仓位先用于满足新买)。
            # 当天新建仓不会被风控误杀 (_process_risk_exits 跳过 entry_date == d_str 的仓位)。
            _process_risk_exits(d_str, row_by_symbol, sold_today)
            _process_scheduled_exits(d_idx, d_str, row_by_symbol, sold_today)
            if d_idx < len(all_dates) - 1:
                _process_entries(d_str, idxs, sold_today)

            for sym, pos in positions.items():
                idx = row_by_symbol.get(sym)
                if idx is not None:
                    hi = float(high_prices[idx])
                    if _valid_price(hi):
                        pos["max_high"] = max(float(pos.get("max_high", pos["entry_price"])), hi)

            for i in idxs:
                c = float(close_prices[i])
                if c > 0 and np.isfinite(c):
                    last_close[str(panel_symbols[i])] = c

            market_value = _market_value()
            equity = cash + market_value
            peak = max(peak, equity)
            dd = (equity - peak) / peak if peak > 0 else 0.0
            exposure = market_value / equity if equity > 0 else 0.0
            equity_curve.append({
                "date": d_str[:10],
                "value": round(float(equity), 2),
                "cash": round(float(cash), 2),
                "positions": len(positions),
                "exposure": round(float(exposure), 4),
            })
            drawdown_curve.append({"date": d_str[:10], "value": round(float(dd), 4)})

        stats = self._calc_portfolio_stats(equity_curve, trades, config.initial_capital)
        stats["execution"] = execution_stats
        stats["selection_log"] = selection_log
        stats["pending_exit_positions"] = sum(1 for p in positions.values() if p.get("pending_exit_reason"))
        per_symbol = self._calc_per_symbol(trades)
        return SimResult(
            equity_curve=equity_curve,
            drawdown_curve=drawdown_curve,
            trades=trades,
            per_symbol_stats=per_symbol,
            stats=stats,
        )

    # ── 净值曲线 ──────────────────────────────────────


