"""逐月调仓组合回测:防前视(只用<=D数据)、防幸存者偏差(候选来自当时截面)、
T+1 次日开盘成交、每日净值。纯函数,数据由调用方注入。"""
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

    holdings, cash = {}, cap0
    rebalances = []
    equity_curve = []
    pending = None  # (成交日, 目标TopN)

    for di, d in enumerate(trade_days):
        # 到达上次调仓的"次一交易日"→ 成交
        if pending and d == pending[0]:
            targets = pending[1]
            prices = {c: by_code.get(c, {}).get(d, {}).get("open") for c in targets}
            prices = {c: p for c, p in prices.items() if p is not None}
            pv_before = _portfolio_value(holdings, by_code, d, cash)
            res = compute_rebalance(targets, holdings, prices, cash, cost)
            holdings, cash = res["new_holdings"], res["cash"]
            weight = _weights(holdings, by_code, d)
            rebalances.append({"date": d, "buys": res["buys"], "sells": res["sells"],
                               "holdings": weight, "portfolio_value": pv_before})
            pending = None

        # 调仓日 D:选股,预约次日成交
        if d in rebal_days:
            section = monthly_sections[d]
            stocks = []
            for code, cross in section.items():
                rows = by_code.get(code)
                if not rows:
                    continue
                closes, vols = [], []
                for dt in trade_days:
                    if dt > d:
                        break
                    row = rows.get(dt)
                    if row and row.get("close") is not None:
                        closes.append(row["close"]); vols.append(row.get("volume") or 0)
                if not closes:
                    continue
                stocks.append({"code": code, "name": code, "industry": "",
                               "cross": cross, "closes": closes, "volumes": vols})
            ranked = score_universe(stocks, factor_configs, top_n)
            targets = [x["code"] for x in ranked]
            # 预约:下一个交易日成交
            nxt = trade_days[di + 1] if di + 1 < len(trade_days) else None
            if nxt:
                pending = (nxt, targets)

        equity_curve.append((d, _portfolio_value(holdings, by_code, d, cash)))

    benchmark_curve = _normalize_benchmark(benchmark, trade_days, cap0)
    metrics = compute_portfolio_metrics(equity_curve, benchmark_curve, cap0, rebalances)
    return {"config": _config_dict(config), "equity_curve": equity_curve,
            "benchmark_curve": benchmark_curve, "metrics": metrics, "rebalances": rebalances}


def _portfolio_value(holdings, by_code, d, cash):
    v = cash
    for code, sh in holdings.items():
        row = by_code.get(code, {}).get(d)
        if row and row.get("close") is not None:
            v += sh * row["close"]
    return v


def _weights(holdings, by_code, d):
    total = _portfolio_value(holdings, by_code, d, 0.0)
    out = []
    for code, sh in holdings.items():
        row = by_code.get(code, {}).get(d)
        px = row["close"] if row and row.get("close") is not None else 0.0
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
