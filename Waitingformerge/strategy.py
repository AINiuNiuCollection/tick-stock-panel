"D:\Code\githubProject\tick-stock-panel\backend\app\backtest\strategy.py"

    def _resolve_composite_feature_plan(
        self,
        strategy: StrategyDef,
        *,
        params: dict,
        basic_filter: dict,
        overrides: dict,
        asset_type: str = "stock",
    ) -> tuple[ResolvedFeaturePlan, list[tuple[StrategyDef, dict, dict]]]:
        """解析 composite 回测的特征计划: 所有子策略 feature_plan 的并集。

        返回 (合并 feature_plan, [(子策略定义, 子params, 子pipeline_config_dict), ...])。
        子策略必须全为 matrix_native, 否则 fail-closed(首版硬约束)。
        """
        from app.strategy import composite as composite_mod
        from app.strategy.engine import _parse_composite_children

        assert strategy.composite is not None
        # 权重: override.children 优先, 否则 META 声明。
        override_children = overrides.get("children")
        if isinstance(override_children, list) and override_children:
            spec = _parse_composite_children(override_children)
            children = spec.children
        else:
            children = strategy.composite.children

        resolver = StrategyDependencyResolver()
        plans: list[ResolvedFeaturePlan] = []
        resolved_children: list[tuple[StrategyDef, dict, dict]] = []
        for child in children:
            child_def = self.strategy_engine.get(child.strategy_id)
            if child_def.execution_backend != "matrix_native":
                raise ValueError(
                    f"叠加回测暂仅支持矩阵子策略; {child.strategy_id!r} "
                    f"是 {child_def.execution_backend}"
                )
            if child_def.matrix_strategy is None:
                raise ValueError(f"子策略 {child.strategy_id!r} 未注册矩阵策略")
            # 加载子策略的用户 override(参数/评分等), 保证回测与单独跑子策略同口径。
            child_override: dict = {}
            loader = getattr(self.strategy_engine, "_override_loader", None)
            if loader is not None:
                try:
                    loaded = loader(child.strategy_id)
                    if isinstance(loaded, dict):
                        child_override = dict(loaded)
                except Exception:  # noqa: BLE001
                    pass
            child_params = self.strategy_engine.resolve_params(child_def, overrides=child_override)
            child_plan = resolver.resolve(
                child_def,
                params=child_params,
                basic_filter=basic_filter,  # 统一 basic_filter(计划 §3.3)
                entry_signals=[],
                exit_signals=[],
                overrides=child_override,
                asset_type=asset_type,
            )
            plans.append(child_plan)
            # pipeline 用 composite 统一的 basic_filter; scoring 用子策略自己的
            # (默认 + 用户 override), 因为子策略内部排序影响合并器的排名融合。
            child_scoring = effective_scoring(child_def.meta.get("scoring"), child_override)
            child_pipeline_cfg = MatrixPipelineConfig(
                basic_filter=basic_filter,
                scoring=child_scoring,
                scoring_directions=effective_scoring_directions(child_override, child_def.meta),
                order_by=child_def.meta.get("order_by"),
                descending=bool(child_def.meta.get("descending", True)),
                protect_strategy_cache=False,
            )
            resolved_children.append((child_def, child_params, child_pipeline_cfg))

        merged_plan = _merge_resolved_feature_plans(plans)
        # composite 模块用于合并时读取权重列表(顺序对齐 resolved_children)。
        self._composite_children_weights = [(c.strategy_id, c.weight) for c in children]
        _ = composite_mod  # 确保模块可导入(回测时由调用方使用)
        return merged_plan, resolved_children
















*****************************************************************************************************


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
**************************************************************************************************************

    @staticmethod
    def _apply_score(
        panel: pl.DataFrame,
        s: StrategyDef,
        overrides: dict | None,
        universe_mask: pl.Series | None = None,
        factor_snapshot: dict | None = None,
    ) -> pl.DataFrame:
        scoring = effective_scoring(s.meta.get("scoring"), overrides)
        directions = effective_scoring_directions(overrides, s.meta)
