### Task 11: 顶层编排 `result.py` + `run_backtest` + 端到端

**Files:**
- Create: `tradingagents/backtest/result.py`
- Modify: `tradingagents/backtest/__init__.py`（导出 `run_backtest`）
- Test: `tests/backtest/test_end_to_end.py`

**Interfaces:**
- Consumes: 全部上述模块。
- Produces:
  - `@dataclass BacktestResult`: `config, equity_curve, benchmark_curve, trades, metrics`；`to_dict() -> dict`（供 Web 层序列化）
  - `run_backtest(config: BacktestConfig, buy_rules, buy_logic, sell_rules, sell_logic, bars=None, st_service=None) -> BacktestResult`：`bars=None` 时用 `data_feed.load_bars` 从库取；否则用传入 bars（便于测试）。内部构造 `Broker`、`RuleStrategy`（`strategy_factory=lambda broker: RuleStrategy(bars, ..., in_position_fn=lambda i: broker.in_position())`）、`run_loop`、`compute_metrics`。

- [ ] **Step 1: 写失败的端到端测试**（构造行情 + 双均线，注入 bars，不碰数据库）

```python
# tests/backtest/test_end_to_end.py
from tradingagents.backtest import run_backtest
from tradingagents.backtest.types import Bar, BacktestConfig, PositionConfig
from tradingagents.backtest.strategy import Condition

def _bars(closes):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(date=f"2021-01-{i+1:02d}", open=c, high=c, low=c, close=c,
                       pre_close=prev, volume=1e6))
        prev = c
    return out

def test_double_ma_runs_and_reports():
    closes = [10]*20 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10]
    bars = _bars(closes)
    cfg = BacktestConfig(symbol="600000", start_date="2021-01-01", end_date="2021-02-01",
                         initial_capital=100000, position=PositionConfig(parts=1))
    res = run_backtest(
        cfg,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
        bars=bars,
    )
    d = res.to_dict()
    assert "metrics" in d and "equity_curve" in d
    assert d["metrics"]["trade_count"] >= 1
    assert len(d["equity_curve"]) == len(bars)
    assert "benchmark_return" in d["metrics"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_end_to_end.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `result.py` 与 `run_backtest`**

```python
# tradingagents/backtest/result.py
"""回测结果组装与序列化，以及顶层 run_backtest。"""
from dataclasses import dataclass, asdict
from typing import List, Optional
from .types import BacktestConfig
from .broker import Broker
from .strategy import RuleStrategy
from .engine import run_loop
from .metrics import compute_metrics

@dataclass
class BacktestResult:
    config: BacktestConfig
    equity_curve: list
    benchmark_curve: list
    trades: list
    metrics: dict

    def to_dict(self) -> dict:
        return {
            "config": asdict(self.config),
            "equity_curve": self.equity_curve,
            "benchmark_curve": self.benchmark_curve,
            "trades": [asdict(t) for t in self.trades],
            "metrics": self.metrics,
        }

def run_backtest(config: BacktestConfig, buy_rules, buy_logic, sell_rules, sell_logic,
                 bars: Optional[List] = None, st_service=None) -> BacktestResult:
    if bars is None:
        from .data_feed import load_bars
        bars = load_bars(config.symbol, config.start_date, config.end_date, st_service)
    broker = Broker(config.initial_capital, config.cost, config.position, config.symbol)
    def factory(bk):
        return RuleStrategy(bars, buy_rules, buy_logic, sell_rules, sell_logic,
                            in_position_fn=lambda i: bk.in_position())
    out = run_loop(bars, factory, broker)
    metrics = compute_metrics(out["equity_curve"], config.initial_capital, bars, broker.trades)
    return BacktestResult(
        config=config, equity_curve=out["equity_curve"],
        benchmark_curve=metrics.pop("benchmark_curve"),
        trades=broker.trades, metrics=metrics,
    )
```

在 `tradingagents/backtest/__init__.py` 导出：

```python
from .result import run_backtest, BacktestResult
from .types import (Action, Bar, Trade, CostConfig, PositionConfig, BacktestConfig)
from .strategy import Condition, RuleStrategy, SignalSource
__all__ = ["run_backtest", "BacktestResult", "Action", "Bar", "Trade",
           "CostConfig", "PositionConfig", "BacktestConfig",
           "Condition", "RuleStrategy", "SignalSource"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_end_to_end.py -v`
Expected: PASS

- [ ] **Step 5: 跑全量回测测试套件**

Run: `./venv/bin/python -m pytest tests/backtest/ -v`
Expected: 全部 PASS（不含 `-m integration` 的需库测试）

- [ ] **Step 6: 提交**

```bash
git add tradingagents/backtest/result.py tradingagents/backtest/__init__.py tests/backtest/test_end_to_end.py
git commit -m "feat(backtest): 顶层 run_backtest 与结果序列化"
```

