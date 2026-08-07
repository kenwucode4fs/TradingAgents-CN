# 策略回测引擎 Plan 2(Web 接入)设计文档

- 日期：2026-08-07
- 状态：设计确认中
- 前置：Plan 1(数据准备 + 引擎层)已完成上线（`tradingagents/backtest/` 引擎、`run_backtest` 入口、全市场近 20 年数据已同步、每日自动增量同步已启用）

---

## 1. 背景与目标

Plan 1 做完了回测**引擎**(纯 Python:数据/指标/条件积木策略/分批撮合/逐日回放/绩效),但没有界面入口。Plan 2 给它装上"方向盘和仪表盘"——一个 Web「策略回测」页,让用户在浏览器里配策略、跑回测、看净值曲线和绩效。

**目标**:新增前端「策略回测」页 + 后端 `/api/backtest/*` 接口 + 异步任务,把 Plan 1 的 `run_backtest` 接出来,产出净值曲线、绩效指标、交易明细,并能列表回看历史回测。

## 2. 范围

**做（第一版）**
- 前端「策略回测」页(新增侧边栏菜单)
- 条件积木编辑器:**表格式规则行**(买入组/卖出组,每行 指标+比较符+值,可加减行,AND/OR 切换)
- 回测参数输入:股票选择、区间、初始资金、成本参数、份数/减仓模式
- **异步任务**执行(复用 `queue_service` + `BackgroundTasks`)
- 结果展示:**净值曲线图(echarts,策略 vs 买入持有)+ 绩效指标卡 + 交易明细表**
- 回测记录**持久化**(存库)+ 简单历史列表回看

**不做（留后续）**
- 多股组合回测(Plan 1 引擎第一版单股)
- AI 多智能体信号回测(路线阶段 ③)
- 回撤曲线、月度收益热力图等高级图表
- 策略保存/分享、参数寻优

## 3. 架构

```
前端「策略回测」页(Vue)
   │ POST /api/backtest/run(股票/区间/资金/成本/仓位/买卖规则)
   ▼
app/routers/backtest.py ──创建任务──▶ queue_service(现有异步框架)
   │ 返回 task_id                         │
   │                                       ▼
   │                             BackgroundTasks 后台执行
   │                                       │ loop.run_in_executor(线程池)
   │                                       ▼
   │                             run_backtest(Plan1 引擎,单股)
   │                                       │ 结果(净值曲线/指标/交易明细)
   │                                       ▼
   │                             存入 backtest_results 集合
   ▼
前端轮询 GET /api/backtest/status/{task_id} → 完成后 GET /result/{task_id}
   ▼
echarts 净值曲线 + 指标卡 + 交易明细表
```

**关键技术点(解决 Plan 1 遗留的 asyncio 隐患)**：`run_backtest` 内部用 `asyncio.run`(经 `data_feed.load_bars`)。BackgroundTasks 运行在 FastAPI 的事件循环里,直接调 `run_backtest` 会撞"事件循环已在运行"。**解决:在 worker 里用 `await loop.run_in_executor(None, lambda: run_backtest(...))`**,把 `run_backtest` 丢到线程池执行——它内部的 `asyncio.run` 在新线程的独立事件循环里跑,不冲突。这样也避免了改动 Plan 1 引擎。

## 4. 后端

### 4.1 API(`app/routers/backtest.py`,新建)

| 接口 | 说明 |
|---|---|
| `POST /api/backtest/run` | body = {symbol, start_date, end_date, initial_capital, cost:{...}, position:{parts,reduce_mode}, buy_rules:[...], buy_logic, sell_rules:[...], sell_logic}。经 `queue_service` 创建任务,`BackgroundTasks` 后台跑,返回 {task_id} |
| `GET /api/backtest/status/{task_id}` | 任务状态与进度(pending/running/done/failed) |
| `GET /api/backtest/result/{task_id}` | 回测结果:{config, equity_curve, benchmark_curve, metrics, trades} |
| `GET /api/backtest/history` | 当前用户的历史回测列表(分页:symbol/区间/总收益/时间/task_id) |

**请求 → 引擎参数映射**：前端的 `buy_rules`（[{left, op, right}]）直接映射为 Plan 1 的 `Condition` 列表;`cost`/`position` 映射为 `CostConfig`/`PositionConfig`;组装 `BacktestConfig` 调 `run_backtest`。

### 4.2 Worker(`app/services/backtest_service.py`,新建)

- `run_backtest_task(task_id, params)`:构造 `BacktestConfig` + `Condition` 列表 → `loop.run_in_executor` 跑 `run_backtest` → `to_dict()` → 存 `backtest_results` 集合(含 task_id、user_id、config、结果、created_at)→ 更新任务状态。
- 校验:股票有无数据(缺则任务 failed 并提示"该股票暂无回测数据")、规则合法性、区间有效。

### 4.3 持久化

- MongoDB 集合 `backtest_results`:{_id, task_id, user_id, symbol, config, equity_curve, benchmark_curve, metrics, trades, created_at}。
- `GET /history` 从此集合查当前用户的回测,列表展示;`GET /result/{task_id}` 取单条。

## 5. 前端(`frontend/src/views/Backtest/`,新建)

### 5.1 页面结构（单页）

- **输入区(表单)**:
  - 股票选择(复用现有股票选择组件)、回测区间(起止日期)、初始资金、成本参数(佣金率/最低佣金/印花税率/过户费率)、份数 N + 减仓模式(reduce_one/clear_all)
  - **条件积木编辑器**(核心):买入条件组 + 卖出条件组,各是一组"规则行"。每行 = [指标下拉] [比较符下拉] [值:数字 或 指标下拉];行尾有删除;组内可"+ 添加条件";组头有 AND/OR 切换。
    - 指标下拉:MA5/MA10/MA20/MA60、EMA12/EMA26、MACD(DIF/DEA/柱)、RSI6/12/14、BOLL(上/中/下轨)、收盘价、成交量
    - 比较符:`>` `<` `上穿(金叉)` `下穿(死叉)`
  - 「开始回测」按钮 → 提交任务
- **进度**:提交后显示进度条/状态(轮询 status),完成后自动加载结果
- **结果区**:
  - 净值曲线图(echarts):策略净值曲线 vs 买入持有基准,双线对比
  - 绩效指标卡:总收益率、年化、最大回撤、夏普、胜率、盈亏比、交易次数、平均持仓天数、基准收益
  - 交易明细表:每笔 日期/买卖方向/成交价/数量/手续费/盈亏(pnl)
- **历史列表**:页面顶部或侧栏一个"我的回测"入口,列出跑过的回测(symbol/区间/收益/时间),点击加载回看

### 5.2 路由与菜单

- `frontend/src/router/index.ts` 新增 `/backtest` 路由,侧边栏菜单加「策略回测」入口(参考现有 Screening/Analysis 的注册方式)。

### 5.3 复用

- echarts + vue-echarts(净值曲线)、现有股票选择组件、现有异步任务轮询模式(参考 Analysis 页)、Element Plus 表单/表格组件。

## 6. 错误处理

- 股票无数据:任务 failed,前端提示"该股票暂无回测数据,请确认代码或等数据同步"
- 规则为空/非法(指标参数越界、空条件组):接口层校验,返回具体原因
- 区间内无有效交易日:可读错误
- 回测引擎抛错:任务 failed + 错误信息,前端展示
- 任务轮询超时:前端提示并允许重试

## 7. 测试

- 后端:`app/routers/backtest.py` 的参数映射(前端 rules → Condition)、`backtest_service` 的 run_in_executor 调用与结果落库(用注入 bars 或小段真实数据)、history 查询
- worker 关键点:验证 `run_in_executor` 跑 `run_backtest` 不触发事件循环冲突(集成测试,真实库)
- 前端:条件积木编辑器的增删行/AND-OR/规则序列化(组件测试);净值曲线渲染;端到端一次回测流程(提交→轮询→展示)
- 不改 Plan 1 引擎的测试;引擎正确性已由 Plan 1 的 86+5 测试保证

## 8. 边界与后续

- 第一版单股 + 技术规则 + 异步任务,和 Plan 1 引擎能力对齐
- 后续:多股组合、AI 信号回测(阶段③)、高级图表(回撤/月度热力图)、策略保存/参数寻优
- 授权:`app/`、`frontend/` 为专有代码(本地自用),引擎层 `tradingagents/` 开源
