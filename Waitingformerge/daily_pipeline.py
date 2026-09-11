    # Step 2.7: 市场主线(概念/行业涨停梯队聚合) 增量计算 — regime 同开关。
    # 只窄扫连板 >=1 的行, 增量通常 1 天, 开销可忽略。软失败: 不阻断主管道。
    mainline_rows = 0
    if not _prefs_regime.get_pipeline_regime_enabled():
        skipped.append("mainline")
    else:
        try:
            emit("compute_mainline", 93, "计算市场主线…")
            from app.services import market_mainline
            for _kind in ("concept", "industry"):
                rows = market_mainline.compute_mainline_incremental(
                    repo, repo.store.data_dir, kind=_kind
                )
                mainline_rows += rows.height if not rows.is_empty() else 0
            if mainline_rows:
                logger.info("compute_mainline: %d rows", mainline_rows)
            emit("compute_mainline", 94, f"市场主线 {mainline_rows} 行")
        except Exception as e:
            logger.warning("compute_mainline failed (soft): %s", e)
            stage_errors.append(f"compute_mainline: {e}")
            skipped.append("mainline")

    # Step 2.8: 0AMV (活跃市值) 增量计算 — enriched 已就绪后聚合。
    # 前置: Step 2.2 enriched 写盘完成(close/volume 就绪)。
    # 依赖: close × float_shares, float_shares 来自 instruments 快照(无历史变更)。
    # 与 regime 同开关: 本地聚合(非拉取), 软失败不阻断主管道。
    amv_days = 0
    if not _prefs_regime.get_pipeline_regime_enabled():
        skipped.append("amv")
    else:
        try:
            emit("compute_amv", 94, "计算活跃市值…")
            from app.services import market_amv as _amv_svc
            from app.api.market_amv import invalidate_amv_cache
            new_amv = _amv_svc.compute_amv_incremental(repo, repo.store.data_dir)
            amv_days = new_amv.height if not new_amv.is_empty() else 0
            if amv_days:
                invalidate_amv_cache()
                logger.info("compute_amv: %d days", amv_days)
            emit("compute_amv", 95, f"活跃市值 {amv_days} 天")
        except Exception as e:  # noqa: BLE001
            logger.warning("compute_amv failed (soft): %s", e)
            stage_errors.append(f"compute_amv: {e}")
            skipped.append("amv")

    # Step 3: 刷新视图
    emit("refresh_views", 95, "刷新 DuckDB 视图…")
    _refresh_views(repo)

    emit("done", 100, "完成")
    _invalidate(None)  # 兜底:全清
