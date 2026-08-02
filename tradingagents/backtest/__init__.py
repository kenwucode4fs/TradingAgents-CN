"""回测引擎公共 API。"""
from .result import run_backtest, BacktestResult
from .types import Action, Bar, Trade, CostConfig, PositionConfig, BacktestConfig
from .strategy import Condition, RuleStrategy, SignalSource

__all__ = [
    "run_backtest", "BacktestResult",
    "Action", "Bar", "Trade", "CostConfig", "PositionConfig", "BacktestConfig",
    "Condition", "RuleStrategy", "SignalSource",
]
