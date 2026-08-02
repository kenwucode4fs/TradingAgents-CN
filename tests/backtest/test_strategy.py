"""测试条件积木策略与通用信号接口。"""
from tradingagents.backtest.types import Bar, Action
from tradingagents.backtest.strategy import RuleStrategy, Condition


def _bars(closes):
    return [Bar(date=f"2020-02-{i+1:02d}", open=c, high=c, low=c, close=c,
                pre_close=c, volume=100) for i, c in enumerate(closes)]


def test_rsi_threshold_buy():
    bars = _bars([10, 9, 8, 7, 6, 5, 4, 3])   # 持续下跌 → RSI 低
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("rsi6", "<", 30)], buy_logic="AND",
        sell_rules=[Condition("rsi6", ">", 70)], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    # 末日 RSI6 应很低 → 买入
    assert strat.decide(len(bars) - 1) == Action.BUY


def test_ma_cross_up_buy():
    # 构造 MA5 上穿 MA20 的形态：先跌后强涨
    closes = [10]*20 + [11, 13, 15, 17, 19]
    bars = _bars(closes)
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    actions = [strat.decide(i) for i in range(len(bars))]
    assert Action.BUY in actions
