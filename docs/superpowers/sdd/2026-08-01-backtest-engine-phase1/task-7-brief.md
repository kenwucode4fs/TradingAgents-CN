### Task 7: 策略 `strategy.py`（条件积木 + 信号接口）

**Files:**
- Create: `tradingagents/backtest/strategy.py`
- Test: `tests/backtest/test_strategy.py`

**Interfaces:**
- Consumes: `indicators.compute_indicators` 的输出；`types.Action`。
- Produces:
  - `class SignalSource(ABC)`: `decide(i:int) -> Action`（第 i 个交易日的动作）
  - `class Condition`: `{left:str, op:str, right}`，`op ∈ {'>','<','cross_up','cross_down'}`，`right` 为数字或另一指标名
  - `class RuleStrategy(SignalSource)`: `__init__(bars, buy_rules:list[Condition], buy_logic:str, sell_rules, sell_logic, in_position_fn)`；`buy_logic/sell_logic ∈ {'AND','OR'}`；`in_position_fn(i)->bool` 由 broker 提供当前是否持仓。`decide(i)`：持仓时优先判卖出条件→SELL，否则判买入条件→BUY，都不满足→HOLD。
  - `cross_up(series, i)` / `cross_down(series, i)`：金叉/死叉辅助（`series[i-1]<=other[i-1]` 且 `series[i]>other[i]`）。

- [ ] **Step 1: 写失败测试**（比较与金叉、AND/OR）

```python
# tests/backtest/test_strategy.py
from tradingagents.backtest.types import Bar, Action
from tradingagents.backtest.strategy import RuleStrategy, Condition

def _bars(closes):
    return [Bar(date=f"2020-02-{i+1:02d}", open=c, high=c, low=c, close=c,
                pre_close=c, volume=100) for i, c in enumerate(closes)]

def test_rsi_threshold_buy():
    bars = _bars([10, 9, 8, 7, 6, 5, 4, 3])   # 持续下跌 → RSI 低
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("rsi6", "<", 30)], buy_logic="AND",
        sell_rules=[Condition("rsi6", ">", 70)], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    # 末日 RSI6 应很低 → 买入
    assert strat.decide(len(bars) - 1) == Action.BUY

def test_ma_cross_up_buy():
    # 构造 MA5 上穿 MA20 的形态：先跌后强涨
    closes = [10]*20 + [11, 13, 15, 17, 19]
    bars = _bars(closes)
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    actions = [strat.decide(i) for i in range(len(bars))]
    assert Action.BUY in actions
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_strategy.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `strategy.py`**

```python
# tradingagents/backtest/strategy.py
"""条件积木策略与通用信号接口。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Callable, Union
from .types import Action
from .indicators import compute_indicators

@dataclass
class Condition:
    left: str; op: str; right: Union[str, float]

class SignalSource(ABC):
    @abstractmethod
    def decide(self, i: int) -> Action: ...

def _val(ind: dict, name: str, i: int):
    return ind[name][i] if name in ind else None

class RuleStrategy(SignalSource):
    def __init__(self, bars, buy_rules: List[Condition], buy_logic: str,
                 sell_rules: List[Condition], sell_logic: str,
                 in_position_fn: Callable[[int], bool]):
        self.ind = compute_indicators(bars)
        self.close = [b.close for b in bars]
        self.buy_rules, self.buy_logic = buy_rules, buy_logic
        self.sell_rules, self.sell_logic = sell_rules, sell_logic
        self.in_position = in_position_fn

    def _series(self, name, i):
        if name == "close":
            return self.close[i]
        return _val(self.ind, name, i)

    def _eval_one(self, c: Condition, i: int) -> bool:
        left_now = self._series(c.left, i)
        if left_now is None:
            return False
        if c.op in ("cross_up", "cross_down"):
            if i == 0:
                return False
            left_prev = self._series(c.left, i - 1)
            right_now = self._series(c.right, i)
            right_prev = self._series(c.right, i - 1)
            if None in (left_prev, right_now, right_prev):
                return False
            if c.op == "cross_up":
                return left_prev <= right_prev and left_now > right_now
            return left_prev >= right_prev and left_now < right_now
        right = self._series(c.right, i) if isinstance(c.right, str) else c.right
        if right is None:
            return False
        return left_now > right if c.op == ">" else left_now < right

    def _eval_group(self, rules, logic, i) -> bool:
        if not rules:
            return False
        results = [self._eval_one(c, i) for c in rules]
        return all(results) if logic == "AND" else any(results)

    def decide(self, i: int) -> Action:
        if self.in_position(i):
            if self._eval_group(self.sell_rules, self.sell_logic, i):
                return Action.SELL
        else:
            if self._eval_group(self.buy_rules, self.buy_logic, i):
                return Action.BUY
        return Action.HOLD
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_strategy.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/strategy.py tests/backtest/test_strategy.py
git commit -m "feat(backtest): 条件积木策略与信号接口"
```

