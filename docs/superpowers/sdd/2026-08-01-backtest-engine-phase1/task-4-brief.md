### Task 4: A股规则 `market_rules.py`

**Files:**
- Create: `tradingagents/backtest/market_rules.py`
- Test: `tests/backtest/test_market_rules.py`

**Interfaces:**
- Consumes: 无（纯函数模块）。
- Produces:
  - `board_of(symbol:str) -> str`：返回 `'main'|'gem'|'star'|'bse'`（主板/创业板/科创板/北交所）
  - `price_limit_pct(symbol:str, is_st:bool) -> float`：涨跌幅，如 0.10/0.05/0.20/0.30
  - `limit_up_price(pre_close, symbol, is_st) -> float` / `limit_down_price(...) -> float`
  - `can_buy_at_open(open_price, pre_close, symbol, is_st) -> bool`（开盘未封涨停可买）
  - `can_sell_at_open(open_price, pre_close, symbol, is_st) -> bool`（开盘未封跌停可卖）
  - `buy_cost(amount:float, cost:CostConfig) -> tuple[float,float,float]`：返回 (佣金, 印花税=0, 过户费)
  - `sell_cost(amount:float, cost:CostConfig) -> tuple[float,float,float]`：返回 (佣金, 印花税, 过户费)

- [ ] **Step 1: 写失败测试**（板块与涨跌幅）

```python
# tests/backtest/test_market_rules.py
from tradingagents.backtest.market_rules import (
    board_of, price_limit_pct, limit_up_price, can_buy_at_open, can_sell_at_open,
)
from tradingagents.backtest.types import CostConfig
from tradingagents.backtest.market_rules import buy_cost, sell_cost

def test_board_of():
    assert board_of("600000") == "main"
    assert board_of("000001") == "main"
    assert board_of("300750") == "gem"
    assert board_of("688111") == "star"
    assert board_of("830799") == "bse"

def test_price_limit_pct():
    assert price_limit_pct("600000", is_st=False) == 0.10
    assert price_limit_pct("600000", is_st=True) == 0.05
    assert price_limit_pct("300750", is_st=True) == 0.20   # 注册制 ST 仍 20%
    assert price_limit_pct("688111", is_st=False) == 0.20
    assert price_limit_pct("830799", is_st=True) == 0.30
```

- [ ] **Step 2: 写失败测试**（涨跌停价与成交可行性、成本）

```python
def test_limit_price_and_tradability():
    # pre_close=10, 主板普通±10% → 涨停11.00 跌停9.00
    assert limit_up_price(10.0, "600000", False) == 11.0
    assert limit_down_price(10.0, "600000", False) == 9.0
    assert can_buy_at_open(11.0, 10.0, "600000", False) is False   # 一字涨停不可买
    assert can_buy_at_open(10.5, 10.0, "600000", False) is True
    assert can_sell_at_open(9.0, 10.0, "600000", False) is False   # 一字跌停不可卖
    assert can_sell_at_open(9.5, 10.0, "600000", False) is True

def test_costs():
    c = CostConfig()
    # 买入 10000 元：佣金 max(10000*0.00025, 5)=5，印花0，过户 10000*0.00001=0.1
    comm, stamp, transfer = buy_cost(10000.0, c)
    assert comm == 5.0 and stamp == 0.0 and round(transfer, 2) == 0.1
    # 卖出 10000 元：佣金5，印花 10000*0.001=10，过户 0.1
    comm, stamp, transfer = sell_cost(10000.0, c)
    assert comm == 5.0 and stamp == 10.0 and round(transfer, 2) == 0.1
```

- [ ] **Step 3: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_market_rules.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 4: 实现 `market_rules.py`**

```python
# tradingagents/backtest/market_rules.py
"""A股交易规则纯函数：板块、涨跌停、成交可行性、交易成本。"""
from .types import CostConfig

def board_of(symbol: str) -> str:
    s = symbol.zfill(6)
    if s.startswith("688"): return "star"
    if s.startswith("300") or s.startswith("301"): return "gem"
    if s.startswith(("8", "9", "43", "83", "87", "92")): return "bse"
    return "main"

def price_limit_pct(symbol: str, is_st: bool) -> float:
    board = board_of(symbol)
    if board in ("gem", "star"): return 0.20   # 注册制 ST 不改幅度
    if board == "bse": return 0.30
    return 0.05 if is_st else 0.10             # 主板

def limit_up_price(pre_close: float, symbol: str, is_st: bool) -> float:
    return round(pre_close * (1 + price_limit_pct(symbol, is_st)), 2)

def limit_down_price(pre_close: float, symbol: str, is_st: bool) -> float:
    return round(pre_close * (1 - price_limit_pct(symbol, is_st)), 2)

def can_buy_at_open(open_price, pre_close, symbol, is_st) -> bool:
    return open_price < limit_up_price(pre_close, symbol, is_st)

def can_sell_at_open(open_price, pre_close, symbol, is_st) -> bool:
    return open_price > limit_down_price(pre_close, symbol, is_st)

def buy_cost(amount: float, cost: CostConfig):
    comm = max(amount * cost.commission_rate, cost.min_commission)
    transfer = amount * cost.transfer_fee_rate
    return round(comm, 2), 0.0, round(transfer, 2)

def sell_cost(amount: float, cost: CostConfig):
    comm = max(amount * cost.commission_rate, cost.min_commission)
    stamp = amount * cost.stamp_tax_rate
    transfer = amount * cost.transfer_fee_rate
    return round(comm, 2), round(stamp, 2), round(transfer, 2)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_market_rules.py -v`
Expected: PASS（全部）

- [ ] **Step 6: 提交**

```bash
git add tradingagents/backtest/market_rules.py tests/backtest/test_market_rules.py
git commit -m "feat(backtest): A股板块/涨跌停/成本规则"
```

