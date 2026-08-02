### Task 8: 账户与撮合 `broker.py`

**Files:**
- Create: `tradingagents/backtest/broker.py`
- Test: `tests/backtest/test_broker.py`

**Interfaces:**
- Consumes: `types`（Bar/Trade/CostConfig/PositionConfig/Action）；`market_rules`。
- Produces: `class Broker`：
  - `__init__(initial_capital, cost:CostConfig, position:PositionConfig, symbol:str)`
  - 状态：`cash:float`、`shares:int`、`held_parts:int`、`trades:List[Trade]`、`part_shares:list[int]`（每档买入股数，用于减一档）
  - `in_position() -> bool`
  - `try_buy_one_part(bar:Bar) -> bool`：按 A股规则在 `bar.open` 买一档；停牌/涨停/资金不足/已满仓则不成交返回 False
  - `try_sell(bar:Bar) -> bool`：按 `reduce_mode` 减一档或全清；停牌/跌停/无持仓则不成交
  - `market_value(price:float) -> float`：`cash + shares*price`
  - `buyable_shares_for_part(price) -> int`：单档资金可买股数（按 100 取整）

**规则**：一档目标金额 = `initial_capital / parts`。买入股数 = `floor(min(part_amount, cash_available) / price / 100) * 100`，成交额=股数×price，扣 `buy_cost`。卖出减一档 = 弹出 `part_shares` 最后一档股数（`clear_all` 则全部），成交额扣 `sell_cost`。

- [ ] **Step 1: 写失败测试**（买一档 + 成本 + 满仓 + T+1 由 engine 控制此处只测单步）

```python
# tests/backtest/test_broker.py
from tradingagents.backtest.types import Bar, CostConfig, PositionConfig
from tradingagents.backtest.broker import Broker

def _bar(o, pre, vol=1e6, st=False, susp=False):
    return Bar(date="2020-03-02", open=o, high=o, low=o, close=o,
               pre_close=pre, volume=vol, suspended=susp, is_st=st)

def test_buy_one_part_and_cost():
    b = Broker(initial_capital=100000, cost=CostConfig(),
               position=PositionConfig(parts=2), symbol="600000")
    ok = b.try_buy_one_part(_bar(o=10.0, pre=10.0))   # 一档 5万，10元 → 4900股(取整100)
    assert ok is True
    assert b.shares == 4900          # floor(50000/10/100)*100
    assert b.held_parts == 1
    # 现金 = 10万 - 成交额49000 - 佣金max(49000*0.00025,5)=12.25 - 过户0.49
    assert round(b.cash, 2) == round(100000 - 49000 - 12.25 - 0.49, 2)

def test_cannot_buy_on_limit_up():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    assert b.try_buy_one_part(_bar(o=11.0, pre=10.0)) is False   # 涨停
    assert b.shares == 0

def test_cannot_buy_when_suspended():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    assert b.try_buy_one_part(_bar(o=10.0, pre=10.0, susp=True)) is False

def test_sell_reduce_one():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2, reduce_mode="reduce_one"), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))   # 两档
    assert b.held_parts == 2
    sold = b.try_sell(_bar(o=12.0, pre=11.0))    # 减一档
    assert sold is True and b.held_parts == 1

def test_sell_clear_all():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2, reduce_mode="clear_all"), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_sell(_bar(o=12.0, pre=11.0))
    assert b.shares == 0 and b.held_parts == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_broker.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `broker.py`**

```python
# tradingagents/backtest/broker.py
"""账户、持仓、固定份数分批撮合，含 A股成交可行性与成本。"""
import math
from typing import List
from .types import Bar, Trade, CostConfig, PositionConfig
from . import market_rules as mr

class Broker:
    def __init__(self, initial_capital: float, cost: CostConfig,
                 position: PositionConfig, symbol: str):
        self.cash = float(initial_capital)
        self.initial_capital = float(initial_capital)
        self.cost = cost; self.position = position; self.symbol = symbol
        self.shares = 0; self.held_parts = 0
        self.part_shares: List[int] = []
        self.trades: List[Trade] = []

    def in_position(self) -> bool:
        return self.shares > 0

    def market_value(self, price: float) -> float:
        return round(self.cash + self.shares * price, 2)

    def _part_amount(self) -> float:
        return self.initial_capital / self.position.parts

    def try_buy_one_part(self, bar: Bar) -> bool:
        if bar.suspended or self.held_parts >= self.position.parts:
            return False
        if not mr.can_buy_at_open(bar.open, bar.pre_close, self.symbol, bar.is_st):
            return False
        budget = min(self._part_amount(), self.cash)
        lots = math.floor(budget / bar.open / 100)
        shares = lots * 100
        if shares <= 0:
            return False
        amount = shares * bar.open
        comm, stamp, transfer = mr.buy_cost(amount, self.cost)
        total = amount + comm + transfer
        if total > self.cash:
            shares -= 100; amount = shares * bar.open
            if shares <= 0:
                return False
            comm, stamp, transfer = mr.buy_cost(amount, self.cost)
            total = amount + comm + transfer
        self.cash = round(self.cash - total, 2)
        self.shares += shares; self.held_parts += 1
        self.part_shares.append(shares)
        self.trades.append(Trade(bar.date, "buy", bar.open, shares, comm, stamp, transfer))
        return True

    def try_sell(self, bar: Bar) -> bool:
        if self.shares <= 0 or bar.suspended:
            return False
        if not mr.can_sell_at_open(bar.open, bar.pre_close, self.symbol, bar.is_st):
            return False
        if self.position.reduce_mode == "clear_all":
            sell_shares = self.shares
        else:
            sell_shares = self.part_shares[-1] if self.part_shares else self.shares
        amount = sell_shares * bar.open
        comm, stamp, transfer = mr.sell_cost(amount, self.cost)
        self.cash = round(self.cash + amount - comm - stamp - transfer, 2)
        self.shares -= sell_shares
        if self.position.reduce_mode == "clear_all":
            self.held_parts = 0; self.part_shares = []
        else:
            self.held_parts = max(0, self.held_parts - 1)
            if self.part_shares:
                self.part_shares.pop()
        self.trades.append(Trade(bar.date, "sell", bar.open, sell_shares, comm, stamp, transfer))
        return True
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_broker.py -v`
Expected: PASS（全部 5 条）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/broker.py tests/backtest/test_broker.py
git commit -m "feat(backtest): 账户与固定份数分批撮合"
```

