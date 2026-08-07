"""回测 API 路由（app/routers/backtest.py）集成/单元测试。

- test_bad_params_rejected：普通单测，不依赖真实数据库/鉴权也应通过——
  未带 Authorization header 时鉴权依赖会先返回 401，非法参数场景下即使
  带了合法 token 也会在 build_backtest_args 校验阶段返回 400，两者均满足
  “>= 400”的断言。
- test_submit_returns_task_id：integration，需要真实 MongoDB（用户表）
  才能完成 admin/admin123 登录换取 token。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_submit_returns_task_id():
    """POST /api/backtest/run 提交后应同步返回 task_id。

    鉴权说明：`TestClient(app)`（不带 `with`）不会触发 FastAPI 的
    lifespan，而完整走一遍 /api/auth/login 依赖 lifespan 初始化好的
    app.core.database 全局连接（操作日志写入用），且本地 .env 是"最小化
    配置"，缺 REDIS_HOST/JWT_SECRET 等真正跑通完整 lifespan 所需的配置，
    在这个沙盒环境里无法整跑起来。backtest 路由本身鉴权只依赖
    `get_current_user` 返回的 user 字典（取其中的 id 字段），因此这里用
    `app.dependency_overrides` 直接替换掉鉴权依赖，跳过真实登录，同时仍然
    走真实 MongoDB（ensure_db/set_task_status/run_backtest_task 等），
    覆盖的正是本任务要验证的路由逻辑本身。
    """
    from app.main import app
    from app.routers.auth_db import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "test-admin", "username": "admin"}
    try:
        client = TestClient(app)
        body = {
            "symbol": "000001", "start_date": "2023-01-01", "end_date": "2024-01-01",
            "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
            "sell_rules": [{"left": "ma5", "op": "cross_down", "right": "ma20"}], "sell_logic": "AND",
        }
        r = client.post("/api/backtest/run", json=body)
        assert r.status_code in (200, 201), r.text
        assert "task_id" in r.json().get("data", r.json())
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_bad_params_rejected():
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/backtest/run", json={
        "symbol": "000001", "start_date": "2023-01-01", "end_date": "2024-01-01",
        "buy_rules": [], "buy_logic": "XOR", "sell_rules": [], "sell_logic": "AND",
    })
    assert r.status_code >= 400


@pytest.mark.integration
def test_status_and_result_require_ownership():
    """跨用户不能查看别人的回测状态/结果：非本人访问统一返回 404。

    直接调用 backtest_service（注入 bars，绕开 tushare，做法与
    tests/backtest/test_backtest_service.py 一致）为用户 A 造好一条
    "已完成"的任务记录，再分别以用户 B / 用户 A 的身份通过路由查询，
    验证非本人 404、本人 200。
    """
    import asyncio

    from app.core.database import db_manager
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.services import backtest_service as svc
    from tradingagents.backtest.types import Bar

    def _reset_mongo_client():
        # 见 test_backtest_service.py 的同名函数注释：Motor 客户端绑定到
        # 首次使用时的事件循环，这里用独立的 asyncio.run() 造数据，
        # 需要先重置模块级单例，避免复用上一个测试遗留的、已关闭的事件循环。
        db_manager.mongo_client = None
        db_manager.mongo_db = None

    def _bars(closes):
        out, prev = [], closes[0]
        for i, c in enumerate(closes):
            out.append(Bar(date=f"2021-01-{i+1:02d}", open=c, high=c, low=c, close=c, pre_close=prev, volume=1e6))
            prev = c
        return out

    task_id = "task-ownership-test-1"
    owner_id = "user-owner"
    other_id = "user-other"
    payload = {
        "symbol": "600003", "start_date": "2021-01-01", "end_date": "2021-02-01",
        "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
        "sell_rules": [{"left": "ma5", "op": "cross_down", "right": "ma20"}], "sell_logic": "AND",
    }
    bars = _bars([10] * 20 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10])

    async def _seed():
        _reset_mongo_client()
        await svc.ensure_db()
        await svc.set_task_status(task_id, "running", user_id=owner_id)
        await svc.run_backtest_task(task_id, owner_id, payload, bars=bars)
        await svc.set_task_status(task_id, "done")

    asyncio.run(_seed())

    # 用户 B（非本人）：status/result 均应为 404，不暴露任务存在
    # 注意：`TestClient(app)`（不带 `with`）每次 `.get()` 调用都各自另起、
    # 用完即关的事件循环（anyio portal），Motor 客户端不能跨循环复用，
    # 所以每次请求前都要重置模块级单例，而不能只在创建 client 时重置一次。
    app.dependency_overrides[get_current_user] = lambda: {"id": other_id, "username": other_id}
    try:
        client = TestClient(app)
        _reset_mongo_client()
        r_status = client.get(f"/api/backtest/status/{task_id}")
        assert r_status.status_code == 404, r_status.text
        _reset_mongo_client()
        r_result = client.get(f"/api/backtest/result/{task_id}")
        assert r_result.status_code == 404, r_result.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # 用户 A（本人）：应能正常查看
    app.dependency_overrides[get_current_user] = lambda: {"id": owner_id, "username": owner_id}
    try:
        client = TestClient(app)
        _reset_mongo_client()
        r_status_owner = client.get(f"/api/backtest/status/{task_id}")
        assert r_status_owner.status_code == 200, r_status_owner.text
        _reset_mongo_client()
        r_result_owner = client.get(f"/api/backtest/result/{task_id}")
        assert r_result_owner.status_code == 200, r_result_owner.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
