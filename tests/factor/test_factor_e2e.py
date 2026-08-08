"""因子打分选股（子项目 2a）后端端到端集成测试：真实库跑通「提交→轮询→结果」。

真实覆盖 `run_screen_task` 的 `stocks=None` 路径：候选池查询
（`get_candidates`）+ 批量预取（`fetch_price_series`）+ 线程池打分
（`run_in_executor`）+ 落库，全链路不经 mock。

选股域说明（区别于 task-6-brief.md 骨架里的 `industries: ["银行"]`）：
真实库 `stock_screening_view.industry` 约 35% 为空串（如平安银行），按
`industries: ["银行"]` 过滤会命中空候选池导致测试失败；改用市值下限
`mv_min: 2000`（单位：亿）缩小选股域——核实过真实库里 `total_mv >= 2000`
约有 75 只大盘股，候选池不大不小，既保证非空又避免全市场（~5470 只）
预取 20 年日线过慢。

Run: `MONGODB_DATABASE=tradingagents MONGODB_DATABASE_SCOPE=explicit \
    ./venv/bin/python -m pytest tests/factor/test_factor_e2e.py -v -m integration -s`
"""
import time

import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_full_factor_screen_flow():
    from app.main import app
    from app.routers.auth_db import get_current_user
    # Motor 的 AsyncIOMotorClient 惰性绑定到"首次使用时正在运行的事件循环"；
    # TestClient(app) 每次 .get()/.post() 各自另起、用完即关的事件循环，
    # 因此每次请求前都要重置 db_manager 模块级单例，强制下次 ensure_db()
    # 重新连接（同 tests/factor/test_factor_api.py::test_status_result_ownership
    # 手法），避免 "RuntimeError: Event loop is closed"。
    from app.core.database import db_manager

    def _reset_mongo_client():
        db_manager.mongo_client = None
        db_manager.mongo_db = None

    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e-fac", "username": "admin"}
    try:
        client = TestClient(app)
        body = {
            "factors": [
                {"key": "pe", "weight": 2, "direction": "asc"},
                {"key": "mom_60", "weight": 1, "direction": "desc"},
                {"key": "total_mv", "weight": 1, "direction": "asc"},
            ],
            # 小域，加速：市值 >= 2000 亿的大盘股（约 75 只），非全市场
            "universe": {"exclude_st": True, "mv_min": 2000},
            "top_n": 10,
        }
        _reset_mongo_client()
        r = client.post("/api/factor-screen/run", json=body)
        assert r.status_code == 200, r.text
        tid = r.json()["data"]["task_id"]

        final = None
        for _ in range(60):
            _reset_mongo_client()
            st = client.get(f"/api/factor-screen/status/{tid}").json()["data"]
            if st["status"] in ("done", "failed"):
                final = st
                break
            time.sleep(1)

        if final and final["status"] == "failed":
            print("任务失败 error:", final.get("error"))
        assert final and final["status"] == "done", f"最终状态: {final}"

        _reset_mongo_client()
        data = client.get(f"/api/factor-screen/result/{tid}").json()["data"]
        assert len(data["items"]) >= 1, "候选池打分结果为空，请确认真实库 stock_screening_view 中 total_mv>=2000 是否有数据"
        top = data["items"][0]
        assert top["rank"] == 1
        assert 0.0 <= top["score"] <= 1.0
        assert "pe" in top["factors"]
        print("TopN:", [(x["code"], round(x["score"], 3)) for x in data["items"][:5]])
    finally:
        app.dependency_overrides.pop(get_current_user, None)
