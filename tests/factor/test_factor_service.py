from datetime import datetime

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
def test_fetch_price_series_query_has_time_window(monkeypatch):
    """fetch_price_series 需按 LOOKBACK_CALENDAR_DAYS 给 stock_daily_quotes.find 的
    filter 加 trade_date 下界，避免候选池为全市场（选股域留空的常见用例）时把每股
    近 20 年全部历史行无界拉进内存排序。

    仅靠"返回序列长度 <= lookback"不足以防回归——客户端 `[-lookback:]` 截尾在
    未加时间窗的旧代码上也会让长度看起来"正常"，测试仍会误判通过。这里改为
    直接 spy 住 find() 的调用参数，断言 filter 里确实带了 trade_date 时间窗，
    这才是真正会在有人误删 `trade_date: {"$gte": cutoff}` 时变红的回归保护。
    """
    import asyncio

    async def _run():
        _reset_mongo_client()
        await svc.ensure_db()
        real_db = svc.get_mongo_db()
        real_coll = real_db.stock_daily_quotes
        captured = {}

        class _SpyCollection:
            def find(self, flt, *a, **kw):
                captured["filter"] = flt
                return real_coll.find(flt, *a, **kw)

        class _DBStub:
            def __getattr__(self, name):
                if name == "stock_daily_quotes":
                    return _SpyCollection()
                return getattr(real_db, name)

        monkeypatch.setattr(svc, "get_mongo_db", lambda: _DBStub())

        lookback = 260
        series = await svc.fetch_price_series(["000001"], lookback=lookback)

        # 核心断言 1：查询 filter 里必须带 trade_date 时间窗（防"误删时间窗"回归）
        f = captured.get("filter")
        assert f is not None, "未捕获到 stock_daily_quotes.find 调用"
        assert "trade_date" in f and "$gte" in f["trade_date"], f"查询未带时间窗: {f}"
        cutoff = f["trade_date"]["$gte"]
        today = datetime.now().strftime("%Y-%m-%d")
        # cutoff 必须是与 stock_daily_quotes.trade_date 一致的带横线
        # "YYYY-MM-DD" 格式（防"格式不一致导致字符串比较错乱"回归：曾误用
        # 无横线的 "%Y%m%d"，'-'(0x2D) < '0'(0x30) 导致 "2025-XX-XX" 被误判
        # 小于 cutoff 而整年被过滤掉）。
        assert isinstance(cutoff, str) and len(cutoff) == 10 and cutoff.count("-") == 2, \
            f"cutoff 应为 YYYY-MM-DD 格式，实际: {cutoff}"
        assert cutoff < today, f"cutoff 应早于今天，实际: {cutoff}"

        # 核心断言 2：时间窗真的取到了近 LOOKBACK_CALENDAR_DAYS(500) 天的历史，
        # 而不是因格式不一致只取到当年 ~144 天。500 自然日 ≈ 330 交易日，
        # 被客户端 [-lookback:] 截到 lookback=260；格式 bug 存在时这里只有
        # ~144，此断言修复前会失败、修复后通过，是真正的回归保护。
        n = len(series["000001"]["closes"])
        assert n >= 200, f"时间窗覆盖的历史行数偏少（可能是 cutoff 格式与 trade_date 不一致）: {n}"
        assert n <= lookback

    asyncio.run(_run())
