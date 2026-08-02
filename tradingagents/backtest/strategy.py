"""条件积木策略与通用信号接口。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Callable, Union

from .types import Action
from .indicators import compute_indicators


@dataclass
class Condition:
    """单条比较条件。

    left: 指标名（如 'ma5'）或 'close'
    op: 比较算子，取值 '>' / '<' / 'cross_up' / 'cross_down'
    right: 数字阈值，或另一个指标名（字符串）
    """
    left: str
    op: str
    right: Union[str, float]


class SignalSource(ABC):
    """通用信号接口：给定第 i 个交易日，返回交易动作。"""

    @abstractmethod
    def decide(self, i: int) -> Action:
        ...


def _val(ind: dict, name: str, i: int):
    """安全取指标序列第 i 个值，指标不存在时返回 None。"""
    return ind[name][i] if name in ind else None


def cross_up(series, other, i: int) -> bool:
    """判断 series 是否在第 i 个位置相对 other 金叉（上穿）。"""
    if i == 0:
        return False
    a_prev, a_now = series[i - 1], series[i]
    b_prev, b_now = other[i - 1], other[i]
    if None in (a_prev, a_now, b_prev, b_now):
        return False
    return a_prev <= b_prev and a_now > b_now


def cross_down(series, other, i: int) -> bool:
    """判断 series 是否在第 i 个位置相对 other 死叉（下穿）。"""
    if i == 0:
        return False
    a_prev, a_now = series[i - 1], series[i]
    b_prev, b_now = other[i - 1], other[i]
    if None in (a_prev, a_now, b_prev, b_now):
        return False
    return a_prev >= b_prev and a_now < b_now


class RuleStrategy(SignalSource):
    """由比较条件组合而成的规则策略（条件积木）。"""

    def __init__(self, bars, buy_rules: List[Condition], buy_logic: str,
                 sell_rules: List[Condition], sell_logic: str,
                 in_position_fn: Callable[[int], bool]):
        self.ind = compute_indicators(bars)
        self.close = [b.close for b in bars]
        self.buy_rules, self.buy_logic = buy_rules, buy_logic
        self.sell_rules, self.sell_logic = sell_rules, sell_logic
        self.in_position = in_position_fn

    def _series(self, name, i):
        """取 name 对应序列在第 i 个位置的值，name 可为 'close' 或指标名。"""
        if name == "close":
            return self.close[i]
        return _val(self.ind, name, i)

    def _eval_one(self, c: Condition, i: int) -> bool:
        left_now = self._series(c.left, i)
        if left_now is None:
            return False
        if c.op in ("cross_up", "cross_down"):
            if i == 0:
                return False
            left_prev = self._series(c.left, i - 1)
            right_now = self._series(c.right, i)
            right_prev = self._series(c.right, i - 1)
            if None in (left_prev, right_now, right_prev):
                return False
            if c.op == "cross_up":
                return left_prev <= right_prev and left_now > right_now
            return left_prev >= right_prev and left_now < right_now
        right = self._series(c.right, i) if isinstance(c.right, str) else c.right
        if right is None:
            return False
        return left_now > right if c.op == ">" else left_now < right

    def _eval_group(self, rules, logic, i) -> bool:
        if not rules:
            return False
        results = [self._eval_one(c, i) for c in rules]
        return all(results) if logic == "AND" else any(results)

    def decide(self, i: int) -> Action:
        if self.in_position(i):
            if self._eval_group(self.sell_rules, self.sell_logic, i):
                return Action.SELL
        else:
            if self._eval_group(self.buy_rules, self.buy_logic, i):
                return Action.BUY
        return Action.HOLD
