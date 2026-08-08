from tradingagents.portfolio.rebalance import compute_rebalance
from tradingagents.backtest.types import CostConfig

COST = CostConfig()

def test_initial_buy_equal_weight():
    # 空仓，10万资金，买 A/B 两只等权，价 10/20
    r = compute_rebalance(["A", "B"], {}, {"A": 10.0, "B": 20.0}, 100000.0, COST)
    # 每只预算 5 万：A 买 5000 股（5万/10），B 买 2500 股（5万/20），均 100 整数倍
    assert r["new_holdings"]["A"] == 5000
    assert r["new_holdings"]["B"] == 2500
    assert r["cash"] >= 0

def test_sell_dropped_and_buy_new():
    # 持有 A，目标换成 B
    r = compute_rebalance(["B"], {"A": 1000}, {"A": 10.0, "B": 20.0}, 0.0, COST)
    assert "A" not in r["new_holdings"] or r["new_holdings"].get("A", 0) == 0
    assert r["new_holdings"]["B"] > 0
    assert any(s["code"] == "A" for s in r["sells"])

def test_suspended_target_skipped_to_cash():
    # 目标 A/B，但 B 停牌（无价），只买 A，B 权重留现金
    r = compute_rebalance(["A", "B"], {}, {"A": 10.0}, 100000.0, COST)
    assert r["new_holdings"].get("A", 0) > 0
    assert "B" not in r["new_holdings"]
    assert r["cash"] > 0  # B 那份留现金

def test_suspended_holding_not_sold():
    # 持有 A（停牌无价），目标为空 → A 不能卖，保持
    r = compute_rebalance([], {"A": 1000}, {}, 0.0, COST)
    assert r["new_holdings"].get("A") == 1000
