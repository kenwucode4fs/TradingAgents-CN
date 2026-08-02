"""A股交易规则测试。"""
from tradingagents.backtest.market_rules import (
    board_of, price_limit_pct, limit_up_price, limit_down_price,
    can_buy_at_open, can_sell_at_open,
    buy_cost, sell_cost,
)
from tradingagents.backtest.types import CostConfig


def test_board_of():
    """测试板块判定。"""
    assert board_of("600000") == "main"
    assert board_of("000001") == "main"
    assert board_of("300750") == "gem"
    assert board_of("688111") == "star"
    assert board_of("830799") == "bse"


def test_price_limit_pct():
    """测试涨跌幅限制。"""
    assert price_limit_pct("600000", is_st=False) == 0.10
    assert price_limit_pct("600000", is_st=True) == 0.05
    assert price_limit_pct("300750", is_st=True) == 0.20   # 注册制 ST 仍 20%
    assert price_limit_pct("688111", is_st=False) == 0.20
    assert price_limit_pct("830799", is_st=True) == 0.30


def test_limit_price_and_tradability():
    """测试涨跌停价与成交可行性。"""
    # pre_close=10, 主板普通±10% → 涨停11.00 跌停9.00
    assert limit_up_price(10.0, "600000", False) == 11.0
    assert limit_down_price(10.0, "600000", False) == 9.0
    assert can_buy_at_open(11.0, 10.0, "600000", False) is False   # 一字涨停不可买
    assert can_buy_at_open(10.5, 10.0, "600000", False) is True
    assert can_sell_at_open(9.0, 10.0, "600000", False) is False   # 一字跌停不可卖
    assert can_sell_at_open(9.5, 10.0, "600000", False) is True


def test_costs():
    """测试交易成本计算。"""
    c = CostConfig()
    # 买入 10000 元：佣金 max(10000*0.00025, 5)=5，印花0，过户 10000*0.00001=0.1
    comm, stamp, transfer = buy_cost(10000.0, c)
    assert comm == 5.0 and stamp == 0.0 and round(transfer, 2) == 0.1
    # 卖出 10000 元：佣金5，印花 10000*0.001=10，过户 0.1
    comm, stamp, transfer = sell_cost(10000.0, c)
    assert comm == 5.0 and stamp == 10.0 and round(transfer, 2) == 0.1
