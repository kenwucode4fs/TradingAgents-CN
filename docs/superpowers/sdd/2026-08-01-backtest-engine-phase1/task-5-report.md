# Task 5 报告：数据源 data_feed.py

- 状态：完成
- Commit：2df33e4
- 测试摘要：`./venv/bin/python -m pytest tests/backtest/ -v` 22 passed, 3 deselected（integration 用例沿用既有约定跳过）；`test_data_feed.py::test_bars_from_records_sorted_and_qfq` PASSED，先跑确认 ModuleNotFoundError 失败，实现后转绿。
- Concern：无。`load_bars` 未写集成测试（需真实 Mongo），按 brief 建议留待需要时补 `@pytest.mark.integration`。

## 评审修复（Important + M1 + M2）

- 状态：完成
- Fix commit：4c08fe4
- 修复内容：
  - Important：`bars_from_records` 原来只校验首条记录的 `close_qfq`，增量同步导致的中间日期缺复权价会静默写成 `close=None` 的 Bar。改为逐行校验 `open_qfq/high_qfq/low_qfq/close_qfq` 四个字段，任一为 None 就抛 `ValueError`，信息带 symbol + trade_date；`load_bars` 里原先针对 `records[0]` 的校验相应移除，统一交给 `bars_from_records`。
  - M1：删除 `tradingagents/backtest/data_feed.py` 未使用的 `Optional` 导入。
  - M2：用 monkeypatch 打桩 `HistoricalDataService.initialize/get_historical_data`，为 `load_bars` 补齐两条错误分支单测（无数据 / 记录缺复权价），不依赖真实 DB。
- 测试命令与输出：

```
$ ./venv/bin/python -m pytest tests/backtest/ -v
============================= test session starts ==============================
platform darwin -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /Users/kanewu/Projects/TradingAgents-CN/venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/kanewu/Projects/TradingAgents-CN/tests
configfile: pytest.ini
plugins: asyncio-1.4.0, langsmith-0.7.30, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 28 items / 3 deselected / 25 selected

tests/backtest/test_data_feed.py::test_bars_from_records_sorted_and_qfq PASSED [  4%]
tests/backtest/test_data_feed.py::test_bars_from_records_raises_when_middle_record_missing_qfq PASSED [  8%]
tests/backtest/test_data_feed.py::test_load_bars_raises_when_no_data PASSED [ 12%]
tests/backtest/test_data_feed.py::test_load_bars_raises_when_qfq_missing_on_some_record PASSED [ 16%]
tests/backtest/test_market_rules.py::test_board_of PASSED                [ 20%]
tests/backtest/test_market_rules.py::test_price_limit_pct PASSED         [ 24%]
tests/backtest/test_market_rules.py::test_limit_price_and_tradability PASSED [ 28%]
tests/backtest/test_market_rules.py::test_float_precision_in_limit_price PASSED [ 32%]
tests/backtest/test_market_rules.py::test_costs PASSED                   [ 36%]
tests/backtest/test_qfq_sync.py::test_standardize_record_keeps_qfq_fields PASSED [ 40%]
tests/backtest/test_qfq_sync.py::test_standardize_record_qfq_fields_none_when_missing PASSED [ 44%]
tests/backtest/test_qfq_sync.py::test_normalize_ts_code_maps_exchange_suffix_correctly PASSED [ 48%]
tests/backtest/test_qfq_sync.py::test_get_kline_calls_pro_bar_with_normalized_ts_code PASSED [ 52%]
tests/backtest/test_st_status.py::test_is_st_within_period PASSED        [ 56%]
tests/backtest/test_st_status.py::test_is_st_open_ended_period_means_until_now PASSED [ 60%]
tests/backtest/test_st_status.py::test_is_st_unknown_symbol_returns_false PASSED [ 64%]
tests/backtest/test_st_status.py::test_is_st_multiple_non_adjacent_periods PASSED [ 68%]
tests/backtest/test_st_status.py::test_to_ts_code PASSED                 [ 72%]
tests/backtest/test_st_status.py::test_to_ts_code_beijing_exchange PASSED [ 76%]
tests/backtest/test_st_status.py::test_fmt_date PASSED                   [ 80%]
tests/backtest/test_st_status.py::test_fmt_date_more_cases PASSED        [ 84%]
tests/backtest/test_st_status.py::test_save_periods_empty_list_returns_zero_without_touching_db PASSED [ 88%]
tests/backtest/test_st_status.py::test_save_periods_upserts_each_period_by_symbol_and_start_date PASSED [ 92%]
tests/backtest/test_types.py::test_defaults PASSED                       [ 96%]
tests/backtest/test_types.py::test_bar_defaults PASSED                   [100%]

=============================== warnings summary ===============================
tradingagents/config/__init__.py:5
  /Users/kanewu/Projects/TradingAgents-CN/tradingagents/config/__init__.py:5: DeprecationWarning: ConfigManager is deprecated and will be removed in version 2.0 (2026-03-31). Please use app.services.config_service.ConfigService instead. See docs/DEPRECATION_NOTICE.md for migration guide.
    from .config_manager import config_manager, token_tracker, ModelConfig, PricingConfig, UsageRecord

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================= 25 passed, 3 deselected, 1 warning in 2.62s ==================
```
