"""端到端测试：串联 data_feed/strategy/broker/engine/metrics 的顶层 run_backtest。"""
from tradingagents.backtest import run_backtest
from tradingagents.backtest.types import Bar, BacktestConfig, PositionConfig
from tradingagents.backtest.strategy import Condition


def _bars(closes):
    """按给定收盘价序列构造最简 Bar 列表（open=high=low=close，volume 固定）。"""
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        out.append(Bar(date=f"2021-01-{i+1:02d}", open=c, high=c, low=c, close=c,
                       pre_close=prev, volume=1e6))
        prev = c
    return out


def test_double_ma_runs_and_reports():
    """双均线金叉买/死叉卖策略跑通全流程，且结果可序列化。"""
    closes = [10]*20 + [11, 12, 13, 14, 15, 14, 13, 12, 11, 10]
    bars = _bars(closes)
    cfg = BacktestConfig(symbol="600000", start_date="2021-01-01", end_date="2021-02-01",
                         initial_capital=100000, position=PositionConfig(parts=1))
    res = run_backtest(
        cfg,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
        bars=bars,
    )
    d = res.to_dict()
    assert "metrics" in d and "equity_curve" in d
    assert d["metrics"]["trade_count"] >= 1
    assert len(d["equity_curve"]) == len(bars)
    assert "benchmark_return" in d["metrics"]
