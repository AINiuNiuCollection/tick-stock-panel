"""缠论分析请求契约 — 集中参数归一化, 替代散落在路由层的解析与魔数。

设计原则:
    - 不可变 dataclass (frozen), 便于缓存键与并发快照。
    - 不 import FastAPI / czsc, 可被 domain / application / api 共同引用。
    - 所有默认值与白名单只在此处定义 (单一权威)。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, timedelta

# 默认分析参数 (与 czsc 库惯例一致)
DEFAULT_MAX_BI_NUM = 100
DEFAULT_MIN_BI_LEN = 7
# 预热窗口: CZSC 需要足够 K 线才能稳定识别笔/中枢
WARMUP_DAYS = 60  # 日历日, 约 40 交易日
# 均线暖机扩展因子: 后端取数窗口需 >= max(ma_periods) * 1.5 日历日
MA_WARMUP_FACTOR = 1.5
# SMA 支持的周期白名单 (与前端 CzscParamsPanel.MA_PERIOD_OPTIONS 一致)
MA_PERIOD_WHITELIST = (5, 10, 12, 20, 30, 60, 120, 250)
# 允许的特征集合
FEATURE_WHITELIST = ("fx", "bi", "zs", "signals", "bs_points")
DEFAULT_FEATURES = FEATURE_WHITELIST

# 背驰 MACD 面积口径
MACD_AREA_MODES = ("split", "total_abs", "dif_dea")
DEFAULT_BS_MACD_AREA_MODE = "split"
DEFAULT_BS_USE_DIF = True
DEFAULT_BS_USE_MACD_AREA = True
# 背驰条件的组合逻辑:
#   "and" = 面积与DIF极值必须同时满足 (默认, 严格口径, 对齐第24课标准背驰)
#   "or"  = 任一满足即可 (第27课: "只要其中一个符合就可以是一个背弛的信号")
DIVERGENCE_LOGIC_MODES = ("and", "or")
DEFAULT_DIVERGENCE_LOGIC = "and"
# 趋势中枢不重叠判据的口径:
#   "strict"    = 波动区间[DD,GG]不重叠 (缠师第20课严格口径; 笔级近似下趋势稀少)
#   "practical" = 核心区间[ZD,ZG]不重叠 (笔级合理近似; 允许波动区间共享价格带)
TREND_OVERLAP_MODES = ("strict", "practical")
# 趋势中枢重叠口径默认值: practical([ZD,ZG] 核心区间, 第20课原文的中枢区间定义)。
# strict([DD,GG] 波动区间) 比原文更保守, 影线扫过即判重叠, 一/二类点大量消失。
DEFAULT_TREND_OVERLAP_MODE = "practical"
DEFAULT_BS_ONLY_VALID_ZS = True
DEFAULT_TREND_MAX_STEPS = 3
# B2/S2 次级别验证: 30 分钟数据最近可用窗口 (东财兜底硬限制约 224 根 ≈ 5 周)
SUBLEVEL_30M_LOOKBACK_DAYS = 40


def normalize_features(features: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """归一化 features: 支持逗号分隔字符串 / 列表; 未知特征丢弃。"""
    if features is None:
        return DEFAULT_FEATURES
    if isinstance(features, str):
        parts = [p.strip() for p in features.split(",")]
    else:
        parts = [str(p).strip() for p in features]
    normalized = tuple(p for p in parts if p in FEATURE_WHITELIST)
    # 兼容旧行为: 空/未知特征列表回退为全量, 避免返回空结果
    return normalized or DEFAULT_FEATURES


def normalize_ma_periods(periods: list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    """过滤白名单 + 去重 + 升序。"""
    if not periods:
        return ()
    seen: set[int] = set()
    out: list[int] = []
    for p in periods:
        try:
            value = int(p)
        except (TypeError, ValueError):
            continue
        if value in MA_PERIOD_WHITELIST and value not in seen:
            out.append(value)
            seen.add(value)
    out.sort()
    return tuple(out)


@dataclass(frozen=True)
class DivergenceConfig:
    """背驰判定配置 (缠师第 15/24/27/37 课口径)。"""

    macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE
    use_dif: bool = DEFAULT_BS_USE_DIF
    use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA
    only_valid_zs: bool = DEFAULT_BS_ONLY_VALID_ZS
    trend_max_steps: int = DEFAULT_TREND_MAX_STEPS
    sublevel_lookback_days: int = SUBLEVEL_30M_LOOKBACK_DAYS
    divergence_logic: str = DEFAULT_DIVERGENCE_LOGIC
    trend_overlap_mode: str = DEFAULT_TREND_OVERLAP_MODE
    # 区间套下钻(第27课): 是否对买卖点做次级别背驰确认标注。
    # 默认关闭——次级别取数有成本, 且数据不可用时只会降级为 None。
    enable_interval_nest: bool = False

    def normalized(self) -> DivergenceConfig:
        mode = self.macd_area_mode if self.macd_area_mode in MACD_AREA_MODES else DEFAULT_BS_MACD_AREA_MODE
        steps = max(1, int(self.trend_max_steps))
        lookback = max(1, int(self.sublevel_lookback_days))
        logic = self.divergence_logic if self.divergence_logic in DIVERGENCE_LOGIC_MODES else DEFAULT_DIVERGENCE_LOGIC
        overlap = (
            self.trend_overlap_mode if self.trend_overlap_mode in TREND_OVERLAP_MODES
            else DEFAULT_TREND_OVERLAP_MODE
        )
        if (
            mode == self.macd_area_mode and steps == self.trend_max_steps
            and lookback == self.sublevel_lookback_days and logic == self.divergence_logic
            and overlap == self.trend_overlap_mode
        ):
            return self
        return replace(
            self, macd_area_mode=mode, trend_max_steps=steps,
            sublevel_lookback_days=lookback, divergence_logic=logic,
            trend_overlap_mode=overlap,
        )

    def cache_key(self) -> tuple[object, ...]:
        return (
            self.macd_area_mode,
            self.use_dif,
            self.use_macd_area,
            self.only_valid_zs,
            self.trend_max_steps,
            self.sublevel_lookback_days,
            self.divergence_logic,
            self.trend_overlap_mode,
            self.enable_interval_nest,
        )


@dataclass(frozen=True)
class AnalyzeRequest:
    """一次缠论分析的完整输入契约。"""

    symbol: str
    freq: str = "日线"
    start: date | None = None
    end: date | None = None
    max_bi_num: int = DEFAULT_MAX_BI_NUM
    min_bi_len: int = DEFAULT_MIN_BI_LEN
    features: tuple[str, ...] = DEFAULT_FEATURES
    symbol_name: str | None = None
    ma_periods: tuple[int, ...] = ()
    divergence: DivergenceConfig = field(default_factory=DivergenceConfig)
    force_refresh: bool = False
    # 已废弃: 缠师原文未要求 DEA, 仅保留接收以兼容旧前端, 不参与计算
    bs_use_dea: bool = False

    @classmethod
    def from_query(
        cls,
        *,
        symbol: str,
        freq: str = "日线",
        start: date | None = None,
        end: date | None = None,
        max_bi_num: int = DEFAULT_MAX_BI_NUM,
        min_bi_len: int = DEFAULT_MIN_BI_LEN,
        features: str | list[str] | None = None,
        symbol_name: str | None = None,
        ma_periods: list[int] | None = None,
        bs_macd_area_mode: str = DEFAULT_BS_MACD_AREA_MODE,
        bs_use_dif: bool = DEFAULT_BS_USE_DIF,
        bs_use_dea: bool = False,
        bs_use_macd_area: bool = DEFAULT_BS_USE_MACD_AREA,
        bs_divergence_logic: str = DEFAULT_DIVERGENCE_LOGIC,
        bs_trend_overlap_mode: str = DEFAULT_TREND_OVERLAP_MODE,
        bs_enable_interval_nest: bool = False,
        force_refresh: bool = False,
    ) -> AnalyzeRequest:
        return cls(
            symbol=symbol,
            freq=freq,
            start=start,
            end=end,
            max_bi_num=max_bi_num,
            min_bi_len=min_bi_len,
            features=normalize_features(features),
            symbol_name=symbol_name,
            ma_periods=normalize_ma_periods(ma_periods),
            divergence=DivergenceConfig(
                macd_area_mode=bs_macd_area_mode,
                use_dif=bs_use_dif,
                use_macd_area=bs_use_macd_area,
                divergence_logic=bs_divergence_logic,
                trend_overlap_mode=bs_trend_overlap_mode,
                enable_interval_nest=bs_enable_interval_nest,
            ).normalized(),
            force_refresh=force_refresh,
            bs_use_dea=bs_use_dea,
        )

    def with_defaults(self) -> AnalyzeRequest:
        """补齐日期默认值并归一化配置 (幂等)。"""
        end = self.end or date.today()
        start = self.start or (end - timedelta(days=365 + WARMUP_DAYS))
        return replace(
            self,
            start=start,
            end=end,
            features=normalize_features(self.features),
            ma_periods=normalize_ma_periods(self.ma_periods),
            divergence=self.divergence.normalized(),
        )

    def fetch_start(self) -> date:
        """取数起点 — 勾选 SMA 时向前扩展, 保证暖机有足够历史 K 线。"""
        start = self.start or date.today()
        if not self.ma_periods:
            return start
        warmup_calendar_days = int(max(self.ma_periods) * MA_WARMUP_FACTOR)
        return min(start, (self.end or date.today()) - timedelta(days=warmup_calendar_days))

    def cache_key(self) -> tuple[object, ...]:
        """覆盖所有会改变结果的维度 (不含 force_refresh)。"""
        return (
            self.symbol,
            self.freq,
            self.start.isoformat() if self.start else "",
            self.end.isoformat() if self.end else "",
            self.max_bi_num,
            self.min_bi_len,
            self.features,
            self.symbol_name or "",
            self.ma_periods,
            self.divergence.cache_key(),
        )
