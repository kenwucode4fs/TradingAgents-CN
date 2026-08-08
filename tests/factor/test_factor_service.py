import pytest
from app.services import factor_screening_service as svc
from app.core.database import db_manager


def _reset_mongo_client():
    """重置 db_manager 的 mongo 客户端，强制下次 ensure_db() 重新连接。

    Motor 的 AsyncIOMotorClient 会惰性绑定到"首次使用时正在运行的事件循环"，
    绑定后不可跨循环复用。每个测试函数各自 asyncio.run() 出一个独立事件循环，
    若沿用上一个测试遗留的模块级单例客户端，会在新循环里触发
    `RuntimeError: Event loop is closed`。真实的 FastAPI 应用生命周期内只有
    一个常驻事件循环，不会遇到此问题；这里仅为保证测试间相互独立
    （同构自 tests/backtest/test_backtest_service.py）。
    """
    db_manager.mongo_client = None
    db_manager.mongo_db = None


@pytest.mark.integration
def test_run_screen_task_with_injected_stocks(monkeypatch):
    import asyncio

    async def _run():
        _reset_mongo_client()
        await svc.ensure_db()
        stocks = [
            {"code": "000001", "name": "平安银行", "industry": "银行",
             "cross": {"pe": 5.0, "pb": 0.5, "total_mv": 2000.0, "amount": 1.0, "close": 11.0},
             "closes": [10.0 + i for i in range(130)], "volumes": [1.0] * 130},
            {"code": "600000", "name": "浦发银行", "industry": "银行",
             "cross": {"pe": 6.0, "pb": 0.6, "total_mv": 3000.0, "amount": 1.0, "close": 8.0},
             "closes": [20.0 - i * 0.05 for i in range(130)], "volumes": [1.0] * 130},
        ]
        payload = {"factors": [{"key": "pe", "weight": 1, "direction": "asc"},
                               {"key": "mom_20", "weight": 1, "direction": "desc"}],
                   "universe": {}, "top_n": 10}
        res = await svc.run_screen_task("t-fac-1", "user-x", payload, stocks=stocks)
        assert len(res["items"]) == 2
        assert res["items"][0]["rank"] == 1
        # 落库可查
        got = await svc.get_result("t-fac-1")
        assert got is not None and got["user_id"] == "user-x"
        assert len(got["items"]) == 2

    asyncio.run(_run())


@pytest.mark.integration
def test_get_candidates_dedup_by_code():
    """stock_screening_view 同一 code 可能有多条记录，get_candidates 需按 code 去重，
    每股只保留一条最优记录（total_mv 非空优先，其次 trade_date 更新）。"""
    import asyncio

    async def _run():
        _reset_mongo_client()
        await svc.ensure_db()
        candidates = await svc.get_candidates({})
        codes = [c["code"] for c in candidates]
        assert len(codes) == len(set(codes)), "候选池不应有重复 code"
        # 候选数应与 distinct code 量级一致，远小于 stock_screening_view 总文档数
        total_docs = await svc.get_mongo_db().stock_screening_view.count_documents({})
        assert len(codes) < total_docs

    asyncio.run(_run())


@pytest.mark.integration
def test_fetch_price_series_bounded_by_time_window():
    """fetch_price_series 需按 LOOKBACK_CALENDAR_DAYS 加 trade_date 下界，避免候选池为
    全市场（选股域留空的常见用例）时把每股近 20 年全部历史行无界拉进内存排序。"""
    import asyncio

    async def _run():
        _reset_mongo_client()
        await svc.ensure_db()
        # 用全市场候选池（选股域留空，最容易踩坑的用例）触发预取
        candidates = await svc.get_candidates({})
        codes = [c["code"] for c in candidates]
        assert "000001" in codes

        lookback = 260
        series = await svc.fetch_price_series(codes, lookback=lookback)
        n = len(series["000001"]["closes"])
        # 时间窗生效：不再是全历史（未加时间窗时 000001 有约 5846 行），
        # 且不超过 lookback + 合理余量（时间窗内可能略多于 lookback，仍会被
        # 客户端 [-lookback:] 截尾，这里只要不逼近全历史即可）。
        assert n <= lookback
        # 仍需覆盖常见短周期因子（如 mom_60）所需的最小长度
        assert n >= 61

        # 与不加时间窗的真实全历史条数对比，确认确实被大幅裁剪
        total_hist = await svc.get_mongo_db().stock_daily_quotes.count_documents(
            {"symbol": "000001", "close_qfq": {"$ne": None}}
        )
        assert n < total_hist

    asyncio.run(_run())
