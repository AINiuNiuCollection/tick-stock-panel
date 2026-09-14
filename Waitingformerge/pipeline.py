            if not enriched_new.is_empty():
                for date_df in enriched_new.partition_by("date"):
                    dt = date_df["date"][0]
                    ds = dt.isoformat() if hasattr(dt, "isoformat") else str(dt)
                    out = enriched_base / f"date={ds}" / "part.parquet"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    # ── 去重: 同一 symbol+date 可能因增量管道重复回读产生多行,
                    # 按 [symbol, date] 去重保留最后一行, 避免下游 JOIN 放大行数 ──
                    date_df = _select_storage_cols(date_df).unique(subset=["symbol", "date"], keep="last").sort(["symbol"])
                    publication.write_parquet(date_df, out)
                    written += date_df.height
                t_write_new = _t.perf_counter()
                logger.info("增量写入: %.2fs, %d 行", t_write_new - t_new, written)
            del raw_new, hist_df, raw_full, enriched_new

        # 3. 受除权因子影响的个股: 重算全部已有日期 (累积因子链变了)

