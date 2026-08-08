# 组合回测（子项目 2b）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增「组合回测」能力——按月度调仓、每个调仓日用当时因子截面重选等权 TopN、长期持有,产出组合净值曲线 vs 沪深300 + 绩效 + 调仓明细。

**Architecture:** 开源组合引擎 `tradingagents/portfolio/`(逐月调仓纯函数,防前视/防幸存者偏差,复用 2a `score_universe` 选股 + 阶段① `market_rules` 成本);历史数据回填(月末 daily_basic → `stock_monthly_basic`、沪深300 → `index_daily_quotes`);后端 `app/services/portfolio_backtest_service.py` + `app/routers/portfolio_backtest.py` 异步(复用阶段①/2a 的属主校验 + 主循环预取避跨事件循环坑);前端 `frontend/src/views/PortfolioBacktest/` 复用 2a `FactorConfig`。

**Tech Stack:** Python(纯函数引擎 + FastAPI 异步)、MongoDB(Motor)、tushare(daily_basic/index_daily 回填)、Vue 3 + Element Plus + vue-echarts、Docker。

## Global Constraints

- **每完成一个任务先测试通过再 git 提交**;**不为让测试通过而改测试断言**(改实现)。
- 引擎层 `tradingagents/portfolio/` 是**开源纯函数层**,不触库、不 import `app.*`;数据由调用方(service)预取注入。
- **trade_date 统一 "YYYY-MM-DD" 带横线**(全库 `stock_daily_quotes` 就是这个格式;回填 daily_basic/index_daily 时 tushare 返回 "YYYYMMDD" 必须转成带横线再落库;做字符串日期比较时格式必须对齐——这是 2a 踩过的坑)。
- 股票代码用 **6 位 `code`/`symbol`**("000001",与 `stock_daily_quotes.symbol`、`stock_monthly_basic.code` 一致);tushare 的 ts_code("000001.SZ")要去后缀。
- **防前视偏差**:每个调仓日 D 只能用 `trade_date <= D` 的量价数据和 D 月末的估值截面,严禁用 D 之后的数据。
- **防幸存者偏差**:候选池 = D 月末 `stock_monthly_basic` 有记录的股票(当时活跃,含后退市的),**绝不用** `stock_screening_view`(最新截面、无退市股)。
- 后端异步复用阶段①/2a:状态 `running`/`done`/`failed`;status/result 属主校验非本人 **404**;异步 IO 在主循环 `await` 预取,`run_in_executor` 只跑纯计算。
- 集合:`stock_monthly_basic`、`index_daily_quotes`、`portfolio_backtest_tasks`、`portfolio_backtest_results`。
- 前端 `request` 封装 baseURL 空、路径带 `/api`;API 类型定义准确(不留 2a 那种类型债)。
- 复用:`tradingagents/factor.score_universe`、`tradingagents/backtest/market_rules.buy_cost/sell_cost`、`tradingagents/backtest/types.CostConfig`。
- 授权:`tradingagents/portfolio/` 开源;`app`/`frontend` 专有。

---

## 文件结构

- `app/worker/portfolio_data_sync.py` — 月末 daily_basic 回填 + 沪深300 回填(复用 tushare_adapter)
- `tradingagents/portfolio/rebalance.py` — 等权目标 + 调仓 diff → 买卖清单(纯函数)
- `tradingagents/portfolio/metrics.py` — 组合绩效(总收益/年化/回撤/夏普/超额/换手)
- `tradingagents/portfolio/engine.py` — `run_portfolio_backtest` 逐月调仓主循环(防前视/停牌退市/T+1/每日净值)
- `tradingagents/portfolio/__init__.py` — 导出 `run_portfolio_backtest`、`PortfolioConfig`
- `app/services/portfolio_backtest_service.py` — 主循环预取 + run_in_executor + 落库 + 状态
- `app/routers/portfolio_backtest.py` — run/status/result/history + 属主校验
- `app/main.py` — 注册路由(Modify)
- `tests/portfolio/` — 引擎与后端测试
- `frontend/src/api/portfolioBacktest.ts`、`frontend/src/views/PortfolioBacktest/index.vue` + `components/`(EquityVsBenchmark.vue、PortfolioMetrics.vue、RebalanceTable.vue)
- `frontend/src/router/index.ts`、`frontend/src/components/Layout/SidebarMenu.vue`(Modify)

---

### Task 1: 月末 daily_basic 回填 → `stock_monthly_basic`

**Files:**
- Create: `app/worker/portfolio_data_sync.py`
- Test: `tests/portfolio/test_data_sync.py`

**Interfaces:**
- Consumes: `app/services/data_sources/tushare_adapter.py` 的 `TushareAdapter().get_daily_basic(trade_date)`(返回 DataFrame,含 `ts_code`、`pe`、`pb`、`total_mv`;trade_date 入参格式 "YYYYMMDD")。
- Produces:
  - `def month_end_trade_dates(db, start: str, end: str) -> list[str]`:从 `stock_daily_quotes` 的 distinct trade_date(格式 "YYYY-MM-DD")取 [start,end] 内每月最后一个交易日,返回升序 "YYYY-MM-DD" 列表。
  - `async def sync_monthly_basic(db, start: str, end: str) -> int`:对每个月末交易日拉 daily_basic,转换后 upsert 到 `stock_monthly_basic`(文档 `{code, trade_date, pe, pb, total_mv}`,code 去 ts_code 后缀,trade_date 转 "YYYY-MM-DD"),返回写入条数。

- [ ] **Step 1: 写失败测试(月末交易日提取,纯逻辑,可注入 trade_date 列表)**

```python
# tests/portfolio/test_data_sync.py
from app.worker.portfolio_data_sync import _month_end_dates


def test_month_end_dates_picks_last_trading_day_per_month():
    # 注入若干交易日(YYYY-MM-DD),应每月取最后一个
    dates = ["2024-01-05", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-15"]
    assert _month_end_dates(dates, "2024-01-01", "2024-03-31") == ["2024-01-31", "2024-02-29", "2024-03-15"]


def test_month_end_dates_respects_range():
    dates = ["2023-12-29", "2024-01-31", "2024-02-29"]
    assert _month_end_dates(dates, "2024-01-01", "2024-01-31") == ["2024-01-31"]
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/portfolio/test_data_sync.py -v`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现 `portfolio_data_sync.py`**

```python
# app/worker/portfolio_data_sync.py
"""组合回测历史数据回填:月末 daily_basic + 沪深300 指数。trade_date 统一 "YYYY-MM-DD"。"""
from typing import List


def _to_dash(d: str) -> str:
    """tushare 的 "YYYYMMDD" → "YYYY-MM-DD";已带横线则原样。"""
    s = str(d)
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _month_end_dates(all_trade_dates: List[str], start: str, end: str) -> List[str]:
    """从升序交易日(YYYY-MM-DD)取 [start,end] 内每月最后一个交易日。"""
    in_range = sorted(d for d in all_trade_dates if start <= d <= end)
    last_of_month = {}
    for d in in_range:
        last_of_month[d[:7]] = d  # 键 "YYYY-MM",后来的覆盖前面的 → 该月最后一个
    return [last_of_month[k] for k in sorted(last_of_month)]


async def month_end_trade_dates(db, start: str, end: str) -> List[str]:
    dates = await db.stock_daily_quotes.distinct("trade_date", {"symbol": "000001"})
    return _month_end_dates([str(d) for d in dates], start, end)


async def sync_monthly_basic(db, start: str, end: str) -> int:
    from app.services.data_sources.tushare_adapter import TushareAdapter
    adapter = TushareAdapter()
    ends = await month_end_trade_dates(db, start, end)
    written = 0
    for d in ends:
        tushare_date = d.replace("-", "")  # tushare 要 "YYYYMMDD"
        df = adapter.get_daily_basic(tushare_date)
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            code = str(r["ts_code"]).split(".")[0]  # 去后缀 → 6 位
            doc = {"code": code, "trade_date": d,
                   "pe": _num(r.get("pe")), "pb": _num(r.get("pb")), "total_mv": _num(r.get("total_mv"))}
            await db.stock_monthly_basic.update_one(
                {"code": code, "trade_date": d}, {"$set": doc}, upsert=True)
            written += 1
    return written


def _num(v):
    try:
        import pandas as pd
        return None if v is None or pd.isna(v) else float(v)
    except (ValueError, TypeError):
        return None
```

（如 `get_daily_basic` 的 fields 默认不含 pe/pb,回填前确认 adapter 传的 `fields` 含 `ts_code,pe,pb,total_mv`;若 adapter 写死了 fields,在本文件里改成直接调 `adapter._provider.api.daily_basic(trade_date=..., fields="ts_code,pe,pb,total_mv")`。)

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_data_sync.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add app/worker/portfolio_data_sync.py tests/portfolio/test_data_sync.py
git commit -m "feat(portfolio): 月末daily_basic回填(trade_date统一YYYY-MM-DD)"
```

---

### Task 2: 沪深300 指数回填 → `index_daily_quotes`

**Files:**
- Modify: `app/worker/portfolio_data_sync.py`
- Test: `tests/portfolio/test_data_sync.py`(追加)

**Interfaces:**
- Produces: `async def sync_benchmark_index(db, ts_code: str, start: str, end: str) -> int`:拉 tushare `index_daily`(通过 `TushareAdapter()._provider.api.index_daily(ts_code=ts_code, start_date=..., end_date=...)`,入参日期 "YYYYMMDD"),转换后 upsert 到 `index_daily_quotes`(文档 `{ts_code, trade_date, close}`,trade_date 转 "YYYY-MM-DD"),返回写入条数。

- [ ] **Step 1: 写失败测试(转换纯逻辑)**

```python
# 追加到 tests/portfolio/test_data_sync.py
from app.worker.portfolio_data_sync import _to_dash

def test_to_dash_converts_tushare_date():
    assert _to_dash("20240131") == "2024-01-31"
    assert _to_dash("2024-01-31") == "2024-01-31"  # 幂等
```

- [ ] **Step 2: 运行确认失败/通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_data_sync.py::test_to_dash_converts_tushare_date -v`
Expected: `_to_dash` 已在 Task 1 定义则直接 PASS;本任务主要新增 `sync_benchmark_index`(下步)。

- [ ] **Step 3: 实现 `sync_benchmark_index`（追加到 portfolio_data_sync.py）**

```python
async def sync_benchmark_index(db, ts_code: str, start: str, end: str) -> int:
    from app.services.data_sources.tushare_adapter import TushareAdapter
    api = TushareAdapter()._provider.api
    df = api.index_daily(ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
    if df is None or df.empty:
        return 0
    written = 0
    for _, r in df.iterrows():
        doc = {"ts_code": ts_code, "trade_date": _to_dash(r["trade_date"]), "close": float(r["close"])}
        await db.index_daily_quotes.update_one(
            {"ts_code": ts_code, "trade_date": doc["trade_date"]}, {"$set": doc}, upsert=True)
        written += 1
    return written
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_data_sync.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/worker/portfolio_data_sync.py tests/portfolio/test_data_sync.py
git commit -m "feat(portfolio): 沪深300指数回填index_daily_quotes"
```

---

### Task 3: 调仓纯函数 `rebalance.py`

**Files:**
- Create: `tradingagents/portfolio/rebalance.py`
- Create: `tradingagents/portfolio/__init__.py`（占位,Task 6 补 run_portfolio_backtest）
- Test: `tests/portfolio/test_rebalance.py`

**Interfaces:**
- Consumes: `tradingagents/backtest/market_rules.buy_cost(amount, cost)`/`sell_cost(amount, cost)`(各返回三元组,和为该笔费用);`CostConfig`。
- Produces:
  - `compute_rebalance(target_codes: list[str], holdings: dict[str,int], prices: dict[str,float], cash: float, cost) -> dict`:
    - `target_codes`:本次目标持仓(等权,能成交的);`holdings`:当前 `{code: shares}`;`prices`:各 code 的成交价(次日开盘价);`cash`:当前现金。
    - 逻辑:卖出所有不在 target 的持仓(按 sell_cost 扣费)→ 汇总可用资金 = cash + 卖出净额 → 目标每股预算 = 可用资金 / len(target) → 对每个 target 买入 `floor(预算/价格/100)*100` 股(A 股 100 股整数倍,按 buy_cost 扣费)→ 返回 `{new_holdings, cash, buys:[{code,shares,price,fee}], sells:[{code,shares,price,fee,pnl?}]}`。
    - 缺价(停牌无 prices[code])的目标股跳过不买(权重留现金);缺价的持仓股不卖(保持)。

- [ ] **Step 1: 写失败测试**

```python
# tests/portfolio/test_rebalance.py
from tradingagents.portfolio.rebalance import compute_rebalance
from tradingagents.backtest.types import CostConfig

COST = CostConfig()

def test_initial_buy_equal_weight():
    # 空仓,10万资金,买 A/B 两只等权,价 10/20
    r = compute_rebalance(["A", "B"], {}, {"A": 10.0, "B": 20.0}, 100000.0, COST)
    # 每只预算 5 万:A 买 5000 股(5万/10),B 买 2500 股(5万/20),均 100 整数倍
    assert r["new_holdings"]["A"] == 5000
    assert r["new_holdings"]["B"] == 2500
    assert r["cash"] >= 0

def test_sell_dropped_and_buy_new():
    # 持有 A,目标换成 B
    r = compute_rebalance(["B"], {"A": 1000}, {"A": 10.0, "B": 20.0}, 0.0, COST)
    assert "A" not in r["new_holdings"] or r["new_holdings"].get("A", 0) == 0
    assert r["new_holdings"]["B"] > 0
    assert any(s["code"] == "A" for s in r["sells"])

def test_suspended_target_skipped_to_cash():
    # 目标 A/B,但 B 停牌(无价),只买 A,B 权重留现金
    r = compute_rebalance(["A", "B"], {}, {"A": 10.0}, 100000.0, COST)
    assert r["new_holdings"].get("A", 0) > 0
    assert "B" not in r["new_holdings"]
    assert r["cash"] > 0  # B 那份留现金

def test_suspended_holding_not_sold():
    # 持有 A(停牌无价),目标为空 → A 不能卖,保持
    r = compute_rebalance([], {"A": 1000}, {}, 0.0, COST)
    assert r["new_holdings"].get("A") == 1000
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/portfolio/test_rebalance.py -v`
Expected: FAIL(ModuleNotFoundError)

- [ ] **Step 3: 实现 `rebalance.py`**

```python
# tradingagents/portfolio/rebalance.py
"""等权组合调仓:卖出掉榜、买入新进、等权分配。纯函数,复用阶段① market_rules 成本。"""
import math
from tradingagents.backtest.market_rules import buy_cost, sell_cost


def compute_rebalance(target_codes, holdings, prices, cash, cost):
    target = set(target_codes)
    sells, buys = [], []
    new_holdings = dict(holdings)

    # 1) 卖出:当前持仓中不在 target、且有价(未停牌)的
    for code, shares in list(holdings.items()):
        if code in target or shares <= 0:
            continue
        px = prices.get(code)
        if px is None:  # 停牌不卖,保持
            continue
        amount = px * shares
        comm, stamp, transfer = sell_cost(amount, cost)
        cash += amount - comm - stamp - transfer
        sells.append({"code": code, "shares": shares, "price": px, "fee": comm + stamp + transfer})
        del new_holdings[code]

    # 2) 保留股同样纳入"再平衡预算"总池:先按当前价折现估其市值(不强制卖出零头,简化第一版:
    #    只对"新进股"用现金买入,保留股维持原持仓)。等权预算 = 可用现金 / 需买入的目标数。
    to_buy = [c for c in target_codes if c not in new_holdings and prices.get(c) is not None]
    if to_buy:
        budget_each = cash / len(to_buy)
        for code in to_buy:
            px = prices[code]
            shares = int(math.floor(budget_each / px / 100) * 100)  # A股 100 整数倍
            if shares <= 0:
                continue
            amount = px * shares
            comm, _, transfer = buy_cost(amount, cost)
            total = amount + comm + transfer
            if total > cash:
                continue
            cash -= total
            new_holdings[code] = new_holdings.get(code, 0) + shares
            buys.append({"code": code, "shares": shares, "price": px, "fee": comm + transfer})

    return {"new_holdings": new_holdings, "cash": cash, "buys": buys, "sells": sells}
```

（第一版简化:保留股不做零头再平衡,只把现金分给新进股等权买入——避免过度复杂;spec 的"等权再平衡"第一版按此近似,注释说明。)

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_rebalance.py -v`
Expected: PASS(4 passed)

- [ ] **Step 5: 提交**

```bash
git add tradingagents/portfolio/rebalance.py tradingagents/portfolio/__init__.py tests/portfolio/test_rebalance.py
git commit -m "feat(portfolio): 等权调仓纯函数(卖掉榜/买新进/停牌处理)"
```

---

### Task 4: 组合绩效 `metrics.py`

**Files:**
- Create: `tradingagents/portfolio/metrics.py`
- Test: `tests/portfolio/test_portfolio_metrics.py`

**Interfaces:**
- Produces: `compute_portfolio_metrics(equity_curve: list[tuple[str,float]], benchmark_curve: list[tuple[str,float]], initial_capital: float, rebalances: list[dict]) -> dict`:返回 `{total_return, annual_return, max_drawdown, sharpe, benchmark_return, excess_return, turnover, rebalance_count}`。benchmark_curve 已归一到 initial_capital(在 engine 里归一);turnover = 平均每次调仓的买卖额 / 当时组合市值。

- [ ] **Step 1: 写失败测试**

```python
# tests/portfolio/test_portfolio_metrics.py
import math
from tradingagents.portfolio.metrics import compute_portfolio_metrics

def test_total_and_excess_return():
    eq = [("2024-01-01", 100000.0), ("2024-12-31", 120000.0)]     # +20%
    bm = [("2024-01-01", 100000.0), ("2024-12-31", 110000.0)]     # +10%
    m = compute_portfolio_metrics(eq, bm, 100000.0, [])
    assert math.isclose(m["total_return"], 0.20, abs_tol=1e-9)
    assert math.isclose(m["benchmark_return"], 0.10, abs_tol=1e-9)
    assert math.isclose(m["excess_return"], 0.10, abs_tol=1e-9)

def test_max_drawdown():
    eq = [("d1", 100.0), ("d2", 120.0), ("d3", 90.0), ("d4", 110.0)]  # 峰120→谷90 回撤25%
    m = compute_portfolio_metrics(eq, [("d1",100.0),("d4",110.0)], 100.0, [])
    assert math.isclose(m["max_drawdown"], 0.25, abs_tol=1e-9)

def test_rebalance_count():
    m = compute_portfolio_metrics([("d1",100.0),("d2",100.0)], [("d1",100.0),("d2",100.0)], 100.0,
                                   [{"date":"d1","buys":[],"sells":[]}, {"date":"d2","buys":[],"sells":[]}])
    assert m["rebalance_count"] == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/portfolio/test_portfolio_metrics.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `metrics.py`**

```python
# tradingagents/portfolio/metrics.py
"""组合层面绩效:收益/年化/回撤/夏普/超额/换手。纯函数。"""
import math
from statistics import pstdev


def compute_portfolio_metrics(equity_curve, benchmark_curve, initial_capital, rebalances):
    eq = [v for _, v in equity_curve]
    total_return = eq[-1] / initial_capital - 1 if eq else 0.0
    n = len(eq)
    annual = (eq[-1] / initial_capital) ** (252.0 / n) - 1 if n > 1 and eq[-1] > 0 else 0.0

    peak, mdd = eq[0] if eq else 0.0, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)

    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1]]
    sharpe = (sum(rets) / len(rets)) / pstdev(rets) * math.sqrt(252) if len(rets) >= 2 and pstdev(rets) > 0 else 0.0

    bm = [v for _, v in benchmark_curve]
    benchmark_return = bm[-1] / bm[0] - 1 if len(bm) >= 2 and bm[0] else 0.0

    # 换手率:每次调仓的(买额+卖额)/当次组合市值,取均值
    turnovers = []
    for rb in rebalances:
        traded = sum(b["shares"] * b["price"] for b in rb.get("buys", [])) + \
                 sum(s["shares"] * s["price"] for s in rb.get("sells", []))
        mv = rb.get("portfolio_value") or initial_capital
        if mv > 0:
            turnovers.append(traded / mv)
    turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0

    return {
        "total_return": total_return, "annual_return": annual, "max_drawdown": mdd, "sharpe": sharpe,
        "benchmark_return": benchmark_return, "excess_return": total_return - benchmark_return,
        "turnover": turnover, "rebalance_count": len(rebalances),
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_portfolio_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add tradingagents/portfolio/metrics.py tests/portfolio/test_portfolio_metrics.py
git commit -m "feat(portfolio): 组合绩效(收益/回撤/夏普/超额/换手)"
```

---

### Task 5: 组合引擎主循环 `engine.py`（防前视/停牌退市/T+1/每日净值）

**Files:**
- Create: `tradingagents/portfolio/engine.py`
- Test: `tests/portfolio/test_engine.py`

**Interfaces:**
- Consumes: `compute_rebalance`(Task 3)、`compute_portfolio_metrics`(Task 4)、`score_universe`(2a)。
- Produces:
  - `run_portfolio_backtest(config: dict, factor_configs: list, monthly_sections: dict, price_panel: dict, benchmark: list, top_n: int) -> dict`
    - `config`:`{start_date, end_date, initial_capital, cost}`(cost 为 CostConfig)。
    - `monthly_sections`:`{month_end_date: {code: {"pe","pb","total_mv"}}}`(防前视:调仓日 D 用 monthly_sections[D])。
    - `price_panel`:`{code: [{"date","open","close","volume"}...]}`(每股前复权日线,已按 date 升序;date "YYYY-MM-DD")。
    - `benchmark`:`[("YYYY-MM-DD", close)...]`。
    - 逐月调仓日 D(monthly_sections 的 key 中落在 [start,end] 的):
      - 构造候选 `stocks`:仅取 monthly_sections[D] 里的 code(**防幸存者偏差**),`cross`=该 code 的 {pe,pb,total_mv},`closes`/`volumes`=price_panel[code] 中 **date <= D** 的序列(**防前视**)。
      - `score_universe(stocks, factor_configs, top_n)` → 目标 TopN。
      - 成交价 = 各 code 在 **D 的次一交易日**的 open;`compute_rebalance` 撮合。
    - 每个交易日按持仓 × 当日 close + cash 记净值 `equity_curve`;benchmark 归一到 initial_capital。
    - 返回 `{config, equity_curve, benchmark_curve, metrics, rebalances}`;`rebalances` 每项 `{date, buys, sells, holdings:[{code,weight}], portfolio_value}`。

- [ ] **Step 1: 写失败测试(小合成数据,3 只股、2 个调仓日,验证防前视 + 净值 + 调仓)**

```python
# tests/portfolio/test_engine.py
from tradingagents.portfolio import run_portfolio_backtest
from tradingagents.backtest.types import CostConfig

def _panel(code, dates_prices):
    return [{"date": d, "open": p, "close": p, "volume": 1000000} for d, p in dates_prices]

def test_portfolio_backtest_basic():
    dates = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-28", "2024-02-29"]
    # A 持续涨、B 平、C 跌
    panel = {
        "A": _panel("A", [(d, 10 + i) for i, d in enumerate(dates)]),
        "B": _panel("B", [(d, 20.0) for d in dates]),
        "C": _panel("C", [(d, 30 - i) for i, d in enumerate(dates)]),
    }
    sections = {
        "2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
        "2024-02-29": {"A": {"pe": 6, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
    }
    benchmark = [(d, 1000.0 + i) for i, d in enumerate(dates)]
    cfg = {"start_date": "2024-01-30", "end_date": "2024-02-29", "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "pe", "weight": 1, "direction": "asc"}]  # 低 PE 优先 → 选 A
    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)
    assert len(r["equity_curve"]) >= 3
    assert r["rebalances"], "应有调仓记录"
    # 第一个调仓日 2024-01-31,次日 2024-02-01 成交 → 买入低PE的 A
    assert any(any(b["code"] == "A" for b in rb["buys"]) for rb in r["rebalances"])
    assert "total_return" in r["metrics"] and "benchmark_return" in r["metrics"]

def test_no_lookahead_uses_only_past_prices():
    # 调仓日 D 的因子若用了 D 之后的价,结果会不同;这里构造 A 在 D 后暴涨,
    # 若引擎错误地用了未来数据算动量,排序会变。用只有 pe 的因子(不依赖未来)确保稳定,
    # 主要断言:调仓成交价用的是 D 的"次一交易日"open,而非更晚的价。
    dates = ["2024-01-31", "2024-02-01", "2024-02-05"]
    panel = {"A": [{"date": "2024-01-31", "open": 10, "close": 10, "volume": 1e6},
                   {"date": "2024-02-01", "open": 11, "close": 11, "volume": 1e6},
                   {"date": "2024-02-05", "open": 99, "close": 99, "volume": 1e6}]}
    sections = {"2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
    cfg = {"start_date": "2024-01-31", "end_date": "2024-02-05", "initial_capital": 100000.0, "cost": CostConfig()}
    r = run_portfolio_backtest(cfg, [{"key": "pe", "weight": 1, "direction": "asc"}], sections, panel, [("2024-01-31",1000.0),("2024-02-05",1000.0)], top_n=1)
    buy = [b for rb in r["rebalances"] for b in rb["buys"] if b["code"] == "A"][0]
    assert buy["price"] == 11  # 次日 2024-02-01 open,不是 2024-02-05 的 99
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/bin/python -m pytest tests/portfolio/test_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 `engine.py`**

```python
# tradingagents/portfolio/engine.py
"""逐月调仓组合回测:防前视(只用<=D数据)、防幸存者偏差(候选来自当时截面)、
T+1 次日开盘成交、每日净值。纯函数,数据由调用方注入。"""
from tradingagents.factor import score_universe
from .rebalance import compute_rebalance
from .metrics import compute_portfolio_metrics


def _all_dates(price_panel, start, end):
    ds = set()
    for rows in price_panel.values():
        for r in rows:
            if start <= r["date"] <= end:
                ds.add(r["date"])
    return sorted(ds)


def run_portfolio_backtest(config, factor_configs, monthly_sections, price_panel, benchmark, top_n):
    start, end = config["start_date"], config["end_date"]
    cap0 = config["initial_capital"]
    cost = config["cost"]

    trade_days = _all_dates(price_panel, start, end)
    rebal_days = sorted(d for d in monthly_sections if start <= d <= end)

    # 每股 date→row 索引,便于取价与切片
    by_code = {c: {r["date"]: r for r in rows} for c, rows in price_panel.items()}

    holdings, cash = {}, cap0
    rebalances = []
    equity_curve = []
    pending = None  # (成交日, 目标TopN)

    for di, d in enumerate(trade_days):
        # 到达上次调仓的"次一交易日"→ 成交
        if pending and d == pending[0]:
            targets = pending[1]
            prices = {c: by_code.get(c, {}).get(d, {}).get("open") for c in targets}
            prices = {c: p for c, p in prices.items() if p is not None}
            pv_before = _portfolio_value(holdings, by_code, d, cash)
            res = compute_rebalance(targets, holdings, prices, cash, cost)
            holdings, cash = res["new_holdings"], res["cash"]
            weight = _weights(holdings, by_code, d)
            rebalances.append({"date": d, "buys": res["buys"], "sells": res["sells"],
                               "holdings": weight, "portfolio_value": pv_before})
            pending = None

        # 调仓日 D:选股,预约次日成交
        if d in rebal_days:
            section = monthly_sections[d]
            stocks = []
            for code, cross in section.items():
                rows = by_code.get(code)
                if not rows:
                    continue
                closes, vols = [], []
                for dt in trade_days:
                    if dt > d:
                        break
                    row = rows.get(dt)
                    if row and row.get("close") is not None:
                        closes.append(row["close"]); vols.append(row.get("volume") or 0)
                if not closes:
                    continue
                stocks.append({"code": code, "name": code, "industry": "",
                               "cross": cross, "closes": closes, "volumes": vols})
            ranked = score_universe(stocks, factor_configs, top_n)
            targets = [x["code"] for x in ranked]
            # 预约:下一个交易日成交
            nxt = trade_days[di + 1] if di + 1 < len(trade_days) else None
            if nxt:
                pending = (nxt, targets)

        equity_curve.append((d, _portfolio_value(holdings, by_code, d, cash)))

    benchmark_curve = _normalize_benchmark(benchmark, trade_days, cap0)
    metrics = compute_portfolio_metrics(equity_curve, benchmark_curve, cap0, rebalances)
    return {"config": _config_dict(config), "equity_curve": equity_curve,
            "benchmark_curve": benchmark_curve, "metrics": metrics, "rebalances": rebalances}


def _portfolio_value(holdings, by_code, d, cash):
    v = cash
    for code, sh in holdings.items():
        row = by_code.get(code, {}).get(d)
        if row and row.get("close") is not None:
            v += sh * row["close"]
    return v


def _weights(holdings, by_code, d):
    total = _portfolio_value(holdings, by_code, d, 0.0)
    out = []
    for code, sh in holdings.items():
        row = by_code.get(code, {}).get(d)
        px = row["close"] if row and row.get("close") is not None else 0.0
        out.append({"code": code, "weight": (sh * px / total) if total > 0 else 0.0})
    return out


def _normalize_benchmark(benchmark, trade_days, cap0):
    bm = {d: c for d, c in benchmark}
    base = None
    out = []
    for d in trade_days:
        if d in bm:
            if base is None:
                base = bm[d]
            out.append((d, cap0 * bm[d] / base if base else cap0))
    return out


def _config_dict(config):
    c = dict(config)
    cost = c.get("cost")
    if hasattr(cost, "__dict__"):
        from dataclasses import asdict, is_dataclass
        c["cost"] = asdict(cost) if is_dataclass(cost) else vars(cost)
    return c
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/bin/python -m pytest tests/portfolio/test_engine.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add tradingagents/portfolio/engine.py tests/portfolio/test_engine.py
git commit -m "feat(portfolio): 逐月调仓引擎(防前视/T+1成交/每日净值)"
```

---

### Task 6: 引擎导出 `__init__.py`

**Files:**
- Modify: `tradingagents/portfolio/__init__.py`
- Test: `tests/portfolio/test_engine.py`（已 import `from tradingagents.portfolio import run_portfolio_backtest`,本任务确保导出）

- [ ] **Step 1: 实现导出**

```python
# tradingagents/portfolio/__init__.py
"""组合回测（子项目 2b）开源引擎层。"""
from .engine import run_portfolio_backtest
from .rebalance import compute_rebalance
from .metrics import compute_portfolio_metrics

__all__ = ["run_portfolio_backtest", "compute_rebalance", "compute_portfolio_metrics"]
```

- [ ] **Step 2: 运行确认全部引擎测试通过**

Run: `./venv/bin/python -m pytest tests/portfolio/ -v`
Expected: PASS(data_sync + rebalance + metrics + engine 全绿)

- [ ] **Step 3: 提交**

```bash
git add tradingagents/portfolio/__init__.py
git commit -m "feat(portfolio): 导出组合引擎入口"
```

---

### Task 7: 后端组合回测服务 `portfolio_backtest_service.py`

**Files:**
- Create: `app/services/portfolio_backtest_service.py`
- Test: `tests/portfolio/test_portfolio_service.py`

**Interfaces:**
- Consumes: `run_portfolio_backtest`(Task 5)。参考 `app/services/factor_screening_service.py`(2a)的 `ensure_db`/`set_task_status`/`get_task_status`/`get_result`/`get_history` 照搬结构,集合换 `portfolio_backtest_tasks`/`portfolio_backtest_results`。
- Produces:
  - `async def load_monthly_sections(db, start, end) -> dict`:从 `stock_monthly_basic` 取 [start,end] 内各月末截面 → `{trade_date: {code: {pe,pb,total_mv}}}`。
  - `async def load_price_panel(db, codes, end) -> dict`:从 `stock_daily_quotes` 批量取 codes 的 `trade_date <= end` 前复权日线 → `{code: [{date,open,close,volume}...]}`(open=open_qfq、close=close_qfq,过滤 close_qfq 为 None,升序)。
  - `async def load_benchmark(db, ts_code, start, end) -> list`:从 `index_daily_quotes` 取 → `[(date, close)...]`。
  - `async def run_task(task_id, user_id, payload, precomputed=None)`:主循环预取(sections + panel + benchmark)→ `run_in_executor` 跑 `run_portfolio_backtest` → 落库 → 返回。`precomputed` 供测试注入。
  - 候选 codes = 各月末截面里出现过的 code 之并集(**防幸存者偏差**,来自 `stock_monthly_basic` 而非 `stock_screening_view`)。

- [ ] **Step 1: 写失败测试(注入 precomputed 绕库,验证打分落库)**

```python
# tests/portfolio/test_portfolio_service.py
import pytest
from app.services import portfolio_backtest_service as svc

@pytest.mark.integration
def test_run_task_with_injected_data():
    import asyncio
    from tradingagents.backtest.types import CostConfig
    async def _run():
        await svc.ensure_db()
        dates = ["2024-01-31", "2024-02-01", "2024-02-29"]
        panel = {"A": [{"date": d, "open": 10 + i, "close": 10 + i, "volume": 1e6} for i, d in enumerate(dates)]}
        sections = {"2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
        benchmark = [("2024-01-31", 1000.0), ("2024-02-29", 1010.0)]
        payload = {"factors": [{"key": "pe", "weight": 1, "direction": "asc"}],
                   "start_date": "2024-01-31", "end_date": "2024-02-29",
                   "top_n": 1, "initial_capital": 100000.0, "cost": {}}
        res = await svc.run_task("t-pf-1", "user-x", payload,
                                 precomputed={"monthly_sections": sections, "price_panel": panel, "benchmark": benchmark})
        assert "equity_curve" in res and res["metrics"]
        got = await svc.get_result("t-pf-1")
        assert got and got["user_id"] == "user-x"
    asyncio.run(_run())
```

- [ ] **Step 2: 运行确认失败**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/portfolio/test_portfolio_service.py -v -m integration`
Expected: FAIL

- [ ] **Step 3: 实现 service**（`ensure_db`/状态方法照 `factor_screening_service.py` 同构,仅换集合名;核心 `run_task` 与 load_* 如下）

```python
# app/services/portfolio_backtest_service.py（关键片段）
import asyncio
from datetime import datetime, timezone
import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from tradingagents.backtest.types import CostConfig
from tradingagents.portfolio import run_portfolio_backtest

BENCHMARK_TS = "000300.SH"

async def ensure_db():
    if getattr(db_manager, "mongo_db", None) is None:
        await db_manager.init_mongodb()
    db_module.mongo_client = db_manager.mongo_client
    db_module.mongo_db = db_manager.mongo_db

def _results(): return get_mongo_db().portfolio_backtest_results
def _tasks(): return get_mongo_db().portfolio_backtest_tasks

async def load_monthly_sections(db, start, end):
    out = {}
    async for d in db.stock_monthly_basic.find(
            {"trade_date": {"$gte": start, "$lte": end}}, {"_id": 0}):
        out.setdefault(d["trade_date"], {})[d["code"]] = {
            "pe": d.get("pe"), "pb": d.get("pb"), "total_mv": d.get("total_mv")}
    return out

async def load_price_panel(db, codes, end):
    out = {}
    async for d in db.stock_daily_quotes.find(
            {"symbol": {"$in": list(codes)}, "trade_date": {"$lte": end}, "close_qfq": {"$ne": None}},
            {"_id": 0, "symbol": 1, "trade_date": 1, "open_qfq": 1, "close_qfq": 1, "volume": 1}).sort("trade_date", 1):
        out.setdefault(d["symbol"], []).append(
            {"date": d["trade_date"], "open": d.get("open_qfq"), "close": d["close_qfq"], "volume": d.get("volume") or 0})
    return out

async def load_benchmark(db, ts_code, start, end):
    rows = []
    async for d in db.index_daily_quotes.find(
            {"ts_code": ts_code, "trade_date": {"$gte": start, "$lte": end}}, {"_id": 0}).sort("trade_date", 1):
        rows.append((d["trade_date"], d["close"]))
    return rows

async def run_task(task_id, user_id, payload, precomputed=None):
    start, end = payload["start_date"], payload["end_date"]
    if precomputed:
        sections, panel, benchmark = precomputed["monthly_sections"], precomputed["price_panel"], precomputed["benchmark"]
    else:
        db = get_mongo_db()
        sections = await load_monthly_sections(db, start, end)
        codes = {c for sec in sections.values() for c in sec}   # 防幸存者偏差:来自月末截面
        panel = await load_price_panel(db, codes, end)
        benchmark = await load_benchmark(db, BENCHMARK_TS, start, end)
    c = payload.get("cost") or {}
    config = {"start_date": start, "end_date": end,
              "initial_capital": float(payload.get("initial_capital", 100000)),
              "cost": CostConfig(**{k: c[k] for k in ("commission_rate","min_commission","stamp_tax_rate","transfer_fee_rate") if k in c})}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, lambda: run_portfolio_backtest(
        config, payload["factors"], sections, panel, benchmark, payload.get("top_n", 20)))
    doc = {"task_id": task_id, "user_id": user_id, "config": result["config"],
           "equity_curve": result["equity_curve"], "benchmark_curve": result["benchmark_curve"],
           "metrics": result["metrics"], "rebalances": result["rebalances"],
           "created_at": datetime.now(timezone.utc)}
    await _results().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return doc

# set_task_status/get_task_status/get_result/get_history：照 factor_screening_service.py 同名实现,换集合名。
```

- [ ] **Step 4: 运行确认通过**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/portfolio/test_portfolio_service.py -v -m integration`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/portfolio_backtest_service.py tests/portfolio/test_portfolio_service.py
git commit -m "feat(portfolio): 组合回测服务(预取截面/日线panel/基准+run_in_executor)"
```

---

### Task 8: 后端接口 `routers/portfolio_backtest.py`

**Files:**
- Create: `app/routers/portfolio_backtest.py`
- Modify: `app/main.py`
- Test: `tests/portfolio/test_portfolio_api.py`

**Interfaces:**
- 照 `app/routers/factor_screening.py`(2a)结构:`POST /api/portfolio-backtest/run`(校验 factors 非空/每 key 在 FACTORS/top_n>0/区间合法 → 400;uuid task_id;set_task_status running;BackgroundTasks 跑 run_task 并完成/异常置 done/failed;返回 {task_id})、`GET /status/{task_id}`、`GET /result/{task_id}`(属主校验非本人 404)、`GET /history`。`app/main.py` include_router。

- [ ] **Step 1: 写失败测试**

```python
# tests/portfolio/test_portfolio_api.py
import pytest
from fastapi.testclient import TestClient

def test_run_bad_params_400():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        c = TestClient(app)
        r = c.post("/api/portfolio-backtest/run", json={"factors": [], "start_date": "2024-01-01", "end_date": "2024-12-31", "top_n": 20})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.integration
def test_status_result_ownership():
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.services import portfolio_backtest_service as svc
    import asyncio
    asyncio.run(_seed(svc))
    c = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "intruder"}
    try:
        assert c.get("/api/portfolio-backtest/status/t-pf-own").status_code == 404
        assert c.get("/api/portfolio-backtest/result/t-pf-own").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)

async def _seed(svc):
    await svc.ensure_db()
    await svc.set_task_status("t-pf-own", "done", user_id="owner")
    await svc._results().update_one({"task_id": "t-pf-own"},
        {"$set": {"task_id": "t-pf-own", "user_id": "owner", "equity_curve": [], "metrics": {}, "config": {}}}, upsert=True)
```

- [ ] **Step 2: 运行确认失败**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/portfolio/test_portfolio_api.py -v`
Expected: FAIL(404 路由不存在)

- [ ] **Step 3: 实现路由**（照 `app/routers/factor_screening.py`,校验 + BackgroundTasks + 属主 404;`from tradingagents.factor import FACTORS` 校验 key;prefix `/api/portfolio-backtest`;`app/main.py` import+include_router)。校验额外含 `start_date < end_date`。

- [ ] **Step 4: 运行确认通过**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/portfolio/test_portfolio_api.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/routers/portfolio_backtest.py app/main.py tests/portfolio/test_portfolio_api.py
git commit -m "feat(portfolio): 组合回测API路由(run/status/result/history+属主校验)"
```

---

### Task 9: 后端端到端集成（真实库小区间）

**Files:**
- Test: `tests/portfolio/test_portfolio_e2e.py`
- Test: `tests/portfolio/conftest.py`（若无,照 `tests/factor/conftest.py` 补本地 mongo 鉴权）

**Interfaces:**
- 真实库跑通 run→轮询→result,覆盖 run_task 的 precomputed=None 真实路径(load_* + run_in_executor),验证不触发跨事件循环冲突。**前置**:需先有一小段 `stock_monthly_basic` + `index_daily_quotes` 数据(由 controller 在执行本任务前用 Task 1/2 的 sync 函数回填一小段,如近 3 年;或测试内先调 sync 回填再跑)。

- [ ] **Step 1: 写端到端测试**

```python
# tests/portfolio/test_portfolio_e2e.py
import time, pytest
from fastapi.testclient import TestClient

@pytest.mark.integration
def test_full_portfolio_flow():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e-pf", "username": "admin"}
    try:
        c = TestClient(app)
        body = {"factors": [{"key": "pe", "weight": 2, "direction": "asc"},
                            {"key": "mom_120", "weight": 1, "direction": "desc"}],
                "start_date": "2023-01-01", "end_date": "2024-12-31", "top_n": 10, "initial_capital": 1000000.0}
        tid = c.post("/api/portfolio-backtest/run", json=body).json()["data"]["task_id"]
        final = None
        for _ in range(120):
            st = c.get(f"/api/portfolio-backtest/status/{tid}").json()["data"]
            if st["status"] in ("done", "failed"):
                final = st; break
            time.sleep(1)
        assert final and final["status"] == "done", f"最终状态: {final}"
        data = c.get(f"/api/portfolio-backtest/result/{tid}").json()["data"]
        assert len(data["equity_curve"]) > 20 and data["rebalances"]
        m = data["metrics"]
        print("组合总收益:", round(m["total_return"], 4), "基准:", round(m["benchmark_return"], 4),
              "超额:", round(m["excess_return"], 4), "调仓次数:", m["rebalance_count"])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

- [ ] **Step 2: 前置回填 + 运行**

先回填一小段(controller 执行:近 2023-2024 的月末 basic + 沪深300),再:
Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/portfolio/test_portfolio_e2e.py -v -m integration -s`
Expected: PASS,打印组合 vs 基准收益、调仓次数。

- [ ] **Step 3: 提交**

```bash
git add tests/portfolio/test_portfolio_e2e.py tests/portfolio/conftest.py
git commit -m "test(portfolio): 组合回测后端端到端集成(真实库小区间)"
```

---

### Task 10: 前端 API 层 + 路由/菜单 + 占位页

**Files:**
- Create: `frontend/src/api/portfolioBacktest.ts`
- Create: `frontend/src/views/PortfolioBacktest/index.vue`（占位）
- Modify: `frontend/src/router/index.ts`、`frontend/src/components/Layout/SidebarMenu.vue`

**Interfaces:**
- `portfolioApi.run/status/result/history`,照 `frontend/src/api/factorScreening.ts`(baseURL 空、路径带 `/api`、**类型准确**:请求含 factors 数组/start_date/end_date/top_n/initial_capital)。路由 `/portfolio-backtest` + 菜单「组合回测」(图标如 `TrendCharts`)。占位页 `el-empty`。

- [ ] **Step 1: 实现 api + 路由 + 菜单 + 占位**（照 factorScreening.ts 与 2a 路由/菜单块）
- [ ] **Step 2: 构建** `cd frontend && npm run build` → 通过
- [ ] **Step 3: 提交** `git commit -m "feat(portfolio-web): 前端组合回测API与路由菜单"`

---

### Task 11: 净值 vs 基准图 + 绩效卡组件

**Files:**
- Create: `frontend/src/views/PortfolioBacktest/components/EquityVsBenchmark.vue`
- Create: `frontend/src/views/PortfolioBacktest/components/PortfolioMetrics.vue`

**Interfaces:**
- `EquityVsBenchmark`:props `equityCurve: [string,number][]`、`benchmarkCurve: [string,number][]`;vue-echarts 双线(组合 vs 沪深300),照阶段① `EquityChart.vue` 的注册方式。
- `PortfolioMetrics`:props `metrics`;卡片展示 total_return/annual_return/max_drawdown/sharpe/benchmark_return/excess_return/turnover/rebalance_count;百分比字段(total/annual/max_drawdown/benchmark/excess/turnover)×100+%,sharpe/rebalance_count 原样。

- [ ] **Step 1: 实现两组件**（vue-echarts 注册照 `frontend/src/views/Backtest/components/EquityChart.vue`）
- [ ] **Step 2: 构建**通过
- [ ] **Step 3: 提交** `git commit -m "feat(portfolio-web): 净值vs基准图与绩效卡"`

---

### Task 12: 调仓明细表组件

**Files:**
- Create: `frontend/src/views/PortfolioBacktest/components/RebalanceTable.vue`

**Interfaces:**
- props `rebalances: Array<{date,buys,sells,holdings,portfolio_value}>`;`el-table` 展示每个调仓日:日期、买入(codes)、卖出(codes)、持仓数、组合市值;可展开看该次 holdings 明细(code+weight)。

- [ ] **Step 1: 实现组件**
- [ ] **Step 2: 构建**通过
- [ ] **Step 3: 提交** `git commit -m "feat(portfolio-web): 调仓明细表组件"`

---

### Task 13: 主页组装 `index.vue`

**Files:**
- Modify: `frontend/src/views/PortfolioBacktest/index.vue`

**Interfaces:**
- 组装:`onMounted` 拉 `factorApi.factors()`(复用 2a 的因子元信息接口)传给 **复用的 2a `FactorConfig`**;输入区含区间/TopN/初始资金/成本;「开始回测」→ `portfolioApi.run(payload)` → 轮询 `status`(running/done/failed,清定时器)→ done 取 `result` → `EquityVsBenchmark` + `PortfolioMetrics` + `RebalanceTable`;历史 `history()` 列表回看。payload 结构见 Task 8。

- [ ] **Step 1: 实现主页**（轮询/清定时器照 2a `FactorScreening/index.vue`;因子配置直接 import 复用 `@/views/FactorScreening/components/FactorConfig.vue`)
- [ ] **Step 2: 构建**通过
- [ ] **Step 3: 提交** `git commit -m "feat(portfolio-web): 组合回测主页(配置+区间+轮询+净值vs基准+调仓明细)"`

---

### Task 14: 浏览器端到端验证 + 重建镜像

**Files:** 无（验证任务)

- [ ] **Step 1: 全量回填**(controller 执行):跑 Task 1/2 的 `sync_monthly_basic` + `sync_benchmark_index` 回填近 20 年月末 basic + 沪深300。
- [ ] **Step 2: 重建 backend+frontend 镜像并起容器**:`docker compose build backend frontend && docker compose up -d --force-recreate backend frontend`。
- [ ] **Step 3: 浏览器验证**:`http://localhost:3000` → 登录 → 「组合回测」→ 配因子(PE+120日动量)+ 区间 2020-2024 + TopN 20 + 100万 → 开始 → 确认:进度→净值曲线 vs 沪深300 双线→绩效卡(超额/换手/调仓次数)→调仓明细表。
- [ ] **Step 4: 记录验证结果**,有 bug 回对应 Task 修。

---

## Self-Review

**1. Spec coverage:**
- 数据回填(月末 basic + 沪深300,trade_date "YYYY-MM-DD")→ Task 1/2 ✅
- 组合引擎(逐月调仓/防前视/防幸存者偏差/停牌退市/T+1/净值)→ Task 3(调仓)/5(引擎主循环) ✅
- 组合绩效 vs 基准 → Task 4 ✅
- 后端异步(预取/run_in_executor/属主/状态)→ Task 7/8 ✅
- 后端 e2e → Task 9 ✅
- 前端(API/路由/净值vs基准/绩效/调仓明细/主页复用2a FactorConfig)→ Task 10-13 ✅
- 浏览器验证 + 全量回填 → Task 14 ✅
- 防前视(engine 只用 <=D)、防幸存者(候选来自 monthly_sections/stock_monthly_basic 非 stock_screening_view)→ Task 5/7 显式实现并有测试 ✅

**2. Placeholder scan:** 状态方法在 Task 7/8 明确"照 factor_screening_service/factor_screening 同构"并给核心代码,非占位;前端 Task 10-13 给了接口契约与复用指向。✅

**3. Type consistency:** `run_portfolio_backtest(config, factor_configs, monthly_sections, price_panel, benchmark, top_n)` 签名在 Task 5 定义、Task 7 调用一致;结果字段 `{config,equity_curve,benchmark_curve,metrics,rebalances}` 贯穿 Task 5→7→8→11/12;`compute_rebalance` 返回 `{new_holdings,cash,buys,sells}` Task 3 定义、Task 5 用;集合名 `stock_monthly_basic`/`index_daily_quotes`/`portfolio_backtest_*` 一致;trade_date "YYYY-MM-DD" 全程一致。✅
