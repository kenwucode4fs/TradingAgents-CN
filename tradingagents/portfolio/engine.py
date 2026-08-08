"""逐月调仓组合回测:防前视(只用<=D数据)、防幸存者偏差(候选来自当时截面)、
T+1 次日开盘成交、每日净值。纯函数,数据由调用方注入。"""
import bisect
from tradingagents.factor import score_universe
from .rebalance import compute_rebalance
from .metrics import compute_portfolio_metrics


def _all_dates(price_panel, start, end):
    ds = set()
    for rows in price_panel.values():
        for r in rows:
            if start <= r["date"] <= end:
                ds.add(r["date"])
    return sorted(ds)


def run_portfolio_backtest(config, factor_configs, monthly_sections, price_panel, benchmark, top_n):
    start, end = config["start_date"], config["end_date"]
    cap0 = config["initial_capital"]
    cost = config["cost"]

    trade_days = _all_dates(price_panel, start, end)
    rebal_days = sorted(d for d in monthly_sections if start <= d <= end)

    # 每股 date→row 索引,便于取价与切片
    by_code = {c: {r["date"]: r for r in rows} for c, rows in price_panel.items()}

    # 每股升序 date/close/volume 数组(含 start 之前的 lookback 历史),供因子计算按 <=D 二分取前缀。
    # price_panel 已是按 date 升序的 list,这里仍防御性排序一次(仅在回测启动时做一次,不在逐日循环里)。
    hist = {}
    for c, rows in price_panel.items():
        rows_sorted = sorted(rows, key=lambda r: r["date"])
        ds, cs, vs = [], [], []
        for r in rows_sorted:
            if r.get("close") is None:
                continue
            ds.append(r["date"]); cs.append(r["close"]); vs.append(r.get("volume") or 0)
        hist[c] = (ds, cs, vs)

    holdings, cash = {}, cap0
    rebalances = []
    equity_curve = []
    pending = None  # (成交日, 目标TopN)
    last_close = {}  # 每股最后已知收盘价（停牌/数据缺口日用于估值兜底）

    for di, d in enumerate(trade_days):
        # 先更新当日可得的收盘价（缺行/停牌则沿用上一次的已知价）
        for code, rows in by_code.items():
            row = rows.get(d)
            if row and row.get("close") is not None:
                last_close[code] = row["close"]

        # 到达上次调仓的"次一交易日"→ 成交
        if pending and d == pending[0]:
            targets = pending[1]
            # 目标 + 当前持仓 都要取价：当前持仓中跌出目标榜的，也需要当日成交价才能卖出；
            # 若当日无价（真停牌）则 prices 里没有该 code，compute_rebalance 会保持不卖。
            codes_needed = set(targets) | set(holdings)
            prices = {c: by_code.get(c, {}).get(d, {}).get("open") for c in codes_needed}
            prices = {c: p for c, p in prices.items() if p is not None}
            pv_before = _portfolio_value(holdings, last_close, cash)
            res = compute_rebalance(targets, holdings, prices, cash, cost)
            holdings, cash = res["new_holdings"], res["cash"]
            weight = _weights(holdings, last_close)
            rebalances.append({"date": d, "buys": res["buys"], "sells": res["sells"],
                               "holdings": weight, "portfolio_value": pv_before})
            pending = None

        # 调仓日 D:选股,预约次日成交
        if d in rebal_days:
            section = monthly_sections[d]
            stocks = []
            for code, cross in section.items():
                ds, cs, vs = hist.get(code, ([], [], []))
                if not ds:
                    continue
                # 二分定位 <= d 的切点:取包含 start 之前 lookback 的全部历史前缀,
                # 而不是只从 [start,end] 内的 trade_days 取(否则首个调仓日长周期因子算不出)。
                idx = bisect.bisect_right(ds, d)
                if idx == 0:
                    continue
                closes, vols = cs[:idx], vs[:idx]
                stocks.append({"code": code, "name": code, "industry": "",
                               "cross": cross, "closes": closes, "volumes": vols})
            ranked = score_universe(stocks, factor_configs, top_n)
            targets = [x["code"] for x in ranked]
            # 预约:下一个交易日成交
            nxt = trade_days[di + 1] if di + 1 < len(trade_days) else None
            if nxt:
                pending = (nxt, targets)

        equity_curve.append((d, _portfolio_value(holdings, last_close, cash)))

    benchmark_curve = _normalize_benchmark(benchmark, trade_days, cap0)
    metrics = compute_portfolio_metrics(equity_curve, benchmark_curve, cap0, rebalances)
    return {"config": _config_dict(config), "equity_curve": equity_curve,
            "benchmark_curve": benchmark_curve, "metrics": metrics, "rebalances": rebalances}


def _portfolio_value(holdings, last_close, cash):
    """持仓市值 + 现金。停牌/当日缺数据时用该股最后已知收盘价估值,避免净值假暴跌。"""
    v = cash
    for code, sh in holdings.items():
        px = last_close.get(code)
        if px is not None:
            v += sh * px
    return v


def _weights(holdings, last_close):
    total = _portfolio_value(holdings, last_close, 0.0)
    out = []
    for code, sh in holdings.items():
        px = last_close.get(code) or 0.0
        out.append({"code": code, "weight": (sh * px / total) if total > 0 else 0.0})
    return out


def _normalize_benchmark(benchmark, trade_days, cap0):
    bm = {d: c for d, c in benchmark}
    base = None
    out = []
    for d in trade_days:
        if d in bm:
            if base is None:
                base = bm[d]
            out.append((d, cap0 * bm[d] / base if base else cap0))
    return out


def _config_dict(config):
    c = dict(config)
    cost = c.get("cost")
    if hasattr(cost, "__dict__"):
        from dataclasses import asdict, is_dataclass
        c["cost"] = asdict(cost) if is_dataclass(cost) else vars(cost)
    return c
