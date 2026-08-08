"""组合回测（子项目 2b）后端端到端集成测试（真实库小区间）。

覆盖 `portfolio_backtest_service.run_task` 的 `precomputed=None` 生产路径：
真实 `load_monthly_sections`/`load_price_panel`/`load_benchmark`（主事件循环
里的纯异步 Motor 查询）+ `run_in_executor` 里跑纯 CPU 的
`run_portfolio_backtest`。全链路走 提交 -> 轮询 status -> 取 result，
不注入 precomputed，验证不触发跨事件循环冲突（Motor client 绑定的事件循环
与请求循环不一致时会抛 `RuntimeError: Event loop is closed`）。

回测区间固定为 2023-01-01 ~ 2024-12-31：与 `tests/portfolio/test_data_sync.py`
回填的真实数据范围对齐 —— `stock_monthly_basic` 覆盖该区间内 23 个月末
截面（约 12 万行），`index_daily_quotes` 沪深300（000300.SH）同区间共
484 行，足以支撑月度调仓组合回测产出多个 equity 点位与多次调仓记录。
"""
import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_full_portfolio_flow():
    from app.main import app
    from app.routers.auth_db import get_current_user
    from app.core.database import db_manager

    def _reset_mongo_client():
        # Motor 的 AsyncIOMotorClient 惰性绑定到"首次使用时正在运行的事件
        # 循环"，绑定后不可跨循环复用；`TestClient(app)`（不带 `with`）每次
        # `.get()`/`.post()` 调用各自另起、用完即关的事件循环（anyio
        # portal），因此每次请求前都要重置 db_manager 模块级单例，强制下次
        # ensure_db() 重新连接，与 test_portfolio_api.py::test_status_result_
        # ownership 同一手法，避免 "RuntimeError: Event loop is closed"。
        db_manager.mongo_client = None
        db_manager.mongo_db = None

    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e-pf", "username": "admin"}
    try:
        c = TestClient(app)
        body = {
            "factors": [
                {"key": "pe", "weight": 2, "direction": "asc"},
                {"key": "mom_120", "weight": 1, "direction": "desc"},
            ],
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "top_n": 10,
            "initial_capital": 1000000.0,
        }

        _reset_mongo_client()
        r = c.post("/api/portfolio-backtest/run", json=body)
        assert r.status_code == 200, r.text
        task_id = r.json()["data"]["task_id"]

        final = None
        for _ in range(120):
            _reset_mongo_client()
            st = c.get(f"/api/portfolio-backtest/status/{task_id}").json()["data"]
            if st["status"] in ("done", "failed"):
                final = st
                break
            time.sleep(1)

        if final and final["status"] == "failed":
            print("任务失败, error:", final.get("error"))
        assert final and final["status"] == "done", f"最终状态: {final}"

        _reset_mongo_client()
        data = c.get(f"/api/portfolio-backtest/result/{task_id}").json()["data"]

        assert len(data["equity_curve"]) > 20, f"equity_curve 点数过少: {len(data['equity_curve'])}"
        assert data["rebalances"], "rebalances 为空，应有多次月度调仓"

        m = data["metrics"]
        assert "total_return" in m
        assert "benchmark_return" in m
        assert "excess_return" in m
        assert "rebalance_count" in m
        assert m["rebalance_count"] > 1, f"调仓次数过少: {m['rebalance_count']}"

        print(
            "组合总收益:", round(m["total_return"], 4),
            "基准:", round(m["benchmark_return"], 4),
            "超额:", round(m["excess_return"], 4),
            "调仓次数:", m["rebalance_count"],
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)
