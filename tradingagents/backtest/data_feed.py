"""从历史库加载前复权日线为 Bar 序列。"""
import asyncio
from typing import List

from .types import Bar

_QFQ_FIELDS = ("open_qfq", "high_qfq", "low_qfq", "close_qfq")


def _to_dash_date(d: str) -> str:
    """把 trade_date 统一成 YYYY-MM-DD（库里可能是 YYYYMMDD 或 YYYY-MM-DD）。"""
    s = str(d)
    return s if "-" in s else f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def bars_from_records(records: list, symbol: str, st_service=None) -> List[Bar]:
    """把库记录（可能降序）转成升序 Bar 列表，价格取前复权字段。

    Args:
        records: historical_data_service 返回的原始 dict 列表（可能降序）。
        symbol: 股票代码，用于 st_service 按日判定。
        st_service: 提供 is_st(symbol, date) 的对象；为 None 时 is_st 恒为 False。

    Returns:
        按日期升序排列的 Bar 列表。
    """
    rows = sorted(records, key=lambda r: _to_dash_date(r["trade_date"]))
    bars: List[Bar] = []
    for r in rows:
        date = _to_dash_date(r["trade_date"])
        missing = [f for f in _QFQ_FIELDS if r.get(f) is None]
        if missing:
            raise ValueError(
                f"{symbol} {date} 缺前复权价字段 {missing}，请先跑复权同步（Task 1）"
            )
        vol = r.get("volume") or 0
        is_st = bool(st_service.is_st(symbol, date)) if st_service else False
        bars.append(Bar(
            date=date,
            open=r.get("open_qfq"), high=r.get("high_qfq"),
            low=r.get("low_qfq"), close=r.get("close_qfq"),
            pre_close=r.get("pre_close"), volume=vol,
            suspended=(vol == 0), is_st=is_st,
        ))
    return bars


def load_bars(symbol: str, start_date: str, end_date: str, st_service=None) -> List[Bar]:
    """从 historical_data_service 读数据并转 Bar。缺复权字段则报错。

    内部把 async 的 get_historical_data 用 asyncio.run 包成同步调用。

    Args:
        symbol: 股票代码。
        start_date: 起始日期 YYYY-MM-DD。
        end_date: 结束日期 YYYY-MM-DD。
        st_service: 可选的 StStatusService 实例，用于 ST 标记；传入时会先 load(symbol)。

    Returns:
        按日期升序排列的 Bar 列表。

    Raises:
        ValueError: 无历史数据，或缺前复权价字段（需先跑复权同步）。
    """
    from app.services.historical_data_service import HistoricalDataService

    svc = HistoricalDataService()

    async def _run():
        await svc.initialize()
        return await svc.get_historical_data(
            symbol, start_date, end_date, data_source="tushare", period="daily"
        )

    records = asyncio.run(_run())
    if not records:
        raise ValueError(f"无历史数据：{symbol} {start_date}~{end_date}，请先同步")
    # 逐行复权价校验交给 bars_from_records（增量同步可能导致中间日期缺复权价，
    # 不能只查首条记录）。
    if st_service:
        asyncio.run(st_service.load(symbol))
    return bars_from_records(records, symbol, st_service)
