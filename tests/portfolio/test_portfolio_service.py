"""tests/portfolio/test_portfolio_service.py：组合回测后端服务集成测试。

用 precomputed 注入的方式绕开真实查库，验证 run_task 能正确跑通
（预取 -> run_in_executor 执行引擎 -> 落库），以及 get_result 能取回
落库结果，且带上正确的 user_id 属主字段。
"""
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
