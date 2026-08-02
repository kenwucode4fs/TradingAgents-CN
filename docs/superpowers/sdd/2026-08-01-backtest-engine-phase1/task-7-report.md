# Task 7 报告：策略 strategy.py

- 状态：完成（含评审修复）
- Commit：a906368（初版）、90ed14c（修复 review）
- 测试摘要：tests/backtest/test_strategy.py 12 passed；tests/backtest/ 全量 52 passed, 3 deselected
- Review 修复：
  - Important（选择「复用」）：`_eval_one` 改为调用模块级 `cross_up`/`cross_down`，删除内联重复的金叉/死叉判断；并为这两个模块级函数补充了直接单元测试（金叉点 True、非金叉 False、i==0 False、含 None False）。
  - Minor：`_eval_one`/`_eval_group` 对非法 `op`/`logic` 抛 `ValueError`，不再静默降级；补充对应测试。
