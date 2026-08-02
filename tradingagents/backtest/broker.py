"""账户、持仓、固定份数分批撮合，含 A股成交可行性与交易成本。

T+1 限制由上层 engine 控制，本模块只负责单步撮合逻辑。
"""
import math
from typing import List

from .types import Bar, Trade, CostConfig, PositionConfig
from . import market_rules as mr


class Broker(object):
    """模拟账户：维护现金/持仓/分档买入记录，并按 A 股规则单步撮合。"""

    def __init__(self, initial_capital: float, cost: CostConfig,
                 position: PositionConfig, symbol: str):
        self.cash = float(initial_capital)
        self.initial_capital = float(initial_capital)
        self.cost = cost
        self.position = position
        self.symbol = symbol
        self.shares = 0
        self.held_parts = 0
        self.part_shares: List[int] = []  # 每档买入股数，用于按档减仓
        self.trades: List[Trade] = []

    def in_position(self) -> bool:
        """是否持有仓位。"""
        return self.shares > 0

    def market_value(self, price: float) -> float:
        """按给定价格计算账户市值（现金 + 持仓市值）。"""
        return round(self.cash + self.shares * price, 2)

    def _part_amount(self) -> float:
        """单档目标金额 = 初始资金 / 分仓数。"""
        return self.initial_capital / self.position.parts

    def _budget(self) -> float:
        """本档实际可用预算 = min(单档目标金额, 当前现金)。"""
        return min(self._part_amount(), self.cash)

    def buyable_shares_for_part(self, price: float) -> int:
        """按单档资金、给定价格计算可买股数（按 100 股取整，不含成本）。"""
        if price <= 0:
            return 0
        lots = math.floor(self._budget() / price / 100)
        return lots * 100

    def try_buy_one_part(self, bar: Bar) -> bool:
        """尝试按 A 股规则以 bar.open 买入一档。

        停牌 / 一字涨停（无法买入）/ 资金不足 / 已满仓 时不成交，返回 False。
        """
        # 已停牌或已买满所有档位，不成交
        if bar.suspended or self.held_parts >= self.position.parts:
            return False
        # 一字涨停（开盘价触及涨停）无法买入
        if not mr.can_buy_at_open(bar.open, bar.pre_close, self.symbol, bar.is_st):
            return False

        budget = self._budget()
        shares = self.buyable_shares_for_part(bar.open)
        if shares <= 0:
            return False

        amount = shares * bar.open
        comm, stamp, transfer = mr.buy_cost(amount, self.cost)
        total = amount + comm + transfer
        # 含成本后超出本档预算（或现金），减一手再试一次
        if total > budget:
            shares -= 100
            if shares <= 0:
                return False
            amount = shares * bar.open
            comm, stamp, transfer = mr.buy_cost(amount, self.cost)
            total = amount + comm + transfer
            if total > budget:
                return False
        # 不变量：budget = min(单档金额, cash) <= cash，
        # 经上面对 budget 的校验后 total 必然 <= cash；此处仅作防御性断言。
        assert total <= self.cash, "买入总花费不应超过可用现金（不变量被打破）"

        self.cash = round(self.cash - total, 2)
        self.shares += shares
        self.held_parts += 1
        self.part_shares.append(shares)
        self.trades.append(Trade(bar.date, "buy", bar.open, shares, comm, stamp, transfer))
        return True

    def try_sell(self, bar: Bar) -> bool:
        """尝试按 A 股规则以 bar.open 卖出（按 reduce_mode 减一档或全清）。

        停牌 / 一字跌停（无法卖出）/ 无持仓 时不成交，返回 False。
        """
        if self.shares <= 0 or bar.suspended:
            return False
        # 一字跌停（开盘价触及跌停）无法卖出
        if not mr.can_sell_at_open(bar.open, bar.pre_close, self.symbol, bar.is_st):
            return False

        if self.position.reduce_mode == "clear_all":
            sell_shares = self.shares
        else:
            # 按档减仓：卖出最后买入的一档股数
            sell_shares = self.part_shares[-1] if self.part_shares else self.shares

        amount = sell_shares * bar.open
        comm, stamp, transfer = mr.sell_cost(amount, self.cost)
        self.cash = round(self.cash + amount - comm - stamp - transfer, 2)
        self.shares -= sell_shares

        if self.position.reduce_mode == "clear_all":
            self.held_parts = 0
            self.part_shares = []
        else:
            self.held_parts = max(0, self.held_parts - 1)
            if self.part_shares:
                self.part_shares.pop()

        self.trades.append(Trade(bar.date, "sell", bar.open, sell_shares, comm, stamp, transfer))
        return True
