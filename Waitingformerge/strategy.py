"D:\Code\githubProject\tick-stock-panel\backend\app\backtest\strategy.py"

    # 分钟K精确成交: 开启后用当日分钟K确定穿越价/VWAP (需 Pro+ 分钟K能力)
    minute_fill: bool = False
    # 同日买卖执行顺序: "auto"=按 entry_fill/exit_fill 时序自动判断,
    # "sell_first"=强制先卖后买(向后兼容), "buy_first"=强制先买后卖。
    fill_order: Literal["auto", "sell_first", "buy_first"] = "auto"
    # 市场环境过滤: {"states": ["strong",...], "min_score": 60}。
    # 强制 T-1: regime[T-1] 决定 entry[T](防未来函数)。None=不过滤。
    regime_filter: dict | None = None
