"""组合回测历史数据回填:月末 daily_basic + 沪深300 指数。trade_date 统一 "YYYY-MM-DD"。"""
import logging
from typing import List

import pandas as pd

logger = logging.getLogger(__name__)


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
    # 用全市场任一股票有记录的交易日作为交易日历（不依赖单只股票，避免其停牌导致漏月份）
    dates = await db.stock_daily_quotes.distinct("trade_date", {"trade_date": {"$gte": start, "$lte": end}})
    return _month_end_dates([str(d) for d in dates], start, end)


def _num(v):
    try:
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
            logger.warning(f"portfolio_data_sync: {d}(tushare {tushare_date}) 未拉取到 daily_basic 数据,跳过")
            continue
        for _, r in df.iterrows():
            code = str(r["ts_code"]).split(".")[0]  # 去后缀 → 6 位
            doc = {"code": code, "trade_date": d,
                   "pe": _num(r.get("pe")), "pb": _num(r.get("pb")), "total_mv": _num(r.get("total_mv"))}
            await db.stock_monthly_basic.update_one(
                {"code": code, "trade_date": d}, {"$set": doc}, upsert=True)
            written += 1
    return written


async def sync_benchmark_index(db, ts_code: str, start: str, end: str) -> int:
    """回填基准指数(如沪深300 000300.SH)日线收盘到 index_daily_quotes,按 (ts_code, trade_date) upsert。"""
    from app.services.data_sources.tushare_adapter import TushareAdapter
    api = TushareAdapter()._provider.api
    df = api.index_daily(ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
    if df is None or df.empty:
        return 0
    written = 0
    for _, r in df.iterrows():
        doc = {"ts_code": ts_code, "trade_date": _to_dash(r["trade_date"]), "close": float(r["close"])}
        await db.index_daily_quotes.update_one(
            {"ts_code": ts_code, "trade_date": doc["trade_date"]}, {"$set": doc}, upsert=True)
        written += 1
    return written
