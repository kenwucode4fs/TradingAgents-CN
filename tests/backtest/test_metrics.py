"""绩效指标与买入持有基准的测试。"""
from tradingagents.backtest.metrics import compute_metrics
from tradingagents.backtest.types import Bar, Trade


def _bars(closes):
    return [Bar(date=f"2020-04-{i+1:02d}", open=c, high=c, low=c, close=c, pre_close=c, volume=1)
            for i, c in enumerate(closes)]


def test_total_return_and_drawdown():
    curve = [("d1", 100000), ("d2", 110000), ("d3", 99000), ("d4", 121000)]
    m = compute_metrics(curve, 100000, _bars([10, 11, 9.9, 12.1]), trades=[])
    assert round(m["total_return"], 4) == 0.21            # 121000/100000-1
    # 最大回撤：从110000跌到99000 → 1-99000/110000=0.10
    assert round(m["max_drawdown"], 4) == 0.10
    # 基准：买入持有 12.1/10-1 = 0.21
    assert round(m["benchmark_return"], 4) == 0.21


def test_annual_return():
    # n=4 天净值序列，年化 = (1+total_return)**(252/4)-1
    curve = [("d1", 100000), ("d2", 110000), ("d3", 99000), ("d4", 121000)]
    m = compute_metrics(curve, 100000, _bars([10, 11, 9.9, 12.1]), trades=[])
    expected_annual = (1 + 0.21) ** (252 / 4) - 1
    assert round(m["annual_return"], 6) == round(expected_annual, 6)


def test_sharpe_ratio():
    # 手算日收益率: r2=0.10, r3=99000/110000-1=-0.10, r4=121000/99000-1≈0.222222
    curve = [("d1", 100000), ("d2", 110000), ("d3", 99000), ("d4", 121000)]
    m = compute_metrics(curve, 100000, _bars([10, 11, 9.9, 12.1]), trades=[])
    rets = [0.10, 99000 / 110000 - 1, 121000 / 99000 - 1]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = var ** 0.5
    expected_sharpe = mean / std * (252 ** 0.5)
    assert round(m["sharpe"], 6) == round(expected_sharpe, 6)


def test_win_rate_and_profit_loss_ratio():
    # 两笔配对交易：第一笔买10卖12盈利，第二笔买10卖8亏损
    trades = [
        Trade(date="d1", side="buy", price=10.0, shares=100, commission=1.0, stamp_tax=0.0, transfer_fee=0.1),
        Trade(date="d2", side="sell", price=12.0, shares=100, commission=1.0, stamp_tax=1.2, transfer_fee=0.1),
        Trade(date="d3", side="buy", price=10.0, shares=100, commission=1.0, stamp_tax=0.0, transfer_fee=0.1),
        Trade(date="d4", side="sell", price=8.0, shares=100, commission=1.0, stamp_tax=0.8, transfer_fee=0.1),
    ]
    curve = [("d1", 100000), ("d2", 100000)]
    m = compute_metrics(curve, 100000, _bars([10, 10]), trades=trades)

    # 第一笔盈亏: (12-10)*100 - 1(卖commission) - 1.2(印花税) - 0.1(卖过户费) - 1(买commission) - 0.1(买过户费)
    pnl1 = (12.0 - 10.0) * 100 - 1.0 - 1.2 - 0.1 - 1.0 - 0.1
    # 第二笔盈亏: (8-10)*100 - 1(卖commission) - 0.8(印花税) - 0.1(卖过户费) - 1(买commission) - 0.1(买过户费)
    pnl2 = (8.0 - 10.0) * 100 - 1.0 - 0.8 - 0.1 - 1.0 - 0.1

    assert pnl1 > 0 and pnl2 < 0
    assert round(m["win_rate"], 4) == 0.5  # 1胜1负
    expected_ratio = pnl1 / abs(pnl2)
    assert round(m["profit_loss_ratio"], 4) == round(expected_ratio, 4)
    assert m["trade_count"] == 4


def test_win_loss_one_buy_many_sells():
    """一笔买入分两笔卖出各卖一半（一买对多卖），须按股数 FIFO 逐股配对。"""
    trades = [
        Trade(date="d1", side="buy", price=10.0, shares=300, commission=3.0, stamp_tax=0.0, transfer_fee=0.3),
        Trade(date="d2", side="sell", price=11.0, shares=150, commission=1.5, stamp_tax=1.65, transfer_fee=0.15),
        Trade(date="d3", side="sell", price=9.0, shares=150, commission=1.5, stamp_tax=1.35, transfer_fee=0.15),
    ]
    curve = [("d1", 100000), ("d2", 100000)]
    m = compute_metrics(curve, 100000, _bars([10, 10]), trades=trades)

    per_share_buy_cost = (3.0 + 0.3) / 300  # 0.011
    per_share_sell1_cost = (1.5 + 1.65 + 0.15) / 150  # 0.022
    per_share_sell2_cost = (1.5 + 1.35 + 0.15) / 150  # 0.02

    pnl1 = (11.0 - 10.0) * 150 - per_share_buy_cost * 150 - per_share_sell1_cost * 150  # 盈利
    pnl2 = (9.0 - 10.0) * 150 - per_share_buy_cost * 150 - per_share_sell2_cost * 150  # 亏损

    assert pnl1 > 0 and pnl2 < 0
    assert m["trade_count"] == 3
    assert round(m["win_rate"], 4) == 0.5  # 两段配对：1胜1负
    expected_ratio = pnl1 / abs(pnl2)
    assert round(m["profit_loss_ratio"], 4) == round(expected_ratio, 4)


def test_win_loss_many_buys_one_sell():
    """多笔小额买入后一次性全卖（多买对一卖），须按股数 FIFO 逐股配对。"""
    trades = [
        Trade(date="d1", side="buy", price=10.0, shares=100, commission=1.0, stamp_tax=0.0, transfer_fee=0.1),
        Trade(date="d2", side="buy", price=12.0, shares=200, commission=2.0, stamp_tax=0.0, transfer_fee=0.2),
        Trade(date="d3", side="sell", price=11.0, shares=300, commission=3.0, stamp_tax=3.3, transfer_fee=0.3),
    ]
    curve = [("d1", 100000), ("d2", 100000)]
    m = compute_metrics(curve, 100000, _bars([10, 10]), trades=trades)

    per_share_buy1_cost = (1.0 + 0.1) / 100  # 0.011
    per_share_buy2_cost = (2.0 + 0.2) / 200  # 0.011
    per_share_sell_cost = (3.0 + 3.3 + 0.3) / 300  # 0.022

    # 第一段：卖出配对第一笔买入的 100 股
    pnl1 = (11.0 - 10.0) * 100 - per_share_buy1_cost * 100 - per_share_sell_cost * 100  # 盈利
    # 第二段：卖出配对第二笔买入的 200 股
    pnl2 = (11.0 - 12.0) * 200 - per_share_buy2_cost * 200 - per_share_sell_cost * 200  # 亏损

    assert pnl1 > 0 and pnl2 < 0
    assert m["trade_count"] == 3
    assert round(m["win_rate"], 4) == 0.5  # 两段配对：1胜1负
    expected_ratio = pnl1 / abs(pnl2)
    assert round(m["profit_loss_ratio"], 4) == round(expected_ratio, 4)


def test_no_trades_no_crash():
    curve = [("d1", 100000), ("d2", 105000)]
    m = compute_metrics(curve, 100000, _bars([10, 10.5]), trades=[])
    assert m["trade_count"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_loss_ratio"] == 0.0


def test_single_point_curve_no_crash():
    curve = [("d1", 100000)]
    m = compute_metrics(curve, 100000, _bars([10]), trades=[])
    assert m["total_return"] == 0.0
    assert m["annual_return"] == 0.0
    assert m["sharpe"] == 0.0
    assert m["max_drawdown"] == 0.0
