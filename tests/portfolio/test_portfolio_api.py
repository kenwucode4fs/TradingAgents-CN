"""组合回测（子项目 2b）后端 API 测试。

结构照 2a `tests/factor/test_factor_screening_api.py`：
- `test_run_bad_params_400` 用空因子列表触发 400，无需真实 MongoDB。
- `test_run_factor_weight_must_be_positive`/`test_run_factors_must_be_dicts`
  校验 `_validate` 与 2a `factor_screening._validate` 对齐：factor 必须是
  含合法 `key`（在 `FACTORS` 中）与正 `weight` 的 dict，裸字符串或非正
  权重都应在 400 阶段被一次性拒绝，而不是拖到后台任务里以模糊异常 failed。
- `test_status_result_ownership` 是集成测试，先用 `svc` 直接写入一条属于
  `owner` 的任务/结果记录，再用 `intruder` 身份访问，验证属主校验统一
  返回 404（不泄露 task_id 是否存在）。
"""
import pytest
from fastapi.testclient import TestClient


def test_run_bad_params_400():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        c = TestClient(app)
        r = c.post("/api/portfolio-backtest/run", json={"factors": [], "start_date": "2024-01-01", "end_date": "2024-12-31", "top_n": 20})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_run_factor_weight_must_be_positive():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        c = TestClient(app)
        r = c.post("/api/portfolio-backtest/run", json={
            "factors": [{"key": "pe", "weight": 0}],
            "start_date": "2024-01-01", "end_date": "2024-12-31", "top_n": 10})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_run_factors_must_be_dicts():
    from app.main import app
    from app.routers.auth_db import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "username": "admin"}
    try:
        c = TestClient(app)
        r = c.post("/api/portfolio-backtest/run", json={
            "factors": ["pe"],
            "start_date": "2024-01-01", "end_date": "2024-12-31", "top_n": 10})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.integration
def test_status_result_ownership():
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.services import portfolio_backtest_service as svc
    import asyncio

    # Motor 的 AsyncIOMotorClient 惰性绑定到"首次使用时正在运行的事件循环"，
    # 绑定后不可跨循环复用；`TestClient(app)`（不带 `with`）每次 `.get()`
    # 调用各自另起、用完即关的事件循环（anyio portal），因此每次请求前都要
    # 重置 db_manager 模块级单例，强制下次 ensure_db() 重新连接（与
    # tests/factor/test_factor_api.py::test_status_result_ownership 同一手法，
    # 避免 "RuntimeError: Event loop is closed"）。
    from app.core.database import db_manager

    def _reset_mongo_client():
        db_manager.mongo_client = None
        db_manager.mongo_db = None

    _reset_mongo_client()
    asyncio.run(_seed(svc))

    c = TestClient(app)
    app.dependency_overrides[get_current_user] = lambda: {"id": "intruder"}
    try:
        _reset_mongo_client()
        assert c.get("/api/portfolio-backtest/status/t-pf-own").status_code == 404
        _reset_mongo_client()
        assert c.get("/api/portfolio-backtest/result/t-pf-own").status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def _seed(svc):
    await svc.ensure_db()
    await svc.set_task_status("t-pf-own", "done", user_id="owner")
    await svc._results().update_one({"task_id": "t-pf-own"},
        {"$set": {"task_id": "t-pf-own", "user_id": "owner", "equity_curve": [], "metrics": {}, "config": {}}}, upsert=True)
