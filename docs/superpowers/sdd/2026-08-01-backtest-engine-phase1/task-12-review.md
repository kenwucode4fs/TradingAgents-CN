# Task 12 代码评审：真实数据端到端冒烟

## 结论

- **Spec 合规**：✅
- **代码质量**：Approved

## 核对详情

### 1. Spec 合规（逐项核对，diff + 实跑双重验证）

| 要求 | 结果 |
|---|---|
| 文件位置 `tests/backtest/test_smoke_real.py` | ✅ |
| 用 000001 + 双均线跑 `run_backtest` | ✅ `Condition("ma5","cross_up","ma20")` / `cross_down`，`symbol="000001"` |
| 走真实库（不传 bars） | ✅ 调用未传 `bars` 参数，走 `run_backtest` 默认 `bars=None` 分支 |
| 断言 equity_curve 长度 | ✅ `assert len(d["equity_curve"]) > 100` |
| 断言 metrics 含 total_return / benchmark_return | ✅ 两个 `assert "xxx" in d["metrics"]` |
| 标 `@pytest.mark.integration` | ✅ |
| print 收益数值 | ✅ `print("总收益:", ..., "基准:", ...)` |

区间从 brief 建议的 2023-01-01~2024-12-31 改为 2026-01-01~2026-07-31，report 里给出了合理依据
（库内 000001 前复权数据实际覆盖范围为 2026-01-05~2026-07-31，源自 Task1 的同步测试写入，
无缺口），属于对齐真实环境数据的合理调整，不算 spec 偏离。

**独立复核**：实际执行 `./venv/bin/python -m pytest tests/backtest/test_smoke_real.py -v -m integration -s`，
结果与 report 完全一致：139 条记录、总收益 ≈0.00154、基准收益 ≈0.04492、PASSED。

### 2. 代码质量核对

- **是否真端到端**：✅ 追踪 `tradingagents/backtest/result.py::run_backtest` 源码确认，
  `bars is None` 时会 `from .data_feed import load_bars` 并调用，`data_feed.py::load_bars`
  内部经 `HistoricalDataService.get_historical_data` 查真实 MongoDB（`asyncio.run` 包装），
  测试没有 mock/monkeypatch 这条路径，也没有注入假 bars 绕过。是真实端到端。
- **断言是否有意义**：✅ 非空断言（长度阈值 + 关键字段存在性），对于会随数据/日期漂移的真实
  数据冒烟测试，这是恰当粒度（不对具体收益数值做硬断言，避免因数据源更新变脆）。
- **`@pytest.mark.integration` 标注是否正确**：✅ 核对 `tests/pytest.ini`，`addopts = -m "not
  integration"` 是既有配置（本次 diff 未触碰），默认跑不会选中该用例。实测
  `pytest tests/backtest/ -q -m "not integration"` → `77 passed, 4 deselected`，与 report 一致，
  证明不会拖慢/污染单元测试快跑。
- **跨事件循环解法是否合理**：对比同目录 `test_qfq_sync.py`/`test_st_status.py`，两者用单个外层
  `asyncio.run(_run())` 把"建连接(`init_mongodb`)+查询"包在同一协程里，天然同一事件循环。本测试
  无法照搬，因为 `run_backtest` 本身是同步函数、内部自己再 `asyncio.run`，外层不能再套一层
  `asyncio.run`（会冲突/嵌套）。测试改为只构造 `AsyncIOMotorClient`（不触发 I/O，不绑定循环），
  把"建连接+首次查询"都留给 `load_bars` 内部唯一的 `asyncio.run`，逻辑自洽，不是取巧绕过测试的
  workaround，且用 try/finally 正确清理全局状态（`db_manager.mongo_client/mongo_db` 及
  `app.core.database` 模块级变量），不会污染后续用例。
- **diff 范围**：✅ `git show d7860dd --stat` 确认仅 `tests/backtest/test_smoke_real.py`
  一个文件、76 行新增，无其他文件改动；commit message 与 report 一致。

未发现 Critical / Important 问题。无 Minor 问题需要修复项（Jupyter 相关的表述纳入下方 asyncio
concern 判断里的一个次要注记，不构成本任务缺陷）。

### 3. asyncio 事件循环 concern 是否影响 Plan 1

**判断：仅影响 Plan 2（Web 层 async 调用），不影响 Plan 1（脚本/测试）。核实通过，你的判断成立。**

依据：
- `run_backtest` 是同步函数，`bars=None` 时内部唯一一次 `asyncio.run(...)` 由 `data_feed.load_bars`
  发起。`asyncio.run()` 仅在“调用时已存在运行中的事件循环”场景下才会报错
  （`RuntimeError: asyncio.run() cannot be called from a running event loop`）。
- 纯 Python 脚本、pytest 同步测试函数（本用例即是）在调用 `run_backtest()` 那一刻本身不处于运行中
  的事件循环里 —— 本测试就是最直接的证据：它以普通同步函数调用 `run_backtest()`，内部
  `asyncio.run()` 正常起停，未见任何嵌套/冲突报错，实测通过。
- 搜索 `app/` 目录，当前代码库里没有任何地方引用 `run_backtest`/`tradingagents.backtest`
  （Web 层尚未接入，与 brief"Web 接入不在本计划（Plan 2）"一致），说明当前不存在会在运行中
  事件循环里调用 `run_backtest` 的代码路径。
- 该 concern 真正会触发的场景是 Plan 2 里 FastAPI 的 `async def` 路由处理函数（本身运行在
  uvicorn 的事件循环里）直接调用 `run_backtest()`——这会在其内部 `asyncio.run()` 上报错。
  这是 Plan 2 设计需要处理的输入（如用 `asyncio.to_thread`/线程池跑同步的 `run_backtest`，
  或把 `data_feed.load_bars` 改造成可复用外部循环的异步版本），不是本任务范围要修的东西。
- 一个次要注记（不影响上述结论）：report/你的判断里把"Jupyter"也归为不在运行中事件循环的
  场景，这一点不完全可靠——现代 `ipykernel`（6.x+）本身在运行中的 asyncio 循环上执行 cell，
  在 Jupyter 交互式环境里直接调用 `run_backtest()` 也可能触发同样的
  `RuntimeError: asyncio.run() cannot be called from a running event loop`（这也是
  `nest_asyncio` 这类库存在的原因）。但 Task 12 与 brief 的 Plan 1 范围只涉及脚本与 pytest
  测试，不涉及 Jupyter 场景，因此这个次要不准确之处不构成本任务的缺陷，仅供后续文档/说明时
  参考。
