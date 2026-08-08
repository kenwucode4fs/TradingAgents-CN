import pytest
from app.services import factor_screening_service as svc


@pytest.mark.integration
def test_run_screen_task_with_injected_stocks(monkeypatch):
    import asyncio

    async def _run():
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
