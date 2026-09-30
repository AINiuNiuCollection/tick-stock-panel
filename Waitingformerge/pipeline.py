"D:\CodeHub\github-tick-stock\tick-stock-panel\backend\app\indicators\pipeline.py"




    df = df.join(inst_subset, on="symbol", how="left", suffix="_inst")

    # 换手率: 优先用 API 提供值, null 时从 float_shares 计算 (与全量路径 compute_limit_signals 一致)
    if "float_shares" in df.columns and "volume" in df.columns:
        if "turnover_rate" in df.columns:
            df = df.with_columns(
                pl.when(pl.col("turnover_rate").is_not_null())
                  .then(pl.col("turnover_rate"))
                  .otherwise(
                      pl.when(pl.col("float_shares") > 0)
                        .then(pl.col("volume") * 10000.0 / pl.col("float_shares"))
                        .otherwise(None)
                  )
                  .alias("turnover_rate")
            )
        else:
            df = df.with_columns(
                pl.when(pl.col("float_shares") > 0)
                  .then(pl.col("volume") * 10000.0 / pl.col("float_shares"))
                  .otherwise(None)
                  .alias("turnover_rate")
            )

    # 涨跌停 (用 raw_close / raw_high 和前一日原始收盘价)
    # 优先用 API 原始前收盘价, 回退到 close_right, 最后回退到 raw_close

