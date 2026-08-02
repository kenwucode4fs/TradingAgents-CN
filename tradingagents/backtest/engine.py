"""逐日回放主循环。

语义（严格遵循 T+1、杜绝前视偏差）：
1. 遍历交易日 bars，索引 i 从 0 到末尾。
2. 信号在第 i 日**收盘后**由 ``strategy.decide(i)`` 产生（买/卖/持有）。
3. 该信号产生的成交发生在**第 i+1 日的开盘价**——即挂单（pending），下一根
   bar 开盘时才执行 ``broker.try_buy_one_part``/``broker.try_sell``。
4. 若因停牌或涨跌停未成交（返回 False），挂单**顺延**到再下一个可交易日
   开盘继续尝试（pending 保留），直到成交，或被当日新产生的非 HOLD 信号取代。
5. 每根 bar 收盘记净值 ``broker.market_value(bar.close)``。
"""
from typing import Callable, List, Tuple

from .broker import Broker
from .types import Action, Bar


def run_loop(bars: List[Bar], strategy_factory: Callable, broker: Broker) -> dict:
    """逐日回放：驱动策略产生信号、由 broker 在次日开盘撮合、记录每日净值。

    Args:
        bars: 按日期升序排列的 K 线序列。
        strategy_factory: 接受 broker、返回 SignalSource 的工厂函数，
            使策略能够查询 broker.in_position() 等账户状态。
        broker: 已初始化的模拟账户，负责实际撮合与成本计算。

    Returns:
        {"equity_curve": [(date, equity), ...], "trades": broker.trades}
    """
    strategy = strategy_factory(broker)
    equity_curve: List[Tuple[str, float]] = []
    # 当前挂单：上一次收盘产生、尚未成交的信号；HOLD 表示无挂单。
    pending: Action = Action.HOLD

    for i, bar in enumerate(bars):
        # 1. 先尝试用当日开盘价撮合挂单（T+1 成交）。
        if pending != Action.HOLD and not bar.suspended:
            if pending == Action.BUY:
                executed = broker.try_buy_one_part(bar)
            else:  # Action.SELL
                executed = broker.try_sell(bar)
            if executed:
                pending = Action.HOLD
            # 未成交（涨跌停等）：保留 pending，顺延到下一个可交易日再试。
        # 停牌日无法撮合：同样保留 pending，顺延。

        # 2. 收盘后产生新决策；非 HOLD 信号覆盖挂单（取代旧的、或设置新的）。
        action = strategy.decide(i)
        if action != Action.HOLD:
            pending = action

        # 3. 收盘记净值。
        equity_curve.append((bar.date, broker.market_value(bar.close)))

    return {"equity_curve": equity_curve, "trades": broker.trades}
