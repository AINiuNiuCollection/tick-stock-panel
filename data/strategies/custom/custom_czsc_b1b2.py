"""缠论 B1/B2 买点选股 — 复用 czsc 严格识别算法。

在候选池上逐股运行缠论分析, 筛选已出现 B1(趋势背驰)或 B2(盘整背驰+次级别确认)
买点的股票。缠论级别(日线/30分钟/周线)与判定口径全部通过策略设置面板配置,
复用 /api/czsc/analyze 的同一套 DivergenceConfig。

候选池构造顺序 (需求A, 2026-11-23):
    1. 引擎在调本策略前已按 as_of 横截面应用基础过滤 (价格/流通市值/成交额/
       板块/ST, 即策略设置里的"基础参数"), 只保留符合基础条件的股票 —
       全市场 ~5000 只先缩到用户条件的几百只, 结果统计行展示过滤后数量;
    2. 本策略再按成交额排序截断到 max_symbols 只 (0=不截断), 逐股缠论分析。

信号输出 (需求2, 2026-11-23):
    czsc_signal = "B1@本级别日期@价格@次级别日期, ..." — 第4段次级别日期
    来自区间套下钻 (缠师第27课) 的次级别背驰段结束时间; 次级别数据不可用
    或区间套未确认时省略第4段 (保持旧3段格式, 前端兼容解析)。

B1 次级别确认 (2026-11-23): bs_b1_sub_confirm 默认开启 — B1 必须区间套
下钻确认 (次级别同向背驰, 即信号含第4段次级别日期) 才算命中。源不可用
例外 (G, 2026-11-23): 次级别源级失败 (取数异常/空帧/熔断冷却) 时 B1 保留
并随结果返回警告 — 不静默丢弃; "有数据但未确认" 仍丢弃 (fail-closed)。
B2 不受影响。当日 30 分钟 K 线缺失不算源失败 (取数窗口含历史, 帧非空即正常)。

信号年龄 (2026-11-23): max_signal_age 单位为本级别K线根数 — 周线按周K线、
日线按交易日; 周末/节假日无K线不计 ("只计算交易日的时间")。0=不限。

执行时机 (需求1, 2026-11-23): 全市场逐股缠论分析工作量大 — 仅在用户点击
"分析"按钮或定时任务到达时执行; 前端所有自动触发路径对带 META.manual_run_only
标记的策略跳过 (设置保存后重跑/进页面自动补跑/策略池新增/新建策略/重新运行按钮)。
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
    # 需求1 (2026-11-23): 全市场逐股缠论分析工作量大 — 仅在用户点击"分析"
    # 按钮或定时任务时执行; 前端所有自动触发路径对本策略跳过。
    "manual_run_only": True,
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
            "id": "max_signal_age", "label": "信号最大年龄(本级别K线数, 0=不限)", "type": "int",
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
        {
            # B1 需次级别背驰确认 (区间套下钻, 缠师第27课): 开启时 B1 必须在
            # 次级别(日线→30分钟)也出现同向背驰才算命中; 30分钟源不可用或
            # 区间套未确认时 B1 不输出 (fail-closed)。B2 不受此开关影响
            # (定律一次级别验证已作置信度标注)。
            "id": "bs_b1_sub_confirm", "label": "B1需次级别背驰确认", "type": "bool",
            "default": True,
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
1. 引擎先按基础条件(价格/流通市值/成交额/板块/ST)过滤 as_of 横截面, 统计符合数量后再进本策略
2. 候选池按成交额排序取前 max_symbols 只(控制缠论逐股分析耗时, 0=不截断)
3. 在指定缠论级别(日线/30分钟/周线)上识别 B1(趋势背驰)或 B2(盘整背驰)
4. 信号年龄不超过 max_signal_age 根本级别K线(周线按周K线, 只计交易日); 背驰条件命中数达到阈值
5. 判定口径(面积/DIF/逻辑/重叠/回抽深度)与缠论分析页面完全同源
6. 信号含本级别与次级别触发日期(区间套下钻); 执行时机仅"分析"按钮/定时任务
7. B1 默认需次级别背驰确认(bs_b1_sub_confirm, 区间套); 有数据但未确认时 B1 丢弃,
   次级别源不可用时 B1 保留并返回警告 (G, 2026-11-23)
"""


def filter_history(df: pl.DataFrame, params: dict):
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
    # B1 次级别背驰确认 (2026-11-23, 默认开启): B1 必须区间套下钻确认
    # (次级别同向背驰, 即信号带第4段次级别日期) 才算命中 — sub_dt 为空
    # = 未确认 → 丢弃 (fail-closed)。G (2026-11-23): 源级失败
    # (sub_source_unavailable) 时例外 — B1 保留并返回警告, 不静默丢弃。
    # B2 不受此开关影响。
    b1_sub_confirm = bool(params.get("bs_b1_sub_confirm", True))
    # 信号详情随行透出 (需求2: 第4段=次级别背驰点日期, 区间套下钻):
    # "B1@2026-11-12@12.34@2026-11-13" — 有次级别日期时价格段固定占位
    # (可为空), 保证前端按段索引解析; 无次级别日期保持旧3段格式。
    hits_by_symbol: dict[str, list[str]] = {}
    retained_unconfirmed = 0
    for h in result.hits:
        # sub_source_unavailable 是 ScanHit 声明字段 (缺省 False), 直接访问
        # (getattr 不在策略安全白名单)
        if b1_sub_confirm and h.type == "B1" and not h.sub_dt:
            if h.sub_source_unavailable:
                retained_unconfirmed += 1
            else:
                continue
        dt = str(h.dt)[:10]
        price = h.price if h.price else None
        price_s = f"{price:g}" if price else ""
        # sub_dt 是 ScanHit 声明字段 (缺省 None), 直接访问 (getattr 不在策略安全白名单)
        sub_dt = str(h.sub_dt)[:10] if h.sub_dt else ""
        parts = f"{h.type}@{dt}@{price_s}"
        if sub_dt:
            parts += f"@{sub_dt}"
        hits_by_symbol.setdefault(h.symbol, []).append(parts)
    # G: 警告透传 — 扫描层源不可用提示 + 因源不可用而保留的未确认 B1 计数,
    # 经引擎元组协议 (df, warnings) 上报前端; 早期返回路径保持纯 df 兼容。
    warnings = list(result.warnings or [])
    if retained_unconfirmed > 0:
        warnings.append(
            f"次级别源不可用: {retained_unconfirmed} 个 B1 信号未经区间套确认即保留 — "
            "请谨慎参考, 源恢复后重跑可补全确认"
        )
    if not hits_by_symbol:
        return latest.head(0), warnings
    out = latest.filter(pl.col("symbol").is_in(list(hits_by_symbol.keys())))
    return out.with_columns(
        pl.col("symbol")
        .map_elements(lambda s: ", ".join(hits_by_symbol.get(s, [])), return_dtype=pl.Utf8)
        .alias("czsc_signal")
    ), warnings
