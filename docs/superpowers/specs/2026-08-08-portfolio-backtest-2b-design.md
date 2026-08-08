# 组合回测（子项目 2b）设计文档

- 日期：2026-08-08
- 状态：设计确认中
- 路线定位：量化四阶段路线的**阶段②「多因子选股」的第二半（2b）**。
- 前置已完成（均在 `origin/main`）：阶段①（`tradingagents/backtest/` 单股引擎 + Web 回测页）、阶段②2a（`tradingagents/factor/` 因子打分选股器 `score_universe` + 选股 Web 页）。

---

## 1. 背景与目标

2a 做出了「用一组因子对全市场最新截面打分、选出 TopN」的选股器,但只是**某一时点**的选股,无法回答"这套因子按月调仓、长期持有,历史表现如何"。2b 补上这一环:**组合回测**——按月度调仓、每个调仓日用**当时**的因子截面重选 TopN、等权买入持有,算出组合净值曲线并与沪深300 对比。

**目标**:新增开源组合回测层 `tradingagents/portfolio/` + 历史数据回填(月末估值截面 + 基准指数)+ 后端 `/api/portfolio-backtest/*` 异步接口 + 前端「组合回测」页,实现「配因子 → 跑月度调仓组合回测 → 看净值 vs 沪深300 + 组合绩效 + 调仓明细」的闭环。

## 2. 范围

**做（2b 第一版）**
- 数据回填:全市场月末 `daily_basic`(pe/pb/total_mv)近 20 年 → `stock_monthly_basic`;沪深300(000300.SH)近 20 年日线 → `index_daily_quotes`。
- 开源组合回测层 `tradingagents/portfolio/`:逐月调仓引擎(防前视偏差、停牌/退市处理、T+1 次日开盘成交、成本)+ 组合绩效(vs 基准)。复用 2a `score_universe`、阶段① `broker` 成本/涨跌停规则。
- 后端异步组合回测:`POST /run` + 轮询 `status`/`result` + `history`,属主校验,主循环预取避跨事件循环坑。
- 前端「组合回测」页:因子配置(复用 2a `FactorConfig`)+ 区间/TopN/资金/成本 → 异步 → 组合净值曲线 vs 沪深300 + 绩效卡 + 调仓/持仓明细表。

**不做（留后续）**
- 非等权组合(按因子得分加权、风险平价等)、行业/风格中性约束。
- 非月度调仓频率(周/季)、交易日级再平衡。
- 财务质量因子(需财务数据回填)、因子有效性分析(IC/分层)。
- 多基准切换、组合优化器、滑点模型。

## 3. 架构

```
前端「组合回测」页(Vue)
   │ POST /api/portfolio-backtest/run（因子配置+区间+TopN+资金+成本）
   ▼
app/routers/portfolio_backtest.py ──BackgroundTasks──▶ 后台执行
   │ 返回 task_id                     │ 主循环预取(月末估值截面+基准+候选日线) → run_in_executor
   │                                   ▼
   │                     portfolio_backtest_service.run_task
   │                        │ 逐月调仓:每调仓日 score_universe 选 TopN → 调仓撮合 → 净值
   │                        ▼
   │                     tradingagents/portfolio/ 引擎 + 绩效
   │                        │ 组合净值/基准/绩效/调仓明细
   │                        ▼
   │                     存 portfolio_backtest_results 集合
   ▼
前端轮询 status → done → result → 净值曲线vs基准 + 绩效卡 + 调仓明细表
```

**复用**:2a `score_universe(stocks, factor_configs, top_n)`(纯函数,每个调仓日构造历史截面后调用);阶段① `CostConfig`、`market_rules`(涨跌停/成本);阶段①/2a 的异步任务+属主校验+主循环预取模式。

## 4. 数据回填（2b 硬前置）

### 4.1 月末估值截面 `stock_monthly_basic`
- 内容:每月最后交易日全市场 `daily_basic` 的 `pe`(市盈率)、`pb`(市净率)、`total_mv`(总市值),近 20 年 ~240 个月末截面(~131 万行)。
- 文档:`{code, trade_date, pe, pb, total_mv}`,`trade_date` **统一 "YYYY-MM-DD" 带横线**(与 `stock_daily_quotes` 一致,避免 2a 踩过的格式坑;做字符串日期比较时格式必须对齐)。
- 来源:tushare `daily_basic`(按 trade_date 全市场拉),复用 `app/services/data_sources` tushare adapter + `basics_sync` 基础设施。
- 月末交易日:取每月 `stock_daily_quotes` / 交易日历里该月最后一个交易日。

### 4.2 基准指数 `index_daily_quotes`
- 内容:沪深300(000300.SH)近 20 年日线收盘,文档 `{ts_code, trade_date, close}`,`trade_date` 同样 "YYYY-MM-DD"。
- 来源:tushare `index_daily`。
- 用途:组合净值归一对比、超额收益计算。

## 5. 组合回测引擎（`tradingagents/portfolio/`）

### 5.1 输入
- 因子配置 `factor_configs`(复用 2a:`[{key,weight,direction}]`)。
- 回测区间 `start_date`/`end_date`、`top_n`、`initial_capital`、`cost`(复用阶段① `CostConfig`)。

### 5.2 逐月调仓流程
1. 确定区间内所有**月末调仓日**(每月最后交易日)。
2. 对每个调仓日 D:
   - **构造当时因子截面(防前视偏差,严禁用 D 之后的数据)**:估值 ← `stock_monthly_basic` 中 trade_date == D 月末的 pe/pb/total_mv;量价 ← `stock_daily_quotes` 中每只候选股 **trade_date <= D** 的前复权序列(截止 D)。
   - **候选池(防幸存者偏差)**:该调仓日的候选池 = **D 月末 `stock_monthly_basic` 有估值记录的股票**(即当时真实活跃的全市场,**含后来退市的**)。**绝不能用 `stock_screening_view`**——它只有最新截面、已剔除退市股,用它会引入幸存者偏差(历史组合里塞进只有"活到今天"的股)。选股域从简:按 `list_date` 剔次新(距 D 不足 1 年);ST 历史精确判定第一版从简——若阶段① `st_status_service` 能按日判 ST 则复用,否则第一版不剔 ST 并在结果/文档注明(留后续完善)。
   - `score_universe(stocks, factor_configs, top_n)` → 目标 TopN,等权(每只目标权重 1/N)。
   - **调仓撮合**:目标组合 与 当前持仓 diff → 卖出掉榜股、买入新进股、对保留股再平衡到等权 → 按 **D 的次一交易日开盘价**成交(T+1),扣成本(佣金/印花税/过户费,复用阶段① broker 逻辑)。
3. **停牌/退市处理(第一版)**:
   - 调仓日目标股停牌(该日无有效行情)→ 跳过不买,**其权重留作现金**(不顺延)。
   - 持仓股停牌 → 保持不动,到复牌;停牌期间按最后有效价估值。
   - 持仓股退市 → 按最后有效价清仓转现金。
4. **每日净值**:调仓日之间,每个交易日按持仓 × 当日前复权收盘价 + 现金 = 组合总市值,记入净值曲线。

### 5.3 输出
`PortfolioResult`:`{config, equity_curve:[[date,value]], benchmark_curve:[[date,value]], metrics, rebalances:[{date, buys:[code...], sells:[code...], holdings:[{code,weight}]}]}`。

## 6. 绩效（组合层面）

- `total_return`、`annual_return`、`max_drawdown`、`sharpe`(组合净值)。
- `benchmark_return`(沪深300 同区间)、`excess_return`(组合 − 基准)。
- `turnover`(平均月换手率 = 每次调仓买卖额 / 组合市值 的均值)。
- `rebalance_count`(调仓次数)。
- 净值曲线与基准均归一到初始资金(或归一到 1)做双线对比。

## 7. 后端

### 7.1 引擎层 `tradingagents/portfolio/`（开源纯函数,不触库）
- `engine.py`:`run_portfolio_backtest(config, factor_configs, monthly_sections, price_panel, benchmark, ...) -> PortfolioResult`。所有数据由调用方预取注入(月末截面 dict、候选股日线 panel、基准序列),引擎不触库——与 2a 打分层同纪律,可独立单测。
- `rebalance.py`:调仓 diff 与等权再平衡纯函数(目标 vs 现持仓 → 买卖清单)。
- `metrics.py`:组合绩效(可复用/参考阶段① `backtest/metrics.py`)。

### 7.2 数据回填 Service `app/worker/`（或复用 basics_sync）
- `sync_monthly_basic(start, end)`:按月末交易日拉 daily_basic 落 `stock_monthly_basic`(增量、幂等)。
- `sync_benchmark_index(ts_code, start, end)`:拉 index_daily 落 `index_daily_quotes`。

### 7.3 组合回测 Service `app/services/portfolio_backtest_service.py`
- `run_task(task_id, user_id, payload)`:**主循环预取**(区间内月末截面 + 候选股日线 panel + 基准)→ `run_in_executor` 跑 `run_portfolio_backtest`(纯计算)→ 落库 → 状态。
- `set/get_task_status`、`get_result`、`get_history`(集合 `portfolio_backtest_tasks`/`portfolio_backtest_results`,属主 user_id),照阶段①/2a 同构。

### 7.4 API `app/routers/portfolio_backtest.py`
| 接口 | 说明 |
|---|---|
| `POST /api/portfolio-backtest/run` | body={factors,start_date,end_date,top_n,initial_capital,cost}。校验→任务→{task_id} |
| `GET /status/{task_id}` | running/done/failed,属主校验非本人 404 |
| `GET /result/{task_id}` | {config,equity_curve,benchmark_curve,metrics,rebalances},属主校验 |
| `GET /history` | 当前用户历史组合回测列表 |

## 8. 前端（`frontend/src/views/PortfolioBacktest/`）

- 输入区:**复用 2a `FactorConfig`**(因子勾选+权重+方向)+ 回测区间(起止)+ TopN + 初始资金 + 成本参数。
- 「开始回测」→ `run` → 轮询 `status` → done → `result`。
- 结果区:**组合净值曲线 vs 沪深300**(echarts 双线,归一)+ 绩效卡(总收益/年化/回撤/夏普/超额/换手/调仓次数)+ **调仓明细表**(每个调仓日的买入/卖出/持仓)。
- 复用:2a `FactorConfig`、阶段① echarts 曲线/异步轮询/清定时器模式;新增路由 `/portfolio-backtest` + 菜单「组合回测」。
- API 层 `frontend/src/api/portfolioBacktest.ts`(遵循仓库 request 封装,路径带 `/api`,类型准确——不重复 2a 类型债)。

## 9. 错误处理

- 回测区间早于数据覆盖(如月末截面缺该月)→ 该调仓日跳过或用最近可用截面,并在结果里标注;区间完全无数据 → 任务 failed 可读提示。
- 某调仓日 TopN 全停牌 → 该期留现金,记入调仓明细。
- 基准数据缺失区间 → 绩效里基准段标注,不崩。
- 计算抛错 → 任务 failed + 错误信息。
- status/result 属主校验非本人 404;/run 参数 400 校验(因子空/区间非法/topN≤0)。

## 10. 测试

- **引擎层**(`tradingagents/portfolio/`,纯函数):小样本单测——调仓 diff/等权再平衡(rebalance.py)、**防前视偏差**(断言某调仓日只用 <=D 的数据:构造含"未来"数据的输入,验证不被使用)、停牌跳过留现金、退市清仓、净值计算、绩效(含超额/换手)。真实数据冒烟:跑一小段区间的组合回测看净值/基准合理。
- **数据回填**:集成测试——回填一小段月末 daily_basic + 基准,验证落库字段与 trade_date 格式("YYYY-MM-DD")。
- **后端**:异步任务 + 4 API(run/status/result/history)+ 属主校验;真实库小区间 e2e(覆盖 run_in_executor 不触发事件循环冲突)。
- **前端**:无单测框架,`npm run build`(vue-tsc)+ 浏览器端到端验证(配因子→跑组合回测→净值 vs 基准→调仓明细→绩效)。
- 不改阶段①/2a 引擎及其测试。

## 11. 边界与后续

- 第一版:月度调仓、等权 TopN、沪深300 基准、近 20 年、防前视偏差、基础停牌/退市处理。
- 早期(约 2005 年前)A 股股票少、退市多、数据参差,回测早期段结果**仅供参考**(设计已知,结果里可标注)。
- 后续:非等权/风险平价、行业中性、多调仓频率、财务质量因子、因子有效性分析(IC/分层)、滑点模型、组合优化器。
- 授权:`tradingagents/portfolio/` 开源(与 `backtest/`/`factor/` 一致);`app/`、`frontend/` 专有。
