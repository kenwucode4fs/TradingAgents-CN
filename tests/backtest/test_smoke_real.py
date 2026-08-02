"""端到端冒烟测试：真实数据（MongoDB 中已同步的 000001 前复权日线）跑通完整回测引擎。

背景：前面各 Task 都在 bars 由测试手工构造的前提下验证了引擎各环节，本测试是
唯一一个不传 bars、走 `run_backtest` 内部 `data_feed.load_bars` 真实查库的用例，
用来证明"数据层 -> 策略 -> 撮合 -> 绩效 -> 序列化"整条链路接上真实 MongoDB 数据可用。

区间选择：库里 000001 的 tushare 前复权价（close_qfq 等）目前覆盖
2026-01-05 ~ 2026-07-31（由 Task 1 的 `TushareSyncService.sync_historical_qfq`
同步写入，见 tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields），
共 139 个交易日且无缺口，故本测试直接用这个区间，无需再跑一次同步。
"""
import pytest


@pytest.mark.integration
def test_real_000001_double_ma():
    """000001 双均线（MA5 上穿 MA20 买 / 下穿卖）在真实库数据上跑通 run_backtest。

    `run_backtest(bars=None)` 是同步函数，内部经 `data_feed.load_bars` 自行
    `asyncio.run(...)` 查库——也就是说真正发起 MongoDB 查询的事件循环，是
    `run_backtest` 调用时才新建、随调用结束就关闭的那一个。

    这决定了这里不能照抄其余集成测试（test_qfq_sync.py、test_st_status.py）里
    "先 `asyncio.run(db_manager.init_mongodb())` 建连接、再另起一个 `asyncio.run`
    做查询"的两段式写法：`init_mongodb()` 里会 `await mongo_client.admin.command
    ("ping")`，这一步会把 motor 的 AsyncIOMotorClient 实际绑定到"建连接"用的
    那个事件循环上；等这个 `asyncio.run` 返回、循环被关闭后，`load_bars` 内部
    另开的新循环再复用同一个 client 发请求，就会报 `RuntimeError: Event loop
    is closed`（本测试最初就是这样失败的）。

    解决办法：只构造 `AsyncIOMotorClient`（构造本身不需要运行中的事件循环，
    不会触发任何网络 I/O）并挂到 `db_manager`/全局变量上，不在这里主动 ping；
    client 与运行中的事件循环的绑定，留到 `load_bars` 内部那个唯一的
    `asyncio.run` 里首次真正查询时才发生，从而保证"建连接"和"用连接"发生在
    同一个事件循环里。
    """
    from motor.motor_asyncio import AsyncIOMotorClient

    from app.core import database as db_module
    from app.core.config import settings
    from tradingagents.backtest import run_backtest, BacktestConfig, Condition

    client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=settings.MONGO_MAX_CONNECTIONS,
        minPoolSize=settings.MONGO_MIN_CONNECTIONS,
        serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,
        connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,
        socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,
    )
    db = client[settings.MONGO_DB]
    db_module.db_manager.mongo_client = client
    db_module.db_manager.mongo_db = db
    db_module.mongo_client = client
    db_module.mongo_db = db
    try:
        cfg = BacktestConfig(symbol="000001", start_date="2026-01-01", end_date="2026-07-31")
        res = run_backtest(
            cfg,
            buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
            sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
        )
    finally:
        client.close()
        db_module.db_manager.mongo_client = None
        db_module.db_manager.mongo_db = None
        db_module.mongo_client = None
        db_module.mongo_db = None

    d = res.to_dict()

    assert len(d["equity_curve"]) > 100
    assert "total_return" in d["metrics"]
    assert "benchmark_return" in d["metrics"]

    print("总收益:", d["metrics"]["total_return"], "基准:", d["metrics"]["benchmark_return"])
