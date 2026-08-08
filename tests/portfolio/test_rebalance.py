from tradingagents.portfolio.rebalance import compute_rebalance
from tradingagents.backtest.types import CostConfig

COST = CostConfig()

def test_initial_buy_equal_weight():
    # 空仓，10万资金，买 A/B 两只等权，价 10/20（买入扣手续费后不再是精确 5000/2500，
    # 断言近似等权 + 资金守恒）
    r = compute_rebalance(["A", "B"], {}, {"A": 10.0, "B": 20.0}, 100000.0, COST)
    assert r["new_holdings"]["A"] > 0 and r["new_holdings"]["B"] > 0
    mv_a = r["new_holdings"]["A"] * 10.0
    mv_b = r["new_holdings"]["B"] * 20.0
    assert abs(mv_a - mv_b) / 50000 < 0.05           # 近似等权（5%内）
    total_fee = sum(b["fee"] for b in r["buys"])
    # 资金守恒：现金 + 持仓市值 + 买入手续费 == 初始资金
    assert abs(r["cash"] + mv_a + mv_b + total_fee - 100000.0) < 1e-6
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
