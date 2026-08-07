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
    for idx, r in enumerate(rows):
        date = _to_dash_date(r["trade_date"])
        missing = [f for f in _QFQ_FIELDS if r.get(f) is None]
        if missing:
            raise ValueError(
                f"{symbol} {date} 缺前复权价字段 {missing}，请先跑复权同步（Task 1）"
            )
        vol = r.get("volume") or 0
        is_st = bool(st_service.is_st(symbol, date)) if st_service else False
        open_qfq, high_qfq = r.get("open_qfq"), r.get("high_qfq")
        low_qfq, close_qfq = r.get("low_qfq"), r.get("close_qfq")

        # pre_close 必须与 open/high/low/close 同为前复权口径，否则 broker 用
        # market_rules.limit_up/down_price(bar.pre_close, ...) 算出的涨跌停价
        # 会和前复权的 bar.open 标度不一致，导致涨跌停判定系统性失真
        # （多年分红股会被误判成一字跌停/涨停）。
        # 前复权序列的性质：当日复权昨收 = 前一交易日的复权收盘价。
        if idx == 0:
            # 首日没有"前一条记录"可用，借助当日复权因子把库里的原始
            # pre_close 换算成前复权口径：f0 = close_qfq / close_raw，
            # pre_close_qfq = pre_close_raw * f0。
            raw_close = r.get("close")
            raw_pre_close = r.get("pre_close")
            if raw_close is not None and raw_close != 0 and raw_pre_close is not None:
                f0 = close_qfq / raw_close
                pre_close = raw_pre_close * f0
            else:
                # 原始 close 缺失/为 0 无法算复权因子，兜底用当日复权开盘价，
                # 保证至少与 open 同口径（不会跨标度触发误判涨跌停）。
                pre_close = open_qfq
        else:
            pre_close = bars[-1].close

        bars.append(Bar(
            date=date,
            open=open_qfq, high=high_qfq,
            low=low_qfq, close=close_qfq,
            pre_close=pre_close, volume=vol,
            suspended=(vol == 0), is_st=is_st,
        ))
    return bars


async def async_load_bars(symbol: str, start_date: str, end_date: str, st_service=None) -> List[Bar]:
    """`load_bars` 的原生协程版本：直接 await，不自建事件循环。

    供已经身处事件循环中的调用方使用（如 Web 层 `app/services/backtest_service.py`
    在主事件循环里预取 K 线），避免像 `load_bars` 那样用 `asyncio.run` 另起一个
    独立事件循环——若调用方自身也运行在事件循环里（例如 FastAPI 的
    `BackgroundTasks`），`asyncio.run` 会报 "cannot be called from a running
    event loop"；即便躲开这一层，`HistoricalDataService` 底层的 Motor 客户端是
    进程级共享、绑定在主事件循环上的，从另一个独立事件循环（哪怕是同线程新建的）
    去用它也会报 "attached to a different loop"。所以真正安全的用法是：全程留在
    调用方所在的（主）事件循环里 await，不新建循环。

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
    await svc.initialize()
    records = await svc.get_historical_data(
        symbol, start_date, end_date, data_source="tushare", period="daily"
    )
    if not records:
        raise ValueError(f"无历史数据：{symbol} {start_date}~{end_date}，请先同步")
    # 逐行复权价校验交给 bars_from_records（增量同步可能导致中间日期缺复权价，
    # 不能只查首条记录）。
    if st_service:
        await st_service.load(symbol)
    return bars_from_records(records, symbol, st_service)


def load_bars(symbol: str, start_date: str, end_date: str, st_service=None) -> List[Bar]:
    """`async_load_bars` 的同步包装：用 `asyncio.run` 另起一个独立事件循环执行。

    供 Plan 1 引擎脱离 Web 独立运行的场景使用（如脚本、CLI、
    `run_backtest(bars=None)` 的非 Web 调用方），此时不存在"调用方已身处事件
    循环"的问题，`asyncio.run` 是安全的。Web 层（FastAPI 事件循环内）应改用
    `async_load_bars`，见其 docstring。

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
    return asyncio.run(async_load_bars(symbol, start_date, end_date, st_service))
