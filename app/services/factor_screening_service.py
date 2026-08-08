"""因子打分选股（子项目 2a）后端选股服务。

关键约束（跨事件循环避坑，同阶段① `backtest_service.py` 的血泪教训）：
候选池查询（`get_candidates`）与日线预取（`fetch_price_series`）都是纯
异步 Motor 查询，留在**主事件循环**里直接 `await`；把数据组装好之后，
只把纯 CPU 计算的 `score_universe` 丢进 `run_in_executor` 的线程池。
绝不能在线程池里再触库或另起事件循环——否则会撞上 Motor 客户端
"attached to a different loop" 的问题。
"""
import asyncio
from datetime import date, datetime, timedelta, timezone

import app.core.database as db_module
from app.core.database import get_mongo_db, db_manager
from tradingagents.factor import score_universe

# fetch_price_series 时间窗下界（自然日）。打分最长的因子是 250 交易日的
# high_250_prox，260 个交易日 ≈ 375~390 自然日；停牌/节假日会进一步拉长
# "最近 N 个交易日"对应的自然日跨度，留足余量取约 500 自然日（覆盖
# ~345 交易日），既足够覆盖默认 lookback=260，又避免不设下界时把每只
# 股票近 20 年全部历史行（千万级行）拉进内存排序导致 OOM/选股超时。
LOOKBACK_CALENDAR_DAYS = 500


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


def _results():
    """获取 factor_screen_results 集合。"""
    return get_mongo_db().factor_screen_results


def _tasks_collection():
    """获取 factor_screen_tasks 集合（记录任务状态，与结果集合分开存放）。"""
    return get_mongo_db().factor_screen_tasks


def _is_new(list_date) -> bool:
    """判断是否次新股（上市不满 1 年）。list_date 形如 "20230101"，空串或格式异常视为未知（不剔除）。"""
    if not list_date or len(str(list_date)) != 8:
        return False
    try:
        y, m, d = int(str(list_date)[:4]), int(str(list_date)[4:6]), int(str(list_date)[6:8])
        days = (date.today() - date(y, m, d)).days
        return days < 365
    except ValueError:
        return False


async def get_candidates(universe: dict) -> list:
    """从 `stock_screening_view` 按选股域取候选截面。

    Args:
        universe: `{exclude_st, exclude_new, industries, mv_min, mv_max}`。

    Returns:
        `[{code, name, industry, cross: {pe, pb, total_mv, amount, close}}]`。
    """
    q = {}
    if universe.get("exclude_st"):
        q["name"] = {"$not": {"$regex": "ST"}}
    if universe.get("industries"):
        q["industry"] = {"$in": universe["industries"]}
    mv = {}
    if universe.get("mv_min") is not None:
        mv["$gte"] = universe["mv_min"]
    if universe.get("mv_max") is not None:
        mv["$lte"] = universe["mv_max"]
    if mv:
        q["total_mv"] = mv
    proj = {"_id": 0, "code": 1, "name": 1, "industry": 1, "pe": 1, "pb": 1,
            "total_mv": 1, "amount": 1, "close": 1, "list_date": 1, "trade_date": 1}
    # stock_screening_view 同一 code 可能存在多条记录（同一 trade_date 下
    # 截面值不一致，甚至 total_mv 缺失），需在应用层按 code 去重，每股只保留
    # 一条"最优"记录，否则同一代码会被当成多只候选混进榜单。
    best = {}  # code -> 选中的原始文档
    async for d in get_mongo_db().stock_screening_view.find(q, proj):
        if universe.get("exclude_new") and _is_new(d.get("list_date")):
            continue
        code = d["code"]
        cur = best.get(code)
        if cur is None or _prefer(d, cur):
            best[code] = d
    out = []
    for d in best.values():
        out.append({
            "code": d["code"], "name": d.get("name", ""), "industry": d.get("industry", ""),
            "cross": {"pe": d.get("pe"), "pb": d.get("pb"), "total_mv": d.get("total_mv"),
                      "amount": d.get("amount"), "close": d.get("close")},
        })
    return out


def _prefer(new: dict, old: dict) -> bool:
    """`get_candidates` 去重时，new 是否比 old 更该保留：total_mv 非空优先，其次 trade_date 更新。"""
    new_has = new.get("total_mv") is not None
    old_has = old.get("total_mv") is not None
    if new_has != old_has:
        return new_has
    return str(new.get("trade_date") or "") > str(old.get("trade_date") or "")


async def fetch_price_series(codes: list, lookback: int = 260) -> dict:
    """批量从 `stock_daily_quotes` 取每股最近 `lookback` 条前复权序列。

    查询按 `LOOKBACK_CALENDAR_DAYS` 自然日加了 trade_date 下界，避免候选池
    为全市场（选股域留空的常见用例）时无界拉取每股近 20 年全部历史行导致
    内存/耗时爆炸；时间窗内每股条数可能略多于 `lookback`，仍用客户端
    `[-lookback:]` 截尾取最近的 `lookback` 条。

    Returns:
        `{code: {"closes": [...], "volumes": [...]}}`，按 trade_date 升序，
        过滤 close_qfq 为 None 的记录。
    """
    proj = {"_id": 0, "symbol": 1, "trade_date": 1, "close_qfq": 1, "volume": 1}
    cutoff = (datetime.now() - timedelta(days=LOOKBACK_CALENDAR_DAYS)).strftime("%Y%m%d")
    cur = get_mongo_db().stock_daily_quotes.find(
        {"symbol": {"$in": codes}, "close_qfq": {"$ne": None}, "trade_date": {"$gte": cutoff}}, proj
    ).sort("trade_date", 1)
    by_code = {}
    async for d in cur:
        by_code.setdefault(d["symbol"], []).append(d)
    out = {}
    for code, rows in by_code.items():
        rows = rows[-lookback:]
        out[code] = {"closes": [r["close_qfq"] for r in rows],
                     "volumes": [r.get("volume") or 0 for r in rows]}
    return out


async def run_screen_task(task_id: str, user_id: str, payload: dict, stocks=None) -> dict:
    """跑一次选股任务：候选池+预取（主循环）-> 线程池打分 -> 落库 -> 返回结果字典。

    Args:
        task_id: 任务 ID，用作落库的唯一键（upsert）。
        user_id: 发起用户 ID。
        payload: 前端选股请求 payload，含 `factors`/`universe`/`top_n`。
        stocks: 预取好的候选股+序列，测试场景可显式注入以绕开真实查库；为
            None（生产环境默认）时本函数会先在当前主事件循环里依次
            `await get_candidates` 和 `await fetch_price_series` 预取好
            stocks，再传给线程池里的 `score_universe`（见模块顶部关键
            约束说明）。
    """
    if stocks is None:
        candidates = await get_candidates(payload.get("universe", {}))
        series = await fetch_price_series([c["code"] for c in candidates])
        stocks = []
        for c in candidates:
            s = series.get(c["code"], {"closes": [], "volumes": []})
            stocks.append({**c, "closes": s["closes"], "volumes": s["volumes"]})
    loop = asyncio.get_event_loop()
    # stocks 已预取好，score_universe 是纯 CPU 计算，线程池里不产生任何新的
    # 事件循环，也不触库，自然不会有事件循环冲突。
    items = await loop.run_in_executor(
        None,
        lambda: score_universe(stocks, payload["factors"], payload.get("top_n", 50)),
    )
    doc = {
        "task_id": task_id,
        "user_id": user_id,
        "config": payload,
        "items": items,
        "created_at": datetime.now(timezone.utc),
    }
    await _results().update_one({"task_id": task_id}, {"$set": doc}, upsert=True)
    return doc


async def set_task_status(task_id: str, status: str, error: str = None, user_id: str = None) -> None:
    """写入/更新选股任务状态（factor_screen_tasks 集合，按 task_id upsert）。

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
    """按 task_id 取选股任务状态记录，不存在时返回 None。"""
    return await _tasks_collection().find_one({"task_id": task_id}, {"_id": 0})


async def get_result(task_id: str):
    """按 task_id 取单条选股结果，不存在时返回 None。"""
    return await _results().find_one({"task_id": task_id}, {"_id": 0})


async def get_history(user_id: str, limit: int = 20, skip: int = 0) -> list:
    """取某用户的历史选股结果摘要列表，按创建时间倒序。"""
    cursor = _results().find(
        {"user_id": user_id},
        {"_id": 0, "task_id": 1, "config": 1, "created_at": 1},
    ).sort("created_at", -1).skip(skip).limit(limit)
    return [d async for d in cursor]
