### Task 3: 核心类型 `types.py`

**Files:**
- Create: `tradingagents/backtest/__init__.py`（空）
- Create: `tradingagents/backtest/types.py`
- Test: `tests/backtest/test_types.py`

**Interfaces:**
- Produces: 下列类型供全引擎使用。
  - `class Action(Enum): BUY / SELL / HOLD`
  - `@dataclass Bar`: `date:str, open:float, high:float, low:float, close:float, pre_close:float, volume:float, suspended:bool=False, is_st:bool=False`
  - `@dataclass Trade`: `date:str, side:str('buy'|'sell'), price:float, shares:int, commission:float, stamp_tax:float, transfer_fee:float`
  - `@dataclass CostConfig`: `commission_rate:float=0.00025, min_commission:float=5.0, stamp_tax_rate:float=0.001, transfer_fee_rate:float=0.00001`
  - `@dataclass PositionConfig`: `parts:int=3, reduce_mode:str='reduce_one'`（`'reduce_one'`/`'clear_all'`）
  - `@dataclass BacktestConfig`: `symbol:str, start_date:str, end_date:str, initial_capital:float=100000.0, cost:CostConfig=CostConfig(), position:PositionConfig=PositionConfig()`

- [ ] **Step 1: 写失败测试**

```python
# tests/backtest/test_types.py
from tradingagents.backtest.types import Action, Bar, CostConfig, PositionConfig, BacktestConfig

def test_defaults():
    c = BacktestConfig(symbol="000001", start_date="2020-01-01", end_date="2020-12-31")
    assert c.initial_capital == 100000.0
    assert c.cost.stamp_tax_rate == 0.001
    assert c.position.parts == 3 and c.position.reduce_mode == "reduce_one"
    assert Action.BUY != Action.SELL

def test_bar_defaults():
    b = Bar(date="2020-01-02", open=10, high=11, low=9, close=10.5, pre_close=10, volume=1e6)
    assert b.suspended is False and b.is_st is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_types.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `types.py`**（用 `dataclasses` + `field(default_factory=...)` 处理嵌套默认）

```python
# tradingagents/backtest/types.py
"""回测引擎核心数据类型。"""
from dataclasses import dataclass, field
from enum import Enum

class Action(Enum):
    BUY = "buy"; SELL = "sell"; HOLD = "hold"

@dataclass
class Bar:
    date: str; open: float; high: float; low: float; close: float
    pre_close: float; volume: float
    suspended: bool = False; is_st: bool = False

@dataclass
class Trade:
    date: str; side: str; price: float; shares: int
    commission: float; stamp_tax: float; transfer_fee: float

@dataclass
class CostConfig:
    commission_rate: float = 0.00025; min_commission: float = 5.0
    stamp_tax_rate: float = 0.001; transfer_fee_rate: float = 0.00001

@dataclass
class PositionConfig:
    parts: int = 3; reduce_mode: str = "reduce_one"

@dataclass
class BacktestConfig:
    symbol: str; start_date: str; end_date: str
    initial_capital: float = 100000.0
    cost: CostConfig = field(default_factory=CostConfig)
    position: PositionConfig = field(default_factory=PositionConfig)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_types.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/__init__.py tradingagents/backtest/types.py tests/backtest/test_types.py
git commit -m "feat(backtest): 引擎核心数据类型"
```

