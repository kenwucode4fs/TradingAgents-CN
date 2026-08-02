# Final fix wave 复审结论

复审范围：`review-d7860dd..4060483.diff`（3 个提交：097ba06 / 49980f0 / 4060483）。
验证方式：逐行手工推演 + 独立数值复核 + 实跑测试套件（`venv` 下
`pytest tests/backtest/ -m "not integration"`，86 passed / 4 deselected，
新增 9 个测试全部通过）。

## 1. Critical：pre_close 前复权口径 — **ADDRESSED**

`tradingagents/backtest/data_feed.py::bars_from_records`：
- `idx >= 1`：`pre_close = bars[-1].close`（即前一条记录的 `close_qfq`）。
- `idx == 0`：`f0 = close_qfq / raw_close`；`pre_close = raw_pre_close * f0`；
  `raw_close` 为 `None`/`0` 或 `raw_pre_close` 缺失时兜底为 `open_qfq`。

**手工推演（标度不一致场景，复权因子=0.5）：**

```
day0: close=20, close_qfq=10.0, pre_close(raw)=19.8
  f0 = 10.0/20 = 0.5
  pre_close_qfq = 19.8*0.5 = 9.9  → bar0 = (open=10, pre_close=9.9)
day1: close_qfq=10.1, open_qfq=10.1
  pre_close = bar0.close = 10.0   → bar1 = (open=10.1, pre_close=10.0)
```

用 `market_rules`：`board_of("600000")="main"` → 涨跌幅 10%。
- `limit_up_price(9.9)=10.89`，`bar0.open=10 < 10.89` → 可买。
- `limit_down_price(10.0)=9.0`，`bar1.open=10.1 > 9.0` → 可卖（正常）。

**反例（回归旧 bug，验证修复必要性）：** 若 `pre_close` 仍用库里原始值 20（未复权），
`limit_down_price(20)=18.0`，而复权后的 `bar1.open=10.1`，`10.1 < 18.0` 会被误判为
一字跌停，卖单被无限顺延——这正是 Critical bug 的复现路径。修复后两个标度统一，
误判消除。

关键正确性依据：前复权（qfq）序列的构造性质保证「当日调整后 pre_close = 前一
交易日调整后 close」在同一复权因子区间内恒成立，且该性质在除权除息日本身也成立
（这正是前复权计算的定义所在——消除跳空）。因此 `idx>=1` 直接取 `bars[-1].close`
是严格正确的，比重新用因子折算更稳健。`idx==0` 的因子折算 `f0=close_qfq/close_raw`
在窗口首日恰好是除权除息日时存在理论上的边界误差（应使用前一日的旧因子而非当日
新因子折算原始 pre_close，但前一日数据不在查询窗口内、无法获取），这是查询窗口
设计的固有局限，非本次修复引入的新 bug，且与 review 要求的实现方案一致。

新增 4 个测试（`test_pre_close_from_second_bar_onward_equals_previous_qfq_close`、
`test_pre_close_first_bar_uses_day0_qfq_factor`、
`test_pre_close_first_bar_fallback_when_raw_close_missing`、
`test_pre_close_qfq_scale_prevents_false_limit_down_in_broker`）均构造了原始价
（20 一线）与复权价（10 一线，复权因子=0.5）不同标度的数据，最后一个测试直接跑
`Broker.try_buy_one_part` / `try_sell` 端到端验证不再误判涨跌停，并在注释里写出
「若仍用原始 pre_close 会误判」的反例数值。手工重算与代码/测试结果一致，全部
PASSED。

## 2. Important：Trade.pnl 回填 — **ADDRESSED**

- `types.py`：`Trade` 新增 `pnl: Optional[float] = None`（末尾字段，有默认值，
  不影响两处既有的位置参数构造 `Trade(bar.date, "buy"/"sell", ...)`，`broker.py`
  两处调用均为 7 个位置参数，`pnl` 保持默认 `None`）。
- `metrics.py`：FIFO 逐股配对循环中，每笔 sell 累加 `sell_total_pnl`（各买入段
  pnl 之和），循环结束后 `t.pnl = sell_total_pnl`；buy 笔不赋值，保持 `None`。
- `result.py::BacktestResult.to_dict`：`"trades": [asdict(t) for t in self.trades]`
  ——`asdict` 自动包含新增的 `pnl` 字段，无需额外改动即可序列化输出。
- `run_backtest`：`compute_metrics` 先于 `BacktestResult` 构造调用，且两者共享
  同一个 `broker.trades` 列表对象，回填对 `to_dict()` 可见。

独立数值复核（不依赖被测代码，手算过公式）：
- 一买两卖：`pnl1=145.05`，`pnl2=-154.65`（与测试期望一致）。
- 两买一卖：卖出笔总 pnl = `pnl1+pnl2 = -109.9`（与测试期望一致）。

测试断言买入笔 `pnl is None`，卖出笔 `pnl` 与手算合计一致，均 PASSED。

## 3. Minor：avg_holding_days — **ADDRESSED**

`metrics.py` 新增按「配对股数加权」的平均持仓天数：`date_to_idx` 把 bar 日期
映射为交易日序号，FIFO 配对时以 `(sell_idx-buy_idx)*matched` 累加、除以配对总股数。
手工推演：d1买100/d3卖100→2个交易日；d2买200/d5卖200→3个交易日；
加权平均 `(2*100+3*200)/300=800/300≈2.667`，与代码执行结果及测试断言一致。
无平仓交易时返回 `0.0`，有对应测试覆盖，PASSED。

按股数加权、用交易日序号差（非日历天数）是合理实现选择，注释说明清楚。

## 4. Minor：_fmt NaT — **ADDRESSED**

`st_status_service._fmt`：`if not s or s in ("None", "nan", "NaT")`，新增
`"NaT"` 归为 `None`。因函数内先 `str(v)`，对真实 `pandas.NaT` 对象
（`str(pd.NaT)=="NaT"`）与字符串 `"NaT"` 均生效。测试
`test_fmt_date_nat_is_none` 断言 `_fmt("NaT") is None`，PASSED。

## 新破坏检查 — **未发现**

- 全量 `tests/backtest/` 套件（不含 integration）执行结果：**86 passed, 4
  deselected**，与复审开始前的基线一致，含本次新增 9 个测试全部 PASSED。
- 单独跑 `test_data_feed.py` + `test_metrics.py` + `test_st_status.py`：
  31 passed（含旧用例 `test_win_loss_one_buy_many_sells` /
  `test_win_loss_many_buys_one_sell` 等仍通过，证明 pnl 回填未破坏既有
  胜率/盈亏比逻辑）。
- 全仓库检索 `Trade(` 构造点，只有 `broker.py` 两处，均为 7 个位置参数，
  新增的 `pnl` 默认值不影响现有调用。
- `metrics.compute_metrics` 对 `t.pnl` 的回填直接修改传入的 `trades`
  （即 `broker.trades`）列表中的对象本身——`run_backtest` 里
  `BacktestResult.trades` 与传给 `compute_metrics` 的是同一个列表/同一批
  对象，回填后两处保持同步，未引入悬空引用或数据不一致。
- `pre_close` 改动只影响 `Bar.pre_close` 的取值来源，不改变 `Bar` 其它字段
  语义，未见对 `engine.py`/`strategy.py`/`indicators.py` 的连锁影响；对应的
  `test_broker.py`、`test_engine.py`、`test_bt_indicators.py`、
  `test_strategy.py`、`test_end_to_end.py` 均在全量跑中保持通过。

## 总体 Verdict：**可合并**

Critical 项经手工推演确认标度换算严格正确（含首日边界情况的已知固有局限，
非新引入 bug，且与既定修复方案一致）；Important 与两项 Minor 均已实现、有
测试覆盖且断言正确；未发现对既有功能的新破坏。
