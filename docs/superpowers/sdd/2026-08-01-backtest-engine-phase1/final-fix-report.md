# 全分支最终评审 fix wave 报告

处理全分支最终评审发现的 4 项问题（1 Critical + 1 Important + 2 Minor），均已修复并补测试，
提交在分支 `feature/backtest-engine`（直接提交，未合并）。

## 【Critical】pre_close 复权口径不一致

### 问题

`data_feed.bars_from_records` 里 `Bar.open/high/low/close` 取前复权价（`*_qfq`），
但 `Bar.pre_close` 取的是库记录里的**原始** `pre_close`。`broker` 用
`market_rules.limit_up/down_price(bar.pre_close, ...)` 算涨跌停价，再拿**前复权**的
`bar.open` 去比，两者标度不同——历史存在分红的股票复权因子 `f<1`，会导致普通交易日
被误判成一字涨停/跌停（卖单无限顺延、真正的涨跌停封板检测不到）。

### 修复

`tradingagents/backtest/data_feed.py`：让 `Bar.pre_close` 也是前复权口径。

- 对 `idx >= 1`：`pre_close = 前一条 Bar 的 close`（即 `bars[idx-1].close`，
  复权序列性质：当日复权昨收 = 前一交易日复权收盘价）。
- 对 `idx == 0`：用首日复权因子 `f0 = close_qfq / close_raw` 把库里的原始
  `pre_close` 换算成前复权口径：`pre_close_qfq = pre_close_raw * f0`。若原始
  `close` 缺失/为 0 无法算因子，兜底用当日 `open_qfq`（保证至少与 `open`
  同口径，不会跨标度触发误判）。

### 测试

`tests/backtest/test_data_feed.py` 新增 4 个测试：

- `test_pre_close_from_second_bar_onward_equals_previous_qfq_close`：i>=1 的 pre_close 等于前一条复权收盘价，且不等于原始 pre_close。
- `test_pre_close_first_bar_uses_day0_qfq_factor`：首日按因子换算（f0=0.5 场景手算校验）。
- `test_pre_close_first_bar_fallback_when_raw_close_missing`：原始 close 缺失时兜底 open_qfq。
- `test_pre_close_qfq_scale_prevents_false_limit_down_in_broker`（**关键回归测试**）：
  构造复权因子=0.5 的两日数据（原始 pre_close=20 与复权 open=10.1 标度差一倍以上），
  串联 `broker.try_buy_one_part` + `broker.try_sell`，断言修复后第二日能正常卖出。

**验证测试确实暴露了 bug**：临时 `git stash` 掉 `data_feed.py` 的修复（保留新测试），
重跑该测试：

```
FAILED tests/backtest/test_data_feed.py::test_pre_close_qfq_scale_prevents_false_limit_down_in_broker
AssertionError: assert False is True
 +  where False = try_sell(Bar(date='2020-01-03', open=10.1, ..., pre_close=20, ...))
```

即修复前 `pre_close=20`（原始标度）算出跌停价 18.0，`open=10.1` 被误判跌停无法卖出；
`git stash pop` 恢复修复后该测试通过。

## 【Important】Trade 缺 pnl 字段

### 问题

`types.Trade` 无 `pnl` 字段；`metrics.compute_metrics` 内部按股数 FIFO 逐股配对算出
每段盈亏，但没有回填到任何地方，前端拿不到每笔交易的盈亏。

### 修复

- `tradingagents/backtest/types.py`：给 `Trade` 加 `pnl: Optional[float] = None`
  （买入笔恒为 `None`；卖出笔为该笔配对出的总盈亏）。字段放在末尾并给默认值，
  不影响 `broker.py` 里两处位置参数构造 `Trade(...)` 的现有调用。
- `tradingagents/backtest/metrics.py`：在逐股配对循环里，为每个 sell 交易累加
  `sell_total_pnl`（该笔 sell 消耗的各买入段 pnl 之和），循环结束后 `t.pnl =
  sell_total_pnl` 回填。因为 `trades` 是 `broker.trades` 的同一引用，回填会
  同步反映到 `BacktestResult.trades` 及 `to_dict()` 输出。

### 测试

`tests/backtest/test_metrics.py` 新增 2 个测试：

- `test_trade_pnl_backfilled_buy_none_sell_matches_manual_pairing`：一买两卖（分批减仓），
  断言买入笔 `pnl is None`，两笔卖出的 `pnl` 分别等于手算配对盈亏。
- `test_trade_pnl_backfilled_one_sell_covers_multiple_buys`：两买一卖（clear_all 场景），
  断言唯一的卖出笔 `pnl` 等于它消耗的两个买入段盈亏之和。

## 【Minor】平均持仓天数

### 修复

`tradingagents/backtest/metrics.py` 的 `compute_metrics` 新增 `avg_holding_days`：
复用逐股配对循环，buy_queue 额外携带买入日期；每完成一段配对（matched 股数）时，
用 `bars` 构造的 `date -> 序号` 映射算出该段的交易日间隔（`sell_idx - buy_idx`，
按 bar 序号差而非日历天数差，天然跳过非交易日），按**配对股数加权平均**汇总
（选择按股数加权而非按笔平均，注释里说明了理由：避免小额多笔段被等权拉偏）。
无已平仓成交时返回 `0.0`。

### 测试

`tests/backtest/test_metrics.py` 新增 2 个测试：

- `test_avg_holding_days_weighted_by_shares`：两段持仓（100股持2个交易日、200股持
  3个交易日），断言 `avg_holding_days == (2*100+3*200)/300`。
- `test_avg_holding_days_zero_when_no_closed_trades`：无成交时返回 0.0，不崩溃。

## 【Minor】`_fmt` 对 "NaT" 归 None

### 修复

`app/services/st_status_service.py` 的 `_fmt`：把 `"NaT"`（pandas 缺失日期常见
字符串表现）加入空值判定集合 `("None", "nan", "NaT")`，与已有的 `""`/`"None"`/
`"nan"` 一起统一返回 `None`。

### 测试

`tests/backtest/test_st_status.py` 新增 `test_fmt_date_nat_is_none`：
`assert StStatusService._fmt("NaT") is None`。

## 提交

按 Git 卫生要求，只 `git add` 本次改动的引擎/测试/服务文件（未 `git add -A`，
工作区里与本任务无关的 `docker-compose*.yml`、`default_config.py` 改动未纳入）：

```
<fix commit 列表由 git log 给出，见下方"验证"章节>
```

## 验证

单独运行各修复相关用例：

```bash
./venv/bin/python -m pytest tests/backtest/test_data_feed.py tests/backtest/test_metrics.py \
    tests/backtest/test_st_status.py -m "not integration" -v
```

全量回归：

```bash
./venv/bin/python -m pytest tests/backtest/ -m "not integration"
```

结果：

```
86 passed, 4 deselected, 1 warning in 2.38s
```

无回归，4 项修复共新增测试 9 个（Critical 4 + Important 2 + avg_holding_days 2 +
NaT 1）全部通过。
