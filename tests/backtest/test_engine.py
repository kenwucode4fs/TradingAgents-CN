"""逐日回放主循环 run_loop 测试。

核心语义：
- 信号在第 i 日收盘后由 strategy.decide(i) 产生。
- 该信号在第 i+1 日开盘价成交（T+1，杜绝前视偏差）。
- 若因停牌 / 涨跌停未成交，挂单顺延到再下一个可交易日开盘继续尝试，
  直到成交或被新的非 HOLD 信号取代。
- 每根 bar 收盘记净值 broker.market_value(bar.close)。
"""
from tradingagents.backtest.types import Bar, Action, CostConfig, PositionConfig
from tradingagents.backtest.broker import Broker
from tradingagents.backtest.engine import run_loop


def _bar(d, o, c, pre, susp=False):
    return Bar(date=d, open=o, high=max(o, c), low=min(o, c), close=c,
               pre_close=pre, volume=1e6, suspended=susp)


class _BuyOnceAtStart:
    """第 0 日收盘决策买入一次，此后持有不动。"""

    def __init__(self, broker):
        self.b = broker

    def decide(self, i):
        return Action.BUY if (i == 0 and not self.b.in_position()) else Action.HOLD


def test_signal_executes_next_day_open():
    """第0日收盘决策买 → 第1日(次日)开盘成交，价格为次日开盘价。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 12, 10),
            _bar("2020-03-04", 12, 13, 12)]
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: _BuyOnceAtStart(b), broker)

    assert len(broker.trades) == 1
    assert broker.trades[0].date == "2020-03-03"
    assert broker.trades[0].price == 10
    assert len(out["equity_curve"]) == 3


def test_buy_postponed_on_limit_up():
    """次日一字涨停买不进 → 挂单顺延到再下一个可交易日开盘成交。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 11, 11, 10),   # 一字涨停（10*1.1=11），买不进
            _bar("2020-03-04", 10.5, 11, 10.8)]
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: _BuyOnceAtStart(b), broker)

    assert len(broker.trades) == 1
    assert broker.trades[0].date == "2020-03-04"   # 涨停日跳过，顺延成交
    assert broker.trades[0].price == 10.5


def test_buy_postponed_on_suspension():
    """次日停牌无法成交 → 挂单顺延到复牌后第一个开盘继续尝试。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 10, 10, susp=True),   # 停牌
            _bar("2020-03-04", 10, 10, 10, susp=True),   # 继续停牌
            _bar("2020-03-05", 10.2, 11, 10)]             # 复牌，成交
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: _BuyOnceAtStart(b), broker)

    assert len(broker.trades) == 1
    assert broker.trades[0].date == "2020-03-05"
    assert broker.trades[0].price == 10.2


def test_sell_signal_executes_next_day_open():
    """持仓后卖出信号同样在次日开盘成交（T+1）。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 12, 10),   # 次日开盘买入成交
            _bar("2020-03-04", 12, 11, 12),   # 第2日收盘决策卖出 → 第3日开盘成交
            _bar("2020-03-05", 11, 11, 11)]

    class BuyThenSell:
        def __init__(self, b):
            self.b = b

        def decide(self, i):
            if i == 0 and not self.b.in_position():
                return Action.BUY
            if i == 2 and self.b.in_position():
                return Action.SELL
            return Action.HOLD

    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: BuyThenSell(b), broker)

    assert len(broker.trades) == 2
    assert broker.trades[0].side == "buy"
    assert broker.trades[0].date == "2020-03-03"
    assert broker.trades[1].side == "sell"
    assert broker.trades[1].date == "2020-03-05"
    assert broker.trades[1].price == 11


def test_equity_curve_length_matches_bars():
    """无论是否交易，equity_curve 长度必须与 bars 长度一致，且每日记录收盘净值。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 11, 10),
            _bar("2020-03-04", 11, 9, 11),
            _bar("2020-03-05", 9, 9.5, 9)]

    class NeverTrade:
        def __init__(self, b):
            self.b = b

        def decide(self, i):
            return Action.HOLD

    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: NeverTrade(b), broker)

    assert len(out["equity_curve"]) == len(bars)
    dates = [d for d, _ in out["equity_curve"]]
    assert dates == [b.date for b in bars]
    # 从未成交，净值始终等于初始资金
    assert all(eq == 100000 for _, eq in out["equity_curve"])
    assert out["trades"] == []


def test_pending_buy_overridden_by_reverse_signal_yields_no_trade():
    """顺延中的 BUY 挂单被反向 SELL 信号覆盖后，未持仓时 SELL 是安全死单。

    场景：第0日决策 BUY；第1日一字涨停买不进（挂单顺延），但第1日收盘策略
    又改口给出 SELL（此时仍未持仓）——按当前状态机语义，非 HOLD 信号会覆盖
    挂单，pending 变为 SELL。之后每日尝试撮合该 SELL，但 broker.try_sell
    在未持仓（shares<=0）时始终返回 False，因此绝不会产生任何成交，更不会
    做空。此测试锁定这条状态机最脆弱的路径，防止未来修改 try_sell 的前置
    检查时悄悄劣化为错误做空。
    """
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 11, 11, 10),   # 一字涨停，BUY 挂单顺延
            _bar("2020-03-04", 10.5, 10.5, 10.8),
            _bar("2020-03-05", 10, 10, 10)]

    class ReverseWithoutPosition:
        def __init__(self, b):
            self.b = b

        def decide(self, i):
            if i == 0 and not self.b.in_position():
                return Action.BUY
            if i == 1:
                # 未持仓状态下反悔给出 SELL，覆盖尚未成交的 BUY 挂单
                return Action.SELL
            return Action.HOLD

    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: ReverseWithoutPosition(b), broker)

    # 未持仓时的 SELL 挂单必须是安全死单：不产生任何成交，不做空。
    assert broker.trades == []
    assert broker.shares == 0
    assert broker.cash == 100000.0
    assert all(eq == 100000.0 for _, eq in out["equity_curve"])


def test_sell_postponed_on_limit_down():
    """对称场景：持仓后卖出信号遇一字跌停不能卖 → 顺延到再下一日开盘成交。"""
    bars = [_bar("2020-03-02", 10, 10, 10),
            _bar("2020-03-03", 10, 12, 10),    # 次日开盘买入成交
            _bar("2020-03-04", 9, 9, 10),      # 第2日收盘决策卖出；第3日一字跌停(9<=10*0.9)
            _bar("2020-03-05", 9.5, 9.5, 9)]   # 复牌可交易，跌停顺延到此日成交

    class BuyThenSellLimitDown:
        def __init__(self, b):
            self.b = b

        def decide(self, i):
            if i == 0 and not self.b.in_position():
                return Action.BUY
            if i == 1 and self.b.in_position():
                return Action.SELL
            return Action.HOLD

    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    run_loop(bars, lambda b: BuyThenSellLimitDown(b), broker)

    assert len(broker.trades) == 2
    assert broker.trades[0].side == "buy"
    assert broker.trades[1].side == "sell"
    assert broker.trades[1].date == "2020-03-05"   # 跌停日跳过，顺延成交
    assert broker.trades[1].price == 9.5


def test_return_dict_keys():
    """返回值结构：equity_curve 与 trades 两个键，trades 与 broker.trades 是同一对象。"""
    bars = [_bar("2020-03-02", 10, 10, 10)]
    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), "600000")
    out = run_loop(bars, lambda b: _BuyOnceAtStart(b), broker)
    assert set(out.keys()) == {"equity_curve", "trades"}
    assert out["trades"] is broker.trades
