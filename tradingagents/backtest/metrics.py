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

    # 每笔盈亏：按股数 FIFO 逐股配对（不能整笔配对）。
    # 本回测采用固定份数分批建仓/减仓（broker.py），reduce_one 按 LIFO
    # 卖出最后一档、clear_all 会把多档合并成 1 笔 sell——因此一笔 buy
    # 可能被多笔 sell 分批平仓，一笔 sell 也可能同时平掉多笔 buy，
    # 买卖的笔数和股数并不对称，必须按股数配对，而非整笔配对。
    # 队列维护 [买入价, 剩余未平仓股数, 该买入笔每股应分摊的买方成本]。
    wins, losses, pnl_pos, pnl_neg = 0, 0, 0.0, 0.0
    buy_queue = []
    for t in trades:
        if t.shares <= 0:
            continue
        if t.side == "buy":
            # 买方每股成本 = (手续费 + 过户费) / 股数。
            # 注：A股买入印花税恒为 0（mr.buy_cost 返回值如此），
            # 因此这里刻意不计入 t.stamp_tax，避免日后误以为遗漏。
            per_share_cost = (t.commission + t.transfer_fee) / t.shares
            buy_queue.append([t.price, t.shares, per_share_cost])
        elif t.side == "sell":
            remaining = t.shares
            # 卖方每股成本 = (手续费 + 印花税 + 过户费) / 股数，
            # 按实际配对到的股数比例分摊到每一段配对。
            per_share_sell_cost = (t.commission + t.stamp_tax + t.transfer_fee) / t.shares
            while remaining > 0 and buy_queue:
                buy_price, buy_remaining, buy_per_share_cost = buy_queue[0]
                matched = min(remaining, buy_remaining)
                pnl = ((t.price - buy_price) * matched
                       - buy_per_share_cost * matched
                       - per_share_sell_cost * matched)
                # 打平（pnl == 0）按约定计为 win，而非单独归类。
                if pnl >= 0:
                    wins += 1
                    pnl_pos += pnl
                else:
                    losses += 1
                    pnl_neg += -pnl
                buy_remaining -= matched
                remaining -= matched
                if buy_remaining <= 0:
                    buy_queue.pop(0)
                else:
                    buy_queue[0][1] = buy_remaining
            # remaining > 0 但队列已空：无对应买入可配对（数据异常），
            # 不计入 win/loss，也不抛异常。
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
