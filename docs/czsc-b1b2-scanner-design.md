# 缠论 B1/B2 信号选股策略 — 架构设计与实现方案

- 日期：2026-11-22
- 状态：设计定稿 → 分步实现
- 相关模块：`backend/app/custom/czsc/`（L2 扩展）、`backend/app/tickflow/pools.py`、`backend/app/strategy/`

---

## 1. 业务需求

从 A 股全市场（或指定股票池）自动筛选**已出现 B1 或 B2 买点信号**的股票，支持级别参数（30 分钟 / 日线 / 周线）及缠论判定口径配置，复用现有 `identify_bs_points` 算法，**不改变单股分析行为**，与工程架构一致。

产出：一张候选清单，每股带 `symbol / name / 周期 / 信号类型(B1/B2) / 信号时间 / 信号价 / 背驰明细 / 口径标注`，可按信号类型、时间新旧、背驰强度排序。

---

## 2. 可行性评估（基于代码现状）

| 能力 | 现状 | 结论 |
|---|---|---|
| B1/B2 识别 | `identify_bs_points` 严格实现 B1(趋势背驰)/B2(盘整背驰+次级别确认)，产出 `BsPoint(type='B1'/'B2')` | ✅ 直接复用 |
| 单股分析入口 | `AnalyzeService.analyze(req)` 同步；`analyzer.analyze_async(req)` 异步（线程池+超时） | ✅ 直接复用 |
| 级别参数 | `freq` 支持 日线/周线/月线/5/15/30/60 分钟；次级别映射已有 | ✅ 直接复用 |
| 判定口径配置 | `DivergenceConfig` 12 个字段（面积口径/DIF/逻辑/重叠/回抽深度/区间套）全可配 | ✅ 直接复用 |
| 全 A 股票池 | `get_pool("CN_Equity_A")`，parquet 缓存 | ✅ 直接复用 |
| 信号→选股 | screener/strategy 与 czsc **零耦合**；23 个内置策略无缠论 | ❌ 需新建桥接 |
| 批量分析 | czsc 无批量端点；全后端无 `asyncio.gather` 封装，但有 `ThreadPoolExecutor` 惯例 | ⚠️ 需自建并发 |
| 缓存 | `AnalysisCache` 已按 `cache_key`（含全部判定参数+日期）缓存单股结果 | ✅ 天然复用 |

**可行性结论**：高。核心算法与配置全部现成，只需新建「池 → 并发逐股分析 → 按 type 过滤 → 排序产出」的桥接层和一个 API 端点。不触碰主工程 screener/strategy 代码，保持 czsc 扩展的隔离性（见 `app/custom/czsc/__init__.py` 设计约束：不修改主工程核心路由）。

---

## 3. 策略规则

### 3.1 信号定义（严格复用现有算法，不重新实现）

- **B1**：下跌趋势中，次级别走势跌破最后中枢形成趋势背驰（面积+ DIF 同时衰竭，`logic=and`）；位置在中枢下方；取全窗口最低点那笔。
- **B2**：B1 之后第一次回抽结束点，低点不破 B1，且盘整背驰成立（第17课定律一次级别确认）。
- 过滤条件：`bp.type in {"B1","B2"} and bp.direction == "买"`。
- 口径标注：`definition_mode`（`practical`/`strict`）、`divergence_pass`（命中的条件集合）随结果透出，便于用户判断信号强度。

### 3.2 时间窗口

- 分析窗口：`as_of` 往前 `lookback_days` 自然日（默认 425 天 ≈ 单股分析默认 365+60 暖机）。
- 信号新鲜度：`signal_age_days <= max_signal_age` 才算候选（默认 5 个自然日），避免把半年前的历史信号当成当前机会；设为 0 表示不限。
- B1/B2 时间顺序天然由算法保证（B2 依赖 B1），无需额外校验。

### 3.3 排序与截取

- 默认排序：信号时间倒序（最新在前）；可选按 `divergence_pass` 命中数（面积+DIF 都命中优先）。
- `limit` 默认 50，上限 500。

---

## 4. 参数设计

新增 `ScanRequest`（frozen dataclass，位于 `app/custom/czsc/config.py` 或独立 `scan_config.py`）：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `pool` | str | `CN_Equity_A` | 股票池 id（`CN_Equity_A`/`CSI300`/`CSI500`/`SSE50`/`watchlist`）或显式 symbols 列表 |
| `symbols` | list[str]\|None | None | 显式指定标的（优先于 pool），便于小范围验证 |
| `freq` | str | `日线` | 级别：日线/周线/30分钟/60分钟/15分钟/5分钟 |
| `as_of` | date\|None | None(今日) | 扫描截止日 |
| `lookback_days` | int | 425 | 分析窗口自然日 |
| `signal_types` | tuple[str,...] | (`B1`,`B2`) | 目标信号，白名单 {B1,B2}；本期不做 S1/S2 |
| `max_signal_age` | int | 5 | 信号最大年龄(自然日), 0=不限 |
| `min_divergence_hits` | int | 0 | 至少命中几个背驰条件(0/1/2)，过滤弱信号 |
| `order_by` | str | `dt_desc` | `dt_desc` / `divergence_desc` |
| `limit` | int | 50 | 返回上限(1~500) |
| `max_workers` | int | 8 | 并发线程数(1~32) |
| `per_symbol_timeout_s` | float | 30 | 单股分析超时 |
| `max_symbols` | int\|None | None | 扫描标的上限(防全市场过载), None=不限 |
| `divergence` | DivergenceConfig | 默认 | **完整复用**单股分析的 12 项判定口径参数 |
| `force_refresh` | bool | False | 透传单股分析，忽略缓存 |

API 层用扁平 query 参数（`pool`, `symbols` 逗号分隔, `freq`, `signal_types=B1,B2`, `bs_*` 系列同 `/analyze`），内部组装 `ScanRequest`。

**关键设计决策**：扫描的 `bs_*` 参数与单股 `/analyze` **同名同默认**，保证「页面上看到某股 B1 的条件」与「扫描筛出该股的条件」完全一致，避免双套口径漂移。

---

## 5. 模块划分

```
backend/app/custom/czsc/
├── config.py                    # + ScanRequest dataclass / normalize / cache_key
├── schemas.py                   # + ScanResult / ScanHit / ScanProgress Pydantic
├── application/
│   ├── service.py               # 不改（复用 AnalyzeService.analyze）
│   └── scanner.py               # NEW: ScanService —— 池解析+并发扫描+过滤+排序
├── routes.py                    # + POST /api/czsc/scan（同步/异步两种模式）
└── analyzer.py                  # + analyze_scan 门面（可选）
tests/
└── test_czsc_scanner.py         # NEW: 单元测试
```

**职责边界**：
- `ScanService` 只做编排，不复制任何买卖点判定逻辑。
- 单股分析一律走 `AnalyzeService.analyze(req)`，保证与 UI 一致。
- `DivergenceConfig` 作为参数对象整体透传，零字段重复定义。

---

## 6. 数据流

```
POST /api/czsc/scan {pool, freq, signal_types, bs_*, ...}
  ↓ routes: 解析 query → ScanRequest.normalized()
  ↓ ScanService.scan(req)
     1. resolve_symbols: symbols 显式 → 否则 get_pool(pool) → 过滤 ST/退市 → max_symbols 截断
     2. 构造 AnalyzeRequest(symbol, freq, divergence=req.divergence, features="bi,zs,bs_points")
        （features 不含 fx/macd/bars/ma —— 扫描只需买卖点，省序列化）
     3. ThreadPoolExecutor(max_workers) 并发: svc.analyze(req_i) → 单股 result
        （exception/NO_DATA 记 errors，不中断整体）
     4. for bp in result["bs_points"]:
            if bp.type in signal_types and (as_of - bp.dt).days <= max_signal_age
            and len(bp.divergence_pass) >= min_divergence_hits:
                → ScanHit(symbol, name, freq, type, dt, price, divergence_type,
                          divergence_pass, definition_mode, zs_range)
     5. 排序(按 order_by) → 截断 limit
  ↓ ScanResult(as_of, freq, params, hits, total_scanned, elapsed_ms, errors, warnings)
  ↓ JSONResponse
```

**异步渐进模式**（大面积扫描）：当 `symbols` 为空且池规模 > 阈值（默认 200），走后台任务：
- `POST /scan` 立即返回 `{task_id, status:"running"}`；
- `GET /scan/{task_id}` 查 `{status, progress, partial_hits, errors}`；
- 结果落 `data/czsc_scan/{task_id}.json`，与工程 `strategy_run_queue` 的渐进式范式一致。

---

## 7. 与现有代码的衔接

| 衔接点 | 方式 |
|---|---|
| 路由注册 | `app/custom/czsc/__init__.py::setup(registrar)` → `registrar.include_router(build_router())`，无需改 main.py |
| 单股分析 | `get_default_service().analyze(req)`，复用单例 + AnalysisCache + 次级别验证器 |
| 判定口径 | `DivergenceConfig` 整体复用（含本周新增的 `zs_pullback_base/min_ratio`） |
| 股票池 | `get_pool(pool_id)` 复用 parquet 缓存；`watchlist` 复用用户自选 |
| 数据源/周期 | `KlineSourceChain`（primary→eastmoney）+ `_KLT_MAP` 周期映射，无需新数据源 |
| 并发 | `ThreadPoolExecutor`（与 `engine.run_all`、`kline_sync.fetch_intraday_full_market_burst` 同范式） |
| 结果结构 | 新 `ScanHit/ScanResult`，字段对齐 `BsPointItem`，前端可复用买卖点悬浮卡 |

**不改动**：`app/api/screener.py`、`app/services/screener.py`、`app/strategy/**` 全部零改动，避免污染主工程选股/策略路径。

---

## 8. 边界条件与风险

1. **数据不可用**：czsc 依赖可选，`czsc_enabled=false` 或未安装时端点返回 503 + 安装提示（复用现有 `error_status`）；单股 `NO_DATA` 记入 errors 跳过，不中断全池。
2. **分钟级全市场不可行**：30 分钟数据东财仅约 5 周历史，且全市场逐股拉取会触发限流。策略：分钟级别强制要求显式 `symbols`（上限 200）或 `watchlist`，全 A + 分钟级别直接返回参数错误，提示缩小范围。
3. **并发与限流**：默认 8 线程；单股分析内部已用 `run_in_executor` + 30s 超时；`AnalysisCache` 与 `SublevelVerifier` 已有锁。扫描层再加信号量池防止过载。
4. **信号过期**：`max_signal_age` 默认 5 天；B1/B2 出现在很久以前但最近无新信号 → 不入选，避免"历史信号冒充当前机会"。
5. **口径一致性**：扫描结果 `definition_mode` 必须透出；用户切 `strict` 时 B1/B2 会大幅减少，属预期。
6. **B2 次级别验证**：`enable_interval_nest` 默认关闭时 B2 次级别确认走 fail-open；若用户开启，扫描耗时显著增加，需提示。
7. **幂等与缓存**：`force_refresh=false` 时命中 AnalysisCache 的分析不重复取数；重复扫描同一组合结果稳定。
8. **内存**：扫描不保留 K 线/笔/中枢明细，只保留 ScanHit；5000 股 × 少量命中 → 内存可控。

---

## 9. 验证方案

1. **单元测试**（`tests/test_czsc_scanner.py`）：
   - 参数归一化（白名单、范围钳制、信号类型过滤）
   - 信号过滤：注入 mock `AnalyzeService`，构造含 B1/B2/B3/S1 的结果，断言只留 B1/B2
   - 时间新鲜度：`max_signal_age` 边界
   - 背驰命中数过滤：`min_divergence_hits`
   - 排序与 limit
   - 错误隔离：单股抛异常时其余继续
   - 分钟级别全 A 拒绝
2. **集成冒烟**：用 `symbols=["300124.SZ","002027.SZ"]` + 日线跑真实扫描，断言能返回结构正确的 ScanResult（不强制有信号）。
3. **一致性校验**：对扫描命中的某股，用相同 `bs_*` 参数调 `/api/czsc/analyze`，断言 B1/B2 的 `dt/type/price` 与扫描结果一致（证明复用同一算法）。
4. **全量回归**：`backend` 全量 pytest + Ruff；前端 `npm run build` 若涉及参数 UI。

---

## 10. 实施步骤（分步）

1. `config.py` 加 `ScanRequest` + 归一化/校验；`schemas.py` 加 `ScanHit/ScanResult/ScanTaskStatus`。
2. `application/scanner.py` 实现 `ScanService`（同步扫描 + 异步任务管理 + 结果落盘）。
3. `routes.py` 加 `POST /scan`、`GET /scan/{task_id}`；`__init__.py` 无需改。
4. `tests/test_czsc_scanner.py` 单元测试 + 集成冒烟。
5. 全量回归 + 文档更新。

---

## 11. 实现完成记录（2026-11-22）

| 步骤 | 交付 | 验证 |
|---|---|---|
| 1 | `config.py` + `ScanRequest`（归一化/校验/analysis_request/cache_key）；`schemas.py` + `ScanHit/ScanResult/ScanTaskStatus` | — |
| 2 | `application/scanner.py` `ScanService`：池解析（ST 过滤）、并发扫描、B1/B2 过滤、新鲜度/背驰命中数、排序、错误隔离、异步任务+落盘 | 9 条单测通过 |
| 3 | `routes.py` + `POST /api/czsc/scan`（同步/异步自动切换）、`GET /api/czsc/scan/{task_id}`；disabled 分支同步注册 | FastAPI TestClient 200，结构/口径透传正确 |
| 4 | `tests/test_czsc_scanner.py` 9 条单测 | 全量 2248 passed、Ruff 改动文件全过 |

**实测**：3 只小样本真实扫描（日线）产出 1 个 B1（600000.SH @2026-06-30），同实例二次扫描结果一致（幂等，命中 AnalysisCache）。

**已知限制**：
- 首次全池扫描受数据源取数影响较大（网络取数约 100s/3 只）；缓存命中后显著加快。
- 分钟级别全 A 被显式拒绝（东财历史窗口 + 限流），需 `symbols` 指定 ≤200 只。
- 异步任务状态仅进程内存 + 结果落盘 `data/czsc_scan/{task_id}.json`，进程重启后 `GET /scan/{task_id}` 不再返回内存状态（结果文件仍在）。
- 数据源切换（primary/eastmoney）会改变笔序列 → 同一参数在不同数据源下信号可能不同；扫描结果带 `params` 摘要与 `definition_mode` 便于追溯。

---

## 12. 策略面板接入（2026-11-22 补充）

用户期望的不是独立 API，而是**策略面板里的一个自定义策略**（策略池可选、点开设置、按策略筛股）。已按此实现：

| 交付 | 文件 | 说明 |
|---|---|---|
| 自定义策略 | `data/strategies/custom/custom_czsc_b1b2.py` | META 13 项参数（`freq` 选日线/30分钟/周线、`signal_types`、回抽深度基准/比例等），`python_history_legacy` 后端 |
| AST 白名单增强 | `app/strategy/ai_generator.py` | ① 白名单加 `app.custom.czsc`；② `_module_allowed` 改为逐级前缀匹配（放行 `app.custom.czsc.*` 子模块，但 `app.os` 仍被拒） |
| 策略单测 | `tests/test_czsc_strategy.py` | 5 条：AST 校验、注册与后端、过滤命中、空命中、候选截断 |

**策略设置面板**：点开「缠论B1/B2买点」策略的设置齿轮，可切换：
- 缠论级别（日线/30分钟/周线）
- 信号类型（B1+B2 / 仅B1 / 仅B2）
- 信号年龄、分析窗口、背驰命中数、最多扫描只数
- 全部判定口径（MACD面积/DIF/逻辑/重叠口径/回抽深度基准+比例）—— 与缠论分析页同源

**关键设计**：
- 策略声明 `timeframes=["1d"]`（消费日线 enriched 拿候选池），缠论级别通过 `freq` 参数表达，与面板 `1d/1m` 周期语义解耦。
- `filter_history` 先用成交额排序取 Top N（默认300，控制逐股分析耗时），再同步调用 `ScanService.scan()`，返回命中 symbol 当日行。
- 参数持久化走工程标准 `strategy_overrides`（`POST /api/strategies/config`），无需新机制。

**验证**：策略出现在 `/api/strategies` 列表（source=custom）；14 passed（策略+扫描单测）；全量 2253 passed。

**已知限制**：策略面板是同步执行，全池逐股缠论分析耗时较长；已用 `max_symbols`（默认300）截断控制。若需全 A 异步扫描，用独立端点 `POST /api/czsc/scan`（池>200 自动转异步任务）。
