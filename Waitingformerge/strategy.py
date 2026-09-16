"D:\Code\githubProject\tick-stock-panel\backend\app\backtest\strategy.py"

 

        try:
            if s.execution_backend == "composite":
                # composite 回测: 子策略必须全为 matrix_native(否则 fail-closed),
                # feature_plan 取所有子策略计划的并集(_merge_resolved_feature_plans)。
                feature_plan, composite_children_resolved = self._resolve_composite_feature_plan(
                    s,
                    params=params,
                    basic_filter=basic_filter,
                    overrides=overrides,
                    asset_type=config.asset_type,
                )
            else:
                composite_children_resolved = None
                feature_plan = StrategyDependencyResolver().resolve(
                    s,
                    params=params,
                    basic_filter=basic_filter,
                    entry_signals=entry_signals,
                    exit_signals=exit_signals,
                    overrides=overrides,
                    minute_fill=config.minute_fill,
                    asset_type=config.asset_type,
                )
        except ValueError as e:
            return _err(str(e))

        timing_ms: dict[str, float] = {}
        matrix_data_cache_hit = False
        matrix_data_cache_status = "none"
        matrix_data_cache_timing_ms: Mapping[str, float] = {}

        # ── regime_filter 过滤信号收集 ──
        # 被市场环境过滤拦截的信号按信号日分组, 回测后映射到买入日注入 selection_log,
        # 使前端"选股过程"Tab 日期连续且能看到被拦截的原因。
        regime_rejected_by_signal_date: dict[str, list[dict]] = {}
        all_trade_dates: list[str] = []

        # 加载 warmup + 正式区间。矩阵策略的 warmup 由协议解析，不再依赖策略名称。
        warmup_days = max(120, int(max(feature_plan.warmup_bars, 1) * 1.6))
        load_start = config.start - timedelta(days=warmup_days)

        # 全量模式: entries 只在正式区间触发, exits 需要 end 之后的尾部数据继续执行策略卖点。
        # 若策略有 max_hold_days, 用它决定尾部窗口；否则 holding_days 只作为兜底观察上限。
        full_horizon_days = int(max_hold_days or config.holding_days or 5)
        full_horizon_days = max(full_horizon_days, 1)
        load_end = config.end
        if config.mode == "full":
            fwd_buffer = full_horizon_days + 5  # 多取几天, 容错停牌缺口/open_t+1
            load_end = config.end + timedelta(days=fwd_buffer * 2)  # 日历日放宽, 确保覆盖 N 个交易日

        sim_end = load_end if config.mode == "full" else config.end
        panel: pl.DataFrame | None = None
        formal_range: pl.Series | None = None
        market_data: MarketDataMatrix | None = None
        if prepared is not None:
            if s.execution_backend != "matrix_native":
                return _err("共享基础矩阵只能用于 matrix_native 策略")
            if prepared.signature != self._matrix_prepare_signature(config):
                return _err("共享基础矩阵与当前回测配置不匹配")
            load_start = prepared.load_start
            load_end = prepared.load_end
            sim_end = prepared.sim_end
            feature_width = prepared.feature_width
            timing_ms["load_panel"] = 0.0
            timing_ms["market_data_matrix_build"] = 0.0
            matrix_data_cache_status = prepared.market_data.cache_status
            matrix_data_cache_hit = matrix_data_cache_status in {"exact", "covering"}
            matrix_data_cache_timing_ms = prepared.market_data.cache_timing_ms
            # 环境过滤下正式起点=矩阵首日时顺延 (首日让渡为预热)
            if config.regime_filter:
                config = self._clamp_regime_formal_start(
                    config, prepared.market_data.timestamp_labels
                )
        elif s.execution_backend in ("matrix_native", "composite"):
            t_load = time.perf_counter()
            max_hold_for_profile = self._override_value(
                overrides,
                "max_hold_days",
                s.max_hold_days,
            )
            profile_forward = max(int(max_hold_for_profile or config.holding_days or 5), 1)
            cache_profile = build_matrix_cache_profile(
                self.strategy_engine,
                config.asset_type,
                requested_plan=feature_plan,
                requested_forward_bars=profile_forward,
                max_disk_bytes=settings.backtest_matrix_cache_max_mb * 1024 * 1024,
            )
            cache_warmup_days = max(
                120,
                int(max(cache_profile.warmup_bars, 1) * 1.6),
            )
            coverage_start = config.start - timedelta(days=cache_warmup_days)
            coverage_end = config.end
            if config.mode == "full":
                coverage_end = config.end + timedelta(
                    days=(cache_profile.forward_bars + 5) * 2
                )
            try:
                market_data = self.engine.load_market_data_matrix_for_backtest(
                    config.symbols,
                    load_start,
                    load_end,
                    feature_plan,
                    asset_type=config.asset_type,
                    cache_profile=cache_profile,
                    coverage_start=coverage_start,
                    coverage_end=coverage_end,
                )
            except (ValueError, OSError) as e:
                return _err(f"回测矩阵准备失败: {e}")
            direct_load_ms = round((time.perf_counter() - t_load) * 1000, 1)
            timing_ms["load_panel"] = direct_load_ms
            timing_ms["market_data_matrix_build"] = 0.0
            timing_ms["market_data_direct_load"] = direct_load_ms
            matrix_data_cache_status = market_data.cache_status
            matrix_data_cache_hit = matrix_data_cache_status in {"exact", "covering"}
            matrix_data_cache_timing_ms = market_data.cache_timing_ms
            # 环境过滤下正式起点=矩阵首日时顺延 (首日让渡为预热)
            if config.regime_filter:
                config = self._clamp_regime_formal_start(
                    config, market_data.timestamp_labels
                )
            formal_time_mask = self._matrix_date_range_mask(
                market_data.timestamp_labels,
                config.start,
                config.end,
            )
            if not formal_time_mask.any():
                return _err("正式回测区间内无数据")
            feature_width = len(feature_plan.matrix_columns)
        else:
            t_load = time.perf_counter()
            try:
                panel = self.engine.load_panel_for_backtest(
                    config.symbols,
                    load_start,
                    load_end,
                    feature_plan,
                    asset_type=config.asset_type,
                )
            except (ValueError, pl.exceptions.PolarsError) as e:
                return _err(f"回测特征准备失败: {e}")
            timing_ms["load_panel"] = round((time.perf_counter() - t_load) * 1000, 1)
            if panel.is_empty():
                return _err("无数据，请检查日期范围或先运行盘后管道")
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
        )
        t_signal = time.perf_counter()
        selection_stats: dict[str, int | bool]

        if s.execution_backend == "composite":
            # composite 回测信号生成: 复用 matrix 数据加载, 逐子策略算信号后合并。
            # 退出采用来源投影(composite.merge_signal_matrices), 不串平其他子策略仓位。
            if composite_children_resolved is None:
                return _err("叠加策略子策略解析失败")
            if market_data is None:
                return _err("矩阵回测缺少基础行情矩阵")
            entry_time_mask = self._matrix_date_range_mask(
                market_data.timestamp_labels,
                config.start,
                config.end,
            )
            # 市场环境过滤(强制 T-1): 只叠加 entry, 不影响 exit
            try:
                _rm = self._build_regime_mask(
                    market_data.timestamp_labels, config.regime_filter,
                    getattr(getattr(self.engine.repo, "store", None), "data_dir", None),
                    required_start=config.start,
                    required_end=config.end,
                )
            except ValueError as e:
                return _err(str(e))
            if _rm is not None:
                _regime_rejected_tids = np.flatnonzero(entry_time_mask & ~_rm)
                entry_time_mask = entry_time_mask & _rm
            else:
                _regime_rejected_tids = None
            exit_time_mask = self._matrix_date_range_mask(
                market_data.timestamp_labels,
                config.start,
                load_end if config.mode == "full" else config.end,
            )
            sim_time_mask = self._matrix_date_range_mask(
                market_data.timestamp_labels,
                config.start,
                sim_end,
            )
            time_ids = np.flatnonzero(sim_time_mask)
            if time_ids.size == 0:
                return _err("正式回测区间内无数据")
            start_id = int(time_ids[0])
            stop_id = int(time_ids[-1]) + 1
            panel_rows = int(np.isfinite(market_data.close[start_id:stop_id]).sum())
            panel_columns = len(feature_plan.matrix_columns)
            reference_price = (
                rolling_mean(market_data.close, 5)[start_id:stop_id]
                if matcher_config.minute_fill
                else None
            )

            merge_mode = str(params.get("merge_mode") or "union")
            min_confirm = int(params.get("min_confirm") or 0)
            # max_hold 用于退出投影窗口封顶; 无值时给一个足够大的兜底(仅靠信号退出)。
            composite_max_hold = max(int(max_hold_days or 0), 1) if max_hold_days else 250
            try:
                signal_matrix = self._generate_composite_signal_matrix(
                    composite_children_resolved,
                    market_data,
                    merge_mode,
                    min_confirm,
                    composite_max_hold,
                    timing_ms,
                )
            except ValueError as e:
                return _err(str(e))

            # 收集被 regime_filter 过滤的信号 (在 apply_time_masks 清零前)
            if _regime_rejected_tids is not None and _regime_rejected_tids.size > 0:
                all_trade_dates = [str(lbl)[:10] for lbl in market_data.timestamp_labels]
                for _t in _regime_rejected_tids:
                    _asset_ids = np.flatnonzero(signal_matrix.entry[_t])
                    if _asset_ids.size == 0:
                        continue
                    _date_lbl = str(market_data.timestamp_labels[_t])[:10]
                    for _a in _asset_ids:
                        _sym = str(market_data.symbols[_a])
                        _nm = str(market_data.names[_a]) if market_data.names is not None else _sym
                        _sc = float(signal_matrix.score[_t, _a]) if signal_matrix.score is not None else 0.0
                        regime_rejected_by_signal_date.setdefault(_date_lbl, []).append({
                            "symbol": _sym, "name": _nm, "score": round(_sc, 4),
                            "rank": None, "status": "rejected", "reason": "regime_filter",
                        })

            sim_market_data = slice_market_data_matrix(market_data, start_id, stop_id)
            sim_signal_matrix = slice_signal_matrix(signal_matrix, start_id, stop_id)
            sim_signal_matrix = apply_time_masks(
                sim_signal_matrix,
                entry_time_mask[start_id:stop_id],
                exit_time_mask[start_id:stop_id],
            )
            timing_ms["signals_score"] = round((time.perf_counter() - t_signal) * 1000, 1)
            if not sim_signal_matrix.entry.any():
                return _err("在指定区间内未产生买入信号")

            raw_candidates = int(sim_signal_matrix.entry.sum())
            selection_stats = {
                "strategy_matches": raw_candidates,
                "entry_candidates": raw_candidates,
                "entry_trigger_filtered": 0,
                "entry_trigger_enabled": False,
            }
            del market_data, signal_matrix

            t_matrix = time.perf_counter()
            market_matrix = build_market_matrix_from_signals(
                sim_market_data,
                sim_signal_matrix,
                entry_delay_bars=1 if matcher_config.entry_fill == "open_t+1" else 0,
                exit_delay_bars=1 if matcher_config.exit_fill == "open_t+1" else 0,
                reference_price=reference_price,
                minute_exit_trigger=matcher_config.exit_fill == "signal_next_minute",
            )
            timing_ms["matrix_build"] = round((time.perf_counter() - t_matrix) * 1000, 1)
            del sim_market_data, sim_signal_matrix
        elif s.execution_backend == "matrix_native":
            if s.matrix_strategy is None:
                return _err("矩阵策略未注册")
            if self._has_matrix_signal_override(s, overrides):
                return _err("matrix_native 策略的进出场信号由策略协议生成，不支持列信号覆盖")

            if prepared is not None:
                market_data = prepared.market_data
                entry_time_mask = prepared.entry_time_mask
                exit_time_mask = prepared.exit_time_mask
                start_id = prepared.start_id
                stop_id = prepared.stop_id
                reference_price = prepared.reference_price
                _regime_rejected_tids = None  # prepared 已预过滤, 无 regime 收集
                panel_rows = int(np.isfinite(market_data.close[start_id:stop_id]).sum())
                panel_columns = len(feature_plan.matrix_columns)
            else:
                if market_data is None:
                    return _err("矩阵回测缺少基础行情矩阵")
                entry_time_mask = self._matrix_date_range_mask(
                    market_data.timestamp_labels,
                    config.start,
                    config.end,
                )
                try:
                    _rm = self._build_regime_mask(
                        market_data.timestamp_labels, config.regime_filter,
                        getattr(getattr(self.engine.repo, "store", None), "data_dir", None),
                        required_start=config.start,
                        required_end=config.end,
                    )
                except ValueError as e:
                    return _err(str(e))
                if _rm is not None:
                    _regime_rejected_tids = np.flatnonzero(entry_time_mask & ~_rm)
                    entry_time_mask = entry_time_mask & _rm
                else:
                    _regime_rejected_tids = None
                exit_time_mask = self._matrix_date_range_mask(
                    market_data.timestamp_labels,
                    config.start,
                    load_end if config.mode == "full" else config.end,
                )
                sim_time_mask = self._matrix_date_range_mask(
                    market_data.timestamp_labels,
                    config.start,
                    sim_end,
                )
                time_ids = np.flatnonzero(sim_time_mask)
                if time_ids.size == 0:
                    return _err("正式回测区间内无数据")
                start_id = int(time_ids[0])
                stop_id = int(time_ids[-1]) + 1
                panel_rows = int(np.isfinite(market_data.close[start_id:stop_id]).sum())
                panel_columns = len(feature_plan.matrix_columns)
                reference_price = (
                    rolling_mean(market_data.close, 5)[start_id:stop_id]
                    if matcher_config.minute_fill
                    else None
                )

            scoring = effective_scoring(s.meta.get("scoring"), overrides)
            try:
                pipeline_config = MatrixPipelineConfig(
                    basic_filter=basic_filter,
                    scoring=scoring,
                    scoring_directions=effective_scoring_directions(overrides, s.meta),
                    order_by=s.meta.get("order_by"),
                    descending=bool(s.meta.get("descending", True)),
                    protect_strategy_cache=prepared is not None,
                )
                if prepared is None:
                    signal_matrix = MatrixStrategyPipeline().run(
                        s.matrix_strategy,
                        market_data,
                        params,
                        pipeline_config,
                        timing_ms,
                    )
                else:
                    with prepared.compute_cache.activate(market_data):
                        signal_matrix = MatrixStrategyPipeline().run(
                            s.matrix_strategy,
                            market_data,
                            params,
                            pipeline_config,
                            timing_ms,
                        )
            except (TypeError, ValueError) as e:
                return _err(f"矩阵策略信号计算失败: {e}")

            # 收集被 regime_filter 过滤的信号 (在 apply_time_masks 清零前)
            if _regime_rejected_tids is not None and _regime_rejected_tids.size > 0:
                all_trade_dates = [str(lbl)[:10] for lbl in market_data.timestamp_labels]
                for _t in _regime_rejected_tids:
                    _asset_ids = np.flatnonzero(signal_matrix.entry[_t])
                    if _asset_ids.size == 0:
                        continue
                    _date_lbl = str(market_data.timestamp_labels[_t])[:10]
                    for _a in _asset_ids:
                        _sym = str(market_data.symbols[_a])
                        _nm = str(market_data.names[_a]) if market_data.names is not None else _sym
                        _sc = float(signal_matrix.score[_t, _a]) if signal_matrix.score is not None else 0.0
                        regime_rejected_by_signal_date.setdefault(_date_lbl, []).append({
                            "symbol": _sym, "name": _nm, "score": round(_sc, 4),
                            "rank": None, "status": "rejected", "reason": "regime_filter",
                        })

            sim_market_data = slice_market_data_matrix(market_data, start_id, stop_id)
            sim_signal_matrix = slice_signal_matrix(signal_matrix, start_id, stop_id)
            sim_signal_matrix = apply_time_masks(
                sim_signal_matrix,
                entry_time_mask[start_id:stop_id],
                exit_time_mask[start_id:stop_id],
            )
            timing_ms["signals_score"] = round((time.perf_counter() - t_signal) * 1000, 1)
            if not sim_signal_matrix.entry.any():
                return _err("在指定区间内未产生买入信号")

            raw_candidates = int(sim_signal_matrix.entry.sum())
            selection_stats = {
                "strategy_matches": raw_candidates,
                "entry_candidates": raw_candidates,
                "entry_trigger_filtered": 0,
                "entry_trigger_enabled": False,
            }
            del market_data, signal_matrix

            t_matrix = time.perf_counter()
            market_matrix = build_market_matrix_from_signals(
                sim_market_data,
                sim_signal_matrix,
                entry_delay_bars=1 if matcher_config.entry_fill == "open_t+1" else 0,
                exit_delay_bars=1 if matcher_config.exit_fill == "open_t+1" else 0,
                reference_price=reference_price,
                minute_exit_trigger=matcher_config.exit_fill == "signal_next_minute",
            )
            timing_ms["matrix_build"] = round((time.perf_counter() - t_matrix) * 1000, 1)
            del sim_market_data, sim_signal_matrix
        else:
            if panel is None or formal_range is None:
                return _err("非矩阵策略不能使用共享基础矩阵")
            # basic_filter 只影响买入候选，不能删除持仓估值和卖出所需行情。
            basic_mask = pl.Series("_basic", [True] * len(panel), dtype=pl.Boolean)
            if basic_filter and basic_filter.get("enabled", True):
                expr = StrategyEngine._basic_filter_expr(panel, basic_filter)
                if expr is not None:
                    try:
                        basic_mask = panel.select(expr.alias("_basic"))["_basic"].fill_null(False).cast(pl.Boolean)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("basic_filter mask failed: %s", e)
                        return _err(f"基础过滤计算失败: {e}")

            candidate_filter_mask = self._build_candidate_filter_mask(panel, s, params)
            candidate_mask = basic_mask & candidate_filter_mask
            panel = self._apply_score(panel, s, overrides, universe_mask=candidate_mask, factor_snapshot=factor_snapshot)
            formal_candidate_mask = candidate_mask & formal_range
            entry_mask = self._build_entry_mask_from_candidate(panel, candidate_mask, s, entry_signals)
            entry_mask = entry_mask & formal_range
            if config.regime_filter:
                date_values = panel.get_column("date").unique().sort().to_list()
                date_labels = tuple(str(value)[:10] for value in date_values)
                try:
                    regime_time_mask = self._build_regime_mask(
                        date_labels,
                        config.regime_filter,
                        getattr(getattr(self.engine.repo, "store", None), "data_dir", None),
                        required_start=config.start,
                        required_end=config.end,
                    )
                except ValueError as e:
                    return _err(str(e))
                if regime_time_mask is not None:
                    allowed_dates = [
                        value for value, allowed in zip(date_values, regime_time_mask, strict=True)
                        if allowed
                    ]
                    regime_row_mask = panel.get_column("date").is_in(allowed_dates).fill_null(False)
                    # 收集被 regime_filter 过滤的信号
                    _regime_rejected_mask = entry_mask & ~regime_row_mask
                    if _regime_rejected_mask.any():
                        all_trade_dates = [str(d)[:10] for d in date_values]
                        for row in panel.filter(_regime_rejected_mask).select(
                            "date", "symbol", "name", "score"
                        ).iter_rows(named=True):
                            _d = str(row["date"])[:10]
                            _sc = float(row.get("score") or 0)
                            regime_rejected_by_signal_date.setdefault(_d, []).append({
                                "symbol": str(row["symbol"]),
                                "name": str(row.get("name") or ""),
                                "score": round(_sc, 4),
                                "rank": None,
                                "status": "rejected",
                                "reason": "regime_filter",
                            })
                    formal_candidate_mask = formal_candidate_mask & regime_row_mask
                    entry_mask = entry_mask & regime_row_mask
            raw_exit_mask = self._build_signal_mask(panel, exit_signals, "_exit")
            exit_range = self._date_range_mask(panel, config.start, load_end) if config.mode == "full" else formal_range
            exit_mask = raw_exit_mask & exit_range
            timing_ms["signals_score"] = round((time.perf_counter() - t_signal) * 1000, 1)
            if not entry_mask.any():
                return _err("在指定区间内未产生买入信号")

            sim_range = self._date_range_mask(panel, config.start, sim_end)
            sim_columns = [column for column in feature_plan.matrix_columns if column in panel.columns]
            sim_panel = panel.filter(sim_range).select(sorted(sim_columns))
            sim_entry_mask = entry_mask.filter(sim_range)
            sim_exit_mask = exit_mask.filter(sim_range)
            if sim_panel.is_empty():
                return _err("正式回测区间内无数据")
            panel_rows = int(sim_panel.height)
            panel_columns = int(sim_panel.width)
            raw_candidates = int(sim_entry_mask.sum())
            strategy_matches = int(formal_candidate_mask.sum())
            selection_stats = {
                "strategy_matches": strategy_matches,
                "entry_candidates": raw_candidates,
                "entry_trigger_filtered": max(strategy_matches - raw_candidates, 0),
                "entry_trigger_enabled": bool(entry_signals),
            }

            t_matrix = time.perf_counter()
            market_matrix = build_market_matrix(
                sim_panel,
                sim_entry_mask,
                sim_exit_mask,
                entry_delay_bars=1 if matcher_config.entry_fill == "open_t+1" else 0,
                exit_delay_bars=1 if matcher_config.exit_fill == "open_t+1" else 0,
                entry_signal_ids=entry_signals,
                exit_signal_ids=exit_signals,
                minute_exit_trigger=matcher_config.exit_fill == "signal_next_minute",
            )
            timing_ms["matrix_build"] = round((time.perf_counter() - t_matrix) * 1000, 1)
            del panel, sim_panel, sim_entry_mask, sim_exit_mask

        t_sim = time.perf_counter()

        # 撮合 — 两条生产路径共享同一只读 MarketMatrix。
        if config.mode == "full":
            result = self.engine.simulate_independent_market_matrix(
                market_matrix,
                raw_candidates,
                matcher_config,
                progress_cb,
                cancel_event,
                result_policy.simulation_options(),
            )
        else:
            result = self.engine.simulate_market_matrix(
                market_matrix,
                matcher_config,
                progress_cb,
                cancel_event,
                result_policy.simulation_options(),
            )
        timing_ms["simulate"] = round((time.perf_counter() - t_sim) * 1000, 1)
        timing_ms["statistics"] = float(result.stats.pop("statistics_ms", 0.0))

        # ── 注入被 regime_filter 过滤的信号到 selection_log ──
        if regime_rejected_by_signal_date:
            _date_idx = {d: i for i, d in enumerate(all_trade_dates)}
            _regime_by_buy_date: dict[str, list[dict]] = {}
            for _sig_date, _candidates in regime_rejected_by_signal_date.items():
                if matcher_config.entry_fill == "open_t+1":
                    _idx = _date_idx.get(_sig_date)
                    if _idx is not None and _idx + 1 < len(all_trade_dates):
                        _buy_date = all_trade_dates[_idx + 1]
                    else:
                        continue
                else:
                    _buy_date = _sig_date
                _regime_by_buy_date.setdefault(_buy_date, []).extend(_candidates)

            _sel_log = result.stats.get("selection_log", [])
            _existing_by_date = {e["date"]: e for e in _sel_log}
            for _buy_date, _candidates in _regime_by_buy_date.items():
                if _buy_date in _existing_by_date:
                    _entry = _existing_by_date[_buy_date]
                    _entry["candidates"].extend(_candidates)
                    _entry["signal_count"] += len(_candidates)
                else:
                    _sel_log.append({
                        "date": _buy_date,
                        "signal_count": len(_candidates),
                        "slots_available": 0,
                        "candidates": _candidates,
                    })
            _sel_log.sort(key=lambda x: x["date"])
            result.stats["selection_log"] = _sel_log

        # 检查是否被取消
        if cancel_event is not None and cancel_event.is_set():
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error="cancelled",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
