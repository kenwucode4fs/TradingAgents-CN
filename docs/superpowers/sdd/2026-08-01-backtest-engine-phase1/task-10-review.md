# Task 10 代码评审：绩效指标与买入持有基准

## 结论

- **Spec 合规**：✅
- **代码质量**：1 Important（分级：Critical x0 / Important x1 / Minor x2）

## Spec 合规核对

- `compute_metrics` 返回 9 个键（total_return/annual_return/max_drawdown/sharpe/
  win_rate/profit_loss_ratio/trade_count/benchmark_return/benchmark_curve），与
  brief 完全一致。
- 6 个测试均为真断言（手算期望值或独立套用公式重算，非同义反复）：
  `test_total_return_and_drawdown`、`test_annual_return`、`test_sharpe_ratio`、
  `test_win_rate_and_profit_loss_ratio`、`test_no_trades_no_crash`、
  `test_single_point_curve_no_crash`。
- 约束核对：metrics.py 只 `import math` / `from typing import ...`，未 import
  `app/`，符合引擎层隔离要求；测试文件位于 `tests/backtest/test_metrics.py`；
  diff 仅含 `tradingagents/backtest/metrics.py` + `tests/backtest/test_metrics.py`
  两个文件（diff stat 确认），无关改动（docker-compose*/default_config.py）未混入。
- 中文注释齐全，docstring 完整。

## 公式逐项核对

| 项 | 结论 |
|---|---|
| 总收益 `equity[-1]/initial-1` | ✅ 正确，`n==0` 时安全返回 0.0 |
| 年化 `(1+total_return)**(252/n)-1` | ✅ 正确，`n<=1` 守卫为 0.0 |
| 最大回撤 `max(1-e_t/peak_t)` | ✅ 正确，`peak` 为截至 t（含 t）的最高净值，手算验证（0.10）与测试一致 |
| 夏普 `mean/std*sqrt(252)`，ddof=1 | ✅ 正确；`len(rets)<=1` 与 `std==0` 均安全返回 0.0（避免除零） |
| 买入持有基准 `close[末]/close[首]-1`，curve = close 比例 × initial | ✅ 公式正确。⚠️ 是否传入前复权（qfq）close 取决于调用方传入的 `bars`，metrics.py 本身不做复权判断——diff 中无法确认上游是否保证传入 qfq 数据，标记 ⚠️ |
| 胜率 `wins/closed`，盈亏比 `(均盈)/(均亏)` | 公式本身正确，但**配对算法有 Important 问题**，见下 |
| 除零/边界（n<=1、std=0、无交易、wins=0/losses=0） | ✅ 全部有短路守卫，不会 ZeroDivisionError / inf / nan（`test_no_trades_no_crash`、`test_single_point_curve_no_crash` 覆盖） |

## Important 问题

**买-卖 FIFO 配对是"逐笔"而非"逐股"配对，与引擎默认的多档建仓/减仓语义不兼容。**

`metrics.py` 第 73-86 行（对应 diff L154-174）用 `buy_stack.pop(0)` 把 1 笔 buy
trade 整体对 1 笔 sell trade，按 `t.shares`（sell 的股数）直接计算 pnl，不检查
`b.shares == t.shares`，也不做剩余股数回填。

但回看 `tradingagents/backtest/broker.py` + `types.py`：
- `PositionConfig` 默认 `parts=3`、`reduce_mode="reduce_one"`，即引擎默认按档
  建仓（每次 `try_buy_one_part` 产生一笔 buy trade，档位股数可能因价格不同而不同）。
- `reduce_one` 模式下 `try_sell` 卖出**最后买入的一档**（`part_shares[-1]`，
  LIFO），`clear_all` 模式下则一次性卖出全部持仓（多档合并为 1 笔 sell）。

因此一旦对接真实引擎输出（目前仓库内尚无调用方，`grep compute_metrics` 只命中
定义与测试，属于待后续任务接入），会出现两类实际问题：
1. `clear_all` 模式：1 笔 sell 对应多笔历史 buy，但算法只 pop 1 笔 buy 计算
   pnl，其余 buy 永久滞留 `buy_stack`，既不计入 wins/losses，pnl 计算也用错误的
   买入成本基准。
2. `reduce_one` 模式：多档股数不等时，FIFO 弹出的 buy 与本次 sell 的股数可能
   不一致，同样导致 pnl 计算和后续配对错位；`buy_stack` 提前耗尽时，后续 sell
   会因 `elif t.side == "sell" and buy_stack:` 条件不成立被静默丢弃（不计入
   win/loss，也不报错）。

代码注释里承认这是"简化"（`FIFO 简化：一买对一卖`），brief 公式描述也较简略，
且当前测试只覆盖 1 买 1 卖股数相等的场景（`test_win_rate_and_profit_loss_ratio`）
未触达上述路径，不会在现有测试下暴露。判定 Important 而非 Critical：不会崩溃、
不影响 total_return/annual_return/max_drawdown/sharpe/benchmark 等核心指标，且
目前 metrics.py 尚未被引擎接入，影响面暂未扩散到生产路径；但由于该配对偏差是
在 static 分析下确定可复现的（非猜测），且触发条件正是引擎的默认配置
（parts=3, reduce_one），建议在后续任务把 `compute_metrics` 接入 engine 输出
之前，把配对逻辑改为按股数（quantity-aware）FIFO/加权平均，或至少在
`compute_metrics` 文档中明确声明当前只支持"每笔 buy/sell 股数一一对应"的
使用前提，避免被后续任务直接套用到多档场景产生静默错误的 win_rate/
profit_loss_ratio。

## Minor 问题

1. `pnl >= 0` 把打平（pnl==0）计为 win，brief 未定义打平归类，属可接受但未声明
   的约定，建议注释说明。
2. pnl 公式省略了 `b.stamp_tax`（只减了 `t.stamp_tax`）。核对
   `market_rules.buy_cost` 确认买入侧印花税恒为 0，因此当前结果正确，但写法
   对成本模型的隐含假设未加注释，若未来 `buy_cost` 规则变化（如政策调整）会
   悄悄产生偏差，建议显式减去 `b.stamp_tax` 以保持公式自解释、抗未来变更。
