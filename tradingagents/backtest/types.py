"""回测引擎核心数据类型。"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class Action(Enum):
    """交易动作枚举。"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Bar:
    """K线数据。"""
    date: str
    """交易日期"""
    open: float
    """开盘价"""
    high: float
    """最高价"""
    low: float
    """最低价"""
    close: float
    """收盘价"""
    pre_close: float
    """前收盘价"""
    volume: float
    """成交量"""
    suspended: bool = False
    """是否停牌"""
    is_st: bool = False
    """是否 ST 股票"""


@dataclass
class Trade:
    """交易记录。"""
    date: str
    """交易日期"""
    side: Literal['buy', 'sell']
    """交易方向: 'buy' 或 'sell'"""
    price: float
    """成交价格"""
    shares: int
    """成交数量"""
    commission: float
    """手续费"""
    stamp_tax: float
    """印花税"""
    transfer_fee: float
    """过户费"""


@dataclass
class CostConfig:
    """交易成本配置。"""
    commission_rate: float = 0.00025
    """手续费率"""
    min_commission: float = 5.0
    """最小手续费"""
    stamp_tax_rate: float = 0.001
    """印花税率"""
    transfer_fee_rate: float = 0.00001
    """过户费率"""


@dataclass
class PositionConfig:
    """持仓配置。"""
    parts: int = 3
    """分仓数量"""
    reduce_mode: Literal['reduce_one', 'clear_all'] = "reduce_one"
    """减仓模式: 'reduce_one' 或 'clear_all'"""


@dataclass
class BacktestConfig:
    """回测配置。"""
    symbol: str
    """股票代码"""
    start_date: str
    """回测开始日期"""
    end_date: str
    """回测结束日期"""
    initial_capital: float = 100000.0
    """初始资金"""
    cost: CostConfig = field(default_factory=CostConfig)
    """交易成本配置"""
    position: PositionConfig = field(default_factory=PositionConfig)
    """持仓配置"""
