"""缠论 B1/B2 买点选股 — 复用 czsc 严格识别算法。

在候选池(按成交额/流动性取 Top N)上逐股运行缠论分析, 筛选已出现 B1(趋势背驰)
或 B2(盘整背驰+次级别确认)买点的股票。缠论级别(日线/30分钟/周线)与判定口径
全部通过策略设置面板配置, 复用 /api/czsc/analyze 的同一套 DivergenceConfig。

注意: 缠论分析是逐股 CPU 密集计算, 不写普通 Polars 表达式策略。本策略用
python_history_legacy 后端, 在 filter_history 里同步调用 czsc 扫描服务:
先用 enriched 横截面按流动性缩到 max_symbols 只, 再逐股分析。
"""
import polars as pl

from app.custom.czsc.application.scanner import ScanService
from app.custom.czsc.config import DivergenceConfig, ScanRequest

META = {
    "id": "custom_czsc_b1b2",
    "name": "缠论B1/B2买点",
    "description": "缠论严格识别: 趋势背驰B1 + 盘整背驰B2。级别与判定口径可在设置里切换(日线/30分钟/周线)",
    "tags": ["缠论", "背驰", "B1", "B2", "抄底"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "price_max": 500,
        "market_cap_min": 20e8,
        "amount_min": 1e8,
        "exclude_st": True,
        "exclude_new_days": 60,
    },
    "params": [
        {
            "id": "freq", "label": "缠论级别", "type": "select", "default": "日线",
            "options": [
                {"label": "日线", "value": "日线"},
                {"label": "30分钟", "value": "30分钟"},
                {"label": "周线", "value": "周线"},
            ],
        },
        {
            "id": "signal_types", "label": "信号类型", "type": "select", "default": "B1,B2",
            "options": [
                {"label": "B1+B2", "value": "B1,B2"},
                {"label": "仅B1(趋势背驰)", "value": "B1"},
                {"label": "仅B2(盘整背驰)", "value": "B2"},
            ],
        },
        {
            "id": "max_signal_age", "label": "信号最大年龄(天)", "type": "int",
            "default": 10, "min": 0, "max": 60, "step": 1,
        },
        {
            "id": "lookback_days", "label": "分析窗口(天)", "type": "int",
            "default": 425, "min": 120, "max": 1200, "step": 30,
        },
        {
            "id": "min_divergence_hits", "label": "背驰条件最少命中数", "type": "int",
            "default": 2, "min": 0, "max": 2, "step": 1,
        },
        {
            "id": "max_symbols", "label": "最多扫描只数(按成交额, 0=全部)", "type": "int",
            "default": 0, "min": 0, "max": 8000, "step": 100,
        },
        {
            "id": "bs_macd_area_mode", "label": "MACD面积口径", "type": "select", "default": "split",
            "options": [
                {"label": "红绿柱分计", "value": "split"},
                {"label": "Σ|hist|", "value": "total_abs"},
                {"label": "Σ|DIF-DEA|", "value": "dif_dea"},
            ],
        },
        {
            "id": "bs_use_dif", "label": "启用DIF极值条件", "type": "bool", "default": True,
        },
        {
            "id": "bs_use_macd_area", "label": "启用MACD面积条件", "type": "bool", "default": True,
        },
        {
            "id": "bs_divergence_logic", "label": "背驰条件逻辑", "type": "select", "default": "and",
            "options": [
                {"label": "AND(严格,第24课)", "value": "and"},
                {"label": "OR(宽松,第27课)", "value": "or"},
            ],
        },
        {
            "id": "bs_trend_overlap_mode", "label": "趋势中枢重叠口径", "type": "select", "default": "practical",
            "options": [
                {"label": "核心区间[ZD,ZG]", "value": "practical"},
                {"label": "波动区间[DD,GG](严格)", "value": "strict"},
            ],
        },
        {
            "id": "bs_zs_pullback_base", "label": "回抽深度基准", "type": "select", "default": "zg",
            "options": [
                {"label": "中枢上沿ZG", "value": "zg"},
                {"label": "中枢高度", "value": "height"},
            ],
        },
        {
            "id": "bs_zs_pullback_min_ratio", "label": "回抽最小深度比例", "type": "float",
            "default": 0.02, "min": 0.0, "max": 0.2, "step": 0.01,
        },
    ],
    "scoring": {"amount": 1.0},
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "python_history_legacy"
LOOKBACK_DAYS = 430

ENTRY_SIGNALS = []
EXIT_SIGNALS = []
STOP_LOSS = -0.08
MAX_HOLD_DAYS = 20

RULES = """
1. 候选池按成交额排序取前 max_symbols 只(控制缠论逐股分析耗时)
2. 在指定缠论级别(日线/30分钟/周线)上识别 B1(趋势背驰)或 B2(盘整背驰)
3. 信号年龄不超过 max_signal_age 天; 背驰条件命中数达到阈值
4. 判定口径(面积/DIF/逻辑/重叠/回抽深度)与缠论分析页面完全同源
"""


def filter_history(df: pl.DataFrame, params: dict) -> pl.DataFrame:
    if df.is_empty() or "symbol" not in df.columns or "date" not in df.columns:
        return df

    as_of = df["date"].max()
    latest = df.filter(pl.col("date") == as_of)
    if latest.is_empty():
        return latest

    freq = str(params.get("freq", "日线"))
    signal_types = tuple(
        s.strip().upper() for s in str(params.get("signal_types", "B1,B2")).split(",") if s.strip()
    ) or ("B1", "B2")
    # max_symbols<=0 表示不截断 — 基础条件筛出多少检视多少
    # (本地日K源后单股毫秒级, 全市场 ~5000 只在 16 并发下分钟级完成)
    max_symbols = int(params.get("max_symbols", 0) or 0)

    # 候选按成交额排序截断 — 0/负值 = 全量
    if max_symbols > 0 and "amount" in latest.columns:
        candidates = latest.sort("amount", descending=True).head(max_symbols)
    else:
        candidates = latest
    symbols = candidates["symbol"].to_list()
    if not symbols:
        return latest.head(0)

    divergence = DivergenceConfig(
        macd_area_mode=str(params.get("bs_macd_area_mode", "split")),
        use_dif=bool(params.get("bs_use_dif", True)),
        use_macd_area=bool(params.get("bs_use_macd_area", True)),
        divergence_logic=str(params.get("bs_divergence_logic", "and")),
        trend_overlap_mode=str(params.get("bs_trend_overlap_mode", "practical")),
        zs_pullback_base=str(params.get("bs_zs_pullback_base", "zg")),
        zs_pullback_min_ratio=float(params.get("bs_zs_pullback_min_ratio", 0.02)),
    )
    req = ScanRequest(
        symbols=tuple(symbols),
        freq=freq,
        as_of=as_of.date() if hasattr(as_of, "date") else as_of,
        lookback_days=int(params.get("lookback_days", 425)),
        signal_types=signal_types,
        max_signal_age=int(params.get("max_signal_age", 10)),
        min_divergence_hits=int(params.get("min_divergence_hits", 2)),
        order_by="dt_desc",
        limit=len(symbols),
        max_workers=16,
        divergence=divergence,
    ).normalized()

    result = ScanService().scan(req)
    # 信号详情随行透出: symbol → "B1@2026-11-12@12.34, B2@..." (前端 B1/B2 信号列)
    hits_by_symbol: dict[str, list[str]] = {}
    for h in result.hits:
        dt = str(h.dt)[:10]
        price = h.price if h.price else None
        price_s = f"{price:g}" if price else ""
        hits_by_symbol.setdefault(h.symbol, []).append(
            f"{h.type}@{dt}" + (f"@{price_s}" if price_s else "")
        )
    if not hits_by_symbol:
        return latest.head(0)
    out = latest.filter(pl.col("symbol").is_in(list(hits_by_symbol.keys())))
    return out.with_columns(
        pl.col("symbol")
        .map_elements(lambda s: ", ".join(hits_by_symbol.get(s, [])), return_dtype=pl.Utf8)
        .alias("czsc_signal")
    )
