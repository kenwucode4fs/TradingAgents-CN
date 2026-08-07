# 策略回测引擎 Plan 2(Web 接入)实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增前端「策略回测」页 + 后端 `/api/backtest/*` 异步接口,把 Plan 1 的 `run_backtest` 引擎接出来,产出净值曲线、绩效指标、交易明细,并能列表回看历史回测。

**Architecture:** 前端页 → `app/routers/backtest.py` → 复用 `queue_service` + `BackgroundTasks` 异步 → `backtest_service` 用 `run_in_executor`(线程池)跑 `run_backtest`(避开 asyncio 冲突、不改引擎)→ 结果存 `backtest_results` 集合 → 前端 echarts 展示。

**Tech Stack:** 后端 FastAPI + pytest;前端 Vue 3 + Element Plus + echarts/vue-echarts;MongoDB。复用 Plan 1 `tradingagents/backtest`(`run_backtest`、`Condition`、`BacktestConfig`、`CostConfig`、`PositionConfig`)、`queue_service`、`MultiMarketStockSearch.vue`。

## Global Constraints

- Python 3.10+;所有注释/docstring/日志/commit 描述用中文;conventional commits。
- **后端走 TDD**(pytest,`./venv/bin/python -m pytest`);**前端无测试框架,不引入新框架**——前端任务用"`npm run build` 构建通过 + 浏览器端到端验证"作为验收,不写前端单测。
- 只 git add 本任务相关文件,**绝不 `git add -A`**(工作区有 `.env` 等本地改动)。
- 不修改 Plan 1 引擎(`tradingagents/backtest/`)及其测试;引擎正确性已由 Plan 1 的 86+5 测试保证。
- 关键技术约束:`run_backtest` 内部有 `asyncio.run`,必须在 worker 里用 `await loop.run_in_executor(None, lambda: run_backtest(...))` 跑,不能在 FastAPI 事件循环里直接调。
- MongoDB 库名:`tradingagents`(本地脚本/测试连库设 `MONGODB_DATABASE=tradingagents` + `MONGODB_DATABASE_SCOPE=explicit`,鉴权见 `tests/backtest/conftest.py`)。
- 后端异步任务复用现有 `queue_service`(参考 `app/routers/analysis.py` 的 `submit_single_analysis`:`queue_service` 建任务 + `BackgroundTasks` 后台执行 + 状态/结果查询)。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `app/services/backtest_param_mapper.py` | 纯函数:前端请求 payload → Plan 1 的 `Condition`/`CostConfig`/`PositionConfig`/`BacktestConfig` |
| `app/services/backtest_service.py` | worker:`run_backtest_task`（run_in_executor 跑 run_backtest + 存库 + 更新任务）；history 查询 |
| `app/routers/backtest.py` | API：`POST /run`、`GET /status/{id}`、`GET /result/{id}`、`GET /history` |
| `frontend/src/api/backtest.ts` | 前端 API 调用（提交/轮询/结果/历史） |
| `frontend/src/views/Backtest/index.vue` | 主页：输入区 + 提交 + 轮询 + 结果区 + 历史列表 |
| `frontend/src/views/Backtest/components/ConditionEditor.vue` | 条件积木编辑器（买入组/卖出组，表格式规则行） |
| `frontend/src/views/Backtest/components/EquityChart.vue` | 净值曲线图（echarts，策略 vs 买入持有） |
| `frontend/src/views/Backtest/components/MetricsCards.vue` | 绩效指标卡 |
| `frontend/src/views/Backtest/components/TradesTable.vue` | 交易明细表 |
| `frontend/src/router/index.ts`（改） | 新增 `/backtest` 路由 + 侧边栏菜单 |

---

## Phase 1：后端（TDD）

### Task 1: 参数映射 `backtest_param_mapper.py`

**Files:**
- Create: `app/services/backtest_param_mapper.py`
- Test: `tests/backtest/test_param_mapper.py`

**Interfaces:**
- Produces: `build_backtest_args(payload: dict) -> dict` —— 返回 `{"config": BacktestConfig, "buy_rules": [Condition], "buy_logic": str, "sell_rules": [Condition], "sell_logic": str}`。payload 形如 `{symbol,start_date,end_date,initial_capital,cost:{commission_rate,min_commission,stamp_tax_rate,transfer_fee_rate},position:{parts,reduce_mode},buy_rules:[{left,op,right}],buy_logic,sell_rules:[...],sell_logic}`。非法值抛 `ValueError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/backtest/test_param_mapper.py
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import BacktestConfig, Condition

def test_maps_payload_to_engine_args():
    payload = {
        "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
        "initial_capital": 100000,
        "cost": {"commission_rate": 0.00025, "min_commission": 5, "stamp_tax_rate": 0.001, "transfer_fee_rate": 0.00001},
        "position": {"parts": 3, "reduce_mode": "reduce_one"},
        "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
        "sell_rules": [{"left": "close", "op": "<", "right": 10}], "sell_logic": "OR",
    }
    args = build_backtest_args(payload)
    cfg = args["config"]
    assert isinstance(cfg, BacktestConfig)
    assert cfg.symbol == "000001" and cfg.position.parts == 3
    assert cfg.cost.stamp_tax_rate == 0.001
    assert args["buy_rules"][0].left == "ma5" and args["buy_rules"][0].op == "cross_up"
    assert args["buy_logic"] == "AND" and args["sell_logic"] == "OR"

def test_rejects_bad_logic():
    import pytest
    with pytest.raises(ValueError):
        build_backtest_args({"symbol":"000001","start_date":"2020-01-01","end_date":"2021-01-01",
                             "buy_rules":[], "buy_logic":"XOR", "sell_rules":[], "sell_logic":"AND"})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_param_mapper.py -v`
Expected: FAIL(模块不存在）

- [ ] **Step 3: 实现 `backtest_param_mapper.py`**

```python
# app/services/backtest_param_mapper.py
"""前端回测请求 payload 映射为 Plan 1 引擎参数。"""
from tradingagents.backtest import BacktestConfig, CostConfig, PositionConfig, Condition

_VALID_OP = {">", "<", "cross_up", "cross_down"}
_VALID_LOGIC = {"AND", "OR"}
_VALID_REDUCE = {"reduce_one", "clear_all"}

def _rules(raw: list) -> list:
    out = []
    for r in raw or []:
        op = r.get("op")
        if op not in _VALID_OP:
            raise ValueError(f"非法比较符: {op}")
        out.append(Condition(left=r["left"], op=op, right=r["right"]))
    return out

def build_backtest_args(payload: dict) -> dict:
    for k in ("symbol", "start_date", "end_date"):
        if not payload.get(k):
            raise ValueError(f"缺少必填参数: {k}")
    buy_logic = payload.get("buy_logic", "AND")
    sell_logic = payload.get("sell_logic", "OR")
    if buy_logic not in _VALID_LOGIC or sell_logic not in _VALID_LOGIC:
        raise ValueError("buy_logic/sell_logic 必须是 AND 或 OR")
    c = payload.get("cost", {}) or {}
    p = payload.get("position", {}) or {}
    reduce_mode = p.get("reduce_mode", "reduce_one")
    if reduce_mode not in _VALID_REDUCE:
        raise ValueError(f"非法减仓模式: {reduce_mode}")
    cfg = BacktestConfig(
        symbol=payload["symbol"], start_date=payload["start_date"], end_date=payload["end_date"],
        initial_capital=float(payload.get("initial_capital", 100000)),
        cost=CostConfig(
            commission_rate=float(c.get("commission_rate", 0.00025)),
            min_commission=float(c.get("min_commission", 5.0)),
            stamp_tax_rate=float(c.get("stamp_tax_rate", 0.001)),
            transfer_fee_rate=float(c.get("transfer_fee_rate", 0.00001)),
        ),
        position=PositionConfig(parts=int(p.get("parts", 3)), reduce_mode=reduce_mode),
    )
    return {
        "config": cfg,
        "buy_rules": _rules(payload.get("buy_rules")), "buy_logic": buy_logic,
        "sell_rules": _rules(payload.get("sell_rules")), "sell_logic": sell_logic,
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_param_mapper.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/services/backtest_param_mapper.py tests/backtest/test_param_mapper.py
git commit -m "feat(backtest-web): 回测请求参数映射到引擎参数"
```

### Task 2: 回测 worker `backtest_service.py`

**Files:**
- Create: `app/services/backtest_service.py`
- Test: `tests/backtest/test_backtest_service.py`

**Interfaces:**
- Consumes: `backtest_param_mapper.build_backtest_args`;`tradingagents.backtest.run_backtest`;MongoDB `backtest_results` 集合。
- Produces:
  - `async def run_backtest_task(task_id, user_id, payload, bars=None) -> dict`：用 `loop.run_in_executor` 跑 `run_backtest`（bars 可注入用于测试），`to_dict()` 后存 `backtest_results`（含 task_id/user_id/symbol/config/结果/created_at），返回结果 dict。
  - `async def get_history(user_id, limit=20, skip=0) -> list`：查该用户历史回测摘要（symbol/区间/total_return/created_at/task_id）。
  - `async def get_result(task_id) -> dict|None`：取单条结果。

- [ ] **Step 1: 写失败测试（注入 bars，不碰 tushare，只验证 run_in_executor 编排 + 落库）**

```python
# tests/backtest/test_backtest_service.py
import asyncio, pytest
from tradingagents.backtest.types import Bar

def _bars(closes):
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(date=f"2021-01-{i+1:02d}", open=c, high=c, low=c, close=c, pre_close=prev, volume=1e6)); prev=c
    return out

@pytest.mark.integration
def test_run_backtest_task_persists(monkeypatch):
    from app.services import backtest_service as svc
    payload = {"symbol":"600000","start_date":"2021-01-01","end_date":"2021-02-01","initial_capital":100000,
               "position":{"parts":1,"reduce_mode":"reduce_one"},
               "buy_rules":[{"left":"ma5","op":"cross_up","right":"ma20"}],"buy_logic":"AND",
               "sell_rules":[{"left":"ma5","op":"cross_down","right":"ma20"}],"sell_logic":"AND"}
    bars = _bars([10]*20 + [11,12,13,14,15,14,13,12,11,10])
    async def run():
        await svc.ensure_db()  # 初始化 mongo（见实现）
        res = await svc.run_backtest_task("task-test-1", "user-1", payload, bars=bars)
        assert "metrics" in res and "equity_curve" in res
        got = await svc.get_result("task-test-1")
        assert got is not None and got["symbol"] == "600000"
    asyncio.run(run())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/backtest/test_backtest_service.py -v -m integration`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `backtest_service.py`**

```python
# app/services/backtest_service.py
"""回测异步 worker：run_in_executor 跑 Plan1 引擎，结果落库。"""
import asyncio
from datetime import datetime
from app.core.database import get_mongo_db, db_manager
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import run_backtest

async def ensure_db():
    if getattr(db_manager, "mongo_db", None) is None:
        await db_manager.init_mongodb()

def _collection():
    return get_mongo_db().backtest_results

async def run_backtest_task(task_id: str, user_id: str, payload: dict, bars=None) -> dict:
    args = build_backtest_args(payload)
    loop = asyncio.get_event_loop()
    # 关键：run_backtest 内部有 asyncio.run，必须丢到线程池（独立事件循环）
    result = await loop.run_in_executor(
        None,
        lambda: run_backtest(
            args["config"], args["buy_rules"], args["buy_logic"],
            args["sell_rules"], args["sell_logic"], bars=bars,
        ),
    )
    d = result.to_dict()
    doc = {
        "task_id": task_id, "user_id": user_id, "symbol": payload["symbol"],
        "config": d["config"], "equity_curve": d["equity_curve"],
        "benchmark_curve": d["benchmark_curve"], "metrics": d["metrics"],
        "trades": d["trades"], "created_at": datetime.utcnow(),
    }
    await _collection().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return d

async def get_result(task_id: str):
    return await _collection().find_one({"task_id": task_id}, {"_id": 0})

async def get_history(user_id: str, limit: int = 20, skip: int = 0) -> list:
    cursor = _collection().find(
        {"user_id": user_id},
        {"_id": 0, "task_id": 1, "symbol": 1, "config": 1, "metrics.total_return": 1, "created_at": 1},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return [d async for d in cursor]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/backtest/test_backtest_service.py -v -m integration`
Expected: PASS（run_in_executor 跑通、落库、get_result 取回）

- [ ] **Step 5: 提交**

```bash
git add app/services/backtest_service.py tests/backtest/test_backtest_service.py
git commit -m "feat(backtest-web): 回测异步worker(run_in_executor跑引擎+落库)"
```

### Task 3: API 路由 `backtest.py`

**Files:**
- Create: `app/routers/backtest.py`
- Modify: `app/main.py`（注册 router，参考现有 include_router）
- Test: `tests/backtest/test_backtest_api.py`

**Interfaces:**
- Consumes: `backtest_service`;`queue_service`（建任务）；FastAPI `BackgroundTasks`；现有鉴权依赖（参考 `analysis.py` 取 user_id 的方式）。
- Produces:
  - `POST /api/backtest/run` → `{task_id}`（queue_service 建任务；BackgroundTasks 调 `run_backtest_task`）
  - `GET /api/backtest/status/{task_id}` → `{status, progress?}`
  - `GET /api/backtest/result/{task_id}` → 结果 dict（404 若无）
  - `GET /api/backtest/history` → 历史列表

- [ ] **Step 1: 写失败测试（FastAPI TestClient，参数校验 + 提交返回 task_id）**

```python
# tests/backtest/test_backtest_api.py
import pytest
from fastapi.testclient import TestClient

@pytest.mark.integration
def test_submit_returns_task_id(monkeypatch):
    from app.main import app
    client = TestClient(app)
    # 视鉴权情况：若需要 token，先登录 admin/admin123 取 token 加到 headers
    body = {"symbol":"000001","start_date":"2023-01-01","end_date":"2024-01-01",
            "buy_rules":[{"left":"ma5","op":"cross_up","right":"ma20"}],"buy_logic":"AND",
            "sell_rules":[{"left":"ma5","op":"cross_down","right":"ma20"}],"sell_logic":"AND"}
    r = client.post("/api/backtest/run", json=body)
    assert r.status_code in (200, 201)
    assert "task_id" in r.json().get("data", r.json())

def test_bad_params_rejected():
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/backtest/run", json={"symbol":"000001","start_date":"2023-01-01","end_date":"2024-01-01",
                    "buy_rules":[],"buy_logic":"XOR","sell_rules":[],"sell_logic":"AND"})
    assert r.status_code >= 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `./venv/bin/python -m pytest tests/backtest/test_backtest_api.py::test_bad_params_rejected -v`
Expected: FAIL（路由不存在 → 404 而非预期 4xx，或 import 失败）

- [ ] **Step 3: 实现 `backtest.py` 并在 `app/main.py` 注册**

```python
# app/routers/backtest.py
"""策略回测 Web 接口（异步任务）。"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from typing import Dict, Any
from app.services.backtest_param_mapper import build_backtest_args
from app.services import backtest_service
from app.services.queue_service import get_queue_service

router = APIRouter(prefix="/api/backtest", tags=["策略回测"])

@router.post("/run")
async def run(payload: Dict[str, Any], background_tasks: BackgroundTasks):
    # 参数校验（非法直接 400）
    try:
        build_backtest_args(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    queue = get_queue_service()
    user_id = "admin"  # TODO: 从鉴权依赖取真实 user_id（参考 analysis.py）
    task = await queue.create_task(task_type="backtest", payload=payload, user_id=user_id)
    task_id = task["task_id"]

    async def _run():
        await backtest_service.ensure_db()
        try:
            await backtest_service.run_backtest_task(task_id, user_id, payload)
            await queue.mark_done(task_id)
        except Exception as e:
            await queue.mark_failed(task_id, str(e))
    background_tasks.add_task(_run)
    return {"success": True, "data": {"task_id": task_id}}

@router.get("/status/{task_id}")
async def status(task_id: str):
    queue = get_queue_service()
    return {"success": True, "data": await queue.get_status(task_id)}

@router.get("/result/{task_id}")
async def result(task_id: str):
    await backtest_service.ensure_db()
    res = await backtest_service.get_result(task_id)
    if not res:
        raise HTTPException(status_code=404, detail="回测结果不存在或未完成")
    return {"success": True, "data": res}

@router.get("/history")
async def history(limit: int = 20, skip: int = 0):
    await backtest_service.ensure_db()
    user_id = "admin"  # TODO: 鉴权
    return {"success": True, "data": await backtest_service.get_history(user_id, limit, skip)}
```

在 `app/main.py` 参考现有 `include_router` 加：`from app.routers import backtest` + `app.include_router(backtest.router)`。**注意**：`queue_service` 的 `create_task`/`mark_done`/`mark_failed`/`get_status` 方法名以现有实现为准——先读 `app/services/queue_service.py` 对齐真实 API，若方法名不同则适配（本步以对齐现有 queue_service 为准，不要臆造）。

- [ ] **Step 4: 跑测试确认通过**

Run: `./venv/bin/python -m pytest tests/backtest/test_backtest_api.py -v`
Expected: `test_bad_params_rejected` PASS；`test_submit_returns_task_id`(integration) 视 queue_service/鉴权就绪情况 PASS

- [ ] **Step 5: 提交**

```bash
git add app/routers/backtest.py app/main.py tests/backtest/test_backtest_api.py
git commit -m "feat(backtest-web): 回测API路由(提交/状态/结果/历史)"
```

### Task 4: 后端端到端集成

**Files:**
- Test: `tests/backtest/test_backtest_e2e.py`

- [ ] **Step 1: 写集成端到端测试（真实库，提交→轮询→结果）**

```python
# tests/backtest/test_backtest_e2e.py
import pytest, time
from fastapi.testclient import TestClient

@pytest.mark.integration
def test_full_backtest_flow():
    from app.main import app
    client = TestClient(app)
    body = {"symbol":"000001","start_date":"2023-01-01","end_date":"2024-12-31","initial_capital":100000,
            "position":{"parts":1,"reduce_mode":"reduce_one"},
            "buy_rules":[{"left":"ma5","op":"cross_up","right":"ma20"}],"buy_logic":"AND",
            "sell_rules":[{"left":"ma5","op":"cross_down","right":"ma20"}],"sell_logic":"AND"}
    tid = client.post("/api/backtest/run", json=body).json()["data"]["task_id"]
    # 轮询直到完成（BackgroundTasks 在 TestClient 请求返回后已执行）
    r = client.get(f"/api/backtest/result/{tid}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "metrics" in data and len(data["equity_curve"]) > 50
    print("总收益:", data["metrics"]["total_return"], "基准:", data["metrics"]["benchmark_return"])
```

- [ ] **Step 2: 跑并确认端到端跑通**

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit ./venv/bin/python -m pytest tests/backtest/test_backtest_e2e.py -v -m integration -s`
Expected: PASS，打印真实收益（000001 有数据）

- [ ] **Step 3: 提交**

```bash
git add tests/backtest/test_backtest_e2e.py
git commit -m "test(backtest-web): 后端回测端到端集成"
```

---

## Phase 2：前端（实现 + 浏览器验证，无单测框架）

### Task 5: 前端 API 层 + 路由/菜单

**Files:**
- Create: `frontend/src/api/backtest.ts`
- Modify: `frontend/src/router/index.ts`（+ 侧边栏菜单配置文件，参考 Screening 的注册位置）

**Interfaces:**
- Produces: `backtestApi.run(payload)`、`.status(taskId)`、`.result(taskId)`、`.history(params)`（用 `request` 封装，模式参考 `frontend/src/api/analysis.ts`）。

- [ ] **Step 1: 实现 `backtest.ts`**（参考 analysis.ts 的 request 封装）

```typescript
// frontend/src/api/backtest.ts
import request from './request'
export const backtestApi = {
  run: (payload: any) => request.post('/api/backtest/run', payload),
  status: (taskId: string) => request.get(`/api/backtest/status/${taskId}`),
  result: (taskId: string) => request.get(`/api/backtest/result/${taskId}`),
  history: (params?: any) => request.get('/api/backtest/history', { params }),
}
```

- [ ] **Step 2: 注册路由 + 菜单**：在 `frontend/src/router/index.ts` 加 `/backtest` 路由指向 `views/Backtest/index.vue`；在侧边栏菜单配置里加「策略回测」入口（找到 Screening 的注册处，照同样结构加一条）。

- [ ] **Step 3: 构建确认无报错**

Run: `cd frontend && npm run build`
Expected: 构建通过（此时 index.vue 可先放占位内容）

- [ ] **Step 4: 提交**

```bash
git add frontend/src/api/backtest.ts frontend/src/router/index.ts
git commit -m "feat(backtest-web): 前端回测API与路由菜单"
```

### Task 6: 条件积木编辑器 `ConditionEditor.vue`

**Files:**
- Create: `frontend/src/views/Backtest/components/ConditionEditor.vue`

**Interfaces:**
- Props: `modelValue: {rules: [{left,op,right}], logic: 'AND'|'OR'}`；`title: string`（如"买入条件"）。
- Emits: `update:modelValue`。
- 行为：表格式规则行，每行 [指标下拉][比较符下拉][值：数字输入 或 指标下拉]；行尾删除按钮；"+ 添加条件"；组头 AND/OR 切换。指标选项常量：ma5/ma10/ma20/ma60、ema12/ema26、macd_dif/macd_dea/macd_bar、rsi6/rsi12/rsi14、boll_up/boll_mid/boll_low、close、volume；比较符：`>` `<` `cross_up(上穿)` `cross_down(下穿)`。

- [ ] **Step 1: 实现 `ConditionEditor.vue`**（Element Plus el-select/el-input/el-button；用可编辑的规则数组，change 时 emit update:modelValue，序列化为 {rules, logic}）。核心结构：
  - 组头：`<el-radio-group v-model="logic">` AND/OR
  - 每条规则一行：指标 `<el-select>` + 比较符 `<el-select>` + 值（数字或指标，用 `<el-input>`/`<el-select>` 切换）+ 删除按钮
  - 底部："+ 添加条件"按钮 push 一个空规则
  - watch rules/logic → emit `update:modelValue`

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/Backtest/components/ConditionEditor.vue
git commit -m "feat(backtest-web): 条件积木编辑器组件"
```

### Task 7: 结果展示组件（净值曲线 + 指标卡 + 交易明细）

**Files:**
- Create: `frontend/src/views/Backtest/components/EquityChart.vue`
- Create: `frontend/src/views/Backtest/components/MetricsCards.vue`
- Create: `frontend/src/views/Backtest/components/TradesTable.vue`

**Interfaces:**
- `EquityChart`：Props `equityCurve: [[date, value]]`、`benchmarkCurve: [[date, value]]`。用 vue-echarts 画双折线（策略净值 vs 买入持有）。
- `MetricsCards`：Props `metrics: dict`。展示 total_return/annual_return/max_drawdown/sharpe/win_rate/profit_loss_ratio/trade_count/avg_holding_days/benchmark_return，用卡片网格（百分比字段乘 100 + %）。
- `TradesTable`：Props `trades: [{date,side,price,shares,commission,stamp_tax,transfer_fee,pnl}]`。el-table 展示，买卖用 tag 区分，pnl 正红负绿（A股习惯）。

- [ ] **Step 1: 实现三个组件**（EquityChart 用 `<v-chart :option="...">`，option 为双 series line；MetricsCards 用 el-row/el-col 卡片；TradesTable 用 el-table）

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/Backtest/components/EquityChart.vue frontend/src/views/Backtest/components/MetricsCards.vue frontend/src/views/Backtest/components/TradesTable.vue
git commit -m "feat(backtest-web): 净值曲线/指标卡/交易明细组件"
```

### Task 8: 主页组装 `index.vue` + 历史列表

**Files:**
- Create: `frontend/src/views/Backtest/index.vue`

**Interfaces:**
- 组装：输入区（`MultiMarketStockSearch` 选股票 + 日期区间 + 初始资金 + 成本参数 + 份数/减仓模式 + 两个 `ConditionEditor`（买入/卖出））→「开始回测」→ `backtestApi.run` 拿 task_id → 轮询 `status` 直到完成 → `result` → 传给 `EquityChart`/`MetricsCards`/`TradesTable`。
- 历史列表：`backtestApi.history` 拉列表，点击某条 → `result(task_id)` 加载回看。

- [ ] **Step 1: 实现 `index.vue`**（组合上述组件；轮询逻辑参考 analysis 页；提交时把两个 ConditionEditor 的 {rules,logic} 拼进 payload）

- [ ] **Step 2: 构建确认**

Run: `cd frontend && npm run build`
Expected: 构建通过

- [ ] **Step 3: 提交**

```bash
git add frontend/src/views/Backtest/index.vue
git commit -m "feat(backtest-web): 策略回测主页(输入+提交+轮询+结果+历史)"
```

### Task 9: 端到端浏览器验证 + 重建前端镜像

**Files:** 无新增（验证任务）

- [ ] **Step 1: 重建前端镜像并起容器**

```bash
docker compose -f docker-compose.yml build frontend
docker compose -f docker-compose.yml up -d frontend
```

- [ ] **Step 2: 浏览器端到端验证**（用 run/browse 技能或手动）：打开 `http://localhost:3000` → 登录 admin/admin123 → 进「策略回测」→ 选 000001、区间 2023-2024、配双均线策略（买入 ma5 上穿 ma20、卖出 ma5 下穿 ma20）→ 开始回测 → 确认：进度→净值曲线（策略 vs 买入持有）→ 指标卡有数字 → 交易明细表有记录 → 历史列表出现该次回测。

- [ ] **Step 3: 记录验证结果**（截图或文字确认各环节正常），有 bug 则回到对应 Task 修复。

---

## Self-Review（作者自查记录）

- **Spec 覆盖**：参数映射→Task1；worker(run_in_executor)→Task2；API(run/status/result/history)→Task3；后端e2e→Task4；前端API/路由→Task5；条件积木编辑器→Task6；净值曲线/指标卡/明细→Task7；主页+历史→Task8；浏览器验证→Task9。✅
- **占位符**：后端各步有真实测试+实现代码;前端因无测试框架,用"构建通过+浏览器验证",组件实现给了结构与 props 契约(非逐行代码,因 Vue 组件较长,但接口/props/行为明确)。
- **类型一致**：payload 字段(symbol/start_date/cost/position/buy_rules{left,op,right}/buy_logic...)在 mapper、service、API、前端 API、编辑器序列化间一致;`run_backtest` 签名与 Plan1 一致;结果字段(equity_curve/benchmark_curve/metrics/trades)贯穿 service→API→前端组件。
- **已知对齐点**：`queue_service` 的方法名(create_task/mark_done/mark_failed/get_status)与鉴权取 user_id 的方式,Task3 要求实现时读现有代码对齐,不臆造。

## 后续（非本期）

- 多股组合回测、AI 信号回测(阶段③)、回撤/月度热力图、策略保存与参数寻优。
