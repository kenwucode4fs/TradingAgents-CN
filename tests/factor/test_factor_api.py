import pytest
from fastapi.testclient import TestClient


def test_factors_meta_and_bad_params():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        client = TestClient(app)
        # /factors 返回 15 项元信息
        r = client.get("/api/factor-screen/factors")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert len(data) == 15
        # /run 非法：空因子 → 400
        r2 = client.post("/api/factor-screen/run", json={"factors": [], "universe": {}, "top_n": 10})
        assert r2.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_status_result_ownership():
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.services import factor_screening_service as svc
    import asyncio

    # Motor 的 AsyncIOMotorClient 惰性绑定到"首次使用时正在运行的事件循环"，
    # 绑定后不可跨循环复用；`TestClient(app)`（不带 `with`）每次 `.get()`
    # 调用各自另起、用完即关的事件循环（anyio portal），因此每次请求前都要
    # 重置 db_manager 模块级单例，强制下次 ensure_db() 重新连接（与
    # tests/backtest/test_backtest_api.py::test_status_and_result_require_ownership
    # 同一手法，避免 "RuntimeError: Event loop is closed"）。
    from app.core.database import db_manager

    def _reset_mongo_client():
        db_manager.mongo_client = None
        db_manager.mongo_db = None

    async def seed():
        await svc.ensure_db()
        await svc.set_task_status("t-own", "done", user_id="owner")
        await svc._results().update_one({"task_id": "t-own"},
            {"$set": {"task_id": "t-own", "user_id": "owner", "items": [], "config": {}}}, upsert=True)
    _reset_mongo_client()
    asyncio.run(seed())

    client = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "intruder", "username": "x"}
    try:
        _reset_mongo_client()
        assert client.get("/api/factor-screen/status/t-own").status_code == 404
        _reset_mongo_client()
        assert client.get("/api/factor-screen/result/t-own").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_current_user] = lambda: {"id": "owner", "username": "o"}
    try:
        _reset_mongo_client()
        assert client.get("/api/factor-screen/status/t-own").status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)
