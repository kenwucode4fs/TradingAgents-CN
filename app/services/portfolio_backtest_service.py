"""组合回测（子项目 2b）后端服务。

关键约束（跨事件循环避坑，同阶段① `backtest_service.py`/2a
`factor_screening_service.py` 的血泪教训）：
`load_monthly_sections`/`load_price_panel`/`load_benchmark` 都是纯异步 Motor
查询，留在**主事件循环**里直接 `await`；把数据组装好之后，只把纯 CPU 计算的
`run_portfolio_backtest` 丢进 `run_in_executor` 的线程池。绝不能在线程池里
再触库或另起事件循环。

防幸存者偏差：`run_task` 在 `precomputed=None`（生产路径）时，候选 codes
取自各月末截面 `stock_monthly_basic` 里出现过的 code 之并集，而不是当前
最新截面的 `stock_screening_view`（后者会漏掉回测区间内已退市的股票，
导致选股结果系统性偏好"活到最后"的股票）。

`load_price_panel` 时间窗（同 2a `fetch_price_series` 的血泪教训）：候选池
是全市场几千只股票的防幸存者并集，若查询不加 `trade_date` 下界，会把每只
候选股从上市到 `end` 的全部 ~20 年历史都拉出来（千万行级别），游标遍历
太慢会被 MongoDB 回收报 `CursorNotFound`（code 43）。回测最早的调仓日
≈ `start`，引擎在该日算最长因子（`high_250_prox` 需约 250 交易日）只需要
该日往前约 250 交易日的历史，故取 `[start - LOOKBACK_CALENDAR_DAYS 自然日,
end]` 的时间窗已覆盖有余（500 自然日 ≈ 340 交易日）。cutoff 必须用带横线
的 "YYYY-MM-DD" 格式，与 `stock_daily_quotes.trade_date` 一致——2a 曾因
用无横线的 "%Y%m%d" 与带横线数据做字符串比较，'-' (0x2D) < '0' (0x30)
导致整年数据被误判过滤掉。
"""
import asyncio
from datetime import datetime, timedelta, timezone

import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from tradingagents.backtest.types import CostConfig
from tradingagents.portfolio import run_portfolio_backtest

BENCHMARK_TS = "000300.SH"

# load_price_panel 时间窗下界（自然日）。含义与取值同 factor_screening_service
# 的 LOOKBACK_CALENDAR_DAYS：覆盖引擎最长因子（high_250_prox ≈ 250 交易日）
# 所需的历史，又避免无界拉取全市场候选股近 20 年全部历史行导致游标超时。
LOOKBACK_CALENDAR_DAYS = 500


async def ensure_db() -> None:
    """确保 MongoDB 已初始化（幂等），并回填 `app.core.database` 模块级全局变量。

    与 `factor_screening_service.ensure_db` 同构：`db_manager.init_mongodb()`
    只设置 `db_manager.mongo_db` 等实例属性，`get_mongo_db()` 读取的是模块级
    全局变量，这里初始化后同步回填，使本模块可独立初始化也能复用
    `get_mongo_db()`。
    """
    if getattr(db_manager, "mongo_db", None) is None:
        await db_manager.init_mongodb()
    db_module.mongo_client = db_manager.mongo_client
    db_module.mongo_db = db_manager.mongo_db


def _results():
    """获取 portfolio_backtest_results 集合。"""
    return get_mongo_db().portfolio_backtest_results


def _tasks_collection():
    """获取 portfolio_backtest_tasks 集合（记录任务状态，与结果集合分开存放）。"""
    return get_mongo_db().portfolio_backtest_tasks


async def load_monthly_sections(db, start: str, end: str) -> dict:
    """从 `stock_monthly_basic` 取 [start, end] 内各月末截面。

    Returns:
        `{trade_date: {code: {pe, pb, total_mv}}}`。
    """
    out = {}
    async for d in db.stock_monthly_basic.find(
            {"trade_date": {"$gte": start, "$lte": end}}, {"_id": 0}):
        out.setdefault(d["trade_date"], {})[d["code"]] = {
            "pe": d.get("pe"), "pb": d.get("pb"), "total_mv": d.get("total_mv")}
    return out


async def load_price_panel(db, codes, start: str, end: str) -> dict:
    """从 `stock_daily_quotes` 批量取 codes 的 `[start-500自然日, end]` 前复权日线。

    时间窗下界见模块顶部 `LOOKBACK_CALENDAR_DAYS` 说明：候选池是全市场防
    幸存者并集（几千只股票），若不加下界会把每只候选股从上市到 `end` 的
    全部历史都拉出来（千万行级别），导致游标遍历超时被 MongoDB 回收
    （`CursorNotFound`，code 43）。

    Returns:
        `{code: [{date, open, close, volume}...]}`，按 trade_date 升序，
        过滤 close_qfq 为 None 的记录。
    """
    cutoff = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")
    out = {}
    cur = db.stock_daily_quotes.find(
        {"symbol": {"$in": list(codes)}, "trade_date": {"$gte": cutoff, "$lte": end}, "close_qfq": {"$ne": None}},
        {"_id": 0, "symbol": 1, "trade_date": 1, "open_qfq": 1, "close_qfq": 1, "volume": 1},
    ).sort("trade_date", 1)
    async for d in cur:
        out.setdefault(d["symbol"], []).append({
            "date": d["trade_date"], "open": d.get("open_qfq"),
            "close": d["close_qfq"], "volume": d.get("volume") or 0})
    return out


async def load_benchmark(db, ts_code: str, start: str, end: str) -> list:
    """从 `index_daily_quotes` 取基准指数收盘价序列。

    Returns:
        `[(date, close)...]`，按 trade_date 升序。
    """
    rows = []
    cur = db.index_daily_quotes.find(
        {"ts_code": ts_code, "trade_date": {"$gte": start, "$lte": end}}, {"_id": 0},
    ).sort("trade_date", 1)
    async for d in cur:
        rows.append((d["trade_date"], d["close"]))
    return rows


async def run_task(task_id: str, user_id: str, payload: dict, precomputed: dict = None) -> dict:
    """跑一次组合回测任务：预取（主循环）-> 线程池跑引擎 -> 落库 -> 返回结果字典。

    Args:
        task_id: 任务 ID，用作落库的唯一键（upsert）。
        user_id: 发起用户 ID。
        payload: 前端组合回测请求 payload，含
            `factors`/`start_date`/`end_date`/`top_n`/`initial_capital`/`cost`。
        precomputed: 预取好的 `{monthly_sections, price_panel, benchmark}`，
            测试场景可显式注入以绕开真实查库；为 None（生产环境默认）时
            本函数会先在当前主事件循环里依次 `await load_monthly_sections`/
            `load_price_panel`/`load_benchmark` 预取好数据，再传给线程池里
            的 `run_portfolio_backtest`（见模块顶部关键约束说明）。
    """
    start, end = payload["start_date"], payload["end_date"]
    if precomputed:
        sections = precomputed["monthly_sections"]
        panel = precomputed["price_panel"]
        benchmark = precomputed["benchmark"]
    else:
        db = get_mongo_db()
        sections = await load_monthly_sections(db, start, end)
        # 防幸存者偏差：候选 codes 来自各月末截面的并集，而非最新截面
        # stock_screening_view（后者不含回测区间内已退市的股票）。
        codes = {c for sec in sections.values() for c in sec}
        panel = await load_price_panel(db, codes, start, end)
        benchmark = await load_benchmark(db, BENCHMARK_TS, start, end)

    c = payload.get("cost") or {}
    config = {
        "start_date": start,
        "end_date": end,
        "initial_capital": float(payload.get("initial_capital", 100000)),
        "cost": CostConfig(**{
            k: c[k] for k in
            ("commission_rate", "min_commission", "stamp_tax_rate", "transfer_fee_rate")
            if k in c
        }),
    }

    loop = asyncio.get_event_loop()
    # sections/panel/benchmark 已预取好，run_portfolio_backtest 是纯 CPU
    # 计算，线程池里不产生任何新的事件循环，也不触库，自然不会有事件循环冲突。
    result = await loop.run_in_executor(
        None,
        lambda: run_portfolio_backtest(
            config, payload["factors"], sections, panel, benchmark, payload.get("top_n", 20)),
    )

    doc = {
        "task_id": task_id,
        "user_id": user_id,
        "config": result["config"],
        "equity_curve": result["equity_curve"],
        "benchmark_curve": result["benchmark_curve"],
        "metrics": result["metrics"],
        "rebalances": result["rebalances"],
        "created_at": datetime.now(timezone.utc),
    }
    await _results().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return doc


async def set_task_status(task_id: str, status: str, error: str = None, user_id: str = None) -> None:
    """写入/更新组合回测任务状态（portfolio_backtest_tasks 集合，按 task_id upsert）。

    路由层用法：POST /run 时先以 status="running" 插入一条记录（附带
    user_id），BackgroundTasks 跑完后再调用一次更新为 "done"/"failed"
    （失败时附带 error）。

    Args:
        task_id: 任务 ID。
        status: 任务状态，如 "running"/"done"/"failed"。
        error: 失败原因，仅 status="failed" 时传入。
        user_id: 发起用户 ID，仅创建任务记录时需要传入。
    """
    now = datetime.now(timezone.utc)
    fields = {"task_id": task_id, "status": status, "updated_at": now}
    if error is not None:
        fields["error"] = error
    if user_id is not None:
        fields["user_id"] = user_id
    await _tasks_collection().update_one(
        {"task_id": task_id},
        {"$set": fields, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )


async def get_task_status(task_id: str):
    """按 task_id 取组合回测任务状态记录，不存在时返回 None。"""
    return await _tasks_collection().find_one({"task_id": task_id}, {"_id": 0})


async def get_result(task_id: str):
    """按 task_id 取单条组合回测结果，不存在时返回 None。"""
    return await _results().find_one({"task_id": task_id}, {"_id": 0})


async def get_history(user_id: str, limit: int = 20, skip: int = 0) -> list:
    """取某用户的历史组合回测结果摘要列表，按创建时间倒序。"""
    cursor = _results().find(
        {"user_id": user_id},
        {"_id": 0, "task_id": 1, "config": 1, "metrics": 1, "created_at": 1},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return [d async for d in cursor]
