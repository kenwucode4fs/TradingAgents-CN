# Task 9 报告：逐日回放 `engine.py`

## 状态
完成，测试全绿。

## Commit
`2682c67` — feat(backtest): 逐日回放主循环含T+1与顺延

## 实现说明：如何做顺延

没有照抄 brief Step 4 里那段混乱的替换代码（其中含 `if pending == Action.HOLD: pending = Action.HOLD`
之类的 no-op，且在未成交时又调用一次 `strategy.decide(i)` 让策略"临时改主意"，
语义上和"收盘后只 decide 一次"相矛盾）。改为一个更干净的单一状态机：

```python
pending: Action = Action.HOLD  # 当前挂单，HOLD 表示无挂单

for i, bar in enumerate(bars):
    # 1. 用当日开盘价尝试撮合挂单（T+1 成交）
    if pending != Action.HOLD and not bar.suspended:
        executed = (broker.try_buy_one_part(bar) if pending == Action.BUY
                    else broker.try_sell(bar))
        if executed:
            pending = Action.HOLD
        # 未成交（涨跌停）→ pending 原样保留，不清空
    # 停牌日：整个 if 分支跳过，pending 同样原样保留

    # 2. 收盘后产生新决策；非 HOLD 信号覆盖挂单
    action = strategy.decide(i)
    if action != Action.HOLD:
        pending = action

    # 3. 收盘记净值
    equity_curve.append((bar.date, broker.market_value(bar.close)))
```

顺延的关键点：
- **只在"未成交"分支里不清空 `pending`**，其余情况（成交、当日 HOLD）该清的清、该覆盖的覆盖，
  不存在"清空又保留"的歧义分支。
- 停牌日和涨跌停未成交是同一处理路径：`pending` 都原样带到下一根 bar 的开盘再试。
- 每天仍然调用一次 `strategy.decide(i)`（保证收盘信号语义不丢），只有非 HOLD 的新信号
  才会覆盖旧挂单（无论旧挂单是"待撮合"还是"本来就没有"），这就是"顺延直到成交或被新信号取代"。

`strategy_factory(broker)` 在循环开始前调用一次得到 `SignalSource`，供策略内部查
`broker.in_position()`。返回值固定为
`{"equity_curve": [(date, equity)], "trades": broker.trades}`，`trades` 直接引用
`broker.trades`（同一对象，未拷贝）。

## 如何验证

`tests/backtest/test_engine.py`，6 个用例，全部针对语义规格设计（未依赖 brief 给的实现代码）：

1. `test_signal_executes_next_day_open` — brief 要求的基础用例：第0日收盘决策买 →
   第1日(2020-03-03)开盘价10成交。
2. `test_buy_postponed_on_limit_up` — brief 要求的涨停顺延用例：次日一字涨停
   （open=11=pre_close×1.1）买不进，顺延到第2日(2020-03-04)开盘10.5成交。
3. `test_buy_postponed_on_suspension`（自加）— 连续两日停牌，挂单顺延到复牌
   第一个开盘日(2020-03-05)成交。
4. `test_sell_signal_executes_next_day_open`（自加）— 先买后卖，验证卖出信号
   同样遵循 T+1：第2日收盘决策卖出 → 第3日开盘成交。
5. `test_equity_curve_length_matches_bars`（自加）— 全程不交易，equity_curve
   长度与 bars 严格一致、日期顺序对齐、净值恒为初始资金。
6. `test_return_dict_keys`（自加）— 返回字典的键集合、`trades` 与 `broker.trades`
   同一对象。

运行结果：

```
./venv/bin/python -m pytest tests/backtest/test_engine.py -v
6 passed
./venv/bin/python -m pytest tests/backtest/ -m "not integration"
66 passed, 3 deselected（全量 backtest 套件回归无破坏）
```

设计先行、一次实现即全绿通过（未经历"实现 → 失败 → 修补"的循环），因为在写实现前
先用手工推演核对了两个 brief 给定用例的逐日状态转移，确认单一状态机分支能同时满足
两者，再落笔代码。

## Concerns

- `engine.py` 未做 `bars` 为空列表的显式处理，此时直接返回
  `{"equity_curve": [], "trades": []}`，语义上是合理的空回测，未额外加测试覆盖，
  如需求上认为空输入应报错可另补。
- 循环结束时若仍有未成交的 `pending`（例如最后一天涨停/停牌），当前实现会静默丢弃
  该挂单（循环结束即终止），未生成任何"最终未成交"的提示或日志；若上层（app/）需要
  感知"回测结束时仍有挂单未成交"这一情况，需要在更上层自行检查或后续加日志/警告。
- 工作区里 `docker-compose.yml`、`tradingagents/default_config.py` 等文件有用户无关
  的既有改动，本次提交严格只 `git add` 了 `engine.py` 和 `test_engine.py`，未触碰其他文件。
