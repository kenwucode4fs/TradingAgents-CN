"""回测异步 worker：用线程池跑 Plan 1 回测引擎，结果落库。

关键约束：`tradingagents.backtest.run_backtest` 内部（经 data_feed.load_bars）
会调用 `asyncio.run(...)`。而本 worker 运行在 FastAPI 的事件循环协程中，
若直接同步调用会撞上"asyncio.run() cannot be called from a running event loop"。
因此必须通过 `loop.run_in_executor(None, ...)` 把 run_backtest 丢到线程池里，
在一个独立、非运行中的事件循环里执行，从而避免事件循环冲突。
"""
import asyncio
from datetime import datetime, timezone

import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import run_backtest


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
        bars: 预取的 K 线序列，测试场景注入以绕开 tushare；生产环境为 None
            时由引擎内部通过 data_feed.load_bars 从库读取。

    Returns:
        `BacktestResult.to_dict()` 的结果字典（含 config/equity_curve/
        benchmark_curve/metrics/trades）。
    """
    args = build_backtest_args(payload)
    loop = asyncio.get_event_loop()
    # 关键：run_backtest 内部有 asyncio.run，必须丢到线程池（独立事件循环）执行，
    # 避免与当前（FastAPI）事件循环冲突。
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
