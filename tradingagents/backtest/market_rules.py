"""A股交易规则纯函数：板块、涨跌停、成交可行性、交易成本。"""
from typing import Literal
from .types import CostConfig


def board_of(symbol: str) -> Literal["main", "gem", "star", "bse"]:
    """
    判定股票所属板块。

    Args:
        symbol: 股票代码（如 "600000", "300750" 等）

    Returns:
        板块代码：
        - "main": 主板（沪深京 A 股）
        - "gem": 创业板（300/301 开头）
        - "star": 科创板（688 开头）
        - "bse": 北交所（8/9/43/83/87/92 开头）
    """
    s = symbol.zfill(6)
    if s.startswith("688"):
        return "star"
    if s.startswith("300") or s.startswith("301"):
        return "gem"
    if s.startswith(("8", "9", "43", "83", "87", "92")):
        return "bse"
    return "main"


def price_limit_pct(symbol: str, is_st: bool) -> float:
    """
    获取涨跌幅限制百分比。

    规则：
    - 主板：普通 10%，ST 5%
    - 创业板/科创板：注册制 20%（ST 不改）
    - 北交所：30%

    Args:
        symbol: 股票代码
        is_st: 是否 ST 股票

    Returns:
        涨跌幅限制（如 0.10 表示 10%）
    """
    board = board_of(symbol)
    if board in ("gem", "star"):
        return 0.20  # 注册制 ST 不改幅度
    if board == "bse":
        return 0.30
    return 0.05 if is_st else 0.10  # 主板


def limit_up_price(pre_close: float, symbol: str, is_st: bool) -> float:
    """
    计算涨停价。

    Args:
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股票

    Returns:
        涨停价（保留 2 位小数）
    """
    return round(pre_close * (1 + price_limit_pct(symbol, is_st)), 2)


def limit_down_price(pre_close: float, symbol: str, is_st: bool) -> float:
    """
    计算跌停价。

    Args:
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股票

    Returns:
        跌停价（保留 2 位小数）
    """
    return round(pre_close * (1 - price_limit_pct(symbol, is_st)), 2)


def can_buy_at_open(open_price: float, pre_close: float, symbol: str, is_st: bool) -> bool:
    """
    判断开盘时是否可以买入（即开盘未涨停）。

    Args:
        open_price: 开盘价
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股票

    Returns:
        True 表示可以买入，False 表示一字涨停不可买
    """
    return open_price < limit_up_price(pre_close, symbol, is_st)


def can_sell_at_open(open_price: float, pre_close: float, symbol: str, is_st: bool) -> bool:
    """
    判断开盘时是否可以卖出（即开盘未跌停）。

    Args:
        open_price: 开盘价
        pre_close: 前收盘价
        symbol: 股票代码
        is_st: 是否 ST 股票

    Returns:
        True 表示可以卖出，False 表示一字跌停不可卖
    """
    return open_price > limit_down_price(pre_close, symbol, is_st)


def buy_cost(amount: float, cost: CostConfig) -> tuple[float, float, float]:
    """
    计算买入交易成本（佣金、印花税、过户费）。

    买入时：
    - 佣金 = max(金额 * 佣金率, 最小佣金)
    - 印花税 = 0（买入不收）
    - 过户费 = 金额 * 过户费率

    Args:
        amount: 交易金额
        cost: 成本配置

    Returns:
        (佣金, 印花税, 过户费) 三元组，均保留 2 位小数
    """
    comm = max(amount * cost.commission_rate, cost.min_commission)
    transfer = amount * cost.transfer_fee_rate
    return round(comm, 2), 0.0, round(transfer, 2)


def sell_cost(amount: float, cost: CostConfig) -> tuple[float, float, float]:
    """
    计算卖出交易成本（佣金、印花税、过户费）。

    卖出时：
    - 佣金 = max(金额 * 佣金率, 最小佣金)
    - 印花税 = 金额 * 印花税率
    - 过户费 = 金额 * 过户费率

    Args:
        amount: 交易金额
        cost: 成本配置

    Returns:
        (佣金, 印花税, 过户费) 三元组，均保留 2 位小数
    """
    comm = max(amount * cost.commission_rate, cost.min_commission)
    stamp = amount * cost.stamp_tax_rate
    transfer = amount * cost.transfer_fee_rate
    return round(comm, 2), round(stamp, 2), round(transfer, 2)
