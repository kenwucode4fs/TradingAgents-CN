# Task 7 代码评审：条件积木策略与信号接口

## 结论

- **Spec 合规**：✅
- **代码质量**：1 问题：Important x1 / Minor x1（Critical x0）

## Spec 合规细节

- `Condition(left, op, right)`：dataclass 字段与类型完全匹配 brief（`left:str, op:str, right:Union[str,float]`）。
- `SignalSource(ABC)` + 抽象方法 `decide(i:int)->Action`：实现正确。
- `RuleStrategy(bars, buy_rules, buy_logic, sell_rules, sell_logic, in_position_fn)`：签名、`decide()` 行为（持仓先判卖出→SELL，空仓判买入→BUY，否则 HOLD）均与 brief 一致。
- diff 仅含 `tradingagents/backtest/strategy.py` 与 `tests/backtest/test_strategy.py` 两个文件，符合约束；无 `app/` 导入，引擎层隔离未被破坏。
- 两个测试均为真断言（非 `assert True` 类占位）：
  - `test_rsi_threshold_buy`：手工按 `indicators._rsi` 逻辑回溯，8 根连续下跌 K 线在末日 `rsi6=0`（`<30`），确认会触发 BUY，非平凡通过。
  - `test_ma_cross_up_buy`：构造 20 根平盘 + 5 根强涨，手工验证 `ma5[19]=ma20[19]=10`、`ma5[20]=10.2>ma20[20]=10.05`，在 i=20 处金叉成立，`Action.BUY in actions` 断言有效覆盖了 `cross_up` 分支的真实计算路径。

## 条件求值逻辑逐项核对

- `>`/`<`：`right` 为数字或字符串（指标名）两种情况均通过 `isinstance(c.right, str)` 分支正确处理，right 解析后为 None 时安全返回 False。✅
- `cross_up`/`cross_down`：`_eval_one` 内联实现为 `left_prev<=right_prev and left_now>right_now`（金叉）及对称的死叉逻辑，与 brief 描述完全一致；`i==0` 提前返回 False；`left_now`（前置检查）、`left_prev`/`right_now`/`right_prev`（None 联合检查）四个端点均做了 None 防护，不会崩溃。✅
- `left='close'` 用 bar 收盘价，其余走指标序列：`_series()` 对 `left`/`right` 统一处理，一致且正确（`right='close'` 时同样能解析）。✅
- `decide(i)` 顺序：持仓优先判卖出→SELL，空仓判买入→BUY，都不满足→HOLD，与 brief 完全一致。✅
- AND/OR 组合：`_eval_group` 对空规则组直接返回 False；`_eval_one` 对任何 None 值均安全返回 False，不会抛异常。✅
- 前视偏差：`decide(i)` 仅访问索引 `i` 与 `i-1` 的数据；`compute_indicators` 底层用 `rolling`/`ewm`，同样只依赖窗口内的历史数据，无前视偏差。✅

## Important 问题

1. **模块级 `cross_up(series, other, i)` / `cross_down(series, other, i)` 是死代码，且与 `_eval_one` 内联逻辑重复**（`tradingagents/backtest/strategy.py:93-112`）。brief 将其列为该任务应产出的接口之一（"Produces" 一节），但 `RuleStrategy._eval_one` 并未调用这两个函数，而是重新写了一遍等价逻辑；全仓库搜索确认当前没有任何地方 import 或调用它们。report 中提到的"签名与 brief 不一致"确有其事（brief 写的是两参数 `(series, i)`，实现是三参数 `(series, other, i)`——虽然按语义看三参数更合理，brief 本身描述含糊），但更关键的问题是：**这两个函数从未被真正使用，也没有直接测试**，只是通过 `_eval_one` 里手写的等价逻辑被间接验证。两份逻辑重复维护，未来任一处修改容易产生行为分叉（如只改了 `_eval_one` 忘记同步模块函数，或反之），且声明的公共接口实际上无法保证被验证过。建议让 `_eval_one` 直接调用这两个模块函数，消除重复，同时补一条直接调用 `cross_up`/`cross_down` 的单测。

## Minor 问题

1. **`op`/`logic` 字段无校验，非法值被静默吞掉**（`strategy.py:111` `return left_now > right if c.op == ">" else left_now < right`；`strategy.py:117` `return all(results) if logic == "AND" else any(results)`）。若调用方传入拼写错误的算子（如 `">="`）或非 `'AND'/'OR'` 的 `logic`，不会报错，而是被静默当作 `<` 或 `OR` 处理，可能导致策略行为与预期不符且难以排查。不影响当前测试用例，但建议后续加上显式校验或抛出 `ValueError`。
