import math
from tradingagents.portfolio.metrics import compute_portfolio_metrics

def test_total_and_excess_return():
    eq = [("2024-01-01", 100000.0), ("2024-12-31", 120000.0)]     # +20%
    bm = [("2024-01-01", 100000.0), ("2024-12-31", 110000.0)]     # +10%
    m = compute_portfolio_metrics(eq, bm, 100000.0, [])
    assert math.isclose(m["total_return"], 0.20, abs_tol=1e-9)
    assert math.isclose(m["benchmark_return"], 0.10, abs_tol=1e-9)
    assert math.isclose(m["excess_return"], 0.10, abs_tol=1e-9)

def test_max_drawdown():
    eq = [("d1", 100.0), ("d2", 120.0), ("d3", 90.0), ("d4", 110.0)]  # 峰120→谷90 回撤25%
    m = compute_portfolio_metrics(eq, [("d1",100.0),("d4",110.0)], 100.0, [])
    assert math.isclose(m["max_drawdown"], 0.25, abs_tol=1e-9)

def test_rebalance_count():
    m = compute_portfolio_metrics([("d1",100.0),("d2",100.0)], [("d1",100.0),("d2",100.0)], 100.0,
                                   [{"date":"d1","buys":[],"sells":[]}, {"date":"d2","buys":[],"sells":[]}])
    assert m["rebalance_count"] == 2
