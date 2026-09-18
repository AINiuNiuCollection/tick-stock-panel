"D:\CodeHub\github-tick-stock\tick-stock-panel\backend\app\indicators\pipeline.py"








        # 3. 受除权因子影响的个股: 重算全部已有日期 (累积因子链变了)
        if symbols:
            sym_set = set(symbols)
            raw_sym = scan_daily_parquet(daily_glob, cast_options=_cast).sort(["symbol", "date"])
            raw_sym = raw_sym.filter(pl.col("symbol").is_in(list(sym_set)))
            raw_sym = raw_sym.collect(streaming=True)
            if not raw_sym.is_empty():
                factors_sym = factors.filter(pl.col("symbol").is_in(list(sym_set))) if not factors.is_empty() else factors
                inst_sym = instruments.filter(pl.col("symbol").is_in(list(sym_set))) if not instruments.is_empty() else instruments
                shares_sym = historical_shares.filter(pl.col("symbol").is_in(list(sym_set))) if not historical_shares.is_empty() else historical_shares
                enriched_sym = _compute_storage_batches(
                    raw_sym,
                    factors=factors_sym,
                    instruments=inst_sym,
                    historical_shares=shares_sym,
                )
                for date_df in enriched_sym.partition_by("date"):
                    dt = date_df["date"][0]
                    ds = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
                    out = enriched_base / f"date={ds}" / "part.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    date_df_storage = _select_storage_cols(date_df)
                    if out.exists():
                        existing = pl.read_parquet(out)
                        existing = existing.filter(~pl.col("symbol").is_in(list(sym_set)))
                        date_df_storage = pl.concat([existing, date_df_storage], how="diagonal_relaxed")
                    date_df_storage = date_df_storage.unique(subset=["symbol", "date"], keep="last").sort(["symbol"])
                    publication.write_parquet(date_df_storage, out)
                    written += date_df.height
                logger.info("除权重算: %d 只, 共写入 %d 行", len(sym_set), written)



**************************************************************************************************************************************************
            if not enriched.is_empty():
                if symbols:
                    # 局部模式: 直接按日期合并写入
                    for date_df in _select_storage_cols(enriched).partition_by("date"):
                        dt = date_df["date"][0]
                        ds = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
                        out = base / f"date={ds}" / "part.parquet"
                        out.parent.mkdir(parents=True, exist_ok=True)
                        date_df_storage = _select_storage_cols(date_df)
                        if out.exists():
                            existing = pl.read_parquet(out)
                            existing = existing.filter(~pl.col("symbol").is_in(batch_syms))
                            date_df_storage = pl.concat([existing, date_df_storage], how="diagonal_relaxed")
                        date_df_storage = date_df_storage.unique(subset=["symbol", "date"], keep="last").sort(["symbol"])
                        publication.write_parquet(date_df_storage, out)
                        written += date_df_storage.height
                else:
                    # 全量模式: 写单批暂存文件 (按 date,symbol 排序 →
                    # 合并期 parquet 行组统计可按日期裁剪), 随即释放本批内存
                    out = staging_dir / f"batch-{batch_start // SYM_BATCH:04d}.parquet"
                    _select_storage_cols(enriched).sort(["date", "symbol"]).write_parquet(out)
                    staging_files.append(str(out))
                    written += enriched.height





**************************************************************************************************************************************************

                for date_df in block.partition_by("date"):
                    ds = date_df["date"][0]
                    ds_str = ds.isoformat() if hasattr(ds, "isoformat") else str(ds)
                    out = base / f"date={ds_str}" / "part.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    publication.write_parquet(
                        date_df.unique(subset=["symbol", "date"], keep="last").sort(["symbol"]),
                        out,
                    )
            gc.collect()
            logger.info("全量暂存合并完成: %d 个日期分区", len(unique_dates))
    finally:
        # 无论成功/失败/取消都清掉本次暂存 (历史残留由 _sweep_stale_staging 兜底)
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)




