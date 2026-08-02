"""绩效指标与买入持有基准。"""
import math
from typing import List, Tuple


def compute_metrics(equity_curve: List[Tuple[str, float]], initial_capital: float,
                     bars, trades) -> dict:
    """计算回测绩效指标，并附带买入持有基准。

    Args:
        equity_curve: 净值曲线，[(日期, 净值), ...]
        initial_capital: 初始资金
        bars: K线序列（用于计算买入持有基准）
        trades: 成交记录序列（用于计算胜率/盈亏比）

    Returns:
        dict，包含 total_return、annual_return、max_drawdown、sharpe、
        win_rate、profit_loss_ratio、trade_count、benchmark_return、benchmark_curve
    """
    equities = [e for _, e in equity_curve]
    n = len(equities)
    total_return = equities[-1] / initial_capital - 1 if n else 0.0

    # 日收益率
    rets = [equities[i] / equities[i - 1] - 1 for i in range(1, n)]

    # 最大回撤
    peak = -math.inf
    mdd = 0.0
    for e in equities:
        peak = max(peak, e)
        mdd = max(mdd, 1 - e / peak)

    # 年化收益
    annual = (1 + total_return) ** (252 / n) - 1 if n > 1 else 0.0

    # 夏普比率（无风险利率取 0，样本标准差 ddof=1）
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        sharpe = (mean / std * math.sqrt(252)) if std > 0 else 0.0
    else:
        sharpe = 0.0

    # 买入持有基准
    closes = [b.close for b in bars]
    benchmark_return = closes[-1] / closes[0] - 1 if closes else 0.0
    benchmark_curve = ([(bars[i].date, initial_capital * closes[i] / closes[0])
                         for i in range(len(bars))]
                        if closes else [])

    # 每笔盈亏（买-卖配对，FIFO：先入先出，一买对一卖）
    wins, losses, pnl_pos, pnl_neg = 0, 0, 0.0, 0.0
    buy_stack = []
    for t in trades:
        if t.side == "buy":
            buy_stack.append(t)
        elif t.side == "sell" and buy_stack:
            b = buy_stack.pop(0)
            pnl = ((t.price - b.price) * t.shares
                   - t.commission - t.stamp_tax - t.transfer_fee
                   - b.commission - b.transfer_fee)
            if pnl >= 0:
                wins += 1
                pnl_pos += pnl
            else:
                losses += 1
                pnl_neg += -pnl
    closed = wins + losses
    win_rate = wins / closed if closed else 0.0
    profit_loss_ratio = ((pnl_pos / wins) / (pnl_neg / losses)
                          if wins and losses else 0.0)

    return {
        "total_return": total_return,
        "annual_return": annual,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "trade_count": len(trades),
        "benchmark_return": benchmark_return,
        "benchmark_curve": benchmark_curve,
    }
