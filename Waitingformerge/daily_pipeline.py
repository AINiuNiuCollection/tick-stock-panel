    result = {
        "universe_size": len(universe),
        "daily_days": new_daily_days,
        "adj_factor_symbols": len(affected_symbols),
        "enriched_days": written_enriched,
        "index_count": index_count,
        "index_daily_rows": written_index_daily,
        "etf_count": etf_count,
        "etf_daily_rows": written_etf_daily,
        "etf_adj_factor_symbols": etf_adj_symbols,
        "minute_rows": written_minute,
        "regime_days": regime_days,
        # ── 活跃市值(AMV)计算天数: 0 = 未计算或无数据 ──
        "amv_days": amv_days,
        "mainline_rows": mainline_rows,
        "lagging_symbols": len(lagging_symbols),
        "enriched_total_days": enriched_total_days,
        "integrity_repair_from": repair_start.isoformat() if repair_start else None,
        "integrity_issues": len(integrity_issues),
        "skipped_stages": skipped,
        "stage_errors": stage_errors,
    }

    # 有阶段软失败: 进度协议已走完(done/100, 前端进度条正常收尾), 但数据可能陈旧,
    # 抛出让上层 job_store 把终态标记为 failed —— 不再"部分失败却报成功"。
