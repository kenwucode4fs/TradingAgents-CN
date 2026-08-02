# Task 11 报告：顶层编排 result.py + run_backtest

**状态：** 完成

**Commit：** b7f9576

**测试摘要：** `./venv/bin/python -m pytest tests/backtest/ -v -m "not integration"` → 77 passed, 3 deselected（含新增端到端测试 `test_double_ma_runs_and_reports`）。

**实现文件：**
- `tradingagents/backtest/result.py`（新增）：`BacktestResult` dataclass + `to_dict()`；`run_backtest()` 串联 `Broker`、`RuleStrategy`、`run_loop`、`compute_metrics`。
- `tradingagents/backtest/__init__.py`（补齐导出）：导出 `run_backtest`、`BacktestResult`、`Action`、`Bar`、`Trade`、`CostConfig`、`PositionConfig`、`BacktestConfig`、`Condition`、`RuleStrategy`、`SignalSource`。
- `tests/backtest/test_end_to_end.py`（新增）：双均线金叉/死叉端到端测试，注入 bars 不碰数据库。

**流程：** 严格 TDD——先写测试确认 ImportError 失败，再实现，测试转绿，最后跑全量套件确认整套引擎全绿。

**Concerns：** 无。已确认 `git add` 只包含本任务三个文件，未触及工作区中用户无关的 `docker-compose*.yml`、`default_config.py` 改动。
