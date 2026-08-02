### Task 10: 绩效 `metrics.py`

**Files:**
- Create: `tradingagents/backtest/metrics.py`
- Test: `tests/backtest/test_metrics.py`

**Interfaces:**
- Consumes: `equity_curve:List[tuple[str,float]]`、`initial_capital`、`bars`（算买入持有基准）、`trades`。
- Produces: `compute_metrics(equity_curve, initial_capital, bars, trades) -> dict`，键：`total_return`、`annual_return`、`max_drawdown`、`sharpe`、`win_rate`、`profit_loss_ratio`、`trade_count`、`benchmark_return`（买入持有）、`benchmark_curve:List[tuple]`。

**公式**：日收益率 `r_t = equity_t/equity_{t-1}-1`；年化 `=(1+total_return)**(252/n)-1`；最大回撤 `=max(1 - equity_t/peak_t)`；夏普 `=mean(r)/std(r)*sqrt(252)`（无风险利率取 0）；买入持有 `=close_qfq[末]/close_qfq[首]-1`；胜率/盈亏比按"买-卖配对"的每笔盈亏统计。

- [ ] **Step 1: 写失败测试**（已知净值序列）

```python
# tests/backtest/test_metrics.py
from tradingagents.backtest.metrics import compute_metrics
from tradingagents.backtest.types import Bar

def _bars(closes):
    return [Bar(date=f"2020-04-{i+1:02d}", open=c, high=c, low=c, close=c, pre_close=c, volume=1)
            for i, c in enumerate(closes)]

def test_total_return_and_drawdown():
    curve = [("d1", 100000), ("d2", 110000), ("d3", 99000), ("d4", 121000)]
    m = compute_metrics(curve, 100000, _bars([10, 11, 9.9, 12.1]), trades=[])
    assert round(m["total_return"], 4) == 0.21            # 121000/100000-1
    # 最大回撤：从110000跌到99000 → 1-99000/110000=0.10
    assert round(m["max_drawdown"], 4) == 0.10
    # 基准：买入持有 12.1/10-1 = 0.21
    assert round(m["benchmark_return"], 4) == 0.21
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_metrics.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `metrics.py`**

```python
# tradingagents/backtest/metrics.py
"""绩效指标与买入持有基准。"""
import math
from typing import List, Tuple

def compute_metrics(equity_curve: List[Tuple[str, float]], initial_capital: float,
                    bars, trades) -> dict:
    equities = [e for _, e in equity_curve]
    n = len(equities)
    total_return = equities[-1] / initial_capital - 1 if n else 0.0
    # 日收益
    rets = [equities[i] / equities[i-1] - 1 for i in range(1, n)]
    # 最大回撤
    peak = -math.inf; mdd = 0.0
    for e in equities:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)
    # 年化 & 夏普
    annual = (1 + total_return) ** (252 / n) - 1 if n > 1 else 0.0
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std * math.sqrt(252)) if std > 0 else 0.0
    else:
        sharpe = 0.0
    # 基准：买入持有（用复权收盘）
    closes = [b.close for b in bars]
    benchmark_return = closes[-1] / closes[0] - 1 if closes else 0.0
    benchmark_curve = [(bars[i].date, initial_capital * closes[i] / closes[0])
                       for i in range(len(bars))] if closes else []
    # 每笔盈亏（买-卖配对，FIFO 简化：一买对一卖）
    wins, losses, pnl_pos, pnl_neg = 0, 0, 0.0, 0.0
    buy_stack = []
    for t in trades:
        if t.side == "buy":
            buy_stack.append(t)
        elif t.side == "sell" and buy_stack:
            b = buy_stack.pop(0)
            pnl = (t.price - b.price) * t.shares - t.commission - t.stamp_tax - t.transfer_fee - b.commission - b.transfer_fee
            if pnl >= 0: wins += 1; pnl_pos += pnl
            else: losses += 1; pnl_neg += -pnl
    closed = wins + losses
    win_rate = wins / closed if closed else 0.0
    profit_loss_ratio = (pnl_pos / wins) / (pnl_neg / losses) if wins and losses else 0.0
    return {
        "total_return": total_return, "annual_return": annual,
        "max_drawdown": mdd, "sharpe": sharpe, "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio, "trade_count": len(trades),
        "benchmark_return": benchmark_return, "benchmark_curve": benchmark_curve,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/metrics.py tests/backtest/test_metrics.py
git commit -m "feat(backtest): 绩效指标与买入持有基准"
```

