"""回测结果组装与序列化，以及顶层 run_backtest。"""
from dataclasses import dataclass, asdict
from typing import List, Optional

from .types import BacktestConfig
from .broker import Broker
from .strategy import RuleStrategy
from .engine import run_loop
from .metrics import compute_metrics


@dataclass
class BacktestResult:
    """一次回测的完整结果：配置、净值曲线、基准曲线、成交明细与绩效指标。"""
    config: BacktestConfig
    equity_curve: list
    benchmark_curve: list
    trades: list
    metrics: dict

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的字典，供 Web 层直接返回。"""
        return {
            "config": asdict(self.config),
            "equity_curve": self.equity_curve,
            "benchmark_curve": self.benchmark_curve,
            "trades": [asdict(t) for t in self.trades],
            "metrics": self.metrics,
        }


def run_backtest(config: BacktestConfig, buy_rules, buy_logic, sell_rules, sell_logic,
                 bars: Optional[List] = None, st_service=None) -> BacktestResult:
    """顶层回测入口：串联行情加载、策略、撮合与绩效计算。

    Args:
        config: 回测配置（标的、区间、资金、成本、分仓）。
        buy_rules: 买入条件积木列表。
        buy_logic: 买入条件组合逻辑，'AND' 或 'OR'。
        sell_rules: 卖出条件积木列表。
        sell_logic: 卖出条件组合逻辑，'AND' 或 'OR'。
        bars: 预取的 K 线序列；为 None 时通过 data_feed.load_bars 从库读取
            （测试场景应显式传入 bars，避免触库）。
        st_service: 透传给 load_bars 的 ST 状态服务，仅在 bars=None 时使用。

    Returns:
        BacktestResult，含净值曲线、基准曲线、成交明细与绩效指标。
    """
    if bars is None:
        from .data_feed import load_bars
        bars = load_bars(config.symbol, config.start_date, config.end_date, st_service)

    broker = Broker(config.initial_capital, config.cost, config.position, config.symbol)

    def factory(bk):
        return RuleStrategy(bars, buy_rules, buy_logic, sell_rules, sell_logic,
                            in_position_fn=lambda i: bk.in_position())

    out = run_loop(bars, factory, broker)
    metrics = compute_metrics(out["equity_curve"], config.initial_capital, bars, broker.trades)
    return BacktestResult(
        config=config,
        equity_curve=out["equity_curve"],
        benchmark_curve=metrics.pop("benchmark_curve"),
        trades=broker.trades,
        metrics=metrics,
    )
