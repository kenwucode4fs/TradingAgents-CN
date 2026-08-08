"""组合回测历史数据回填:月末 daily_basic + 沪深300 指数。trade_date 统一 "YYYY-MM-DD"。"""
from typing import List


def _to_dash(d: str) -> str:
    """tushare 的 "YYYYMMDD" → "YYYY-MM-DD";已带横线则原样。"""
    s = str(d)
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _month_end_dates(all_trade_dates: List[str], start: str, end: str) -> List[str]:
    """从升序交易日(YYYY-MM-DD)取 [start,end] 内每月最后一个交易日。"""
    in_range = sorted(d for d in all_trade_dates if start <= d <= end)
    last_of_month = {}
    for d in in_range:
        last_of_month[d[:7]] = d  # 键 "YYYY-MM",后来的覆盖前面的 → 该月最后一个
    return [last_of_month[k] for k in sorted(last_of_month)]


async def month_end_trade_dates(db, start: str, end: str) -> List[str]:
    dates = await db.stock_daily_quotes.distinct("trade_date", {"symbol": "000001"})
    return _month_end_dates([str(d) for d in dates], start, end)


def _num(v):
    try:
        import pandas as pd
        return None if v is None or pd.isna(v) else float(v)
    except (ValueError, TypeError):
        return None


async def sync_monthly_basic(db, start: str, end: str) -> int:
    from app.services.data_sources.tushare_adapter import TushareAdapter
    adapter = TushareAdapter()
    ends = await month_end_trade_dates(db, start, end)
    written = 0
    for d in ends:
        tushare_date = d.replace("-", "")  # tushare 要 "YYYYMMDD"
        df = adapter.get_daily_basic(tushare_date)
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            code = str(r["ts_code"]).split(".")[0]  # 去后缀 → 6 位
            doc = {"code": code, "trade_date": d,
                   "pe": _num(r.get("pe")), "pb": _num(r.get("pb")), "total_mv": _num(r.get("total_mv"))}
            await db.stock_monthly_basic.update_one(
                {"code": code, "trade_date": d}, {"$set": doc}, upsert=True)
            written += 1
    return written
