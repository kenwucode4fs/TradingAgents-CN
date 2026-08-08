# 因子打分选股器（子项目 2a）设计文档

- 日期：2026-08-07
- 状态：设计确认中
- 路线定位：量化四阶段路线的**阶段②「多因子选股」**。阶段②拆为两个子项目：
  - **2a（本文）**：因子打分选股器——最新截面选出 TopN 榜单。
  - **2b（后续）**：历史 `daily_basic` 回填 + 组合回测引擎（等权买入 TopN、定期调仓）。
- 前置：阶段①（`tradingagents/backtest/` 引擎 + Web 回测页）已完成上线。

---

## 1. 背景与目标

阶段①做了单股策略回测。阶段②要做「多因子选股」——用一组因子对全市场 A 股打分排序，选出综合得分最高的 TopN。本子项目 2a 只做**选股打分器**：用户配置因子与权重，系统基于**最新截面**给全市场打分，产出可回看的 TopN 榜单，并能把单只股票送去阶段①做单股回测验证。组合回测（一篮子等权持有、定期调仓）需要历史因子截面，依赖 `daily_basic` 历史回填，留到 2b。

**目标**：新增开源打分层 `tradingagents/factor/` + 后端 `/api/factor-screen/*` 异步接口 + 前端「多因子选股」页，实现「配置因子权重 → 全市场标准化加权打分 → TopN 榜单」的闭环，零新增数据同步。

## 2. 范围

**做（2a 第一版）**
- 开源打分层 `tradingagents/factor/`：15 个因子计算 + 横截面百分位标准化 + 方向 + 加权合成 + 排序 + TopN。
- 后端异步选股：`POST /api/factor-screen/run` + 轮询 `status`/`result` + 历史 `history`，复用阶段①异步任务模式。
- 选股域过滤：全市场 / 指定行业 / 剔除 ST / 剔除次新股 / 市值区间。
- 前端「多因子选股」页：因子配置（勾选+权重+方向）、选股域、TopN 数量、结果榜单表、单股回测跳转。
- 榜单持久化 + 历史回看。

**不做（留后续）**
- 组合回测（等权买 TopN、定期调仓、再平衡、组合绩效）——2b。
- 历史 `daily_basic` 回填、财务质量因子（ROE/毛利率/增速）——2b。
- 因子有效性分析（IC、分层回测）——更后续。
- 因子权重寻优、选股方案保存/分享。

## 3. 架构

```
前端「多因子选股」页（Vue）
   │ POST /api/factor-screen/run（因子+权重+方向+选股域+topN）
   ▼
app/routers/factor_screening.py ──创建任务──▶ BackgroundTasks 后台执行
   │ 返回 task_id                              │ loop.run_in_executor（线程池）
   │                                            ▼
   │                         factor_screening_service.run_screen_task
   │                            │ 取候选股（stock_screening_view 最新截面）
   │                            │ 量价因子读 stock_daily_quotes 前复权序列实时算
   │                            ▼
   │                         tradingagents/factor/ 打分（标准化+加权+排序+TopN）
   │                            │ TopN 榜单
   │                            ▼
   │                         存入 factor_screen_results 集合
   ▼
前端轮询 GET /status/{id} → 完成后 GET /result/{id} → 榜单表
```

**复用阶段①的经验**：异步任务用 `BackgroundTasks`；引擎/计算是同步纯函数，若内部触库（读日线）则通过 `loop.run_in_executor` 丢线程池，且**数据在主事件循环预取**后注入（避免阶段①踩过的「线程池内嵌套 asyncio.run 复用主循环 Motor 客户端 → 跨事件循环」坑）。任务状态集合 `factor_screen_tasks`，结果集合 `factor_screen_results`，按 `user_id` 做属主校验（与阶段①一致）。

**与既有 Screening 的关系**：项目已有条件筛选功能（`screening_service`/`enhanced_screening_service`、`stock_screening_view` 宽表、前端 `views/Screening/`）——那是「按字段阈值过滤 + 单列排序」。本子项目是**打分合成排序**，是不同能力，新建独立页与接口，但**复用 `stock_screening_view` 宽表**作为估值/行情/行业的最新截面数据源，不重复造数据层。

## 4. 数据源（零新增同步）

| 数据 | 来源 | 说明 |
|---|---|---|
| 估值：pe/pb/total_mv | `stock_screening_view`（最新截面，16607 条） | 已含真实值，直接读 |
| 行情/分类：close/amount/volume/pct_chg/industry/name/list_date/trade_date | `stock_screening_view` | 展示、流动性、选股域过滤、ST 判定用 |
| 量价历史：前复权日线序列 | `stock_daily_quotes`（1586 万条，~5470 活跃股 × 20 年） | 动量/波动率/均线偏离/RSI/BOLL/量比实时算，用**前复权价**（`close_qfq` 等，与阶段①口径一致） |

- **价格口径**：所有量价类因子用**前复权**序列（避免除权跳空污染动量/波动率）；估值 pe/pb 与展示用价用宽表最新截面原值。
- **ST 判定**：第一版按 `stock_screening_view.name` 是否含 "ST"/"*ST" 判定（最新截面即可，选股域"剔除 ST"用）。
- **次新股**：按 `list_date` 距今交易日数，<阈值（默认 250 交易日/约 1 年）视为次新，"剔除次新"用。

## 5. 因子清单（15 个）

每个因子：`key`（英文）、计算定义、数据源、`default_direction`（`asc`=值越小越好 / `desc`=值越大越好）、方向可配、权重可配、可开关。标准化前统一为「原始因子值」，标准化时按方向处理。

**估值类（宽表最新截面）**
| key | 名称 | 定义 | 默认方向 |
|---|---|---|---|
| `pe` | 市盈率 | 宽表 `pe`；`pe<=0`（亏损）视为缺失 | asc（越小越好） |
| `pb` | 市净率 | 宽表 `pb`；`pb<=0` 视为缺失 | asc |
| `total_mv` | 总市值 | 宽表 `total_mv` | asc（小市值效应） |

**动量/趋势类（前复权日线）**
| key | 名称 | 定义 | 默认方向 |
|---|---|---|---|
| `mom_20` | 20 日动量 | `close_t/close_{t-20} − 1` | desc |
| `mom_60` | 60 日动量 | `close_t/close_{t-60} − 1` | desc |
| `mom_120` | 120 日动量 | `close_t/close_{t-120} − 1` | desc |
| `rev_5` | 5 日反转 | `close_t/close_{t-5} − 1` | asc（短期反转，近期跌的更优） |
| `high_250_prox` | 52 周高接近度 | `close_t / max(close_{t-249..t})` | desc |

**波动/风险类（前复权日线）**
| key | 名称 | 定义 | 默认方向 |
|---|---|---|---|
| `vol_60` | 60 日波动率 | 过去 60 日**日收益率**的样本标准差 | asc（低波动因子） |
| `mdd_120` | 120 日最大回撤 | 过去 120 日前复权净值的最大回撤（正数） | asc |

**技术类（复用 `indicators.py`）**
| key | 名称 | 定义 | 默认方向 |
|---|---|---|---|
| `ma20_bias` | 均线偏离 | `close_t/MA20_t − 1` | asc（可配；默认低偏离优先） |
| `rsi14` | RSI14 | `indicators` 的 rsi14 末值 | asc（可配；默认超卖优先） |
| `boll_pos` | 布林位置 | `(close − boll_low)/(boll_up − boll_low)` 末值 | asc（可配） |

**流动性类（宽表/日线）**
| key | 名称 | 定义 | 默认方向 |
|---|---|---|---|
| `turnover_proxy` | 换手率代理 | 宽表 `amount / total_mv`（amount 单位对齐后近似换手） | asc（可配；默认低换手优先） |
| `vol_ratio` | 量比 | `mean(volume_{t-4..t}) / mean(volume_{t-59..t})` | asc（可配） |

- **前复权序列长度不足**导致某因子无法计算（如次新股不足 120 日）→ 该因子值缺失。
- 技术类默认方向标 asc/可配，是因为"更优方向"因风格而异，交给用户配。
- `turnover_proxy`/`vol_ratio` 只用于**横截面百分位排名**，绝对量纲不影响排名，故不严格对齐单位。
- 标准化边界：某因子有效值股票数 N=1 时百分位记 1.0（`rank/(N−1)` 需按 N≤1 特判避免除零，见测试）。

## 6. 打分流程

1. **候选池**：从 `stock_screening_view` 取全市场股票，按**选股域**过滤：剔除 ST（可选）、剔除次新（可选）、指定行业（可选，多选）、市值区间（可选 min/max）。
2. **因子计算**：对每只候选股，算出用户选中的每个因子的原始值。量价因子读 `stock_daily_quotes` 前复权序列（一次性批量预取候选股的近 ~250 日序列，在主事件循环 await 取好再进线程池计算）。
3. **横截面标准化**：对每个选中因子，在候选池内做**百分位排名**——按因子原始值升序排名，映射到 `[0,1]`（`rank_i/(N−1)`，N=该因子有效值的股票数）。**方向**：`desc`（越大越好）取百分位 `p`；`asc`（越小越好）取 `1−p`。得到每股每因子的 `norm ∈ [0,1]`（越大越好）。
4. **缺失处理**：某股某选中因子值缺失（NaN/None，或 pe/pb≤0，或历史不足）→ **该股整体剔除出榜**（第一版要求候选股在所有选中因子上都有有效值）。这天然剔除数据不全的次新股。
5. **加权合成**：`total_score = Σ(weight_i × norm_i) / Σ(weight_i)`（权重归一，总分 ∈ [0,1]）。
6. **排序取 TopN**：按 `total_score` 降序，取前 `topN`。
7. **产出榜单**：每条含 `code、name、industry、total_score、rank、per_factor:{key: {value, norm, direction}}`，写入 `factor_screen_results`（含 task_id、user_id、配置快照、created_at）。

## 7. 后端

### 7.1 打分层 `tradingagents/factor/`（开源，纯函数可测）
- `factors.py`：每个因子一个计算函数，输入前复权序列/截面值，输出原始因子值；`FACTORS` 注册表（key → {名称、计算、数据需求、default_direction}）。
- `scoring.py`：`percentile_normalize(values, direction)`、`weighted_score(norm_map, weights)`、`rank_topn(scored, n)`。纯函数，不触库。
- `__init__.py`：导出 `FACTORS`、`score_universe(candidates_factor_values, weights, directions, top_n) -> ranked_list`。

### 7.2 Service `app/services/factor_screening_service.py`
- `run_screen_task(task_id, user_id, payload)`：解析配置 → 取候选池（宽表）→ 主循环预取量价序列 → `run_in_executor` 跑纯计算打分 → 落库 → 更新任务状态。
- 校验：至少选 1 个因子、权重>0、topN>0、选股域参数合法。
- `set/get_task_status`、`get_result`、`get_history`，`factor_screen_tasks`/`factor_screen_results` 集合，属主校验。

### 7.3 API `app/routers/factor_screening.py`
| 接口 | 说明 |
|---|---|
| `POST /api/factor-screen/run` | body={factors:[{key,weight,direction}], universe:{exclude_st,exclude_new,industries,mv_min,mv_max}, top_n}。校验→任务→返回 {task_id} |
| `GET /api/factor-screen/status/{task_id}` | 状态 running/done/failed（属主校验，非本人 404） |
| `GET /api/factor-screen/result/{task_id}` | 榜单结果（属主校验） |
| `GET /api/factor-screen/history` | 当前用户历史选股列表 |
| `GET /api/factor-screen/factors` | 返回可用因子元信息（key/名称/类别/default_direction），供前端渲染配置区 |

### 7.4 持久化
- `factor_screen_tasks`：{task_id, user_id, status, error?, created_at, updated_at}
- `factor_screen_results`：{task_id, user_id, config, items:[榜单], created_at}

## 8. 前端（`frontend/src/views/FactorScreening/`）

### 8.1 页面结构（单页）
- **因子配置区**：按 5 类分组列出 15 个因子，每个可勾选启用 + 权重输入（如 0~10）+ 方向切换（越大越好/越小越好，默认取 `default_direction`）。`GET /factors` 拉元信息渲染。
- **选股域**：剔除 ST（开关）、剔除次新（开关）、行业多选、市值区间（min/max，可空）、TopN 数量。
- **「开始选股」**→ `run` 拿 task_id → 轮询 `status`（running/done/failed）→ done 取 `result`。
- **结果榜单表**：el-table，列= 排名/代码/名称/行业/总分 + 各选中因子的标准化得分（可展开看原始值），可按列排序。每行「→ 单股回测」跳阶段①回测页（带入该股代码）。
- **历史选股**：`history` 列表，点击回看某次榜单。

### 8.2 路由与菜单
- `router/index.ts` 加 `/factor-screening` → `views/FactorScreening/index.vue`；`SidebarMenu.vue` 加「多因子选股」入口（与「策略回测」并列）。

### 8.3 API 层 + 复用
- `frontend/src/api/factorScreening.ts`：run/status/result/history/factors，遵循仓库 `request` 封装（baseURL 空、路径带 `/api`）。
- 跳转单股回测复用阶段①回测页（通过路由 query 带入 symbol）。

## 9. 错误处理

- 候选池过滤后为空（如市值区间过窄）：任务 done，榜单为空，前端提示「无符合条件的股票」。
- 未选任何因子 / 权重全 0 / topN≤0：接口层 400，返回具体原因。
- 某股量价序列缺失：该股按第 6 节规则剔除，不报错。
- 打分计算抛错：任务 failed + 错误信息，前端展示。
- 轮询超时：前端提示并允许重试。
- 状态/结果接口属主校验：非本人 404（与阶段①一致，防越权）。

## 10. 测试

- **打分层**（`tradingagents/factor/`）：纯函数单测——`percentile_normalize` 的方向与边界（全同值、单元素、含缺失）、`weighted_score` 权重归一、`rank_topn` 截断与并列、每个因子计算函数用小样本序列断言（含历史不足→缺失）。真实数据冒烟：跑一次全市场打分，看 TopN 数量与总分范围 [0,1] 合理。
- **后端**：`factor_screening_service` 的候选池过滤、预取+run_in_executor 打分落库（注入小样本或小候选集）、属主校验；4+1 个 API 测试（run 校验→400、status/result 属主→404、history 过滤）。集成测试用真实库跑一次小域选股，验证不触发事件循环冲突。
- **前端**：无单测框架，`npm run build`（vue-tsc）通过 + 浏览器端到端验证（配因子→选股→榜单→单股回测跳转）。
- 不改阶段①引擎及其测试。

## 11. 边界与后续（2b 及以后）

- **2b**：历史 `daily_basic` 回填（覆盖回测区间）+ 组合回测引擎（等权买入 TopN、定期调仓、再平衡、组合绩效对比沪深300）+ 组合回测 Web。2a 的打分层 `score_universe` 设计为「给定截面因子值 → 排名」，2b 组合回测可在每个调仓日复用它。
- 更后续：财务质量因子（ROE/毛利率/增速）、因子有效性分析（IC/分层回测）、权重寻优、方案保存。
- 授权：`app/`、`frontend/` 专有（本地自用），打分层 `tradingagents/factor/` 开源（与 `backtest/` 一致）。
