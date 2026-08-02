### Task 2: ST 历史状态落库与按日查询

**Files:**
- Create: `app/services/st_status_service.py`
- Create: `tests/backtest/test_st_status.py`

**Interfaces:**
- Produces: `st_status_service.is_st(symbol, date) -> bool`（按 `YYYY-MM-DD` 判定当日是否 ST），供 `market_rules` 精确涨跌停使用。数据存 MongoDB collection `stock_st_periods`（字段：`symbol`、`start_date`、`end_date`(可空表示至今)、`name`）。

**背景**：tushare `namechange` 返回股票曾用名及生效区间，名称含 `ST`/`*ST` 的区间即 ST 期。

- [ ] **Step 1: 写失败测试** — 区间判定

```python
# tests/backtest/test_st_status.py
from app.services.st_status_service import StStatusService

def test_is_st_within_period(monkeypatch):
    svc = StStatusService()
    # 直接注入内存区间，避开数据库
    svc._periods_cache = {"000001": [{"start_date": "2020-01-01", "end_date": "2020-12-31"}]}
    assert svc.is_st("000001", "2020-06-15") is True
    assert svc.is_st("000001", "2021-06-15") is False
    assert svc.is_st("600000", "2020-06-15") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_st_status.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `StStatusService`**

```python
# app/services/st_status_service.py
"""ST 历史状态服务：按日判定某股是否处于 ST 期。"""
from typing import Dict, List, Optional

class StStatusService:
    def __init__(self):
        self._periods_cache: Dict[str, List[dict]] = {}

    def is_st(self, symbol: str, date: str) -> bool:
        """date: YYYY-MM-DD。区间 end_date 为 None 表示至今。"""
        for p in self._periods_cache.get(symbol, []):
            start = p["start_date"]
            end = p.get("end_date")
            if start <= date and (end is None or date <= end):
                return True
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_st_status.py -v`
Expected: PASS

- [ ] **Step 5: 增加从 tushare 同步 ST 区间并入库/加载**

在 `StStatusService` 增加：

```python
    async def sync_from_tushare(self, symbol: str) -> int:
        """拉 namechange，把含 ST 的曾用名区间写入 stock_st_periods。返回写入区间数。"""
        from app.services.data_sources.tushare_adapter import TushareAdapter
        adapter = TushareAdapter()
        api = adapter._provider.api
        df = api.namechange(ts_code=self._to_ts_code(symbol),
                            fields="name,start_date,end_date")
        periods = []
        for _, r in df.iterrows():
            name = str(r.get("name") or "")
            if "ST" in name:
                periods.append({
                    "symbol": symbol,
                    "start_date": self._fmt(r.get("start_date")),
                    "end_date": self._fmt(r.get("end_date")),  # None if empty
                    "name": name,
                })
        # upsert 到 stock_st_periods（按 symbol+start_date 去重）
        return await self._save_periods(periods)

    async def load(self, symbol: str) -> None:
        """从 stock_st_periods 载入到 _periods_cache。"""
        ...

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        return f"{symbol}.SH" if symbol.startswith("6") else f"{symbol}.SZ"

    @staticmethod
    def _fmt(v) -> Optional[str]:
        s = str(v).strip() if v is not None else ""
        if not s or s in ("None", "nan"):
            return None
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s
```

`_save_periods` 用 pymongo `bulk_write` upsert（`UpdateOne({symbol,start_date}, {$set:...}, upsert=True)`）。

- [ ] **Step 6: 写 `_to_ts_code` / `_fmt` 单测**

```python
def test_to_ts_code():
    from app.services.st_status_service import StStatusService
    assert StStatusService._to_ts_code("600000") == "600000.SH"
    assert StStatusService._to_ts_code("000001") == "000001.SZ"

def test_fmt_date():
    from app.services.st_status_service import StStatusService
    assert StStatusService._fmt("20200101") == "2020-01-01"
    assert StStatusService._fmt("") is None
```

- [ ] **Step 7: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_st_status.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app/services/st_status_service.py tests/backtest/test_st_status.py
git commit -m "feat(backtest): 新增 ST 历史状态同步与按日查询服务"
```

---

## Phase 1：引擎层

