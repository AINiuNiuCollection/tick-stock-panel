        # 2. 为新日期计算 enriched (所有标的)
        if new_date_dirs:
            raw_new = scan_daily_parquet(new_date_dirs[0] / "*.parquet", cast_options=_cast)
            for nd in new_date_dirs[1:]:
                raw_new = pl.concat([raw_new, scan_daily_parquet(nd / "*.parquet", cast_options=_cast)], how="diagonal_relaxed")
            raw_new = raw_new.sort(["symbol", "date"]).collect(streaming=True)

            # 增量模式: 只算新日期, 但指标需要历史窗口
            # 读已有 enriched 最近 60 天作为历史前缀
            sym_list = raw_new["symbol"].unique().to_list()
            hist_df = _load_recent_history(enriched_base, sym_list, days=60)

            # 合并历史 + 新数据
            if not hist_df.is_empty():
                # 只取基础行情列做历史前缀
                hist_cols = [c for c in ["symbol", "date", "open", "high", "low", "close",
                                         "volume", "amount", "raw_close", "raw_high", "raw_low"]
                             if c in hist_df.columns]
                raw_full = pl.concat([hist_df.select(hist_cols), raw_new], how="diagonal_relaxed")
            else:
                raw_full = raw_new

            # 去重: hist_df 可能已包含 new_date_dirs 的日期(前一次同步已写入),
            # 拼接后同一 symbol+date 会出现多行, 导致 enriched 重复行 → prewarm 报错。
            # 按 symbol+date 去重, 保留最后一条(即 raw_new 的新数据)。
            raw_full = raw_full.unique(subset=["symbol", "date"], keep="last").sort(["symbol", "date"])
