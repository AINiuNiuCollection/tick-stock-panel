def run(
        self,
        config: StrategyBacktestConfig,
        progress_cb: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
        prepared: PreparedMatrixBacktest | None = None,
        result_policy: BacktestResultPolicy | None = None,
    ) -> StrategyBacktestResult:
        t0 = time.perf_counter()
        run_id = uuid.uuid4().hex[:10]
        result_policy = result_policy or BacktestResultPolicy()
        # 因子归因快照容器: 日线路径在 _apply_score 里填充, 其余路径保持空
        factor_snapshot: dict = {}

        def _err(msg: str) -> StrategyBacktestResult:
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error=msg,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        # 获取策略定义
        try:
            s = self.strategy_engine.get(config.strategy_id)
            StrategyEngine.validate_context(
                s,
                StrategyDataContext(
                    asset_type=config.asset_type,
                    timeframe="1m" if s.execution_backend == "minute_filter" else "1d",
                    as_of=config.end,
                ),
            )
        except ValueError as e:
            return _err(str(e))

        params = self._normalize_params(config.params or {}, s)
        overrides = config.overrides or {}
        # 同回测 run 路径: 挖掘运行期也要按资产类型中和股票专属过滤键 (#215)
        basic_filter = _basic_filter_for_asset(
            self._effective_basic_filter(s, overrides), config.asset_type
        )
        entry_signals = self._effective_signals(overrides, "entry_signals", s.entry_signals)
        exit_signals = self._effective_signals(overrides, "exit_signals", s.exit_signals)
        if config.exit_fill == "signal_next_minute":
            if not config.minute_fill:
                return _err("触发后下一分钟成交需要先开启分钟成交")
            if not exit_signals:
                return _err("当前策略没有卖出信号，无法使用触发后下一分钟成交")
            unsupported = unsupported_minute_exit_signals(exit_signals)
            if unsupported:
                return _err(f"以下卖出信号暂不支持分钟触发回放: {', '.join(unsupported)}")
        stop_loss = self._override_value(overrides, "stop_loss", s.stop_loss)
        take_profit = self._normalize_pct(
            self._override_value(overrides, "take_profit", getattr(s, "take_profit", None)),
            0.01,
            5.0,
        )
        trailing_stop = self._normalize_pct(
            self._override_value(overrides, "trailing_stop", getattr(s, "trailing_stop", None)),
            0.005,
            0.5,
        )
        trailing_take_profit_activate = self._normalize_pct(
            self._override_value(overrides, "trailing_take_profit_activate", getattr(s, "trailing_take_profit_activate", None)),
            0.01,
            2.0,
        )
        trailing_take_profit_drawdown = self._normalize_pct(
            self._override_value(overrides, "trailing_take_profit_drawdown", getattr(s, "trailing_take_profit_drawdown", None)),
            0.005,
            0.5,
        )
        if trailing_take_profit_activate is not None and trailing_take_profit_drawdown is not None:
            trailing_take_profit_drawdown = min(trailing_take_profit_drawdown, trailing_take_profit_activate)
        max_hold_days = self._override_value(overrides, "max_hold_days", s.max_hold_days)
        cooldown_loss_streak = self._override_value(overrides, "cooldown_loss_streak", s.cooldown_loss_streak)
        cooldown_days = self._override_value(overrides, "cooldown_days", s.cooldown_days)
        score_min, score_max = self._normalize_score_range(
            overrides.get("score_min"),
            overrides.get("score_max"),
        )

        if s.execution_backend == "minute_filter":
            # 分钟策略回测: 逐交易日回放 filter_minute_history (与实盘选股同源),
            # 信号分钟收盘价入场, 之后复用日K矩阵模拟的离场与组合管理。
            return self._run_minute_backtest(
                config, s, params, overrides,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop=trailing_stop,
                trailing_take_profit_activate=trailing_take_profit_activate,
                trailing_take_profit_drawdown=trailing_take_profit_drawdown,
                max_hold_days=max_hold_days,
                score_min=score_min,
                score_max=score_max,
                cooldown_loss_streak=cooldown_loss_streak,
                cooldown_days=cooldown_days,
                progress_cb=progress_cb,
                cancel_event=cancel_event,
                result_policy=result_policy,
                run_id=run_id,
                t0=t0,
            )

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
                entry_time_mask = entry_time_mask & _rm
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
                    entry_time_mask = entry_time_mask & _rm
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
                    scoring_directions=effective_scoring_directions(overrides),
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

        # 检查是否被取消
        if cancel_event is not None and cancel_event.is_set():
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error="cancelled",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            )

        if result.stats.get("error"):
            return _err(result.stats["error"])

        timing_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
        result.stats["timing_ms"] = timing_ms
        result.stats["panel_rows"] = panel_rows
        result.stats["panel_columns"] = panel_columns
        result.stats["feature_columns"] = feature_width
        result.stats["full_feature_fallback"] = feature_plan.full_feature_fallback
        result.stats["execution_backend"] = s.execution_backend
        result.stats["selection"] = selection_stats
        result.stats["shared_market_data"] = prepared is not None
        result.stats["matrix_data_cache_hit"] = matrix_data_cache_hit
        result.stats["matrix_data_cache_status"] = matrix_data_cache_status
        result.stats["matrix_data_cache_timing_ms"] = dict(matrix_data_cache_timing_ms)
        if prepared is not None:
            result.stats["shared_market_data_bytes"] = prepared.market_data.nbytes
            result.stats["shared_prepare_timing_ms"] = prepared.prepare_timing_ms
            result.stats["matrix_compute_cache"] = prepared.compute_cache.snapshot()

        benchmark_curve = (
            self._build_benchmark_curve(config.start, config.end)
            if result_policy.include_benchmark
            else []
        )

        # 构建策略信息
        strategy_info = {
            "id": s.meta.get("id", config.strategy_id),
            "name": s.meta.get("name", config.strategy_id),
            "description": s.meta.get("description", ""),
            "entry_signals": entry_signals,
            "exit_signals": exit_signals,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop": trailing_stop,
            "trailing_take_profit_activate": trailing_take_profit_activate,
            "trailing_take_profit_drawdown": trailing_take_profit_drawdown,
            "max_hold_days": max_hold_days,
            "full_horizon_days": full_horizon_days,
            "score_min": score_min,
            "score_max": score_max,
            "source": s.source,
            "execution_backend": s.execution_backend,
            "cooldown_loss_streak": cooldown_loss_streak,
            "cooldown_days": cooldown_days,
            **(
                {
                    "composite_children": [
                        {
                            "id": cid,
                            "weight": cw,
                        }
                        for cid, cw in getattr(self, "_composite_children_weights", [])
                    ]
                }
                if s.execution_backend == "composite"
                else {}
            ),
        } if result_policy.include_strategy_info else {}

        selected_stats = result_policy.select_stats(result.stats)

        # 因子归因 (fail-open): 快照与成交按信号日关联, 失败只记日志不影响结果
        factor_attribution = None
        if factor_snapshot and result.trades and result_policy.include_trades:
            try:
                factor_attribution = _factor_attribution_summary(
                    factor_snapshot["frame"], result.trades
                )
            except Exception as exc:
                logger.warning("factor attribution failed: %s", exc)

        elapsed = (time.perf_counter() - t0) * 1000

        return StrategyBacktestResult(
            run_id=run_id,
            config=self._config_to_dict(config),
            stats=selected_stats,
            equity_curve=result.equity_curve if result_policy.include_curves else [],
            drawdown_curve=result.drawdown_curve if result_policy.include_curves else [],
            benchmark_curve=benchmark_curve,
            trades=(
                [self._trade_to_dict(t) for t in result.trades]
                if result_policy.include_trades
                else []
            ),
            per_symbol_stats=(
                result.per_symbol_stats
                if result_policy.include_per_symbol_stats
                else []
            ),
            strategy_info=strategy_info,
            factor_attribution=factor_attribution,
            elapsed_ms=round(elapsed, 1),
        )

    # ── 分钟策略回测: 逐日回放入场 + 日K矩阵离场 ──

    def _run_minute_backtest(
        self,
        config: StrategyBacktestConfig,
        s: StrategyDef,
        params: dict,
        overrides: dict,
        *,
        stop_loss,
        take_profit,
        trailing_stop,
        trailing_take_profit_activate,
        trailing_take_profit_drawdown,
        max_hold_days,
        score_min,
        score_max,
        cooldown_loss_streak,
        cooldown_days,
        progress_cb,
        cancel_event,
        result_policy: BacktestResultPolicy,
        run_id: str,
        t0: float,
    ) -> StrategyBacktestResult:
        def _err(msg: str) -> StrategyBacktestResult:
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error=msg,
                elapsed_ms=(time.perf_counter() - t0) * 1000,
            )

        if config.asset_type != "stock":
            return _err("分钟策略回测当前仅支持 A 股 (stock)")
        if config.exit_fill == "signal_next_minute":
            return _err("分钟策略回测暂不支持「信号触发卖出」离场口径")

        minute_days = self.engine.repo.list_minute_dates(config.start, config.end, "stock")
        if not minute_days:
            earliest = self.engine.repo.earliest_minute_date()
            hint = f"本地分钟K最早到 {earliest}, " if earliest else "本地无分钟K数据, "
            return _err(
                f"回测区间内无分钟K数据: {hint}请先用「扩展分钟K历史」拉取, 或开启盘中分钟增量"
            )

        # 日线面板一次加载: 覆盖首个回测日的日线窗口 + 模拟区间 (含 full 模式尾部)。
        daily_bars = int(s.minute_daily_bars or 0)
        feature_plan = minute_replay_feature_plan(daily_bars)
        load_start = minute_panel_start(config.start, daily_bars)
        full_horizon_days = int(max_hold_days or config.holding_days or 5)
        load_end = config.end
        if config.mode == "full":
            load_end = config.end + timedelta(days=(full_horizon_days + 5) * 2)
        sim_end = load_end if config.mode == "full" else config.end

        timing_ms: dict[str, float] = {}
        t_load = time.perf_counter()
        try:
            panel = self.engine.load_panel_for_backtest(
                config.symbols,
                load_start,
                load_end,
                feature_plan,
                asset_type="stock",
            )
        except (ValueError, OSError, pl.exceptions.PolarsError) as e:
            return _err(f"回测特征准备失败: {e}")
        timing_ms["load_panel"] = round((time.perf_counter() - t_load) * 1000, 1)
        if panel.is_empty():
            return _err("无日线数据, 请检查日期范围或先运行盘后管道")

        replayer = MinuteSignalReplayer(self.engine, self.strategy_engine)
        replay = replayer.replay(
            s,
            panel=panel,
            start=config.start,
            end=config.end,
            params=params,
            overrides=overrides,
            symbols=config.symbols,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        timing_ms["minute_replay"] = replay.elapsed_ms
        if cancel_event is not None and cancel_event.is_set():
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error="cancelled",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        if not replay.hits:
            skipped_hint = (
                f" (区间内 {len(replay.skipped_days)} 个交易日缺分钟K分区被跳过)"
                if replay.skipped_days else ""
            )
            return _err("在指定区间内未产生买入信号" + skipped_hint)

        # 日频信号网格: 正式区间面板 → time x asset 矩阵, 命中格写入入场价覆盖。
        sim_panel = panel.filter(
            (pl.col("date") >= config.start) & (pl.col("date") <= sim_end)
        )
        if sim_panel.is_empty():
            return _err("正式回测区间内无数据")
        axis_dates = sim_panel.get_column("date").unique().sort().to_list()
        # 轴顺序必须与 build_market_data_matrix 的 _encode_axes 一致 (unique().sort()),
        # 否则 (time, asset) 下标指向错误的标的。
        axis_symbols = sim_panel.get_column("symbol").cast(pl.Utf8).unique().sort().to_list()
        time_index = {day: i for i, day in enumerate(axis_dates)}
        asset_index = {sym: i for i, sym in enumerate(axis_symbols)}
        shape = (len(axis_dates), len(axis_symbols))

        entry = np.zeros(shape, dtype=np.uint8)
        score = np.zeros(shape, dtype=np.float32)
        entry_price_override = np.full(shape, np.nan, dtype=np.float32)
        trigger_times: dict[tuple[str, date], str] = {}
        dropped_axis_hits = 0
        for hit in replay.hits:
            time_id = time_index.get(hit.trade_date)
            asset_id = asset_index.get(hit.symbol)
            if time_id is None or asset_id is None:
                dropped_axis_hits += 1
                continue
            entry[time_id, asset_id] = 1
            score[time_id, asset_id] = hit.score
            entry_price_override[time_id, asset_id] = hit.entry_price
            trigger_times[(hit.symbol, hit.trade_date)] = hit.trigger_time
        raw_candidates = int(entry.sum())
        entry.setflags(write=False)
        score.setflags(write=False)
        entry_price_override.setflags(write=False)
        exit_mask = np.zeros(shape, dtype=np.uint8)
        exit_mask.setflags(write=False)
        codes = np.zeros(shape, dtype=np.int16)
        codes.setflags(write=False)
        signals = SignalMatrix(
            entry=entry,
            exit=exit_mask,
            score=score,
            entry_signal_code=codes,
            exit_signal_code=codes,
            entry_signal_ids=(),
            exit_signal_ids=(),
        )

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
        )

        t_matrix = time.perf_counter()
        market_data = build_market_data_matrix(sim_panel)
        market_matrix = build_market_matrix_from_signals(
            market_data,
            signals,
            # 入场即信号日盘中 (分钟价覆盖), 离场沿用日K口径。
            entry_delay_bars=0,
            exit_delay_bars=1 if matcher_config.exit_fill == "open_t+1" else 0,
            entry_price_override=entry_price_override,
        )
        timing_ms["matrix_build"] = round((time.perf_counter() - t_matrix) * 1000, 1)
        del sim_panel, market_data

        t_sim = time.perf_counter()
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

        if cancel_event is not None and cancel_event.is_set():
            return StrategyBacktestResult(
                run_id=run_id,
                config=self._config_to_dict(config),
                error="cancelled",
                elapsed_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        if result.stats.get("error"):
            return _err(result.stats["error"])

        execution = result.stats.get("execution") or {}
        execution["buy_limit_up"] = int(execution.get("buy_limit_up", 0)) + replay.buy_limit_up
        result.stats["execution"] = execution
        timing_ms["total"] = round((time.perf_counter() - t0) * 1000, 1)
        result.stats["timing_ms"] = timing_ms
        result.stats["panel_rows"] = int(len(axis_dates) * len(axis_symbols))
        result.stats["panel_columns"] = 0
        result.stats["feature_columns"] = 0
        result.stats["execution_backend"] = s.execution_backend
        result.stats["selection"] = {
            "strategy_matches": replay.strategy_matches,
            "entry_candidates": raw_candidates,
            "entry_trigger_filtered": max(replay.strategy_matches - raw_candidates, 0),
            "entry_trigger_enabled": False,
        }
        result.stats["minute_replay"] = {
            "replayed_days": replay.replayed_days,
            "skipped_days": [str(day) for day in replay.skipped_days[:50]],
            "skipped_day_count": len(replay.skipped_days),
            "dropped_axis_hits": dropped_axis_hits,
        }

        benchmark_curve = (
            self._build_benchmark_curve(config.start, config.end)
            if result_policy.include_benchmark
            else []
        )
        strategy_info = {
            "id": s.meta.get("id", config.strategy_id),
            "name": s.meta.get("name", config.strategy_id),
            "description": s.meta.get("description", ""),
            "entry_signals": [],
            "exit_signals": [],
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop": trailing_stop,
            "trailing_take_profit_activate": trailing_take_profit_activate,
            "trailing_take_profit_drawdown": trailing_take_profit_drawdown,
            "max_hold_days": max_hold_days,
            "full_horizon_days": full_horizon_days,
            "score_min": score_min,
            "score_max": score_max,
            "source": s.source,
            "execution_backend": s.execution_backend,
            "cooldown_loss_streak": cooldown_loss_streak,
            "cooldown_days": cooldown_days,
        } if result_policy.include_strategy_info else {}

        trades = (
            [self._trade_to_dict(t) for t in result.trades]
            if result_policy.include_trades
            else []
        )
        # 入场时间戳补分钟: 交易记录携带触发分钟 (HH:MM), 与日线回测的纯日期区分。
        for trade in trades:
            entry_text = str(trade.get("entry_date") or "")
            try:
                key = (str(trade.get("symbol")), date.fromisoformat(entry_text[:10]))
            except ValueError:
                continue
            trigger = trigger_times.get(key)
            if trigger:
                trade["entry_date"] = f"{entry_text[:10]} {trigger}"
