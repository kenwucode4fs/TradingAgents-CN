# Task 4 Review: A股规则 `market_rules.py`

## 结论 1：Spec 合规
✅ **合规**

- brief 要求的 8 个函数（`board_of`、`price_limit_pct`、`limit_up_price`、`limit_down_price`、
  `can_buy_at_open`、`can_sell_at_open`、`buy_cost`、`sell_cost`）全部实现，签名参数顺序、
  返回类型（`Literal[...]`、`float`、`bool`、`tuple[float,float,float]`）与 brief 一致。
- 实现与 brief Step 4 的参考代码逐行一致（仅多了 `Literal` 类型标注与中文 docstring）。
- 4 个测试函数（`test_board_of`/`test_price_limit_pct`/`test_limit_price_and_tradability`/
  `test_costs`）均对具体数值做真实断言（非 tautology），与 brief Step 1/2 的测试用例完全一致。
- 引擎层未 `import app/`，仅依赖 `typing.Literal` 与本模块内 `.types.CostConfig`，符合分层约束。
- 金额均 `round(x, 2)`，测试文件位于 `tests/backtest/`，注释/docstring 为中文。均符合约束。

## 结论 2：代码质量
**Important 1 / Minor 3**（非 Approved，需跟进但不阻塞合并）

### Important

1. **涨跌停价浮点舍入系统性偏差**（`limit_up_price`/`limit_down_price`，market_rules.py:66,81）
   `round(pre_close * (1 ± pct), 2)` 在 Python 中使用二进制浮点数计算，对约 5.7% 的常见价位
   （用 0.01~300.00 元、步进 0.01 遍历 4 种涨跌幅测试）会与交易所规定的"四舍五入"规则相差 1 分钱，
   且几乎全部偏向**舍入过低**。例如 `pre_close=0.95, pct=0.10` → 精确值 1.045，正确应四舍五入为
   1.05，但 `round(0.95*1.10, 2)` 实际返回 1.04（因为 `0.95*1.10` 在浮点下是
   `1.0449999999999999...`）。类似问题同时影响涨停价和跌停价，进而系统性影响
   `can_buy_at_open`/`can_sell_at_open` 在边界价位的判断结果。
   该问题源自 brief Step 4 参考实现本身（实现者忠实照抄，不算"偏离规范"），且未被任何测试覆盖
   （测试用例都选择了整数分的 `pre_close`，如 10.0，恰好避开了浮点误差区）。建议后续用
   `decimal.Decimal` 或整数分定点运算重写，属于回测正确性核心缺口，建议在 Task 4 收尾前或下一个
   相关任务中补修复。

### Minor

1. **报告与实现不一致**：task-4-report.md 声称"使用 `from __future__ import annotations` 的
   `tuple[...]` 语法"，但实际 `market_rules.py` 并未导入 `from __future__ import annotations`
   （PEP 585 泛型内建于 Python 3.9+ 原生支持 `tuple[...]` 运行时标注，故不影响功能，仅报告表述有误）。
2. **`board_of` 北交所前缀元组存在冗余/潜在误判**：`("8", "9", "43", "83", "87", "92")` 中
   `"8"`/`"9"` 已经覆盖 `"83"`/`"87"`/`"92"`（死代码）；同时任何以 8 或 9 开头的 6 位代码
   （包括不属于北交所覆盖范围的老式 B 股代码 900xxx/上证 B 股）都会被无差别归为 `"bse"`。
   目前测试与 brief 场景均未涉及 B 股，风险较低，但逻辑不够严谨，建议改为精确前缀集合。
3. **测试覆盖不足**：`price_limit_pct` 未覆盖科创板 ST（`688xxx, is_st=True`）与北交所非 ST
   （`is_st=False`）两条对称分支，也未覆盖 `43`/`87`/`92` 等其他北交所前缀；虽然代码路径与已测试
   分支相同、风险较低，但作为"金融边界正确性"的核心模块，建议补齐以防未来重构引入回归。

## 未能从 diff 单独确认项
⚠️ 无（本次改动为新增独立模块，无历史依赖需要额外确认）。
