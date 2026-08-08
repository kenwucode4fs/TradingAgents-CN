"""组合回测主循环测试:验证防前视偏差、T+1 次日开盘成交、每日净值、逐月调仓。"""
import datetime
from tradingagents.portfolio import run_portfolio_backtest
from tradingagents.backtest.types import CostConfig


def _panel(code, dates_prices):
    return [{"date": d, "open": p, "close": p, "volume": 1000000} for d, p in dates_prices]


def test_portfolio_backtest_basic():
    dates = ["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-28", "2024-02-29"]
    # A 持续涨、B 平、C 跌
    panel = {
        "A": _panel("A", [(d, 10 + i) for i, d in enumerate(dates)]),
        "B": _panel("B", [(d, 20.0) for d in dates]),
        "C": _panel("C", [(d, 30 - i) for i, d in enumerate(dates)]),
    }
    sections = {
        "2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
        "2024-02-29": {"A": {"pe": 6, "pb": 1, "total_mv": 100}, "B": {"pe": 8, "pb": 2, "total_mv": 200}, "C": {"pe": 20, "pb": 3, "total_mv": 300}},
    }
    benchmark = [(d, 1000.0 + i) for i, d in enumerate(dates)]
    cfg = {"start_date": "2024-01-30", "end_date": "2024-02-29", "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "pe", "weight": 1, "direction": "asc"}]  # 低 PE 优先 → 选 A
    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)
    assert len(r["equity_curve"]) >= 3
    assert r["rebalances"], "应有调仓记录"
    # 第一个调仓日 2024-01-31,次日 2024-02-01 成交 → 买入低PE的 A
    assert any(any(b["code"] == "A" for b in rb["buys"]) for rb in r["rebalances"])
    assert "total_return" in r["metrics"] and "benchmark_return" in r["metrics"]


def test_no_lookahead_uses_only_past_prices():
    # 调仓日 D 的因子若用了 D 之后的价,结果会不同;这里构造 A 在 D 后暴涨,
    # 若引擎错误地用了未来数据算动量,排序会变。用只有 pe 的因子(不依赖未来)确保稳定,
    # 主要断言:调仓成交价用的是 D 的"次一交易日"open,而非更晚的价。
    dates = ["2024-01-31", "2024-02-01", "2024-02-05"]
    panel = {"A": [{"date": "2024-01-31", "open": 10, "close": 10, "volume": 1e6},
                   {"date": "2024-02-01", "open": 11, "close": 11, "volume": 1e6},
                   {"date": "2024-02-05", "open": 99, "close": 99, "volume": 1e6}]}
    sections = {"2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
    cfg = {"start_date": "2024-01-31", "end_date": "2024-02-05", "initial_capital": 100000.0, "cost": CostConfig()}
    r = run_portfolio_backtest(cfg, [{"key": "pe", "weight": 1, "direction": "asc"}], sections, panel, [("2024-01-31", 1000.0), ("2024-02-05", 1000.0)], top_n=1)
    buy = [b for rb in r["rebalances"] for b in rb["buys"] if b["code"] == "A"][0]
    assert buy["price"] == 11  # 次日 2024-02-01 open,不是 2024-02-05 的 99


def test_sells_stock_that_falls_out_of_topn():
    # 第一次调仓选 A(低 pe),第二次调仓 A 的 pe 变高、B 变低 → A 跌出 TopN、B 进榜。
    # 验证第二次调仓能正常卖出 A(而不是被当成"停牌"永远滞留持仓)。
    dates = ["2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"]
    panel = {
        "A": _panel("A", [(d, 10.0) for d in dates]),
        "B": _panel("B", [(d, 20.0) for d in dates]),
    }
    sections = {
        "2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}, "B": {"pe": 20, "pb": 1, "total_mv": 100}},
        "2024-02-29": {"A": {"pe": 20, "pb": 1, "total_mv": 100}, "B": {"pe": 5, "pb": 1, "total_mv": 100}},
    }
    benchmark = [("2024-01-31", 1000.0), ("2024-03-01", 1000.0)]
    cfg = {"start_date": "2024-01-31", "end_date": "2024-03-01", "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "pe", "weight": 1, "direction": "asc"}]
    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)
    # 第二次调仓应卖出 A、买入 B
    assert any(any(s["code"] == "A" for s in rb["sells"]) for rb in r["rebalances"])
    assert any(any(b["code"] == "B" for b in rb["buys"]) for rb in r["rebalances"])


def test_suspended_day_uses_last_known_close_not_zero():
    # A 中途某日(2024-02-02)在 price_panel 里缺行(停牌/数据缺口),
    # 该日净值应沿用最后已知收盘价估值,不能把持仓当成 0 市值导致净值假暴跌。
    # 用 Z 的行情撑起"2024-02-02"这一天存在于交易日集合里(Z 不在 monthly_sections 候选池内)。
    dates = ["2024-01-31", "2024-02-01", "2024-02-02", "2024-02-05"]
    a_dates = [d for d in dates if d != "2024-02-02"]
    panel = {
        "A": _panel("A", [(d, 10.0) for d in a_dates]),
        "Z": _panel("Z", [(d, 50.0) for d in dates]),
    }
    sections = {"2024-01-31": {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
    benchmark = [("2024-01-31", 1000.0), ("2024-02-05", 1000.0)]
    cfg = {"start_date": "2024-01-31", "end_date": "2024-02-05", "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "pe", "weight": 1, "direction": "asc"}]
    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)
    eq = dict(r["equity_curve"])
    assert eq["2024-02-02"] > 0
    # 缺口日与前一日持仓、价格均未变化,净值应完全相同(用最后已知价兜底),而不是跌成 0
    assert eq["2024-02-02"] == eq["2024-02-01"]


def test_first_rebalance_uses_lookback_history_before_start():
    # price_panel 里预取了 start 之前的 lookback 历史(如实际场景约 500 天),
    # 回测区间起点(start)附近就调仓,因子用 mom_60(需要 61 个收盘点)。
    # 若引擎错误地只从 [start,end] 内的 trade_days 取 closes(丢弃 lookback),
    # 首个调仓日(≈start)只有 1 个收盘点,mom_60 算不出 → score_universe 剔除全部候选
    # → 首次调仓空仓(无 buys)。修复后应能直接用 lookback 历史算出因子,首个调仓日就选出股票。
    d0 = datetime.date(2023, 10, 1)
    all_dates = [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(70)]
    lookback_dates = all_dates[:65]   # start 之前的 lookback 历史(65 天)
    start = all_dates[65]             # 回测区间起点,也是首个调仓日
    trade_window = all_dates[65:]     # [start, end] 区间内的交易日(仅 5 天)
    end = trade_window[-1]

    closes = {d: 10.0 + i * 0.05 for i, d in enumerate(all_dates)}  # 持续小幅上涨,便于算出正的 mom_60
    panel = {"A": _panel("A", [(d, closes[d]) for d in all_dates])}
    sections = {start: {"A": {"pe": 5, "pb": 1, "total_mv": 100}}}
    benchmark = [(start, 1000.0), (end, 1000.0)]
    cfg = {"start_date": start, "end_date": end, "initial_capital": 100000.0, "cost": CostConfig()}
    factors = [{"key": "mom_60", "weight": 1, "direction": "desc"}]

    r = run_portfolio_backtest(cfg, factors, sections, panel, benchmark, top_n=1)

    assert r["rebalances"], "应有调仓记录"
    first_rb = r["rebalances"][0]
    assert first_rb["buys"], "首个调仓日应能用 lookback 历史算出 mom_60 并选出股票,不应空仓"
    assert any(b["code"] == "A" for b in first_rb["buys"])
