### Task 1: 历史库补前复权价

**Files:**
- Modify: `app/worker/tushare_sync_service.py`（新增复权价同步方法）
- Modify: `app/services/historical_data_service.py`（`_standardize_record` 增加复权字段落库）
- Test: `tests/backtest/test_qfq_sync.py`

**Interfaces:**
- Produces: `stock_daily_quotes` 文档新增字段 `open_qfq/high_qfq/low_qfq/close_qfq`（float，前复权价）。回测层据此读取。

**背景**：tushare 前复权数据用 `pro_bar(ts_code, adj='qfq', freq='D')`。现有 `TushareAdapter.get_kline(code, period='day', adj='qfq')`（`app/services/data_sources/tushare_adapter.py:169`）已封装 `pro_bar`，可复用其取数逻辑。

- [ ] **Step 1: 写失败测试** — 复权字段能被标准化写入

```python
# tests/backtest/test_qfq_sync.py
from app.services.historical_data_service import HistoricalDataService

def test_standardize_record_keeps_qfq_fields():
    svc = HistoricalDataService()
    row = {"trade_date": "20260731", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
           "open_qfq": 8.0, "high_qfq": 8.4, "low_qfq": 7.85, "close_qfq": 8.16}
    rec = svc._standardize_record(row, symbol="000001", market="china_a", data_source="tushare")
    assert rec["close_qfq"] == 8.16
    assert rec["open_qfq"] == 8.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v`
Expected: FAIL（`close_qfq` KeyError 或 None）

- [ ] **Step 3: 在 `_standardize_record` 增加复权字段透传**

在 `historical_data_service.py` 的 `_standardize_record`（约 line 248-320）返回 dict 中追加：

```python
        "open_qfq": self._safe_float(row.get("open_qfq")),
        "high_qfq": self._safe_float(row.get("high_qfq")),
        "low_qfq": self._safe_float(row.get("low_qfq")),
        "close_qfq": self._safe_float(row.get("close_qfq")),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v`
Expected: PASS

- [ ] **Step 5: 在同步 worker 增加复权价拉取与落库方法**

在 `tushare_sync_service.py` 增加方法（供 scheduler 调度，回灌历史）：

```python
    async def sync_historical_qfq(self, symbol: str, start_date: str, end_date: str) -> dict:
        """同步单只股票前复权日线到 stock_daily_quotes。start/end 为 YYYYMMDD。"""
        from app.services.data_sources.tushare_adapter import TushareAdapter
        adapter = TushareAdapter()
        bars = adapter.get_kline(code=symbol, period="day",
                                 limit=99999, adj="qfq")  # pro_bar qfq
        if not bars:
            return {"symbol": symbol, "saved": 0}
        records = []
        for b in bars:
            records.append({
                "trade_date": str(b["time"]).replace("-", "")[:8],
                "open_qfq": b.get("open"), "high_qfq": b.get("high"),
                "low_qfq": b.get("low"), "close_qfq": b.get("close"),
            })
        saved = await self.stock_service.merge_qfq_prices(symbol, records)  # 见下
        return {"symbol": symbol, "saved": saved}
```

并在 `historical_data_service.py` 增加 `merge_qfq_prices(symbol, records)`：按 `symbol+trade_date` 对已有文档 `$set` 复权字段（`bulk_write` + `UpdateOne(upsert=False)`），复用现有 `_execute_bulk_write_with_retry`。

- [ ] **Step 6: 写落库集成测试（跑真实一只股票，需容器在运行）**

```python
# tests/backtest/test_qfq_sync.py （追加）
import pytest, asyncio
@pytest.mark.integration
def test_sync_qfq_writes_fields():
    from app.worker.tushare_sync_service import TushareSyncService
    svc = TushareSyncService()
    asyncio.run(svc.initialize())
    r = asyncio.run(svc.sync_historical_qfq("000001", "20260101", "20260731"))
    assert r["saved"] > 0
```

- [ ] **Step 7: 跑集成测试确认落库**

Run: `./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v -m integration`
Expected: PASS，且 `docker exec tradingagents-mongodb mongo ... db.stock_daily_quotes.findOne({symbol:'000001', close_qfq:{$exists:true}})` 有值

- [ ] **Step 8: 提交**

```bash
git add tests/backtest/test_qfq_sync.py app/worker/tushare_sync_service.py app/services/historical_data_service.py
git commit -m "feat(backtest): 历史库补前复权价字段与同步"
```

