"""回测异步 worker(backtest_service)集成测试。

依赖真实 mongodb 容器（见 tests/backtest/conftest.py 中的本地鉴权补全），
通过注入 bars 绕开 tushare，只验证：
- run_in_executor 编排是否能在 FastAPI 事件循环内安全跑通 run_backtest（其内部含 asyncio.run）；
- 回测结果是否正确落库（backtest_results 集合）；
- get_result / get_history 是否能正确取回。
"""
import asyncio

import pytest

from app.core.database import db_manager
from tradingagents.backtest.types import Bar


def _reset_mongo_client():
    """重置 db_manager 的 mongo 客户端，强制下次 ensure_db() 重新连接。

    Motor 的 AsyncIOMotorClient 会惰性绑定到"首次使用时正在运行的事件循环"，
    绑定后不可跨循环复用。每个测试函数各自 asyncio.run() 出一个独立事件循环，
    若沿用上一个测试遗留的模块级单例客户端，会在新循环里触发
    `RuntimeError: Event loop is closed`。真实的 FastAPI 应用生命周期内只有
    一个常驻事件循环，不会遇到此问题；这里仅为保证测试间相互独立。
    """
    db_manager.mongo_client = None
    db_manager.mongo_db = None


def _bars(closes):
    """按收盘价序列构造最简 Bar 列表（open=high=low=close，volume 恒定）。"""
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(date=f"2021-01-{i+1:02d}", open=c, high=c, low=c, close=c, pre_close=prev, volume=1e6))
        prev = c
    return out


@pytest.mark.integration
def test_run_backtest_task_persists(monkeypatch):
    from app.services import backtest_service as svc

    payload = {
        "symbol": "600000", "start_date": "2021-01-01", "end_date": "2021-02-01", "initial_capital": 100000,
        "position": {"parts": 1, "reduce_mode": "reduce_one"},
        "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
        "sell_rules": [{"left": "ma5", "op": "cross_down", "right": "ma20"}], "sell_logic": "AND",
    }
    bars = _bars([10] * 20 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10])

    async def run():
        _reset_mongo_client()
        await svc.ensure_db()  # 初始化 mongo（见实现）
        res = await svc.run_backtest_task("task-test-1", "user-1", payload, bars=bars)
        assert "metrics" in res and "equity_curve" in res
        got = await svc.get_result("task-test-1")
        assert got is not None and got["symbol"] == "600000"

    asyncio.run(run())


@pytest.mark.integration
def test_get_history_returns_summary():
    from app.services import backtest_service as svc

    payload = {
        "symbol": "600001", "start_date": "2021-01-01", "end_date": "2021-02-01", "initial_capital": 100000,
        "position": {"parts": 1, "reduce_mode": "reduce_one"},
        "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
        "sell_rules": [{"left": "ma5", "op": "cross_down", "right": "ma20"}], "sell_logic": "AND",
    }
    bars = _bars([10] * 20 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10])

    async def run():
        _reset_mongo_client()
        await svc.ensure_db()
        await svc.run_backtest_task("task-test-2", "user-history", payload, bars=bars)
        history = await svc.get_history("user-history", limit=10, skip=0)
        assert len(history) >= 1
        assert history[0]["task_id"] == "task-test-2"
        assert history[0]["symbol"] == "600001"

    asyncio.run(run())
