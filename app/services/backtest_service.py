"""回测异步 worker：主循环预取 K 线 + 线程池跑 Plan 1 回测引擎，结果落库。

关键约束（主循环预取，方案 B）：`tradingagents.backtest.run_backtest` 在
`bars=None` 时内部会走 `data_feed.load_bars`，其同步版本用 `asyncio.run(...)`
另起一个独立事件循环——而本 worker 运行在 FastAPI 的事件循环协程中，若直接
同步调用 `run_backtest(bars=None)` 会撞上 "asyncio.run() cannot be called
from a running event loop"；即便把 `run_backtest` 整体丢进线程池
（`run_in_executor`）以避开这一层，线程池新线程里 `load_bars` 自己另建的
事件循环，去用进程级共享、已绑定在**主事件循环**上的 Motor 客户端
（`HistoricalDataService` -> `app.core.database.get_database()`）时，又会
撞上 "attached to a different loop"（Motor 客户端不可跨事件循环/线程复用）。

因此正确的编排是：把"取数据"和"跑计算"拆开——
- 取数据（IO）：留在**主事件循环**里，用 `data_feed.async_load_bars`
  直接 `await`（不新建事件循环，安全复用主循环绑定的 Motor 客户端）。
- 跑计算（纯 CPU，含指标计算等同步逻辑）：把已经预取好 bars 的
  `run_backtest(..., bars=bars)` 丢进线程池（`run_in_executor`），此时
  `run_backtest` 不会再触发 `load_bars`/`asyncio.run` 分支，线程池内不产生
  任何新的事件循环，自然不会有事件循环冲突。
"""
import asyncio
from datetime import datetime, timezone

import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import run_backtest
from tradingagents.backtest.data_feed import async_load_bars


async def ensure_db() -> None:
    """确保 MongoDB 已初始化（幂等）。

    `db_manager.init_mongodb()` 只会设置 `db_manager.mongo_db` 等实例属性，
    而 `get_mongo_db()` 读取的是 `app.core.database` 模块级全局变量
    `mongo_db`（应用启动时由 `init_database()` 一并设置）。为了让本模块
    既能独立初始化数据库连接，又能复用现有的 `get_mongo_db()`，这里在
    初始化后同步回填模块级全局变量。
    """
    if getattr(db_manager, "mongo_db", None) is None:
        await db_manager.init_mongodb()
    # 回填模块级全局变量，使 get_mongo_db() 可用（保持与其余路由一致的取库方式）
    db_module.mongo_client = db_manager.mongo_client
    db_module.mongo_db = db_manager.mongo_db


def _collection():
    """获取 backtest_results 集合。"""
    return get_mongo_db().backtest_results


def _tasks_collection():
    """获取 backtest_tasks 集合（记录任务状态，与结果集合分开存放）。"""
    return get_mongo_db().backtest_tasks


async def run_backtest_task(task_id: str, user_id: str, payload: dict, bars=None) -> dict:
    """跑一次回测任务：参数映射 -> 线程池执行引擎 -> 落库 -> 返回结果字典。

    Args:
        task_id: 任务 ID，用作落库的唯一键（upsert）。
        user_id: 发起用户 ID。
        payload: 前端回测请求 payload（见 backtest_param_mapper.build_backtest_args）。
        bars: 预取的 K 线序列，测试场景可显式注入以绕开真实查库；为 None
            （生产环境默认）时本函数会先在当前主事件循环里用
            `data_feed.async_load_bars` 预取好 bars，再传给线程池里的
            `run_backtest`（见模块顶部关键约束说明）。

    Returns:
        `BacktestResult.to_dict()` 的结果字典（含 config/equity_curve/
        benchmark_curve/metrics/trades）。
    """
    args = build_backtest_args(payload)
    if bars is None:
        # 主循环预取（方案 B）：留在当前（主）事件循环里 await，安全复用主循环
        # 绑定的 Motor 客户端；st_service 传 None——Web 路径的
        # backtest_param_mapper 不产生 ST 服务实例。
        config = args["config"]
        bars = await async_load_bars(config.symbol, config.start_date, config.end_date)
    loop = asyncio.get_event_loop()
    # bars 已预取好，run_backtest 不会再走 data_feed.load_bars/asyncio.run 分支，
    # 线程池里只跑纯 CPU 计算，不产生新的事件循环，自然不会有事件循环冲突。
    result = await loop.run_in_executor(
        None,
        lambda: run_backtest(
            args["config"], args["buy_rules"], args["buy_logic"],
            args["sell_rules"], args["sell_logic"], bars=bars,
        ),
    )
    d = result.to_dict()
    doc = {
        "task_id": task_id,
        "user_id": user_id,
        "symbol": payload["symbol"],
        "config": d["config"],
        "equity_curve": d["equity_curve"],
        "benchmark_curve": d["benchmark_curve"],
        "metrics": d["metrics"],
        "trades": d["trades"],
        "created_at": datetime.now(timezone.utc),
    }
    await _collection().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return d


async def set_task_status(task_id: str, status: str, error: str = None, user_id: str = None) -> None:
    """写入/更新回测任务状态（backtest_tasks 集合，按 task_id upsert）。

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
    """按 task_id 取回测任务状态记录，不存在时返回 None。"""
    return await _tasks_collection().find_one({"task_id": task_id}, {"_id": 0})


async def get_result(task_id: str):
    """按 task_id 取单条回测结果，不存在时返回 None。"""
    return await _collection().find_one({"task_id": task_id}, {"_id": 0})


async def get_history(user_id: str, limit: int = 20, skip: int = 0) -> list:
    """取某用户的历史回测摘要列表，按创建时间倒序。"""
    cursor = _collection().find(
        {"user_id": user_id},
        {"_id": 0, "task_id": 1, "symbol": 1, "config": 1, "metrics.total_return": 1, "created_at": 1},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return [d async for d in cursor]
