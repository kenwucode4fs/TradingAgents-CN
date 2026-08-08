"""组合层面绩效:收益/年化/回撤/夏普/超额/换手。纯函数。"""
import math
from statistics import pstdev


def compute_portfolio_metrics(equity_curve, benchmark_curve, initial_capital, rebalances):
    eq = [v for _, v in equity_curve]
    total_return = eq[-1] / initial_capital - 1 if eq else 0.0
    n = len(eq)
    annual = (eq[-1] / initial_capital) ** (252.0 / n) - 1 if n > 1 and eq[-1] > 0 else 0.0

    peak, mdd = eq[0] if eq else 0.0, 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)

    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq)) if eq[i - 1]]
    sharpe = (sum(rets) / len(rets)) / pstdev(rets) * math.sqrt(252) if len(rets) >= 2 and pstdev(rets) > 0 else 0.0

    bm = [v for _, v in benchmark_curve]
    benchmark_return = bm[-1] / bm[0] - 1 if len(bm) >= 2 and bm[0] else 0.0

    # 换手率:每次调仓的(买额+卖额)/当次组合市值,取均值
    turnovers = []
    for rb in rebalances:
        traded = sum(b["shares"] * b["price"] for b in rb.get("buys", [])) + \
                 sum(s["shares"] * s["price"] for s in rb.get("sells", []))
        mv = rb.get("portfolio_value") or initial_capital
        if mv > 0:
            turnovers.append(traded / mv)
    turnover = sum(turnovers) / len(turnovers) if turnovers else 0.0

    return {
        "total_return": total_return, "annual_return": annual, "max_drawdown": mdd, "sharpe": sharpe,
        "benchmark_return": benchmark_return, "excess_return": total_return - benchmark_return,
        "turnover": turnover, "rebalance_count": len(rebalances),
    }
