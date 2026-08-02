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
    # B 股（900xxx）应被判为主板，不应误判为北交所
    assert board_of("900001") == "main"
    assert board_of("900950") == "main"
    # 北交所新代码（920xxx）及 8 开头
    assert board_of("920000") == "bse"
    assert board_of("800000") == "bse"


def test_price_limit_pct():
    """测试涨跌幅限制。"""
    # 主板
    assert price_limit_pct("600000", is_st=False) == 0.10
    assert price_limit_pct("600000", is_st=True) == 0.05
    # 创业板（注册制 ST 仍 20%）
    assert price_limit_pct("300750", is_st=True) == 0.20
    assert price_limit_pct("300750", is_st=False) == 0.20  # 对称分支
    # 科创板（注册制 ST 仍 20%）
    assert price_limit_pct("688111", is_st=False) == 0.20
    assert price_limit_pct("688111", is_st=True) == 0.20  # 对称分支
    # 北交所
    assert price_limit_pct("830799", is_st=True) == 0.30
    assert price_limit_pct("830799", is_st=False) == 0.30  # 对称分支


def test_limit_price_and_tradability():
    """测试涨跌停价与成交可行性。"""
    # pre_close=10, 主板普通±10% → 涨停11.00 跌停9.00
    assert limit_up_price(10.0, "600000", False) == 11.0
    assert limit_down_price(10.0, "600000", False) == 9.0
    assert can_buy_at_open(11.0, 10.0, "600000", False) is False   # 一字涨停不可买
    assert can_buy_at_open(10.5, 10.0, "600000", False) is True
    assert can_sell_at_open(9.0, 10.0, "600000", False) is False   # 一字跌停不可卖
    assert can_sell_at_open(9.5, 10.0, "600000", False) is True


def test_float_precision_in_limit_price():
    """测试涨跌停价的浮点精度（Decimal 四舍五入）。

    浮点二进制误差导致约 5.7% 的价位与交易所规则差 1 分钱。
    例如：0.95 * 1.1 = 1.045 应四舍五入为 1.05，
    但 round(0.95*1.1, 2) 因浮点误差算出 1.04。
    """
    # 测试触发浮点误差的边界价位：0.95 * 1.10 = 1.045 → 1.05
    assert limit_up_price(0.95, "600000", False) == 1.05
    assert limit_down_price(0.95, "600000", False) == 0.86  # 0.95 * 0.90 = 0.855 → 0.86

    # 测试其他边界：0.97 * 1.10 = 1.067 → 1.07
    assert limit_up_price(0.97, "600000", False) == 1.07
    assert limit_down_price(0.97, "600000", False) == 0.87  # 0.97 * 0.90 = 0.873 → 0.87

    # 测试 ST 股边界：0.99 * 1.05 = 1.0395 → 1.04
    assert limit_up_price(0.99, "600000", True) == 1.04
    assert limit_down_price(0.99, "600000", True) == 0.94  # 0.99 * 0.95 = 0.9405 → 0.94

    # 测试创业板边界：0.95 * 1.20 = 1.14
    assert limit_up_price(0.95, "300750", False) == 1.14
    assert limit_down_price(0.95, "300750", False) == 0.76  # 0.95 * 0.80 = 0.76


def test_costs():
    """测试交易成本计算。"""
    c = CostConfig()
    # 买入 10000 元：佣金 max(10000*0.00025, 5)=5，印花0，过户 10000*0.00001=0.1
    comm, stamp, transfer = buy_cost(10000.0, c)
    assert comm == 5.0 and stamp == 0.0 and round(transfer, 2) == 0.1
    # 卖出 10000 元：佣金5，印花 10000*0.001=10，过户 0.1
    comm, stamp, transfer = sell_cost(10000.0, c)
    assert comm == 5.0 and stamp == 10.0 and round(transfer, 2) == 0.1
