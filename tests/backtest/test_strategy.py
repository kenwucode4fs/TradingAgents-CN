"""测试条件积木策略与通用信号接口。"""
import pytest

from tradingagents.backtest.types import Bar, Action
from tradingagents.backtest.strategy import RuleStrategy, Condition, cross_up, cross_down


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


def test_cross_up_true_at_cross_point():
    series = [1, 3]
    other = [2, 2]
    assert cross_up(series, other, 1) is True


def test_cross_up_false_when_not_crossing():
    series = [3, 3]
    other = [2, 2]
    assert cross_up(series, other, 1) is False


def test_cross_up_false_at_i_zero():
    assert cross_up([1, 3], [2, 2], 0) is False


def test_cross_up_false_when_none_present():
    assert cross_up([None, 3], [2, 2], 1) is False
    assert cross_up([1, 3], [2, None], 1) is False


def test_cross_down_true_at_cross_point():
    series = [3, 1]
    other = [2, 2]
    assert cross_down(series, other, 1) is True


def test_cross_down_false_when_not_crossing():
    series = [1, 1]
    other = [2, 2]
    assert cross_down(series, other, 1) is False


def test_cross_down_false_at_i_zero():
    assert cross_down([3, 1], [2, 2], 0) is False


def test_cross_down_false_when_none_present():
    assert cross_down([None, 1], [2, 2], 1) is False
    assert cross_down([3, 1], [2, None], 1) is False


def test_invalid_op_raises_value_error():
    bars = _bars([10, 9, 8])
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("close", "!=", 5)], buy_logic="AND",
        sell_rules=[], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    with pytest.raises(ValueError):
        strat.decide(len(bars) - 1)


def test_invalid_logic_raises_value_error():
    bars = _bars([10, 9, 8])
    strat = RuleStrategy(
        bars,
        buy_rules=[Condition("close", ">", 1)], buy_logic="XOR",
        sell_rules=[], sell_logic="AND",
        in_position_fn=lambda i: False,
    )
    with pytest.raises(ValueError):
        strat.decide(len(bars) - 1)
