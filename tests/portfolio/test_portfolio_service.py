"""tests/portfolio/test_portfolio_service.py：组合回测后端服务集成测试。

用 precomputed 注入的方式绕开真实查库，验证 run_task 能正确跑通
（预取 -> run_in_executor 执行引擎 -> 落库），以及 get_result 能取回
落库结果，且带上正确的 user_id 属主字段。
"""
from datetime import datetime, timedelta

import pytest

from app.core.database import db_manager
from app.services import portfolio_backtest_service as svc


def _reset_mongo_client():
    """重置 db_manager 的 mongo 客户端，强制下次 ensure_db() 重新连接。

    Motor 的 AsyncIOMotorClient 会惰性绑定到"首次使用时正在运行的事件循环"，
    绑定后不可跨循环复用。每个测试函数各自 asyncio.run() 出一个独立事件循环，
    若沿用上一个测试（如 tests/portfolio/test_data_sync.py）遗留的模块级
    单例客户端，会在新循环里触发 `RuntimeError: Event loop is closed`。
    真实的 FastAPI 应用生命周期内只有一个常驻事件循环，不会遇到此问题；
    这里仅为保证测试间相互独立（同构自 tests/factor/test_factor_service.py）。
    """
    db_manager.mongo_client = None
    db_manager.mongo_db = None


@pytest.mark.integration
def test_run_task_with_injected_data():
    import asyncio

    async def _run():
        _reset_mongo_client()
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


@pytest.mark.integration
def test_load_price_panel_query_has_time_window(monkeypatch):
    """load_price_panel 需按 LOOKBACK_CALENDAR_DAYS 给 stock_daily_quotes.find 的
    filter 加 trade_date 下界，避免全市场候选池（防幸存者并集，几千只股票）
    被无界拉取从上市到 end 的全部 ~20 年历史行（千万行级别），导致游标遍历
    超时被 MongoDB 回收报 CursorNotFound（code 43）。

    直接 spy 住 find() 的调用参数，断言 filter 里带了 trade_date 下界，防止
    有人误删 `trade_date: {"$gte": cutoff}` 导致回归。
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

        start, end = "2024-06-30", "2024-12-31"
        await svc.load_price_panel(_DBStub(), ["000001"], start, end)

        # 核心断言 1：查询 filter 里必须带 trade_date 下界（防"误删时间窗"回归）
        f = captured.get("filter")
        assert f is not None, "未捕获到 stock_daily_quotes.find 调用"
        assert "trade_date" in f and "$gte" in f["trade_date"], f"查询未带时间窗: {f}"
        cutoff = f["trade_date"]["$gte"]

        # 核心断言 2：cutoff 必须是与 stock_daily_quotes.trade_date 一致的带
        # 横线 "YYYY-MM-DD" 格式（防"格式不一致导致字符串比较错乱"回归：曾
        # 误用无横线的 "%Y%m%d"，'-'(0x2D) < '0'(0x30) 导致带横线的日期被
        # 误判小于 cutoff 而整年被过滤掉）。
        assert isinstance(cutoff, str) and len(cutoff) == 10 and cutoff.count("-") == 2, \
            f"cutoff 应为 YYYY-MM-DD 格式，实际: {cutoff}"
        assert cutoff < start, f"cutoff 应早于 start，实际: {cutoff}"

        # 核心断言 3：cutoff 确实是 start 往前约 LOOKBACK_CALENDAR_DAYS(500) 自然日
        expected = (datetime.strptime(start, "%Y-%m-%d")
                    - timedelta(days=svc.LOOKBACK_CALENDAR_DAYS)).strftime("%Y-%m-%d")
        assert cutoff == expected, f"cutoff 应为 start-{svc.LOOKBACK_CALENDAR_DAYS}天，期望 {expected}，实际 {cutoff}"

        assert f["trade_date"]["$lte"] == end
    asyncio.run(_run())
