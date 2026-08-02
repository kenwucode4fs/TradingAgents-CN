### Task 6: 逐日指标 `indicators.py`

**Files:**
- Create: `tradingagents/backtest/indicators.py`
- Test: `tests/backtest/test_bt_indicators.py`

**Interfaces:**
- Consumes: `List[Bar]`（用其 `close`）。
- Produces: `compute_indicators(bars) -> dict[str, list]` —— 返回与 bars 等长、按日对齐的指标序列，键含：`ma5,ma10,ma20,ma60,ema12,ema26,macd_dif,macd_dea,macd_bar,rsi6,rsi12,rsi14,boll_up,boll_mid,boll_low`。首段不足窗口的置 `None`。

**说明**：优先复用 `tradingagents/tools/analysis/indicators.py`；若其接口不便按日对齐，则在本模块用 pandas 直接计算（MA=rolling mean，EMA=ewm，RSI=经典公式，BOLL=20 日均线±2 倍标准差）。

- [ ] **Step 1: 写失败测试**（用可手算的序列）

```python
# tests/backtest/test_bt_indicators.py
from tradingagents.backtest.types import Bar
from tradingagents.backtest.indicators import compute_indicators

def _bars(closes):
    return [Bar(date=f"2020-01-{i+1:02d}", open=c, high=c, low=c, close=c,
                pre_close=c, volume=100) for i, c in enumerate(closes)]

def test_ma5():
    bars = _bars([1, 2, 3, 4, 5, 6])
    ind = compute_indicators(bars)
    assert ind["ma5"][0] is None            # 不足5日
    assert ind["ma5"][4] == 3.0             # (1+2+3+4+5)/5
    assert ind["ma5"][5] == 4.0             # (2+3+4+5+6)/5
    assert len(ind["ma5"]) == len(bars)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_bt_indicators.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `indicators.py`**（pandas 计算，按日对齐）

```python
# tradingagents/backtest/indicators.py
"""逐日技术指标序列，与 bars 等长对齐。"""
import pandas as pd
from typing import List
from .types import Bar

def _rsi(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - 100 / (1 + rs)

def compute_indicators(bars: List[Bar]) -> dict:
    close = pd.Series([b.close for b in bars], dtype="float64")
    out = {}
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = close.rolling(n).mean()
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["ema12"], out["ema26"] = ema12, ema26
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    out["macd_dif"], out["macd_dea"], out["macd_bar"] = dif, dea, (dif - dea) * 2
    for n in (6, 12, 14):
        out[f"rsi{n}"] = _rsi(close, n)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_mid"], out["boll_up"], out["boll_low"] = mid, mid + 2 * std, mid - 2 * std
    # 转 list，NaN -> None
    return {k: [None if pd.isna(v) else float(v) for v in s] for k, s in out.items()}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_bt_indicators.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/indicators.py tests/backtest/test_bt_indicators.py
git commit -m "feat(backtest): 逐日技术指标序列"
```

