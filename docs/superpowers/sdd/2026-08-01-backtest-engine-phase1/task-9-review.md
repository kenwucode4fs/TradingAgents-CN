# Task 9 代码评审：逐日回放主循环 `engine.py`

评审对象：`tradingagents/backtest/engine.py`（commit `2682c67`），
对照 brief 语义规格（非 Step 4 字面代码），逐条核对状态机边界。

## 结论

1. **Spec 合规**：✅
   `run_loop(bars, strategy_factory, broker)` 签名、返回结构
   `{"equity_curve": [(date, equity)], "trades": broker.trades}` 均正确；
   6 个测试均为真断言（具体日期/价格/长度/对象同一性），非空跑一遍式假测试。

2. **代码质量**：1 Important / 2 Minor（非 Critical，无需推倒重来）
   - Important：brief 明确点名要核实的"顺延中来了反向新信号"路径未被任何测试覆盖。
   - Minor：跌停顺延（SELL 侧）无对应测试，只测了涨停顺延（BUY 侧）。
   - Minor：`out["trades"]` 是 `broker.trades` 的同一引用而非拷贝（作者已在报告里坦承，非缺陷但是个隐性契约）。

---

## 逐项状态机审查

### 1. 前视偏差（look-ahead bias）
无泄漏。逐行追踪：
- 循环第 i 轮开始时，`pending` 是**上一轮**（decide(i-1)）产生的挂单，本轮 step 1 用
  `bar[i].open` 撮合它——即 T 日收盘信号在 T+1 日开盘成交，时间顺序正确。
- `action = strategy.decide(i)` 在 step 1 撮合**之后**才调用，其结果只写入 `pending`，
  且要等到**下一轮**迭代的 step 1 才会被用来尝试撮合（用的是 `bar[i+1].open`）。
  即"当日收盘决策"绝不会在"当日"被撮合，天然不可能出现"信号当日成交"的泄漏。
- 循环第 0 轮：`pending` 初值 HOLD，step 1 是 no-op，避免了"用不存在的挂单去撮合"的假成交。

结论：语义①②③在实现里严格成立。

### 2. T+1（当日买入当日不可卖）
天然满足，不存在绕过路径。推演：假设 `pending=BUY` 在第 i 轮 step 1 成交（`executed=True` →
`pending=HOLD`），随后 step 2 的 `decide(i)` 因为 `broker.in_position()` 已经为真而返回 SELL，
这个 SELL 只会写入 `pending`，要到第 i+1 轮的 step 1 才会尝试用 `bar[i+1].open` 撮合——
不可能在同一根 bar 内先买后卖。`test_sell_signal_executes_next_day_open` 从买到卖的完整链路
覆盖了这一点（买入 03-03，卖出信号产生于 i=2 收盘，成交于 03-05）。

### 3. 顺延（postponement）状态机
- **停牌顺延**：`if pending != Action.HOLD and not bar.suspended` 门控，停牌日整个撮合分支
  被跳过，`pending` 原样带到下一轮。`test_buy_postponed_on_suspension` 验证了连续两天停牌，
  挂单顺延到复牌当天开盘正确成交，覆盖了"连续多日停牌"路径。
- **涨跌停顺延**：`try_buy_one_part`/`try_sell` 内部通过 `market_rules.can_buy_at_open` /
  `can_sell_at_open` 判断一字板，返回 `False` 时 engine 侧 `executed=False`，同样不清空
  `pending`。`test_buy_postponed_on_limit_up` 验证了这条路径（复核了涨停价计算：
  `pre_close=10, open=11` → `limit_up=10*1.1=11.0`，`11 < 11.0` 为假，正确判定为一字涨停无法买入，
  测试不是"巧合通过"）。
  - ⚠️ 跌停导致 SELL 顺延的对称路径（`can_sell_at_open` 返回 False）**没有测试**，
    虽然代码结构与 BUY 侧完全对称、风险较低，仍属覆盖缺口（见 Minor #2）。
- **顺延期间来了新信号，是否正确覆盖旧挂单**（brief 重点点名的场景）：
  代码逻辑是 `if action != Action.HOLD: pending = action`——非 HOLD 的新信号无条件覆盖，
  不管旧 `pending` 是"待撮合"还是"没有"。我人工推演了 brief 提示的边界情形：
  `pending=BUY` 因涨停未成交，此时 `decide(i)` 返回 SELL（但 `broker.in_position()` 仍为假，
  因为 BUY 从未真正成交）。此时 `pending` 被覆盖为 SELL；下一轮 `try_sell` 内部第一行
  `if self.shares <= 0 or bar.suspended: return False`（`broker.py:96`）会因为 `shares==0`
  永远返回 False——即这个 SELL 挂单会变成一个"死单"，每天尝试撮合但永远失败，直到被
  再一次非 HOLD 信号覆盖。**不会产生错误成交、不会抛异常、不会造成账户状态损坏**，
  效果等价于"取消了那笔未成交的 BUY"，语义上可以接受，是覆盖旧挂单的合理副作用。
  但——**这条路径完全没有测试覆盖**，而它恰恰是 brief 特别要求核实的顺延语义边界，
  也是整个状态机里最容易被后续重构不小心破坏的一处（例如以后有人给 `try_sell` 去掉
  `shares<=0` 前置检查，这个"死单"就会变成真实的错误做空）。判定为 **Important**：
  不是当前代码的正确性缺陷，而是缺了一道关键回归防线。
- **pending 清空时机**：只有"成交成功"（`executed=True`）才清空为 HOLD；"当日 HOLD"
  分支完全不触碰 `pending`（`if action != Action.HOLD` 才赋值，HOLD 时跳过）。
  即 HOLD **不会**清掉一个尚未成交的顺延挂单——这与 brief 里提出的疑问对应，
  实现选择了"保留"而非"清空"。这是更合理的语义：HOLD 代表"策略这一天没有新指令"，
  不代表"撤单"；若 HOLD 清空顺延挂单，涨停顺延测试（strategy 在 i>0 时全部返回 HOLD）
  会直接失效——`test_buy_postponed_on_suspension` 里 i=1、i=2 两天 `decide` 都返回
  HOLD，挂单仍能顺延到 i=3 成交，实测验证了"HOLD 保留 pending"这一选择是自洽且正确的。

### 4. 净值记录
`equity_curve.append(...)` 在循环体最后一行，无条件对每根 bar 执行一次，长度必然等于
`len(bars)`（`test_equity_curve_length_matches_bars` 显式断言，且断言了日期顺序对齐、
未交易时净值恒等于初始资金）。停牌日用 `bar.close` 计价是合理简化——停牌日通常沿用
停牌前收盘价或数据源填充的 close，用它做逐日 mark-to-market 是行业惯常做法，
无需在本任务范围内额外处理。

### 5. Concern 1：末日未成交挂单静默丢弃
判定为可接受的边界行为。多数轻量回测引擎对"回测区间结束时仍挂单未成交"采取隐式丢弃
（不计入 trades，不影响 equity_curve），因为已经没有"下一日开盘"可以撮合。
作者在报告里已如实记录该限制，未过度承诺，若上层需要"回测结束仍有挂单"的告警，
留给上层是合理分工。不构成缺陷。

### 6. 测试未覆盖的状态机路径（汇总）
- **Important**：顺延中的挂单被"方向不一致或不满足前置条件的新信号"覆盖后的行为
  （如未成交 BUY 遇到 SELL 信号、`in_position()` 仍为 False 的情形）——见上文分析，
  行为本身安全，但完全没有回归测试锁定。
- **Minor**：跌停导致 SELL 顺延（`can_sell_at_open` 返回 False）路径未测试，
  只测了对称的涨停 BUY 顺延。
- 未发现的其他缺口：多日停牌（已测）、买卖 T+1 链路（已测）、equity_curve 长度/对齐
  （已测）、返回值结构与 `trades` 同一性（已测）。

---

## Minor 项详情

1. **Minor**：`test_buy_postponed_on_limit_up` / suspension 测试只覆盖了 BUY 侧的
   顺延来源（涨停、停牌），SELL 侧的跌停顺延未覆盖，建议后续补一条
   `test_sell_postponed_on_limit_down` closing the loop。
2. **Minor**：`return {"trades": broker.trades}` 返回的是活引用而非快照，调用方若在
   回测结束后继续用同一个 broker 做别的操作（不太可能，但接口上没约束），
   `out["trades"]` 会跟着变。作者已在报告里坦承，建议在函数 docstring 里显式声明
   "trades 为 broker.trades 的引用，非快照"，避免下游误用。
