### Task 5: 数据源 `data_feed.py`

**Files:**
- Create: `tradingagents/backtest/data_feed.py`
- Test: `tests/backtest/test_data_feed.py`

**Interfaces:**
- Consumes: `types.Bar`；`st_status_service.StStatusService.is_st`。
- Produces: `load_bars(symbol, start_date, end_date, st_service=None) -> List[Bar]` —— 升序（按日期从早到晚），价格用**前复权**字段（`*_qfq`），`suspended` 由成交量为 0 或缺失日推断，`is_st` 由 `st_service` 按日判定。内部把 async `historical_data_service.get_historical_data` 用 `asyncio.run` 包成同步。

- [ ] **Step 1: 写失败测试**（用假数据源，验证升序 + 复权取价 + ST 标记）

```python
# tests/backtest/test_data_feed.py
from tradingagents.backtest.data_feed import bars_from_records

def test_bars_from_records_sorted_and_qfq():
    # 输入降序（模拟库返回），且含原始价与复权价
    records = [
        {"trade_date": "2020-01-03", "open": 20, "high": 21, "low": 19, "close": 20.5,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.25},
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 0,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
    ]
    class FakeSt:
        def is_st(self, symbol, date): return date == "2020-01-02"
    bars = bars_from_records(records, symbol="000001", st_service=FakeSt())
    assert [b.date for b in bars] == ["2020-01-02", "2020-01-03"]   # 升序
    assert bars[0].close == 10.0        # 用复权价
    assert bars[0].suspended is True     # volume==0 视为停牌
    assert bars[0].is_st is True
    assert bars[1].is_st is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_data_feed.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `data_feed.py`**

```python
# tradingagents/backtest/data_feed.py
"""从历史库加载前复权日线为 Bar 序列。"""
import asyncio
from typing import List, Optional
from .types import Bar

def _to_dash_date(d: str) -> str:
    s = str(d)
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"

def bars_from_records(records: list, symbol: str, st_service=None) -> List[Bar]:
    """把库记录（可能降序）转成升序 Bar 列表，价格取前复权字段。"""
    rows = sorted(records, key=lambda r: _to_dash_date(r["trade_date"]))
    bars: List[Bar] = []
    for r in rows:
        date = _to_dash_date(r["trade_date"])
        vol = r.get("volume") or 0
        is_st = bool(st_service.is_st(symbol, date)) if st_service else False
        bars.append(Bar(
            date=date,
            open=r.get("open_qfq"), high=r.get("high_qfq"),
            low=r.get("low_qfq"), close=r.get("close_qfq"),
            pre_close=r.get("pre_close"), volume=vol,
            suspended=(vol == 0), is_st=is_st,
        ))
    return bars

def load_bars(symbol: str, start_date: str, end_date: str, st_service=None) -> List[Bar]:
    """从 historical_data_service 读数据并转 Bar。缺复权字段则报错。"""
    from app.services.historical_data_service import HistoricalDataService
    svc = HistoricalDataService()
    async def _run():
        await svc.initialize()
        return await svc.get_historical_data(symbol, start_date, end_date,
                                             data_source="tushare", period="daily")
    records = asyncio.run(_run())
    if not records:
        raise ValueError(f"无历史数据：{symbol} {start_date}~{end_date}，请先同步")
    if records[0].get("close_qfq") is None:
        raise ValueError(f"{symbol} 缺前复权价，请先跑复权同步（Task 1）")
    if st_service:
        asyncio.run(st_service.load(symbol))
    return bars_from_records(records, symbol, st_service)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_data_feed.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/backtest/data_feed.py tests/backtest/test_data_feed.py
git commit -m "feat(backtest): 前复权行情加载 data_feed"
```

