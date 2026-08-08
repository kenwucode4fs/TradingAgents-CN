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


def test_turnover_budget_uses_total_value_not_only_cash():
    # 换手场景：持有 A(1000股@10) + C(1000股@10)，总市值 20000，现金 0。
    # 目标变为 [A, B]：卖出 C（掉榜）、A 保留不动、B 新进。
    # 若预算分母仍用"卖出得到的现金"（旧 bug），B 的预算会被 A 这只"保留股"稀释掉一半；
    # 修复后预算基准应为"调仓前组合总市值"（现金+保留持仓市值），B 应能拿到接近满额的一份预算。
    holdings = {"A": 1000, "C": 1000}
    prices = {"A": 10.0, "B": 20.0, "C": 10.0}
    r = compute_rebalance(["A", "B"], holdings, prices, 0.0, COST)

    # A 是保留股，原样不动
    assert r["new_holdings"]["A"] == 1000
    # C 掉榜被卖出
    assert any(s["code"] == "C" for s in r["sells"])
    assert "C" not in r["new_holdings"]

    # 旧 bug 下 budget_each = 卖出所得现金 / 2 ≈ 4992，只能买 200 股 B；
    # 修复后 budget_each = 总市值(≈19984.9) / 2 ≈ 9992，应能买到 400 股 B（预算翻倍）。
    assert r["new_holdings"].get("B", 0) == 400

    # 资金守恒：现金 + 持仓市值 + 已扣手续费(买+卖) == 调仓前总资产(20000,忽略卖出手续费前)
    mv = r["new_holdings"]["A"] * 10.0 + r["new_holdings"]["B"] * 20.0
    total_fee = sum(x["fee"] for x in r["buys"]) + sum(x["fee"] for x in r["sells"])
    assert abs(r["cash"] + mv + total_fee - 20000.0) < 1e-6

    # 预算未被过度稀释：买入 B 的市值不应远小于总市值的一半（旧 bug 下约为一半的一半）
    buy_b_value = r["new_holdings"]["B"] * 20.0
    assert buy_b_value > 6000.0  # 远高于旧 bug 下的 4000
