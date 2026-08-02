# Task 11 评审：顶层 run_backtest + result.py + 端到端

## 结论

- **Spec 合规**：✅
- **代码质量**：Approved（0 Critical / 0 Important / 0 Minor）

## 核对细节

### Spec 合规

- `BacktestResult` dataclass 字段 `config, equity_curve, benchmark_curve, trades, metrics` 齐全，`to_dict()` 存在且实现符合预期。
- `run_backtest(config, buy_rules, buy_logic, sell_rules, sell_logic, bars=None, st_service=None)` 签名与 brief 完全一致。
- `__init__.py` 导出 `run_backtest, BacktestResult, Action, Bar, Trade, CostConfig, PositionConfig, BacktestConfig, Condition, RuleStrategy, SignalSource`，逐一核对 `types.py`/`strategy.py`/`result.py` 源码，全部真实存在、拼写正确（此前 `__init__.py` 为空文件，本任务从零补齐）。
- 端到端测试 `test_double_ma_runs_and_reports` 独立重跑通过（`PASSED`），驱动了完整链路：`RuleStrategy`（读取 `compute_indicators` 产出的 `ma5`/`ma20`，两键名核实存在于 `indicators.py`）→ `run_loop` → `Broker` 撮合 → `compute_metrics`；断言 `trade_count >= 1`（非空转义断言，确有信号触发交易）、`equity_curve` 长度与 bars 对齐、`benchmark_return` 存在。
- diff 范围核实仅含 `tradingagents/backtest/result.py`、`tradingagents/backtest/__init__.py`、`tests/backtest/test_end_to_end.py` 三个文件，与约束一致。

### 编排正确性核对（读了 broker.py / strategy.py / engine.py / metrics.py / types.py / data_feed.py 源码逐项对照）

1. **`strategy_factory` 闭包**：`run_loop` 内部 `strategy = strategy_factory(broker)` 只调用一次，`factory(bk)` 中的 `bk` 与 `run_loop` 实际撮合使用的 `broker` 是同一对象引用；`in_position_fn=lambda i: bk.in_position()` 每次 `decide(i)` 调用时才求值（非缓存），随着 `try_buy_one_part`/`try_sell` 原地修改 `broker.shares`，闭包读到的是实时持仓状态。签名对齐 `RuleStrategy.__init__(bars, buy_rules, buy_logic, sell_rules, sell_logic, in_position_fn)`，无参数顺序/命名误用。
2. **`benchmark_curve` 提取**：`compute_metrics` 返回的 dict 含 `benchmark_curve` 键，`result.py` 用 `metrics.pop("benchmark_curve")` 原地弹出后再把 `metrics` 赋给 `BacktestResult.metrics`，`benchmark_curve` 不会重复留在 `metrics` 里；`benchmark_return`（不同键）按预期保留在 `metrics` 中，测试对此有断言覆盖。
3. **`bars=None` 分支**：`load_bars(symbol, start_date, end_date, st_service=None)` 签名核对无误，`run_backtest` 传参顺序 `(config.symbol, config.start_date, config.end_date, st_service)` 完全匹配；`bars` 非 None 时直接跳过该分支使用注入值，测试用例确实走的是注入分支（不触库）。
4. **`to_dict()`**：`config` 用 `asdict`（`BacktestConfig` 内嵌 `CostConfig`/`PositionConfig` 也是 dataclass，`asdict` 递归展开无残留）；`trades` 逐个 `asdict`（`Trade.side` 实际存的是普通字符串 `"buy"/"sell"`，不是枚举实例，无 Enum 残留）；`equity_curve`/`benchmark_curve` 是 `(date, value)` 元组列表，`metrics` 是纯数值字典 —— 整体可安全 `json.dumps`。
5. **`__init__.py` 导出**：逐名核对，均存在且拼写正确（见上）。
6. 未发现对前置任务接口的参数顺序/命名误用。

## 备注

- 复跑了 `tests/backtest/test_end_to_end.py -v`（单文件、耗时 <1s），独立确认 PASSED；未重跑全量套件（报告中已给出 77 passed 记录，未在本次评审范围内复验）。
