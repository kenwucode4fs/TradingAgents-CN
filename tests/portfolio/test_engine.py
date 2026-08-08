"""组合回测主循环测试:验证防前视偏差、T+1 次日开盘成交、每日净值、逐月调仓。"""
from tradingagents.portfolio import run_portfolio_backtest
from tradingagents.backtest.types import CostConfig


def _panel(code, dates_prices):
    return [{"date": d, "open": p, "close": p, "volume": 1000000} for d, p in dates_prices]


def test_portfolio_backtest_basic():
    dates = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-28", "2024-02-29"]
    # A 持续涨、B 平、C 跌
    panel = {
        "A": _panel("A", [(d, 10 + i) for i, d in enumerate(dates)]),
        "B": _panel("B", [(d, 20.0) for d in dates]),
        "C": _panel("C", [(d, 30 - i) for i, d in enumerate(dates)]),
    }
    sections = {
        "2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
        "2024-02-29": {"A": {"pe": 6, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
    }
    benchmark = [(d, 1000.0 + i) for i, d in enumerate(dates)]
    cfg = {"start_date": "2024-01-30", "end_date": "2024-02-29", "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "pe", "weight": 1, "direction": "asc"}]  # 低 PE 优先 → 选 A
    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)
    assert len(r["equity_curve"]) >= 3
    assert r["rebalances"], "应有调仓记录"
    # 第一个调仓日 2024-01-31,次日 2024-02-01 成交 → 买入低PE的 A
    assert any(any(b["code"] == "A" for b in rb["buys"]) for rb in r["rebalances"])
    assert "total_return" in r["metrics"] and "benchmark_return" in r["metrics"]


def test_no_lookahead_uses_only_past_prices():
    # 调仓日 D 的因子若用了 D 之后的价,结果会不同;这里构造 A 在 D 后暴涨,
    # 若引擎错误地用了未来数据算动量,排序会变。用只有 pe 的因子(不依赖未来)确保稳定,
    # 主要断言:调仓成交价用的是 D 的"次一交易日"open,而非更晚的价。
    dates = ["2024-01-31", "2024-02-01", "2024-02-05"]
    panel = {"A": [{"date": "2024-01-31", "open": 10, "close": 10, "volume": 1e6},
                   {"date": "2024-02-01", "open": 11, "close": 11, "volume": 1e6},
                   {"date": "2024-02-05", "open": 99, "close": 99, "volume": 1e6}]}
    sections = {"2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
    cfg = {"start_date": "2024-01-31", "end_date": "2024-02-05", "initial_capital": 100000.0, "cost": CostConfig()}
    r = run_portfolio_backtest(cfg, [{"key": "pe", "weight": 1, "direction": "asc"}], sections, panel, [("2024-01-31", 1000.0), ("2024-02-05", 1000.0)], top_n=1)
    buy = [b for rb in r["rebalances"] for b in rb["buys"] if b["code"] == "A"][0]
    assert buy["price"] == 11  # 次日 2024-02-01 open,不是 2024-02-05 的 99
