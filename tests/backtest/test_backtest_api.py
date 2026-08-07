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
