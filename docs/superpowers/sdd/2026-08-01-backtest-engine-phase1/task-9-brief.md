### Task 9: 逐日回放 `engine.py`

**Files:**
- Create: `tradingagents/backtest/engine.py`
- Test: `tests/backtest/test_engine.py`

**Interfaces:**
- Consumes: `List[Bar]`、`Broker`、`SignalSource`、`types.Action`。
- Produces: `run_loop(bars, strategy_factory, broker) -> dict`，返回 `{"equity_curve": [(date, equity)], "trades": broker.trades}`。
  - **T+1 与次日成交**：第 i 日收盘后 `strategy.decide(i)` 产生动作，成交在**第 i+1 日**的 `bar.open` 执行（`try_buy_one_part`/`try_sell`）。当日买入的份不可当日卖出天然满足（决策在收盘后、成交在次日）。
  - `strategy_factory(broker)` 返回 `SignalSource`（让策略能查 `broker.in_position`）。
  - 每日收盘记 `equity = broker.market_value(bar.close)`。

- [ ] **Step 1: 写失败测试**（双日：D1 决策买、D2 开盘成交）

```python
# tests/backtest/test_engine.py
from tradingagents.backtest.types import Bar, Action, CostConfig, PositionConfig
from tradingagents.backtest.broker import Broker
from tradingagents.backtest.engine import run_loop

def _bar(d, o, c, pre): 
    return Bar(date=d, open=o, high=max(o,c), low=min(o,c), close=c, pre_close=pre, volume=1e6)

def test_signal_executes_next_day_open():
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 12, 10),
            _bar("2020-03-04", 12, 13, 12)]
    # 策略：第0日就要买（decide 返回 BUY when not in position），之后 HOLD
    class AlwaysBuyOnce:
        def __init__(self, broker): self.b = broker
        def decide(self, i):
            return Action.BUY if (i == 0 and not self.b.in_position()) else Action.HOLD
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: AlwaysBuyOnce(b), broker)
    # 第0日收盘决策买 → 第1日(2020-03-03)开盘10元成交
    assert len(broker.trades) == 1
    assert broker.trades[0].date == "2020-03-03"
    assert broker.trades[0].price == 10
    assert len(out["equity_curve"]) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `engine.py`**

```python
# tradingagents/backtest/engine.py
"""逐日回放主循环。信号在 T 日收盘产生，T+1 开盘成交。"""
from typing import Callable, List
from .types import Bar, Action
from .broker import Broker

def run_loop(bars: List[Bar], strategy_factory: Callable, broker: Broker) -> dict:
    strategy = strategy_factory(broker)
    equity_curve = []
    pending: Action = Action.HOLD
    for i, bar in enumerate(bars):
        # 1. 执行上一交易日收盘产生的挂单（次日开盘成交）
        if not bar.suspended:
            if pending == Action.BUY:
                broker.try_buy_one_part(bar)
            elif pending == Action.SELL:
                broker.try_sell(bar)
        # 未成交（停牌/涨跌停）则挂单顺延；成交或 HOLD 则清空
        if pending in (Action.BUY, Action.SELL) and bar.suspended:
            pass  # 顺延，保留 pending
        else:
            pending = Action.HOLD
        # 2. 收盘后产生新决策，挂到下一日
        action = strategy.decide(i)
        if action in (Action.BUY, Action.SELL):
            pending = action
        # 3. 记净值
        equity_curve.append((bar.date, broker.market_value(bar.close)))
    return {"equity_curve": equity_curve, "trades": broker.trades}
```

**注意**：涨跌停导致未成交时的顺延，交由下一轮循环用同一 `pending` 再试。上面简化为"停牌顺延"；涨跌停未成交时 `try_*` 返回 False 但 `pending` 已被清空——需修正：改为根据成交结果决定是否清空。

- [ ] **Step 4: 修正顺延逻辑（涨跌停未成交也顺延）**

将 Step 3 的循环体第 1、2 段替换为：

```python
        executed = True
        if pending == Action.BUY:
            executed = broker.try_buy_one_part(bar) if not bar.suspended else False
        elif pending == Action.SELL:
            executed = broker.try_sell(bar) if not bar.suspended else False
        if pending in (Action.BUY, Action.SELL) and not executed:
            new_action = strategy.decide(i)      # 允许策略撤销/翻转
            pending = new_action if new_action != Action.HOLD else pending  # 顺延
        else:
            pending = strategy.decide(i)
        if pending == Action.HOLD:
            pending = Action.HOLD
```

（保持"未成交则挂单顺延到下一交易日开盘"的语义。）

- [ ] **Step 5: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS

- [ ] **Step 6: 加一条涨停顺延测试并确认**

```python
def test_buy_postponed_on_limit_up():
    from tradingagents.backtest.types import Bar, Action, CostConfig, PositionConfig
    from tradingagents.backtest.broker import Broker
    from tradingagents.backtest.engine import run_loop
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 11, 11, 10),   # 一字涨停，买不进
            _bar("2020-03-04", 10.5, 11, 10.8)]
    class BuyFirst:
        def __init__(self, b): self.b = b
        def decide(self, i): 
            from tradingagents.backtest.types import Action
            return Action.BUY if (i == 0 and not self.b.in_position()) else Action.HOLD
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: BuyFirst(b), broker)
    assert broker.trades[0].date == "2020-03-04"   # 涨停日跳过，顺延成交
```

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add tradingagents/backtest/engine.py tests/backtest/test_engine.py
git commit -m "feat(backtest): 逐日回放主循环含T+1与顺延"
```

