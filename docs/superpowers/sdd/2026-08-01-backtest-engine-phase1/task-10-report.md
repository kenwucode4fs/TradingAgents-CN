# Task 10 报告：绩效 metrics.py

**状态**：完成

**Commit**：420f792 — feat(backtest): 绩效指标与买入持有基准

**测试摘要**：`./venv/bin/python -m pytest tests/backtest/test_metrics.py -v` → 6 passed（含 brief 指定的 test_total_return_and_drawdown，以及自加的年化、夏普、胜率/盈亏比、无交易、单点净值边界测试）

**Concern**：无。metrics.py 仅依赖标准库（math、typing），未 import app/；提交前已确认 git status 只暂存了 metrics.py 与 test_metrics.py 两个目标文件，工作区中其他无关改动（docker-compose*、default_config.py）未被带入。

## 评审修复（fix commit 080fd8a）

- **Important 已修**：胜率/盈亏比配对从"整笔 buy 对整笔 sell"改为"按股数 FIFO 逐股配对"，维护买入队列 `[价格, 剩余股数, 每股买方成本]`，sell 按 `matched = min(remaining, 队首剩余股数)` 逐段消耗队列，成本按配对股数比例分摊；新增 `test_win_loss_one_buy_many_sells`（一买对多卖）与 `test_win_loss_many_buys_one_sell`（多买对一卖）两个分批场景测试，断言与逐股配对手算结果一致。
- **Minor 已修**：注释声明"打平（pnl==0）计为 win"的约定；注释说明买方成本刻意不计 `stamp_tax`（A股买入印花税恒为 0），避免日后误改。
- 测试：`./venv/bin/python -m pytest tests/backtest/test_metrics.py -v` → 8 passed。
