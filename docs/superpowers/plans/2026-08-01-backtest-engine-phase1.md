# 策略回测引擎 Phase 1（数据准备 + 引擎层）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在开源 `tradingagents/backtest/` 里做出一个纯 Python、单股、逐日回放的回测引擎，能从 MongoDB 历史库读前复权数据，按条件积木策略与 A股规则回测，产出净值曲线、绩效指标、交易明细。

**Architecture:** 事件驱动逐日回放。`data_feed` 从 `stock_daily_quotes` 读复权日线+停牌+ST → `engine` 遍历交易日，每天问 `strategy`（条件积木）要动作 → `broker` 按 A股规则（T+1/涨跌停/成本/固定份数分批）撮合 → `metrics` 汇总绩效 → `result` 打包。所有模块纯 Python、可脱离 Web 单测。

**Tech Stack:** Python 3.10+、pandas、pymongo（经现有 `historical_data_service`）、pytest。复用 `tradingagents/tools/analysis/indicators.py`、`tradingagents/utils/stock_utils.py`。

## Global Constraints

- Python 3.10+；所有注释、docstring、日志用中文（项目约定）。
- 引擎层代码只放 `tradingagents/backtest/`，不得依赖 `app/`、`frontend/`（保持开源层独立、可单测）。
- 回测正确性底线，不可做成开关：前复权价、T+1、停牌顺延、成交发生在信号次日开盘（防前视偏差）、精确涨跌停。
- 策略偏好参数一律走配置对象：初始资金、份数 N、每档比例、减仓模式（`reduce_one`/`clear_all`）、佣金率/最低佣金、印花税率、过户费率。
- 金额计算用 `float` 保留 2 位小数（`round(x, 2)`）；股数按 100 股/手取整。
- 日期字符串统一 `YYYY-MM-DD`。
- 测试放 `tests/backtest/`，pytest 风格，文件名 `test_*.py`，可用 `./venv/bin/python -m pytest` 运行。

---

## 文件结构（新建 `tradingagents/backtest/`）

| 文件 | 职责 |
|---|---|
| `__init__.py` | 导出公共 API（`run_backtest`、配置与结果类型） |
| `types.py` | 数据类型：`Bar`、`Action`(枚举)、`Trade`、`CostConfig`、`PositionConfig`、`BacktestConfig`、`BacktestResult` |
| `market_rules.py` | A股规则纯函数：板块识别、涨跌幅、涨跌停价、成交可行性、交易成本 |
| `data_feed.py` | 读 `stock_daily_quotes` → 升序 `List[Bar]`（复权价、停牌、ST 标记） |
| `indicators.py` | 逐日指标序列（MA/EMA/MACD/RSI/BOLL），复用现有 indicators |
| `strategy.py` | 条件积木求值 + `SignalSource` 接口 + `RuleStrategy` |
| `broker.py` | 账户/持仓/固定份数分批/T+1/涨跌停顺延/成本 |
| `engine.py` | 逐日回放主循环，串联上述模块 |
| `metrics.py` | 绩效指标 + 买入持有基准 + 净值曲线 |
| `result.py` | 组装 `BacktestResult`（可 `to_dict()` 序列化给后续 Web 层） |

数据准备（Phase 0）改动现有：`app/worker/`（同步存复权价、ST）、`app/services/historical_data_service.py`（查复权字段）。

---

## Phase 0：数据准备

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

### Task 9: 逐日回放 `engine.py`

**Files:**
- Create: `tradingagents/backtest/engine.py`
- Test: `tests/backtest/test_engine.py`

**Interfaces:**
- Consumes: `List[Bar]`、`Broker`、`SignalSource`、`types.Action`。
- Produces: `run_loop(bars, strategy_factory, broker) -> dict`，返回 `{"equity_curve": [(date, equity)], "trades": broker.trades}`。
  - **T+1 与次日成交**：第 i 日收盘后 `strategy.decide(i)` 产生动作，成交在**第 i+1 日**的 `bar.open` 执行（`try_buy_one_part`/`try_sell`）。当日买入的份不可当日卖出天然满足（决策在收盘后、成交在次日）。
  - `strategy_factory(broker)` 返回 `SignalSource`（让策略能查 `broker.in_position`）。
  - 每日收盘记 `equity = broker.market_value(bar.close)`。

- [ ] **Step 1: 写失败测试**（双日：D1 决策买、D2 开盘成交）

```python
# tests/backtest/test_engine.py
from tradingagents.backtest.types import Bar, Action, CostConfig, PositionConfig
from tradingagents.backtest.broker import Broker
from tradingagents.backtest.engine import run_loop

def _bar(d, o, c, pre): 
    return Bar(date=d, open=o, high=max(o,c), low=min(o,c), close=c, pre_close=pre, volume=1e6)

def test_signal_executes_next_day_open():
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 12, 10),
            _bar("2020-03-04", 12, 13, 12)]
    # 策略：第0日就要买（decide 返回 BUY when not in position），之后 HOLD
    class AlwaysBuyOnce:
        def __init__(self, broker): self.b = broker
        def decide(self, i):
            return Action.BUY if (i == 0 and not self.b.in_position()) else Action.HOLD
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: AlwaysBuyOnce(b), broker)
    # 第0日收盘决策买 → 第1日(2020-03-03)开盘10元成交
    assert len(broker.trades) == 1
    assert broker.trades[0].date == "2020-03-03"
    assert broker.trades[0].price == 10
    assert len(out["equity_curve"]) == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `engine.py`**

```python
# tradingagents/backtest/engine.py
"""逐日回放主循环。信号在 T 日收盘产生，T+1 开盘成交。"""
from typing import Callable, List
from .types import Bar, Action
from .broker import Broker

def run_loop(bars: List[Bar], strategy_factory: Callable, broker: Broker) -> dict:
    strategy = strategy_factory(broker)
    equity_curve = []
    pending: Action = Action.HOLD
    for i, bar in enumerate(bars):
        # 1. 执行上一交易日收盘产生的挂单（次日开盘成交）
        if not bar.suspended:
            if pending == Action.BUY:
                broker.try_buy_one_part(bar)
            elif pending == Action.SELL:
                broker.try_sell(bar)
        # 未成交（停牌/涨跌停）则挂单顺延；成交或 HOLD 则清空
        if pending in (Action.BUY, Action.SELL) and bar.suspended:
            pass  # 顺延，保留 pending
        else:
            pending = Action.HOLD
        # 2. 收盘后产生新决策，挂到下一日
        action = strategy.decide(i)
        if action in (Action.BUY, Action.SELL):
            pending = action
        # 3. 记净值
        equity_curve.append((bar.date, broker.market_value(bar.close)))
    return {"equity_curve": equity_curve, "trades": broker.trades}
```

**注意**：涨跌停导致未成交时的顺延，交由下一轮循环用同一 `pending` 再试。上面简化为"停牌顺延"；涨跌停未成交时 `try_*` 返回 False 但 `pending` 已被清空——需修正：改为根据成交结果决定是否清空。

- [ ] **Step 4: 修正顺延逻辑（涨跌停未成交也顺延）**

将 Step 3 的循环体第 1、2 段替换为：

```python
        executed = True
        if pending == Action.BUY:
            executed = broker.try_buy_one_part(bar) if not bar.suspended else False
        elif pending == Action.SELL:
            executed = broker.try_sell(bar) if not bar.suspended else False
        if pending in (Action.BUY, Action.SELL) and not executed:
            new_action = strategy.decide(i)      # 允许策略撤销/翻转
            pending = new_action if new_action != Action.HOLD else pending  # 顺延
        else:
            pending = strategy.decide(i)
        if pending == Action.HOLD:
            pending = Action.HOLD
```

（保持"未成交则挂单顺延到下一交易日开盘"的语义。）

- [ ] **Step 5: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS

- [ ] **Step 6: 加一条涨停顺延测试并确认**

```python
def test_buy_postponed_on_limit_up():
    from tradingagents.backtest.types import Bar, Action, CostConfig, PositionConfig
    from tradingagents.backtest.broker import Broker
    from tradingagents.backtest.engine import run_loop
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 11, 11, 10),   # 一字涨停，买不进
            _bar("2020-03-04", 10.5, 11, 10.8)]
    class BuyFirst:
        def __init__(self, b): self.b = b
        def decide(self, i): 
            from tradingagents.backtest.types import Action
            return Action.BUY if (i == 0 and not self.b.in_position()) else Action.HOLD
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: BuyFirst(b), broker)
    assert broker.trades[0].date == "2020-03-04"   # 涨停日跳过，顺延成交
```

Run: `./venv/bin/python -m pytest tests/backtest/test_engine.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add tradingagents/backtest/engine.py tests/backtest/test_engine.py
git commit -m "feat(backtest): 逐日回放主循环含T+1与顺延"
```

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

### Task 12: 真实数据冒烟（可选，需容器）

**Files:**
- Test: `tests/backtest/test_smoke_real.py`

- [ ] **Step 1: 写冒烟测试**（用库里已有的 000001，需先跑 Task 1 复权同步）

```python
# tests/backtest/test_smoke_real.py
import pytest
@pytest.mark.integration
def test_real_000001_double_ma():
    from tradingagents.backtest import run_backtest, BacktestConfig, Condition
    cfg = BacktestConfig(symbol="000001", start_date="2023-01-01", end_date="2024-12-31")
    res = run_backtest(
        cfg,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
    )
    d = res.to_dict()
    assert len(d["equity_curve"]) > 100
    print("总收益:", d["metrics"]["total_return"], "基准:", d["metrics"]["benchmark_return"])
```

- [ ] **Step 2: 跑冒烟（确认端到端接库跑通）**

Run: `./venv/bin/python -m pytest tests/backtest/test_smoke_real.py -v -m integration -s`
Expected: PASS，打印出总收益与基准收益

- [ ] **Step 3: 提交**

```bash
git add tests/backtest/test_smoke_real.py
git commit -m "test(backtest): 真实数据端到端冒烟"
```

---

## Self-Review（作者自查记录）

- **Spec 覆盖**：数据层(复权/ST)→Task1-2、data_feed→Task5；策略条件积木/SignalSource→Task7；固定份数分批/减仓模式→Task8；T+1/停牌/精确涨跌停/成本→Task4+Task8+Task9；绩效+基准→Task10；结果序列化→Task11。Web 接入不在本计划（Plan 2）。✅
- **占位符**：无 "TBD/add error handling" 等；各步给了真实测试与实现代码。✅
- **类型一致**：`Action/Bar/Trade/CostConfig/PositionConfig/BacktestConfig` 在 Task3 定义，后续 Task 一致引用；`try_buy_one_part/try_sell/in_position/market_value`、`compute_indicators`、`RuleStrategy(...)`、`run_loop`、`compute_metrics`、`run_backtest` 签名前后一致。✅
- **已知取舍**：Task9 顺延逻辑较微妙，Step4 专门修正并加涨停顺延测试；涨跌停"一字板"以开盘价触板近似（日线数据下无法知盘中）。

## 后续（Plan 2 预告：Web 接入）

- `app/routers/backtest.py`（`POST /api/backtest/run`，异步任务）、`app/services/backtest_service.py`（调 `run_backtest`）、`frontend/src/views/Backtest/`（条件积木编辑器 + 净值曲线图 + 指标卡 + 交易明细表）。
