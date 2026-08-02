"""Broker（账户与固定份数分批撮合）单元测试。"""
from tradingagents.backtest.types import Bar, CostConfig, PositionConfig
from tradingagents.backtest.broker import Broker


def _bar(o, pre, vol=1e6, st=False, susp=False):
    return Bar(date="2020-03-02", open=o, high=o, low=o, close=o,
               pre_close=pre, volume=vol, suspended=susp, is_st=st)


def test_buy_one_part_and_cost():
    b = Broker(initial_capital=100000, cost=CostConfig(),
               position=PositionConfig(parts=2), symbol="600000")
    ok = b.try_buy_one_part(_bar(o=10.0, pre=10.0))   # 一档 5万，10元 → 4900股(取整100)
    assert ok is True
    assert b.shares == 4900          # floor(50000/10/100)*100
    assert b.held_parts == 1
    # 现金 = 10万 - 成交额49000 - 佣金max(49000*0.00025,5)=12.25 - 过户0.49
    assert round(b.cash, 2) == round(100000 - 49000 - 12.25 - 0.49, 2)


def test_cannot_buy_on_limit_up():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    assert b.try_buy_one_part(_bar(o=11.0, pre=10.0)) is False   # 涨停
    assert b.shares == 0


def test_cannot_buy_when_suspended():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    assert b.try_buy_one_part(_bar(o=10.0, pre=10.0, susp=True)) is False


def test_sell_reduce_one():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2, reduce_mode="reduce_one"), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))   # 两档
    assert b.held_parts == 2
    sold = b.try_sell(_bar(o=12.0, pre=11.0))    # 减一档
    assert sold is True and b.held_parts == 1


def test_sell_clear_all():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2, reduce_mode="clear_all"), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    b.try_sell(_bar(o=12.0, pre=11.0))
    assert b.shares == 0 and b.held_parts == 0


def test_cannot_sell_on_limit_down():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    shares_before, cash_before, parts_before = b.shares, b.cash, b.held_parts
    # 主板跌停价 = 10 * 0.9 = 9.0，open 恰好等于跌停价（一字跌停，不可卖）
    sold = b.try_sell(_bar(o=9.0, pre=10.0))
    assert sold is False
    assert b.shares == shares_before
    assert b.cash == cash_before
    assert b.held_parts == parts_before


def test_market_value_after_buy():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    b.try_buy_one_part(_bar(o=10.0, pre=10.0))
    assert b.market_value(12.0) == round(b.cash + b.shares * 12.0, 2)


def test_buyable_shares_for_part():
    b = Broker(100000, CostConfig(), PositionConfig(parts=2), "600000")
    # 单档预算 = min(50000, 100000) = 50000，10元 → floor(50000/10/100)*100 = 5000（不含成本）
    assert b.buyable_shares_for_part(10.0) == 5000
    # 非正价格直接返回 0
    assert b.buyable_shares_for_part(0) == 0
