"""缠论 B1/B2 买点选股 — 复用 czsc 严格识别算法。

在候选池上逐股运行缠论分析, 筛选已出现 B1(趋势背驰)或 B2(盘整背驰+次级别确认)
买点的股票。缠论级别(月线/周线/日线/60分钟/30分钟/15分钟/5分钟)与判定口径全部通过策略设置面板配置,
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

前置校验 (2026-11-25, 用户裁定): 执行前检测 — as_of 横截面完整性(≥上一交易日
95%)、关键列 null 率(<10%)、市场量级(≥500只)、本地日K可用、次级别分钟源探测
可用(B1 需区间套确认时)。任一不通过 → 不执行, UI 提示先做数据同步/检查数据源。

信号年龄 (2026-11-23): max_signal_age 单位为本级别K线根数 — 周线按周K线、
日线按交易日; 周末/节假日无K线不计 ("只计算交易日的时间")。0=不限。

执行时机 (需求1, 2026-11-23): 全市场逐股缠论分析工作量大 — 仅在用户点击
"分析"按钮或定时任务到达时执行; 前端所有自动触发路径对带 META.manual_run_only
标记的策略跳过 (设置保存后重跑/进页面自动补跑/策略池新增/新建策略/重新运行按钮)。

as_of 截止 (2026-11-25): 执行时间 17:00 前不取当日数据 (当日分区可能在增量
同步中途形成残缺横截面), 以上一交易日为 as_of; 17:00 后才取当日。非交易日
自然落到最近一个交易日。
"""
from datetime import datetime, time as dtime, timedelta

import polars as pl

from app.custom.czsc.application.scanner import ScanService
from app.custom.czsc.application.service import build_scan_analyzer
from app.custom.czsc.config import DivergenceConfig, ScanRequest

META = {
    "id": "custom_czsc_b1b2",
    "name": "缠论B1/B2买点",
    "description": "缠论严格识别: 趋势背驰B1 + 盘整背驰B2。级别与判定口径可在设置里切换(月线/周线/日线/60分钟/30分钟/15分钟/5分钟)",
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
                {"label": "月线", "value": "月线"},
                {"label": "周线", "value": "周线"},
                {"label": "日线", "value": "日线"},
                {"label": "60分钟", "value": "60分钟"},
                {"label": "30分钟", "value": "30分钟"},
                {"label": "15分钟", "value": "15分钟"},
                {"label": "5分钟", "value": "5分钟"},
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
            # 方案A (2026-11-26): 日线扫描起点已锚定全历史 (数据头), 本参数
            # 仅在分钟级别生效 (日线级忽略), 保留用于兼容旧覆盖文件。
            "id": "lookback_days", "label": "分析窗口(天, 仅分钟级生效)", "type": "int",
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
3. 在指定缠论级别(月线/周线/日线/60分钟/30分钟/15分钟/5分钟)上识别 B1(趋势背驰)或 B2(盘整背驰)
4. 信号年龄不超过 max_signal_age 根本级别K线(周线按周K线, 只计交易日); 背驰条件命中数达到阈值
5. 判定口径(面积/DIF/逻辑/重叠/回抽深度)与缠论分析页面完全同源
6. 信号含本级别与次级别触发日期(区间套下钻); 执行时机仅"分析"按钮/定时任务
7. B1 默认需次级别背驰确认(bs_b1_sub_confirm, 区间套); 有数据但未确认时 B1 丢弃,
   次级别源不可用时 B1 保留并返回警告 (G, 2026-11-23)
8. 执行17:00前不取当日数据(以上一交易日为as_of), 17:00后才取当日; 非交易日取最近一个交易日
9. 执行前做前置校验(横截面完整性/关键列null/市场量级/本地日K/次级别源探测), 不通过则中止并UI提示
"""

# 前置校验阈值 (2026-11-25, 用户裁定)
_MIN_COMPLETE_RATIO = 0.95    # as_of 行数 ≥ 上一交易日行数的 95%
_MAX_NULL_RATIO = 0.10        # 关键列 null 率 < 10%
_MIN_MARKET_ROWS = 500        # 市场量级下限
_PROBE_SYMBOL = "000001.SZ"   # 数据源探测用的活跃标的


def _preflight(
    df: pl.DataFrame,
    latest: pl.DataFrame,
    as_of,
    freq: str,
    signal_types: tuple,
    params: dict,
) -> list:
    """执行前置校验 — 返回不通过原因列表 (空列表 = 全部通过, 允许执行)。

    任一项不通过即中止执行 (不进扫描/不发次级别外呼), 原因作为警告经
    (df, warnings) 协议透出 UI。fail-fast: 廉价检查(行数/列)失败时不再
    做网络探测。
    """
    reasons: list = []
    n_now = latest.height

    # 1. 市场量级 sanity (极端残缺直接拦截)
    if n_now < _MIN_MARKET_ROWS:
        reasons.append(
            f"执行前置校验未通过: 数据严重缺失({n_now}<{_MIN_MARKET_ROWS}只) — 请先执行数据同步"
        )
    # 2. as_of 横截面完整性 vs 上一交易日 (封"同步中途的半成品分区"场景)
    prev_dates = df.filter(pl.col("date") < as_of)["date"]
    if prev_dates.len():
        prev_day = prev_dates.max()
        n_prev = df.filter(pl.col("date") == prev_day).height
        if n_prev and n_now < n_prev * _MIN_COMPLETE_RATIO:
            reasons.append(
                f"执行前置校验未通过: 当日数据疑似未同步完整"
                f"({n_now}/{n_prev}只, 完整性{int(n_now / n_prev * 100)}%<95%) — 请先执行数据同步"
            )
    # 3. 关键列质量 (Fix C 同口径: 大面积 null 拦截)
    for col in ("close", "amount", "turnover_rate"):
        if col in latest.columns:
            null_ratio = latest[col].null_count() / max(1, n_now)
            if null_ratio >= _MAX_NULL_RATIO:
                reasons.append(
                    f"执行前置校验未通过: 过滤引用列 {col} 缺失率过高"
                    f"({null_ratio:.0%}>={int(_MAX_NULL_RATIO * 100)}%) — 请先执行数据同步"
                )
    # fail-fast: 廉价检查已失败时不再发网络探测
    if reasons:
        return reasons

    # 4. 本地日K可用性 (扫描主源; 缺失会全量退化到网络源, 大盘扫描必然超时)
    try:
        from app.custom.czsc.adapters.kline.local_daily import LocalDailyKlineSource

        frame = LocalDailyKlineSource().fetch(
            _PROBE_SYMBOL, "日线", as_of - timedelta(days=10), as_of
        )
        if frame is None or frame.is_empty():
            reasons.append(
                "执行前置校验未通过: 本地日K数据未就绪 — 请先执行数据同步"
            )
    except Exception:
        reasons.append("执行前置校验未通过: 本地日K读取异常 — 请先执行数据同步")
    if reasons:
        return reasons

    # 5. 次级别(分钟)数据源可用性探测 — 仅 B1 需区间套确认时检查;
    #    探测标的是长期活跃股, 取近 15 日窗口, 空帧/异常均视为源不可用。
    if "B1" in signal_types and params.get("bs_b1_sub_confirm", True):
        probe_freq = freq if freq in ("5分钟", "15分钟", "30分钟", "60分钟") else "30分钟"
        ok = False
        try:
            from app.custom.czsc.adapters.kline.chain import build_default_chain

            res = build_default_chain().fetch(
                _PROBE_SYMBOL, probe_freq, as_of - timedelta(days=15), as_of
            )
            ok = res is not None and not res.frame.is_empty()
        except Exception:
            ok = False
        if not ok:
            reasons.append(
                f"执行前置校验未通过: 次级别({probe_freq})数据源不可用 — "
                "请检查网络与数据源配置后重试; 或关闭「B1需次级别背驰确认」跳过次级别要求"
            )
    return reasons


def filter_history(df: pl.DataFrame, params: dict):
    if df.is_empty() or "symbol" not in df.columns or "date" not in df.columns:
        return df

    # as_of 截止规则 (2026-11-25): 执行时间 17:00 前不取当日数据 —
    # 当日 enriched 分区可能在增量同步中途 (只有部分股票), 取到会得到
    # 残缺横截面导致误判零命中; 以上一交易日截止。17:00 后才允许取当日。
    # 非交易日 df 内本就无该日行, 取 ≤上限 的最大日期自然落到最近一个
    # 交易日。上限本身为当日时, 当日分区未同步也不受影响 (max ≤ 上限)。
    _now = datetime.now()
    _upper = (
        _now.date()
        if _now.time() >= dtime(17, 0)
        else _now.date() - timedelta(days=1)
    )
    max_date = df["date"].max()
    if max_date is not None and max_date <= _upper:
        as_of = max_date
    else:
        # 当日(或更晚)数据超上限 — 截到上限之前最近的一个交易日
        eligible = [d for d in df["date"].unique().to_list() if d <= _upper]
        if not eligible:
            return df.head(0)
        as_of = max(eligible)
    latest = df.filter(pl.col("date") == as_of)

    freq = str(params.get("freq", "日线"))
    signal_types = tuple(
        s.strip().upper() for s in str(params.get("signal_types", "B1,B2")).split(",") if s.strip()
    ) or ("B1", "B2")

    # 前置校验闸门 (2026-11-25, 用户裁定): 检测通过才执行 — 任一项不通过
    # 直接中止 (不进扫描/不发次级别外呼), 警告经 (df, warnings) 协议透出
    # UI, 提示先做数据同步/检查数据源。
    reasons = _preflight(df, latest, as_of, freq, signal_types, params)
    if reasons:
        return latest.head(0), reasons
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

    # 扫描专用分析器 (P1-2): sublevel=None 去掉引擎内逐候选次级别外呼
    # (全市场扫描被 30 分钟源限流拖垮); nest 保留 — 命中后由扫描层
    # _annotate_sub_dt 补次级别日期, bs_b1_sub_confirm 链路不受影响。
    result = ScanService(analyzer=build_scan_analyzer()).scan(req)
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
