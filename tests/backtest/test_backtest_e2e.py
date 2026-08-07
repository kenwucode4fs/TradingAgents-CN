"""策略回测后端端到端集成测试：提交 -> 后台执行 -> 轮询状态 -> 取结果。

依赖真实 MongoDB（见 tests/backtest/conftest.py 的本地容器鉴权补全）和真实
000001 历史行情数据（`tradingagents` 库 `stock_daily_quotes` 集合）。

关键验证点：本测试 **不注入** bars（`run_backtest_task` 的 `bars=None`），
使 `BackgroundTasks` 后台任务真正走一遍
`run_backtest_task -> loop.run_in_executor -> run_backtest -> data_feed.load_bars`
（内部含 `asyncio.run`），从而验证该链路在 FastAPI 事件循环下不会触发
"asyncio.run() cannot be called from a running event loop" /
"Event loop is closed" 之类的冲突。

鉴权：/api/backtest/* 依赖 `get_current_user`，这里用
`app.dependency_overrides` 跳过真实登录（做法与
`tests/backtest/test_backtest_api.py::test_submit_returns_task_id` 一致）。

事件循环说明：`TestClient(app)`（不带 `with`）每次请求都各自另起、
用完即关的事件循环（anyio portal），Motor 客户端不能跨循环复用，因此轮询
过程中每次请求前都要重置 `db_manager` 的模块级单例（做法与
`test_backtest_api.py::test_status_and_result_require_ownership` 一致）。
"""
import time

import pytest
from fastapi.testclient import TestClient

# BackgroundTasks 在真实库上跑一次完整回测（含从 mongo 读取 20 年行情、
# 计算指标、落库），比注入 bars 的单测慢得多，轮询上限要给够时间。
MAX_POLLS = 60
POLL_INTERVAL_SECONDS = 1


def _reset_mongo_client():
    """重置 db_manager 的 mongo 客户端单例，避免跨事件循环复用报错。

    详见 test_backtest_api.py 中同名函数的注释。
    """
    from app.core.database import db_manager

    db_manager.mongo_client = None
    db_manager.mongo_db = None


@pytest.mark.integration
def test_full_backtest_flow():
    from app.main import app
    from app.routers.auth_db import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e-user", "username": "admin"}
    try:
        client = TestClient(app)
        body = {
            "symbol": "000001", "start_date": "2023-01-01", "end_date": "2024-12-31",
            "initial_capital": 100000,
            "position": {"parts": 1, "reduce_mode": "reduce_one"},
            "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
            "sell_rules": [{"left": "ma5", "op": "cross_down", "right": "ma20"}], "sell_logic": "AND",
        }

        _reset_mongo_client()
        r_submit = client.post("/api/backtest/run", json=body)
        assert r_submit.status_code == 200, r_submit.text
        task_id = r_submit.json()["data"]["task_id"]

        # 轮询任务状态直到 done/failed，不假设后台任务在 POST 返回时已完成。
        final_status = None
        for _ in range(MAX_POLLS):
            _reset_mongo_client()
            r_status = client.get(f"/api/backtest/status/{task_id}")
            assert r_status.status_code == 200, r_status.text
            status_doc = r_status.json()["data"]
            status = status_doc.get("status")
            if status in ("done", "failed"):
                final_status = status_doc
                break
            time.sleep(POLL_INTERVAL_SECONDS)
        else:
            pytest.fail(f"任务 {task_id} 在 {MAX_POLLS * POLL_INTERVAL_SECONDS}s 内未完成，最后状态: {status}")

        if final_status["status"] == "failed":
            pytest.fail(f"回测任务后台执行失败: {final_status.get('error')}")

        _reset_mongo_client()
        r_result = client.get(f"/api/backtest/result/{task_id}")
        assert r_result.status_code == 200, r_result.text
        data = r_result.json()["data"]
        assert "metrics" in data
        assert len(data["equity_curve"]) > 50
        print("总收益:", data["metrics"]["total_return"], "基准:", data["metrics"]["benchmark_return"])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
