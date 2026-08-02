"""回测引擎核心数据类型的测试。"""
from tradingagents.backtest.types import Action, Bar, CostConfig, PositionConfig, BacktestConfig


def test_defaults():
    """测试 BacktestConfig 默认值。"""
    c = BacktestConfig(symbol="000001", start_date="2020-01-01", end_date="2020-12-31")
    assert c.initial_capital == 100000.0
    assert c.cost.stamp_tax_rate == 0.001
    assert c.position.parts == 3 and c.position.reduce_mode == "reduce_one"
    assert Action.BUY != Action.SELL


def test_bar_defaults():
    """测试 Bar 默认值。"""
    b = Bar(date="2020-01-02", open=10, high=11, low=9, close=10.5, pre_close=10, volume=1e6)
    assert b.suspended is False and b.is_st is False
