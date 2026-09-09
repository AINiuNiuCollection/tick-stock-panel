# 因子与策略开发完整指南

> 本文档是因子和策略开发的完整参考手册，涵盖体系架构、DSL 语法、策略模板、评分系统、字段含义和完整示例。

---

## 目录

- [第1章 体系架构总览](#第1章-体系架构总览)
- [第2章 因子体系](#第2章-因子体系)
- [第3章 DSL 公式语言](#第3章-dsl-公式语言)
- [第4章 策略体系](#第4章-策略体系)
- [第5章 评分系统](#第5章-评分系统)
- [第6章 完整实战示例](#第6章-完整实战示例)
- [第7章 前端操作指南](#第7章-前端操作指南)
- [第8章 API 接口参考](#第8章-api-接口参考)
- [附录 速查表](#附录-速查表)

---

## 第1章 体系架构总览

### 1.1 核心数据流

```
原始K线数据 → 指标计算(enriched) → 因子值 → 评分归一化 → 策略信号 → 选股结果
     ↓              ↓                ↑            ↑              ↑            ↓
  parquet存储   MA/RSI/MACD等    base/virtual  加权求和     entry/exit   排序+限制
                  预计算          custom DSL    ×100→score   布尔矩阵      返回前N条
                                  composite
```

### 1.2 四种因子类型

| 类型 | ID前缀 | 定义方式 | 计算时机 | 示例 |
|:---|:---|:---|:---|:---|
| `base` | 无 | 注册表内置，数据预计算为 enriched 列 | 数据同步时 | `momentum_5d`, `rsi_14`, `close` |
| `virtual` | 无 | 注册表内置，由表达式实时计算 | 策略运行时 | `ma20_bias` = close/ma20 - 1 |
| `custom` | `uf_` | 用户通过 DSL 公式自定义 | 策略运行时 | `rank(-ts_sum(change_pct, 5))` |
| `composite` | `cf_` | 多因子加权截面 z-score 组合 | 策略运行时 | `0.6*zscore(momentum_20d) + 0.4*zscore(vol_ratio_5d)` |

### 1.3 策略执行后端

| 后端 | 常量 | 适用场景 | 核心接口 |
|:---|:---|:---|:---|
| `matrix_native` | `EXECUTION_BACKEND = "matrix_native"` | 需要历史数据窗口、跨日逻辑（金叉、突破） | `compute_signals(market, params) → SignalMatrix` |

> **说明**：当前所有内置策略均使用 `matrix_native` 后端。该后端将数据组织为 `(天数 × 标的数)` 的 NumPy 矩阵，支持向量化计算和回测。

### 1.4 关键目录结构

```
backend/app/
├── factors/
│   ├── registry.py          # 因子注册表（FactorSpec 元数据）
│   ├── dsl.py               # DSL 编译器（公式 → Polars 表达式）
│   ├── store.py             # 自定义/组合因子持久化
│   └── ext_factors.py       # 外部数据扩展因子
├── indicators/
│   └── pipeline.py          # 指标计算（MA/RSI/MACD/BOLL/KDJ/ATR...）
├── strategy/
│   ├── builtin/             # 内置策略目录（25+ 个 .py 文件）
│   ├── engine.py            # 策略执行引擎
│   ├── scoring.py           # 评分系统（表达式分发 + 归一化）
│   └── config.py            # 策略参数覆盖持久化
├── backtest/
│   ├── matrix.py            # MarketDataMatrix / SignalMatrix / make_signal_matrix
│   ├── strategy.py          # 回测策略服务
│   └── factor.py            # 回测因子服务
└── api/
    ├── factors.py            # 因子 API
    ├── strategy.py           # 策略 API
    └── screener.py           # 选股 API

data/strategies/
├── ai/                       # AI 生成的策略
└── custom/                   # 手写自定义策略

data/custom_factors/
├── uf_*.json                 # 自定义 DSL 因子定义
└── cf_*.json                 # 组合因子定义
```

---

## 第2章 因子体系

### 2.1 因子注册表 FactorSpec

所有因子的元数据统一定义在 `backend/app/factors/registry.py` 中，使用 `FactorSpec` 冻结数据类：

```python
@dataclass(frozen=True)
class FactorSpec:
    id: str                    # 因子唯一标识，如 "momentum_5d"
    label: str                 # 中文显示名，如 "5日动量"
    group: str                 # 分组名，如 "动量"、"均线偏离"
    formula_text: str          # 公式描述文字（非可执行代码）
    kind: Kind                 # 类型: "base" | "virtual" | "composite" | "custom"
    version: int = 1           # 版本号
    dependencies: frozenset[str]  # 依赖的基础列（virtual/custom/composite 有效）
    direction: Direction       # 方向: "high"(越大越好) | "low"(越小越好) | "none"(未定)
    unit: Unit                 # 单位: "ratio"|"pct"|"score"|"count"|"days"|"currency"|"none"
    warmup_bars: int           # 预热所需K线数（窗口越大预热越长）
    pit: bool                  # 是否点时数据（财务因子为 True）
    pit_source: PitSource      # 点时来源: "financial_announce"|"share_capital_announce"|"none"
    asset_types: frozenset[str]  # 适用资产: {"stock","etf"} 或仅 {"stock"}
    incremental_safe: bool     # 增量计算是否安全
    scale_free: bool           # 是否无量纲（跨股票可比）
    null_policy: str           # 空值策略: "keep"|"drop_row"
    stability: Stability       # 稳定性: "stable"|"experimental"|"deprecated"
    tags: tuple[str, ...]      # 标签
    components: tuple          # composite 专用: ((成员id, 权重), ...)
```

**字段详细说明**：

| 字段 | 含义 | 用途 |
|:---|:---|:---|
| `id` | 全局唯一标识符 | 策略 scoring 中通过 id 引用因子 |
| `label` | 中文显示名 | 前端 UI 展示 |
| `group` | 分组 | 前端因子库分类展示（动量、均线偏离、超买超卖等） |
| `formula_text` | 公式描述 | 前端展示因子的计算逻辑（文字描述，非可执行代码） |
| `kind` | 因子类型 | 决定计算路径：base 直接取列，virtual 实时计算，custom 走 DSL，composite 走加权组合 |
| `dependencies` | 依赖列 | virtual/custom 声明依赖哪些 base 列，引擎据此加载所需数据 |
| `direction` | 方向 | 评分时使用："high" 表示值越大得分越高，"low" 表示值越小得分越高 |
| `warmup_bars` | 预热K线数 | 需要多少根历史K线才能计算出该因子值。如 20 日均线需要 20 根 |
| `pit` | 是否点时 | 财务因子为 True，使用公告日对齐避免未来函数 |
| `asset_types` | 适用资产 | 限制因子只能在特定资产类型上使用（如财务因子仅限股票） |
| `scale_free` | 是否无量纲 | False 表示该因子有量纲（如金额），跨股票比较前需要归一化 |
| `components` | 组合成员 | 仅 composite 类型使用，定义组合因子的成员和权重 |

### 2.2 内置因子完整清单

#### 动量类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `momentum_5d` | 5日动量 | base | 5个交易日累计收益率 |
| `momentum_10d` | 10日动量 | base | 10个交易日累计收益率 |
| `momentum_20d` | 20日动量 | base | 20个交易日累计收益率 |
| `momentum_30d` | 30日动量 | base | 30个交易日累计收益率 |
| `momentum_60d` | 60日动量 | base | 60个交易日累计收益率 |
| `change_pct` | 日涨跌幅 | base | 当日收盘相对前收盘的收益率 |
| `momentum_120d` | 120日动量 | virtual | 120个交易日累计收益率（预热121根） |
| `mom_accel_20_60` | 动量加速度 | virtual | 20日动量 - 60日动量 |

#### 均线偏离类

| ID | 标签 | 类型 | 公式 | 依赖 |
|:---|:---|:---|:---|:---|
| `ma5_bias` | MA5乖离 | virtual | close / MA5 - 1 | close, ma5 |
| `ma10_bias` | MA10乖离 | virtual | close / MA10 - 1 | close, ma10 |
| `ma20_bias` | MA20乖离 | virtual | close / MA20 - 1 | close, ma20 |
| `ma30_bias` | MA30乖离 | virtual | close / MA30 - 1 | close, ma30 |
| `ma60_bias` | MA60乖离 | virtual | close / MA60 - 1 | close, ma60 |
| `ema5_bias` | EMA5乖离 | virtual | close / EMA5 - 1 | close, ema5 |
| `ema10_bias` | EMA10乖离 | virtual | close / EMA10 - 1 | close, ema10 |
| `ema20_bias` | EMA20乖离 | virtual | close / EMA20 - 1 | close, ema20 |
| `ema30_bias` | EMA30乖离 | virtual | close / EMA30 - 1 | close, ema30 |
| `ema60_bias` | EMA60乖离 | virtual | close / EMA60 - 1 | close, ema60 |

#### 超买超卖类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `rsi_6` | RSI(6) | base | 6日相对强弱指标 |
| `rsi_14` | RSI(14) | base | 14日相对强弱指标 |
| `rsi_24` | RSI(24) | base | 24日相对强弱指标 |
| `rsi_14_delta_5d` | RSI五日变化 | virtual | RSI(14) - 5日前的RSI(14) |

#### 趋势类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `macd_hist` | MACD柱(原值) | base | MACD柱状图 (DIF-DEA)×2，有量纲 |
| `macd_dif_pct` | MACD DIF强度 | virtual | MACD DIF / 收盘价 |
| `macd_dea_pct` | MACD DEA强度 | virtual | MACD DEA / 收盘价 |
| `macd_hist_pct` | MACD柱强度 | virtual | MACD柱 / 收盘价 |
| `kdj_k` | KDJ-K | base | KDJ指标K值 |
| `kdj_d` | KDJ-D | base | KDJ指标D值 |
| `kdj_j` | KDJ-J | base | KDJ指标J值 (3K-2D) |
| `boll_position` | 布林位置 | virtual | 收盘价在布林带下轨到上轨之间的位置 [0,1] |

#### 波动率类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `annual_vol_20d` | 20日波动率 | base | 20日收益率年化标准差 |
| `atr_14` | ATR(14)原值 | base | 14日平均真实波幅，有量纲 |
| `atr_pct` | ATR相对波动 | virtual | ATR(14) / 收盘价 |
| `amplitude` | 日振幅 | base | 当日高低价差 / 前收盘价 |
| `boll_width` | 布林带宽 | virtual | 布林带上下轨宽度 / MA20 |

#### 量价类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `vol_ratio_5d` | 5日量比 | base | 当日成交量 / 前5日平均成交量 |
| `vol_ratio_10d` | 10日量比 | virtual | 当日成交量 / 前10日平均成交量（预热11） |
| `vol_trend_5_10` | 成交量趋势 | virtual | 5日均量 / 10日均量 - 1 |
| `turnover_rate` | 换手率 | base | 当日换手率 |
| `turnover_ratio_5d` | 换手率放大 | virtual | 当日换手率 / 前5日平均换手率 - 1（预热6） |
| `log_amount` | 成交额对数 | virtual | ln(成交额 + 1) |
| `amount_ratio_5d` | 成交额放大 | virtual | 当日成交额 / 前5日平均成交额 - 1（预热6） |
| `vol_price_corr_20d` | 20日量价相关 | virtual | 近20日日涨跌幅与成交量的相关系数（预热21） |
| `vol_trend_5_60` | 量能趋势(5/60) | virtual | 5日均量 / 60日均量 - 1（预热60） |

#### 价格位置类

| ID | 标签 | 类型 | 公式 |
|:---|:---|:---|:---|
| `gap_return` | 开盘跳空 | virtual | open / prev_close - 1 |
| `intraday_return` | 日内收益 | virtual | close / open - 1 |
| `close_position` | 收盘位置 | virtual | (close - low) / (high - low) |
| `distance_to_high_60d` | 距60日高点 | virtual | close / 60日最高收盘价 - 1 |
| `distance_from_low_60d` | 距60日低点 | virtual | close / 60日最低收盘价 - 1 |
| `vwap_bias` | VWAP乖离 | virtual | close / (amount/(volume×100)) - 1 |

#### 收益形态类

| ID | 标签 | 类型 | 说明 | 预热 |
|:---|:---|:---|:---|:---|
| `max_ret_20d` | 20日最大单日涨幅 | virtual | 近20日单日涨幅最大值（彩票效应） | 21 |
| `ret_skew_20d` | 20日收益偏度 | virtual | 近20日日收益偏度 | 21 |
| `up_days_20d` | 20日上涨天数 | virtual | 近20日中上涨天数(0~20) | 21 |

#### 流动性类

| ID | 标签 | 类型 | 说明 | 预热 |
|:---|:---|:---|:---|:---|
| `amihud_20d` | 20日Amihud非流动性 | virtual | 近20日平均\|日涨跌幅\|/成交额(亿元) | 21 |
| `turnover_z_60d` | 换手率60日z分 | virtual | (当日换手率 - 60日均值) / 60日标准差 | 61 |

#### 涨停基因类

| ID | 标签 | 类型 | 说明 | 预热 |
|:---|:---|:---|:---|:---|
| `limit_up_count_20d` | 涨停基因(20日) | virtual | 近20个交易日涨停次数 | 21 |
| `limit_up_count_60d` | 涨停基因(60日) | virtual | 近60个交易日涨停次数 | 61 |

#### 财务类（仅股票，点时数据）

| ID | 标签 | 说明 |
|:---|:---|:---|
| `pb_latest` | 市净率(最新公告) | 收盘价 / 最新已公告每股净资产 |
| `roe_latest` | ROE(最新公告) | 最新已公告净资产收益率(%) |
| `gross_margin_latest` | 毛利率(最新公告) | 最新已公告销售毛利率(%) |
| `net_margin_latest` | 净利率(最新公告) | 最新已公告销售净利率(%) |
| `revenue_yoy_latest` | 营收增速(最新公告) | 最新已公告营业收入同比(%) |
| `net_income_yoy_latest` | 净利增速(最新公告) | 最新已公告归母净利润同比(%) |
| `debt_ratio_latest` | 资产负债率(最新公告) | 最新已公告资产负债率(%) |

#### 规模类

| ID | 标签 | 类型 | 说明 |
|:---|:---|:---|:---|
| `log_float_mv` | 流通市值对数 | virtual | ln(收盘价 × 成交量 / 换手率) |

### 2.3 可用基础列（DSL 公式原材料）

DSL 公式中可直接引用以下列名（来自 `ENRICHED_COLUMNS`）：

**OHLCV 基础列**：

| 列名 | 说明 |
|:---|:---|
| `open` | 前复权开盘价 |
| `high` | 前复权最高价 |
| `low` | 前复权最低价 |
| `close` | 前复权收盘价 |
| `volume` | 成交量 |
| `amount` | 成交额 |
| `turnover_rate` | 换手率 |
| `prev_close` | 前收盘价 |
| `raw_close` | 原始收盘价（未复权） |

**均线列**：`ma5`, `ma10`, `ma20`, `ma30`, `ma60`, `ema5`, `ema10`, `ema20`, `ema30`, `ema60`

**动量列**：`momentum_5d`, `momentum_10d`, `momentum_20d`, `momentum_30d`, `momentum_60d`, `change_pct`

**超买超卖列**：`rsi_6`, `rsi_14`, `rsi_24`

**趋势列**：`macd_dif`, `macd_dea`, `macd_hist`, `kdj_k`, `kdj_d`, `kdj_j`, `boll_upper`, `boll_lower`

**波动率列**：`annual_vol_20d`, `atr_14`, `amplitude`

**量价列**：`vol_ratio_5d`, `vol_ma5`, `vol_ma10`

**极值列**：`high_60d`, `low_60d`

**涨停列**：`consecutive_limit_ups`, `consecutive_limit_downs`

**信号列**（布尔值，用于策略 ENTRY/EXIT_SIGNALS）：

| 信号列 | 说明 |
|:---|:---|
| `signal_ma_golden_5_20` | MA5上穿MA20（金叉） |
| `signal_ma_dead_5_20` | MA5下穿MA20（死叉） |
| `signal_ma_golden_20_60` | MA20上穿MA60 |
| `signal_macd_golden` | MACD金叉（DIF上穿DEA） |
| `signal_macd_dead` | MACD死叉（DIF下穿DEA） |
| `signal_ma20_breakout` | 收盘突破MA20上方 |
| `signal_ma20_breakdown` | 收盘跌破MA20下方 |
| `signal_ma5_breakout` | 收盘突破MA5上方 |
| `signal_ma5_breakdown` | 收盘跌破MA5下方 |
| `signal_ma10_breakout` | 收盘突破MA10上方 |
| `signal_ma10_breakdown` | 收盘跌破MA10下方 |
| `signal_n_day_high` | 创60日新高 |
| `signal_n_day_low` | 创60日新低 |
| `signal_boll_breakout_upper` | 突破布林上轨 |
| `signal_boll_breakdown_lower` | 跌破布林下轨 |
| `signal_volume_surge` | 放量（量比≥2.0） |
| `signal_limit_up` | 涨停 |
| `signal_limit_down` | 跌停 |
| `signal_limit_down_recovery` | 跌停翘板（跌停后回升） |
| `signal_broken_limit_up` | 炸板（最高触及涨停但收盘未封住） |

---

## 第3章 DSL 公式语言

### 3.1 概述

DSL（Domain-Specific Language）是用户自定义因子的公式语言。公式经编译器（`backend/app/factors/dsl.py`）转换为 Polars 表达式，在策略运行时计算因子值。

**编译流程**：

```
公式文本 → 词法分析 → 语法解析(AST) → 语义检查 → 代码生成 → frame_transform 闭包
```

**编译输出** `CompiledFormula`：

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `ok` | bool | 编译是否成功 |
| `errors` | list[DslError] | 错误列表（含错误码、位置、详情） |
| `frame_transform` | callable | 闭包函数：输入 polars.DataFrame → 输出添加了因子列的 DataFrame |
| `dependencies` | frozenset[str] | 展开到基础列的依赖（如引用 `ma20_bias` 展开为 `close, ma20`） |
| `referenced_factors` | frozenset[str] | 引用的注册因子 id（含 virtual，需先物化） |
| `warmup_bars` | int | 预热所需K线数 |
| `cross_sectional` | bool | 是否包含截面运算（rank/zscore/winsorize） |

### 3.2 运算符完整参考

#### 时序运算符（按标的计算，回看历史）

每个标的独立计算，使用 `.over("symbol")` 分组。

| 运算符 | 签名 | 参数约束 | 说明 | 示例 |
|:---|:---|:---|:---|:---|
| `ts_mean(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日移动平均 | `ts_mean(close, 20)` |
| `ts_std(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日标准差 | `ts_std(change_pct, 20)` |
| `ts_sum(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日累加求和 | `ts_sum(change_pct, 5)` |
| `ts_max(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日最大值 | `ts_max(high, 20)` |
| `ts_min(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日最小值 | `ts_min(low, 20)` |
| `ts_delay(x, n)` | 1个表达式参数 + n | n ∈ [1, 512] | n天前的值 | `ts_delay(close, 5)` |
| `ts_delta(x, n)` | 1个表达式参数 + n | n ∈ [0, 512] | 当日值 − n天前值 | `ts_delta(close, 5)` |
| `ts_rank(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日内排名（0~1） | `ts_rank(close, 20)` |
| `ts_zscore(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | n日z标准化 | `ts_zscore(volume, 60)` |
| `ts_corr(x, y, n)` | 2个表达式参数 + n | n ∈ [2, 512] | n日皮尔逊相关系数 | `ts_corr(change_pct, volume, 20)` |
| `ts_cov(x, y, n)` | 2个表达式参数 + n | n ∈ [2, 512] | n日协方差 | `ts_cov(close, volume, 20)` |
| `ts_quantile(x, n, q)` | 1个表达式参数 + n + q | n ∈ [2, 512], q ∈ [0, 1] | n日分位数 | `ts_quantile(close, 20, 0.9)` |
| `decay_linear(x, n)` | 1个表达式参数 + n | n ∈ [2, 512] | 线性衰减加权均值（近期权重更大） | `decay_linear(close, 10)` |

#### 截面运算符（当日全市场横截面比较）

对当日所有标的进行横截面比较，使用 `.over("date")` 分组。

| 运算符 | 签名 | 说明 | 示例 |
|:---|:---|:---|:---|
| `rank(x)` | 1个表达式参数 | 当日全市场排名，归一化到 [0, 1] | `rank(momentum_20d)` |
| `zscore(x)` | 1个表达式参数 | 当日全市场 z 标准化 (x-均值)/标准差 | `zscore(turnover_rate)` |
| `winsorize(x, k)` | 1个表达式参数 + k | 缩尾去极值，k 默认 3，范围 [1, 6] | `winsorize(change_pct, 3)` |

#### 工具运算符

| 运算符 | 签名 | 参数约束 | 说明 | 示例 |
|:---|:---|:---|:---|:---|
| `power(x, c)` | 1个表达式参数 + c | \|c\| ≤ 4 | 幂运算 | `power(close, 2)` |
| `clamp(x, lo, hi)` | 1个表达式参数 + lo + hi | lo < hi | 限制到 [lo, hi] 范围 | `clamp(change_pct, -0.1, 0.1)` |
| `if_else(cond, a, b)` | 3个表达式参数 | 无 | 条件判断：cond 为真返回 a，否则 b | `if_else(close > open, 1, -1)` |
| `min(a, b)` | 2个表达式参数 | 无 | 取较小值 | `min(close, open)` |
| `max(a, b)` | 2个表达式参数 | 无 | 取较大值 | `max(close, open)` |
| `log(x)` | 1个表达式参数 | 无 | 自然对数 | `log(amount)` |
| `abs(x)` | 1个表达式参数 | 无 | 绝对值 | `abs(change_pct)` |
| `sign(x)` | 1个表达式参数 | 无 | 符号函数（-1/0/1） | `sign(macd_hist)` |
| `sqrt(x)` | 1个表达式参数 | 无 | 平方根 | `sqrt(volume)` |

#### 算术运算符

| 运算符 | 说明 | 示例 |
|:---|:---|:---|
| `+` | 加法 | `close + open` |
| `-` | 减法 / 负号 | `close - open` / `-change_pct` |
| `*` | 乘法 | `close * volume` |
| `/` | 除法 | `close / ma20` |

#### 比较与逻辑运算符

| 运算符 | 说明 | 示例 |
|:---|:---|:---|
| `>` `<` `>=` `<=` `==` `!=` | 比较 | `close > ma20` |
| `and` | 逻辑与 | `close > ma20 and volume > vol_ma5` |
| `or` | 逻辑或 | `rsi_14 < 30 or rsi_14 > 70` |
| `not` | 逻辑非 | `not close > ma20` |

### 3.3 DSL 规则与约束

| 规则 | 约束 | 错误码 |
|:---|:---|:---|
| 最大嵌套深度 | AST 深度 ≤ 12 | E006 |
| 最大 Token 数 | ≤ 200 | E007 |
| 窗口范围 | 2 ≤ n ≤ 512（ts_delay: 1 ≤ n ≤ 512） | E004 |
| 禁止前瞻 | ts_delay 的 n ≥ 1，不允许负数 shift | E005 |
| 幂运算指数 | \|c\| ≤ 4 | E010 |
| 缩尾参数 | k ∈ [1, 6] | E011 |
| 禁止截面套时序 | `ts_mean(rank(x), 20)` 非法 | E009 |
| 禁止纯常量表达式 | `rank(1)` 无意义 | E016 |
| 标识符必须已注册 | 列名或因子 id 必须存在 | E001 |
| 函数必须已定义 | 运算符必须在 OPERATORS 中 | E002 |
| 参数数量/类型匹配 | 运算符参数个数和类型正确 | E003 |
| 循环引用检测 | 因子不能间接引用自身 | E012 |

### 3.4 DSL 公式示例

```python
# 示例1: 5日反转因子
# 逻辑：近5日涨幅越低，反弹潜力越大
# rank 对当日全市场排名，-ts_sum 取负的5日累计涨幅
rank(-ts_sum(change_pct, 5))

# 示例2: 量价相关性因子
# 逻辑：近20日涨跌幅与成交量的正相关系数
# 高值代表量价同向（上涨放量、下跌缩量）
ts_corr(close / ts_delay(close, 1) - 1, volume, 20)

# 示例3: 20日动量的截面 z 分
# 逻辑：标准化后的中期动量，跨股票可比
zscore(ts_delta(close, 20) / ts_delay(close, 20))

# 示例4: 换手率异动因子
# 逻辑：当日换手率相对60日均值的偏离程度
# 高值代表换手率异常放大
(turnover_rate - ts_mean(turnover_rate, 60)) / ts_std(turnover_rate, 60)

# 示例5: 布林位置 × 量比 排名乘积
# 逻辑：布林位置高（接近上轨）且放量 → 强势突破
rank((close - boll_lower) / (boll_upper - boll_lower)) * rank(vol_ratio_5d)

# 示例6: 波动率调整动量
# 逻辑：高动量 + 低波动率 → 风险调整后的优质标的
zscore(momentum_20d) - zscore(annual_vol_20d)

# 示例7: 条件因子
# 逻辑：收阳时取动量，收阴时取负动量
if_else(close > open, momentum_5d, -momentum_5d)

# 示例8: 衰减加权收盘价
# 逻辑：近期收盘价权重更大
decay_linear(close, 10)

# 示例9: 量价趋势因子
# 逻辑：5日均量相对60日均量的放大程度
ts_mean(volume, 5) / ts_mean(volume, 60) - 1

# 示例10: 涨停基因活跃度
# 逻辑：近20日涨停次数的截面排名
rank(ts_sum(consecutive_limit_ups > 0, 20))
```

### 3.5 错误码参考

| 错误码 | 含义 | 常见原因 |
|:---|:---|:---|
| E001 | 未知标识符 | 列名拼写错误或因子 id 不存在 |
| E002 | 未知函数 | 运算符名拼写错误 |
| E003 | 参数数量/类型错误 | 运算符参数个数不匹配 |
| E004 | 窗口超出范围 | n 不在 [2, 512] 或 [1, 512] 范围内 |
| E005 | 负数 shift | 使用了前瞻数据 |
| E006 | AST 深度超限 | 嵌套超过 12 层 |
| E007 | Token 数超限 | 公式超过 200 个 token |
| E008 | 静态除零 | 编译期检测到除以零 |
| E009 | 截面套时序 | 截面运算符嵌套在时序窗口内 |
| E010 | 幂运算指数超限 | \|c\| > 4 |
| E011 | 缩尾参数超限 | k 不在 [1, 6] 范围内 |
| E012 | 循环引用 | 因子间接引用自身 |
| E013 | 运行时缺列 | 依赖的列在 DataFrame 中不存在 |
| E014 | 语法错误 | 无法解析的字符或语法 |
| E015 | 预热不足 | 历史数据不足以计算因子 |
| E016 | 常量表达式 | 公式不包含任何变量引用 |

---

## 第4章 策略体系

### 4.1 策略文件结构

一个策略是一个 Python 文件，包含以下 5 个部分：

```python
"""策略描述"""

# ===== 导入 =====
import numpy as np
from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

# ===== 1. META 元数据 =====
META = { ... }

# ===== 2. 执行后端 =====
EXECUTION_BACKEND = "matrix_native"

# ===== 3. 信号触发器（可选） =====
ENTRY_SIGNALS = ["signal_ma_golden_5_20"]
EXIT_SIGNALS = ["signal_ma_dead_5_20"]

# ===== 4. 风控参数 =====
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 15

# ===== 5. 策略类 =====
class MyStrategy:
    def required_fields(self) -> frozenset[str]: ...
    def required_warmup_bars(self, params: dict) -> int: ...
    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix: ...

MATRIX_STRATEGY = MyStrategy()
```

### 4.2 META 字段详解

```python
META = {
    # ===== 必填字段 =====
    "id": "my_strategy",            # 策略唯一标识（与文件名一致，不含.py）
    "name": "我的策略",              # 前端显示名称
    "description": "策略描述",        # 策略说明
    "asset_types": ["stock", "etf"], # 适用资产类型
    "timeframes": ["1d"],            # 适用周期："1d"(日线) / "1m"(分钟)

    # ===== 可选字段 =====
    "tags": ["趋势", "突破"],         # 标签（用于分类筛选）
    "research_only": False,          # True=研究模式，不出现在公开选股列表
    "params": [...],                 # 用户可调参数定义（见4.3）
    "scoring": {...},                # 评分权重（见第5章）
    "order_by": "score",             # 排序字段
    "descending": True,              # True=降序（高分优先），False=升序
    "limit": 100,                    # 最多返回条数
}
```

**META 字段完整说明**：

| 字段 | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| `id` | str | 是 | 策略唯一标识，与文件名一致（不含 `.py`） |
| `name` | str | 是 | 前端显示名称 |
| `description` | str | 是 | 策略说明文字 |
| `asset_types` | list[str] | 是 | 适用资产类型：`["stock"]` / `["etf"]` / `["stock","etf"]` |
| `timeframes` | list[str] | 是 | 适用周期：`["1d"]`(日线) / `["1m"]`(分钟) / `["1d","1m"]` |
| `tags` | list[str] | 否 | 标签列表，用于前端分类筛选 |
| `research_only` | bool | 否 | True 表示研究模式，不公开显示 |
| `params` | list[dict] | 否 | 用户可调参数定义，见 4.3 节 |
| `scoring` | dict[str,float] | 否 | 评分权重配置，见第5章 |
| `order_by` | str | 否 | 排序字段，通常为 `"score"` |
| `descending` | bool | 否 | 是否降序排列，默认 True |
| `limit` | int | 否 | 最多返回条数，默认 100 |

### 4.3 参数定义详解

`params` 是一个列表，每个元素定义一个用户可调参数：

```python
"params": [
    # 整数参数
    {
        "id": "ma_period",          # 参数唯一标识
        "label": "均线周期",          # 前端显示名
        "type": "int",              # 类型: int
        "default": 20,              # 默认值
        "min": 5,                   # 最小值
        "max": 250,                 # 最大值
        "step": 1                   # 步长
    },

    # 浮点参数
    {
        "id": "vol_ratio_min",
        "label": "最低量比",
        "type": "float",            # 类型: float
        "default": 1.5,
        "min": 0.5,
        "max": 10.0,
        "step": 0.1
    },

    # 布尔参数
    {
        "id": "use_filter",
        "label": "启用过滤",
        "type": "bool",             # 类型: bool
        "default": True             # 默认值 (True/False)
    },

    # 选择参数
    {
        "id": "direction",
        "label": "方向",
        "type": "select",           # 类型: select
        "default": "long",
        "options": ["long", "short"]  # 可选项
    },
]
```

**参数类型说明**：

| type | 数据类型 | 必填字段 | 可选字段 |
|:---|:---|:---|:---|
| `int` | 整数 | `id`, `label`, `default` | `min`, `max`, `step` |
| `float` | 浮点数 | `id`, `label`, `default` | `min`, `max`, `step` |
| `bool` | 布尔值 | `id`, `label`, `default` | 无 |
| `select` | 选择 | `id`, `label`, `default`, `options` | 无 |

在 `compute_signals` 中通过 `params.get("id", default)` 获取参数值。

### 4.4 信号触发器

```python
ENTRY_SIGNALS = ["signal_ma_golden_5_20"]  # 入场信号列名列表
EXIT_SIGNALS = ["signal_ma_dead_5_20"]     # 出场信号列名列表
```

这些信号在回测时用于标记入场/出场事件。信号列必须是 `ENRICHED_COLUMNS` 中以 `signal_` 开头的列（见 2.3 节信号列表）。

### 4.5 风控参数

| 参数 | 类型 | 说明 | 示例 |
|:---|:---|:---|:---|
| `STOP_LOSS` | float | 止损比例（负数），达到时自动平仓 | `-0.06` = 亏损6%止损 |
| `MAX_HOLD_DAYS` | int | 最大持有天数，超时强制平仓 | `15` = 最多持有15个交易日 |

### 4.6 MarketDataMatrix 接口

策略类通过 `market` 参数接收市场数据矩阵：

```python
class MyStrategy:
    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        # ===== 基础属性 =====
        market.shape       # (T, N) 元组：T=天数，N=标的数
        market.symbols     # 标的代码元组
        market.dates       # 日期数组

        # ===== OHLCV 矩阵（np.ndarray, shape=(T, N)） =====
        market.open        # 开盘价矩阵
        market.high        # 最高价矩阵
        market.low         # 最低价矩阵
        market.close       # 收盘价矩阵
        market.volume      # 成交量矩阵

        # ===== 指标列获取 =====
        matrix_feature(market, "ma20")       # 获取 MA20 指标矩阵
        matrix_feature(market, "rsi_14")     # 获取 RSI(14) 指标矩阵
        matrix_feature(market, "vol_ratio_5d")  # 获取量比矩阵
        # 支持所有 ENRICHED_COLUMNS 中的列名

        # ===== 安全 shift =====
        shift(market.close, 1)       # 前一天的收盘价（首行为 NaN）
        shift(matrix_feature(market, "ma5"), 1)  # 前一天的 MA5
```

**`matrix_feature` 支持的列名**：
- OHLCV：`open`, `high`, `low`, `close`, `volume`
- 均线：`ma5`, `ma10`, `ma20`, `ma30`, `ma60`, `ema5`~`ema60`
- 动量：`momentum_5d`~`momentum_60d`, `change_pct`
- RSI：`rsi_6`, `rsi_14`, `rsi_24`
- MACD：`macd_dif`, `macd_dea`, `macd_hist`
- KDJ：`kdj_k`, `kdj_d`, `kdj_j`
- 布林：`boll_upper`, `boll_lower`
- ATR：`atr_14`
- 量价：`vol_ratio_5d`, `vol_ma5`, `vol_ma10`, `turnover_rate`
- 极值：`high_60d`, `low_60d`
- 涨停：`consecutive_limit_ups`, `consecutive_limit_downs`
- 偏离：`deviate_3d`, `deviate_10d`, `deviate_30d`

### 4.7 SignalMatrix 与 make_signal_matrix

```python
def make_signal_matrix(
    shape: tuple[int, int],          # market.shape
    *,
    entry: np.ndarray | None = None,  # 入场信号矩阵 (uint8, 0/1)
    exit: np.ndarray | None = None,   # 出场信号矩阵 (uint8, 0/1)
    score: np.ndarray | None = None,  # 评分矩阵 (float32, 0~100)
    entry_signal_code: np.ndarray | None = None,  # 信号编码 (int16, -1=无信号)
    exit_signal_code: np.ndarray | None = None,
    entry_signal_ids: tuple[str, ...] = (),   # 入场信号ID元组
    exit_signal_ids: tuple[str, ...] = (),    # 出场信号ID元组
) -> SignalMatrix
```

**各参数说明**：

| 参数 | 类型 | 说明 |
|:---|:---|:---|
| `shape` | tuple | 矩阵形状 (天数, 标的数)，来自 `market.shape` |
| `entry` | np.ndarray | 入场信号布尔矩阵，True/1=入场。dtype 会被强制转为 uint8 |
| `exit` | np.ndarray | 出场信号布尔矩阵，True/1=出场 |
| `score` | np.ndarray | 评分矩阵，float32，范围 0~100。可选，由评分系统自动填充 |
| `entry_signal_code` | np.ndarray | 入场信号编码矩阵，int16，0=有信号，-1=无信号 |
| `exit_signal_code` | np.ndarray | 出场信号编码矩阵，int16，0=有信号，-1=无信号 |
| `entry_signal_ids` | tuple | 入场信号ID元组，对应 `ENTRY_SIGNALS` |
| `exit_signal_ids` | tuple | 出场信号ID元组，对应 `EXIT_SIGNALS` |

### 4.8 策略类接口

```python
class MyMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        """声明策略需要的指标列。

        引擎会确保这些列在 market 中可用。
        只需声明 compute_signals 中实际使用的列。

        Returns:
            frozenset[str]: 列名集合
        """
        return frozenset({"close", "volume", "ma20"})

    def required_warmup_bars(self, params: dict) -> int:
        """声明需要多少根历史K线。

        引擎会加载这么多天的历史数据供 compute_signals 使用。
        必须大于策略中使用的最大窗口。

        Args:
            params: 用户配置的参数字典

        Returns:
            int: 历史K线数量
        """
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        """计算入场/出场信号。

        这是策略的核心逻辑。接收市场数据矩阵和参数，
        返回信号矩阵。

        Args:
            market: 市场数据矩阵，包含 OHLCV 和指标列
            params: 用户配置的参数字典

        Returns:
            SignalMatrix: 包含 entry/exit 信号的矩阵
        """
        # 示例：收盘价上穿 MA20
        ma20 = matrix_feature(market, "ma20")
        entry = (market.close > ma20) & (shift(market.close, 1) <= shift(ma20, 1))
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_ma20_breakout",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )

MATRIX_STRATEGY = MyMatrixStrategy()
```

### 4.9 策略文件存放位置

| 位置 | 前缀 | 说明 |
|:---|:---|:---|
| `backend/app/strategy/builtin/` | 无 | 内置策略（项目维护，不接收 PR 外的策略） |
| `data/strategies/custom/` | `custom_` | 手写自定义策略 |
| `data/strategies/ai/` | `ai_` | AI 生成的策略 |

引擎启动时会自动扫描这些目录并加载策略。

### 4.10 因子排名研究策略（无需写代码）

内置的 `factor_rank_research` 策略允许通过参数传入评分配置，无需编写策略文件：

```python
# META.params 定义：
# - entry_score: 入场最低分（默认70）
# - exit_score: 离场最高分（默认40）
# - top_rank: 每日最多入选数（默认20）
# - scoring: 评分字典（运行时传入）
# - directions: 方向字典（运行时传入）

# 限制：最多4个因子
```

使用方式见 [6.3 节](#63-实战3用因子排名研究策略无需写代码)。

---

## 第5章 评分系统

### 5.1 评分流程

```
步骤1: 获取每个因子的值
    ↓
步骤2: min-max 归一化到 [0, 1]
    normalized = (value - min) / (max - min)
    ↓
步骤3: 方向翻转
    direction="high" → 保持不变
    direction="low"  → 1.0 - normalized
    ↓
步骤4: 加权求和
    score = Σ (weight_i × normalized_i) / Σ weight_i
    ↓
步骤5: 缩放到 [0, 100]
    final_score = score × 100
```

### 5.2 META 中的 scoring 配置

```python
"scoring": {
    "momentum_20d": 0.4,    # 20日动量，权重0.4
    "vol_ratio_5d": 0.3,    # 5日量比，权重0.3
    "change_pct":   0.3,    # 日涨跌幅，权重0.3
},
```

**说明**：
- key 是因子 id（可以是 base/virtual/custom/composite 类型）
- value 是权重（正浮点数，不需要加起来等于1，系统自动归一化）
- 权重越大，该因子对评分的影响越大

### 5.3 评分方向

方向决定"因子值大是好还是坏"：

| 方向值 | 含义 | 归一化方式 |
|:---|:---|:---|
| `"high"` | 值越大越好 | 正常归一化：`(value - min) / (max - min)` |
| `"low"` | 值越小越好 | 翻转归一化：`1.0 - (value - min) / (max - min)` |

方向通过策略覆盖（override）配置：

```python
# 在策略设置中配置
"scoring_directions": {
    "momentum_20d": "high",    # 动量大 → 得分高
    "rsi_14": "low",           # RSI低 → 得分高（超卖反弹策略）
}
```

如果未指定方向，默认使用因子注册表中的 `direction` 字段；若该字段为 `"none"`，则默认 `"high"`。

### 5.4 引用不同类型因子

scoring 的 key 可以引用四种因子类型：

```python
# 引用 base 因子（直接取列）
"scoring": {"momentum_20d": 0.5, "change_pct": 0.5}

# 引用 virtual 因子（实时计算表达式）
"scoring": {"ma20_bias": 0.3, "boll_position": 0.3, "vol_ratio_10d": 0.4}

# 引用 custom 因子（DSL公式计算）
"scoring": {"uf_my_factor": 1.0}

# 引用 composite 因子（加权组合）
"scoring": {"cf_my_composite": 1.0}

# 混合引用
"scoring": {
    "momentum_20d": 0.3,       # base
    "ma20_bias": 0.2,          # virtual
    "uf_reversal": 0.2,        # custom
    "cf_momentum_vol": 0.3,    # composite
}
```

### 5.5 评分覆盖（Override）

用户可以在前端策略设置中覆盖默认评分，覆盖保存在 `data/user_data/strategy_overrides/{strategy_id}.json`：

```json
{
    "scoring": {
        "momentum_20d": 0.6,
        "vol_ratio_5d": 0.4
    },
    "scoring_directions": {
        "momentum_20d": "high",
        "vol_ratio_5d": "high"
    },
    "scoring_replace": true
}
```

| 字段 | 说明 |
|:---|:---|
| `scoring` | 覆盖的评分权重 |
| `scoring_directions` | 覆盖的方向配置 |
| `scoring_replace` | True=完全替换默认评分；False=合并（覆盖值优先） |

---

## 第6章 完整实战示例

### 6.1 实战1：创建 DSL 自定义因子

**目标**：创建一个"放量突破动量"因子

**公式逻辑**：放量程度排名 × 突破强度排名

```
rank(vol_ratio_5d) * rank(close / ts_delay(close, 20) - 1)
```

**操作步骤**：

1. 打开页面 → 因子 → 编辑器
2. 在公式框输入：
   ```
   rank(vol_ratio_5d) * rank(close / ts_delay(close, 20) - 1)
   ```
3. 点击"校验" → 确认无语法错误
4. 选择资产类型为"股票"
5. 点击"试算" → 查看 IC 指标：
   - IC均值 > 0.03：因子有效
   - ICIR > 0.5：因子稳定
   - t值 > 2：统计显著
6. 填写：
   - 标签：`放量突破动量`
   - 分组：`自定义`
   - 方向：`high`（值越大越好）
   - 描述：`放量程度与20日突破强度的截面排名乘积`
7. 点击保存

**保存后**：
- 因子 ID：`uf_放量突破动量`（自动生成 `uf_` 前缀）
- 存储位置：`data/custom_factors/uf_放量突破动量.json`
- 可在策略 scoring 中引用：`"scoring": {"uf_放量突破动量": 1.0}`

### 6.2 实战2：创建完整策略

**目标**：MA20 突破 + 放量 + 收阳 + 动量评分

**创建文件**：`data/strategies/custom/my_breakout.py`

```python
"""放量突破策略 — 突破MA20 + 量比确认 + 收阳 + 动量评分"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "my_breakout",
    "name": "放量突破",
    "description": "突破MA20 + 量比≥2.0 + 收阳 + MA60上方 + 动量评分",
    "tags": ["突破", "量价"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "vol_ratio_min",
            "label": "最低量比",
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 10.0,
            "step": 0.1,
        },
        {
            "id": "require_bullish",
            "label": "要求收阳",
            "type": "bool",
            "default": True,
        },
        {
            "id": "require_above_ma60",
            "label": "要求在MA60上方",
            "type": "bool",
            "default": True,
        },
    ],
    "scoring": {
        "momentum_20d": 0.4,      # 中期动量最重要
        "vol_ratio_5d": 0.3,      # 放量程度
        "change_pct": 0.3,        # 当日涨幅
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_ma20_breakout"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.07
MAX_HOLD_DAYS = 10


class MyBreakoutMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        """声明需要的指标列：收盘价、开盘价（用于收阳判断）。"""
        return frozenset({"open", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        """需要60根历史K线（MA60需要60日数据）。"""
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        """计算入场/出场信号。

        入场条件（全部满足）：
        1. 收盘价突破MA20（今天>MA20，昨天≤MA20）
        2. 量比 ≥ vol_ratio_min（放量确认）
        3. 收阳（close > open），可选
        4. 收盘价在MA60上方（趋势保护），可选

        出场条件：
        1. 收盘价跌破MA20（今天<MA20，昨天≥MA20）
        """
        # 获取指标
        ma20 = matrix_feature(market, "ma20")
        ma60 = matrix_feature(market, "ma60")
        vol_ratio = matrix_feature(market, "vol_ratio_5d")

        # 突破MA20：今天收盘>MA20 且 昨天收盘≤MA20
        breakout = (market.close > ma20) & (shift(market.close, 1) <= shift(ma20, 1))

        # 跌破MA20：今天收盘<MA20 且 昨天收盘≥MA20
        breakdown = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))

        # 组合入场条件
        entry = breakout.copy()
        entry &= vol_ratio >= float(params.get("vol_ratio_min", 2.0))

        if params.get("require_bullish", True):
            entry &= market.close > market.open

        if params.get("require_above_ma60", True):
            entry &= market.close > ma60

        # 构建信号矩阵
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=breakdown.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(breakdown, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_ma20_breakout",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = MyBreakoutMatrixStrategy()
```

**验证方式**：
1. 保存文件后，在选股页面点击"重载"
2. 策略列表中出现"放量突破"
3. 点击运行查看选股结果
4. 进入回测页面进行历史回测

### 6.3 实战3：用因子排名研究策略（无需写代码）

**目标**：用3个因子做截面排名选股，不写策略文件

**通过 API 调用**：

```bash
# POST /api/strategies/run
curl -X POST http://localhost:3018/api/strategies/run \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": "factor_rank_research",
    "as_of": "2026-09-08",
    "params": {
      "scoring": {
        "momentum_20d": 0.4,
        "vol_ratio_5d": 0.3,
        "turnover_rate": 0.3
      },
      "directions": {
        "momentum_20d": "high",
        "vol_ratio_5d": "high",
        "turnover_rate": "high"
      },
      "entry_score": 70,
      "exit_score": 40,
      "top_rank": 20
    }
  }'
```

**通过前端操作**：
1. 因子库 → 选一个因子 → 点击"生成策略"
2. 选择方向（high/low）
3. 自动生成策略，进入回测页面

**`factor_rank_research` 参数说明**：

| 参数 | 类型 | 默认值 | 说明 |
|:---|:---|:---|:---|
| `scoring` | dict[str,float] | 无 | 评分因子和权重（最多4个因子） |
| `directions` | dict[str,str] | 无 | 每个因子的方向 |
| `entry_score` | float | 70.0 | 入场最低分（0~100） |
| `exit_score` | float | 40.0 | 离场最高分（0~100） |
| `top_rank` | int | 20 | 每日最多入选标的数（1~100） |

### 6.4 实战4：创建组合因子

**目标**：60%动量 + 40%量比 的组合因子

**计算方式**：`0.6 × zscore(momentum_20d) + 0.4 × zscore(vol_ratio_5d)`

**操作步骤**：
1. 页面 → 因子 → 组合
2. 左侧搜索并添加 `momentum_20d` 和 `vol_ratio_5d`
3. 权重模式选择"手动"
4. 设置权重：`momentum_20d` = 0.6，`vol_ratio_5d` = 0.4
5. 填写：
   - 标签：`动量量比组合`
   - 分组：`组合`
6. 保存

**保存后**：
- 因子 ID：`cf_动量量比组合`
- 存储位置：`data/custom_factors/cf_动量量比组合.json`
- 可在策略中使用：`"scoring": {"cf_动量量比组合": 1.0}`

### 6.5 实战5：超跌反弹策略

**目标**：RSI 超卖 + 反转信号 + 换手率评分

```python
"""超跌反弹策略 — RSI14超卖 + 当日涨幅确认 + 站上MA5"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import valid_shift as shift

META = {
    "id": "my_oversold",
    "name": "超跌反弹",
    "description": "RSI14 < 30超卖 + 涨幅 > 1% + 站上MA5, 超卖反转信号",
    "tags": ["超跌", "反弹", "RSI"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "rsi_max",
            "label": "RSI上限",
            "type": "float",
            "default": 30.0,
            "min": 10.0,
            "max": 50.0,
            "step": 1.0,
        },
        {
            "id": "min_change_pct",
            "label": "最低涨幅%",
            "type": "float",
            "default": 1.0,
            "min": 0.5,
            "max": 5.0,
            "step": 0.5,
        },
        {
            "id": "require_above_ma5",
            "label": "要求收盘价在MA5上方",
            "type": "bool",
            "default": True,
        },
    ],
    "scoring": {
        "change_pct": 0.4,         # 当日涨幅越大越好
        "rsi_14": 0.3,             # RSI越低反弹空间越大 → direction=low
        "vol_ratio_5d": 0.3,       # 放量确认
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = []
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 15


class MyOversoldMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close"})

    def required_warmup_bars(self, params: dict) -> int:
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        rsi_14 = matrix_feature(market, "rsi_14")
        change_pct = matrix_feature(market, "change_pct")
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")

        # 入场条件
        entry = np.ones(market.shape, dtype=bool)
        # 1. RSI < 阈值（超卖）
        entry &= rsi_14 < float(params.get("rsi_max", 30.0))
        # 2. 当日涨幅 > 最低涨幅（反转确认）
        min_change = float(params.get("min_change_pct", 1.0)) / 100.0
        entry &= change_pct > min_change
        # 3. 站上MA5（可选）
        if params.get("require_above_ma5", True):
            entry &= market.close > ma5

        # 出场条件：跌破MA20
        exit_ = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = MyOversoldMatrixStrategy()
```

> **注意**：此策略中 `rsi_14` 的方向应为 `"low"`（RSI越低越好）。在前端策略设置中配置 `scoring_directions: {"rsi_14": "low"}`。

---

## 第7章 前端操作指南

### 7.1 页面导航

| 页面 | 路径 | 功能 |
|:---|:---|:---|
| 因子 | `/factors` | 因子检验、因子库、编辑器、组合、挖掘 |
| 选股 | `/screener` | 运行策略、查看选股结果 |
| 回测 | `/backtest` | 策略历史回测、净值曲线、交易明细 |

### 7.2 因子工作流

```
因子检验 → 因子编辑器 → 因子库 → 生成策略 → 回测验证
  ↓           ↓           ↓          ↓          ↓
验证IC值   写DSL公式   管理因子   一键创建    历史回测
```

### 7.3 因子检验指标解读

| 指标 | 说明 | 参考标准 |
|:---|:---|:---|
| IC均值 | 因子值与次日收益的 Rank IC | >0.03 有效，>0.05 良好 |
| ICIR | IC均值 / IC标准差（稳定性） | >0.5 良好 |
| IC胜率 | IC为正的比例 | >50% 良好 |
| t值(Newey-West) | 统计显著性 | >2 显著 |
| 空值率 | 缺失数据比例 | <20% 良好 |

### 7.4 回测关键指标

| 指标 | 说明 | 参考标准 |
|:---|:---|:---|
| 年化收益 | 策略年化回报率 | >15% 良好 |
| 最大回撤 | 峰值到谷值的最大跌幅 | <20% 良好 |
| 夏普比率 | 风险调整后收益 | >1.0 良好，>2.0 优秀 |
| 胜率 | 盈利交易占比 | >50% 良好 |
| 盈亏比 | 平均盈利 / 平均亏损 | >1.5 良好 |

### 7.5 回测参数说明

| 参数 | 说明 | 建议 |
|:---|:---|:---|
| 回测区间 | 历史数据范围 | 至少3个月，建议1年以上 |
| 初始资金 | 回测起始资金 | 默认100万 |
| 手续费 | 单边佣金费率（万分之） | 默认2（即万分之2） |
| 印花税 | 卖出印花税（千分之） | 默认1（即千分之1） |
| 滑点 | 交易滑点（bps） | 默认5bps |
| 最大持仓数 | 同时持有的标的数 | 默认10 |
| 入场填充 | 买入价格 | `open_t+1`(次日开盘) 或 `close_t`(当日收盘) |
| 出场填充 | 卖出价格 | `open_t+1` / `close_t` / `signal_next_minute` |

---

## 第8章 API 接口参考

### 8.1 因子 API

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/factors` | 获取因子库列表 |
| POST | `/api/factors/validate` | 校验 DSL 公式 |
| POST | `/api/factors/trial` | 试算因子 IC |
| POST | `/api/factors/custom` | 创建自定义因子 |
| POST | `/api/factors/composite` | 创建组合因子 |
| POST | `/api/factors/custom/{id}/update` | 更新自定义因子 |
| DELETE | `/api/factors/custom/{id}` | 删除自定义因子 |
| POST | `/api/factors/custom/{id}/status` | 修改因子状态 |
| POST | `/api/factors/custom/{id}/group` | 修改因子分组 |

**校验公式示例**：

```bash
POST /api/factors/validate
{"formula": "rank(-ts_sum(change_pct, 5))"}

# 响应
{
    "ok": true,
    "errors": [],
    "dependencies": ["change_pct"],
    "referenced_factors": ["change_pct"],
    "warmup_bars": 6,
    "cross_sectional": true
}
```

**试算因子示例**：

```bash
POST /api/factors/trial
{"formula": "rank(-ts_sum(change_pct, 5))", "asset_type": "stock", "days": 40}

# 响应
{
    "ok": true,
    "n_dates": 40,
    "null_ratio": 0.02,
    "ic_mean": 0.045,
    "ic_std": 0.12,
    "ir": 0.375,
    "ic_win_rate": 0.55,
    "t_newey_west": 2.1,
    "ic_series": [{"date": "2026-08-01", "ic": 0.05, "n_symbols": 4500}, ...]
}
```

### 8.2 策略 API

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/strategies` | 获取策略列表 |
| GET | `/api/strategies/{id}` | 获取策略详情 |
| POST | `/api/strategies/run` | 运行单个策略 |
| POST | `/api/strategies/run-all` | 运行所有策略 |
| POST | `/api/strategies/config` | 保存策略覆盖 |
| POST | `/api/strategies/code/validate` | 验证策略代码 |
| POST | `/api/strategies/code/save` | 保存策略代码 |
| POST | `/api/strategies/reload` | 重新加载策略 |

**运行策略示例**：

```bash
POST /api/strategies/run
{
    "strategy_id": "ma_golden_cross",
    "as_of": "2026-09-08",
    "params": {"vol_ratio_min": 1.5}
}
```

### 8.3 选股 API

| 方法 | 路径 | 说明 |
|:---|:---|:---|
| GET | `/api/screener/strategies` | 获取选股策略列表 |
| POST | `/api/screener/run` | 自定义条件筛选 |
| GET | `/api/screener/cached` | 获取缓存结果 |
| GET | `/api/screener/cached-summary` | 获取结果摘要 |

---

## 附录 速查表

### A.1 DSL 公式速查

```
# 动量类
ts_delta(close, 20) / ts_delay(close, 20)       # 20日动量
zscore(ts_delta(close, 20) / ts_delay(close, 20)) # 20日动量z分

# 均值回归
-ts_zscore(close, 20)                             # 20日反转
rank(-ts_sum(change_pct, 5))                      # 5日反转排名

# 量价类
ts_corr(change_pct, volume, 20)                   # 20日量价相关
ts_mean(volume, 5) / ts_mean(volume, 60) - 1      # 量能趋势

# 波动率类
ts_std(change_pct, 20)                            # 20日波动率
zscore(annual_vol_20d)                            # 波动率z分

# 截面排名
rank(momentum_20d)                                # 动量排名
zscore(turnover_rate)                             # 换手率z分

# 条件因子
if_else(close > ma20, 1, -1)                      # 趋势方向
if_else(close > open, change_pct, -change_pct)    # 日内方向加权

# 缩尾去极值
winsorize(change_pct, 3)                          # 3倍标准差缩尾
```

### A.2 策略模板速查

```python
# ===== 最小可用策略 =====
"""最小策略"""
import numpy as np
from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix, matrix_feature

META = {
    "id": "minimal", "name": "最小策略", "description": "收盘价>MA20",
    "asset_types": ["stock"], "timeframes": ["1d"],
    "scoring": {"momentum_20d": 1.0},
}
EXECUTION_BACKEND = "matrix_native"

class S:
    def required_fields(self): return frozenset({"close"})
    def required_warmup_bars(self, params): return 60
    def compute_signals(self, market, params):
        entry = market.close > matrix_feature(market, "ma20")
        return make_signal_matrix(market.shape, entry=entry.astype(np.uint8))
MATRIX_STRATEGY = S()
```

### A.3 常见问题

**Q: 策略文件保存后没有出现在列表中？**
A: 在选股页面点击"重载"按钮，或检查文件路径和 META.id 是否正确。

**Q: DSL 公式校验报 E001 未知标识符？**
A: 检查列名是否在 BASE_COLUMNS 或 ENRICHED_COLUMNS 中，因子 id 是否在注册表中。

**Q: 因子试算 IC 值很低？**
A: 尝试调整公式逻辑、改变方向（high/low）、增加截面运算（rank/zscore）或组合多个因子。

**Q: 回测收益为负？**
A: 检查入场条件是否过于宽松、止损是否太宽、回测区间是否包含极端行情。

**Q: 如何在策略中使用自定义因子？**
A: 先在因子编辑器中保存自定义因子（得到 `uf_xxx` id），然后在策略 META 的 scoring 中引用：`"scoring": {"uf_xxx": 1.0}`。

**Q: scoring 权重必须加起来等于1吗？**
A: 不需要。系统会自动归一化。`{"a": 0.4, "b": 0.6}` 和 `{"a": 2, "b": 3}` 效果相同。

**Q: 如何限制每日选股数量？**
A: 在 META 中设置 `"limit": 20`，或在 `factor_rank_research` 策略中设置 `top_rank` 参数。
