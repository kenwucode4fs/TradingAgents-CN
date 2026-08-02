"""data_feed 单元测试（不依赖数据库/网络）。"""
import pytest

from tradingagents.backtest.data_feed import bars_from_records, load_bars
from tradingagents.backtest.broker import Broker
from tradingagents.backtest.types import CostConfig, PositionConfig


def test_bars_from_records_sorted_and_qfq():
    # 输入降序（模拟库返回），且含原始价与复权价
    records = [
        {"trade_date": "2020-01-03", "open": 20, "high": 21, "low": 19, "close": 20.5,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.25},
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 0,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
    ]

    class FakeSt:
        def is_st(self, symbol, date):
            return date == "2020-01-02"

    bars = bars_from_records(records, symbol="000001", st_service=FakeSt())
    assert [b.date for b in bars] == ["2020-01-02", "2020-01-03"]   # 升序
    assert bars[0].close == 10.0        # 用复权价
    assert bars[0].suspended is True     # volume==0 视为停牌
    assert bars[0].is_st is True
    assert bars[1].is_st is False


def test_bars_from_records_raises_when_middle_record_missing_qfq():
    """增量合并可能导致中间某天的复权价缺失，不能只查首条记录就放行。"""
    records = [
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
        {"trade_date": "2020-01-03", "open": 20, "high": 21, "low": 19, "close": 20.5,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": None},
        {"trade_date": "2020-01-04", "open": 20, "high": 21, "low": 19, "close": 20.5,
         "pre_close": 20.5, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.3},
    ]

    with pytest.raises(ValueError, match="2020-01-03"):
        bars_from_records(records, symbol="000001")


def test_load_bars_raises_when_no_data(monkeypatch):
    """无历史数据（库里查不到任何记录）应抛 ValueError 提示先同步。"""
    from app.services.historical_data_service import HistoricalDataService

    async def fake_initialize(self):
        return None

    async def fake_get_historical_data(self, symbol, start_date, end_date,
                                        data_source=None, period=None):
        return []

    monkeypatch.setattr(HistoricalDataService, "initialize", fake_initialize)
    monkeypatch.setattr(HistoricalDataService, "get_historical_data", fake_get_historical_data)

    with pytest.raises(ValueError, match="无历史数据"):
        load_bars("000001", "2020-01-01", "2020-01-31")


def test_load_bars_raises_when_qfq_missing_on_some_record(monkeypatch):
    """记录里有缺复权价的日期（哪怕不是第一条）应抛 ValueError 提示先跑复权同步。"""
    from app.services.historical_data_service import HistoricalDataService

    records = [
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
        {"trade_date": "2020-01-03", "open": 20, "high": 21, "low": 19, "close": 20.5,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": None},
    ]

    async def fake_initialize(self):
        return None

    async def fake_get_historical_data(self, symbol, start_date, end_date,
                                        data_source=None, period=None):
        return records

    monkeypatch.setattr(HistoricalDataService, "initialize", fake_initialize)
    monkeypatch.setattr(HistoricalDataService, "get_historical_data", fake_get_historical_data)

    with pytest.raises(ValueError, match="2020-01-03"):
        load_bars("000001", "2020-01-01", "2020-01-31")


# ==================== Critical：pre_close 必须是前复权口径，不能混用原始标度 ====================

def test_pre_close_from_second_bar_onward_equals_previous_qfq_close():
    """i>=1 的 pre_close 应等于前一条记录的复权收盘价（close_qfq），
    而不是库里的原始 pre_close 字段（标度不同）。
    """
    records = [
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
        {"trade_date": "2020-01-03", "open": 20.2, "high": 20.5, "low": 19.8, "close": 20.2,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10.1, "high_qfq": 10.25, "low_qfq": 9.9, "close_qfq": 10.1},
    ]
    bars = bars_from_records(records, symbol="600000")
    assert bars[1].pre_close == bars[0].close == 10.0
    assert bars[1].pre_close != 20  # 不应是库里的原始 pre_close


def test_pre_close_first_bar_uses_day0_qfq_factor():
    """首日无前一条记录，需借助当日复权因子 f0=close_qfq/close 换算原始 pre_close。"""
    records = [
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
    ]
    bars = bars_from_records(records, symbol="600000")
    # f0 = 10.0/20 = 0.5；pre_close_qfq = 19.8 * 0.5 = 9.9
    assert bars[0].pre_close == 9.9


def test_pre_close_first_bar_fallback_when_raw_close_missing():
    """原始 close 缺失/为 0 无法算复权因子时，兜底用当日复权开盘价（同口径）。"""
    records = [
        {"trade_date": "2020-01-02", "open": None, "high": 21, "low": 19, "close": None,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
    ]
    bars = bars_from_records(records, symbol="600000")
    assert bars[0].pre_close == 10  # 兜底为 open_qfq


def test_pre_close_qfq_scale_prevents_false_limit_down_in_broker():
    """回归 Critical bug：pre_close 曾取库里原始（未复权）价，与前复权的 open
    标度不一致——历史存在分红的股票复权因子 f<1，会导致普通交易日被误判成
    一字跌停（卖单无限顺延）。这里构造复权因子=0.5（复权价是原始价的一半，
    原始 pre_close 与 open_qfq 标度差一倍以上）的两日数据，验证修复后 broker
    在第二日能正常卖出，而不是被跌停误判卡住。
    """
    records = [
        {"trade_date": "2020-01-02", "open": 20, "high": 21, "low": 19, "close": 20,
         "pre_close": 19.8, "volume": 100,
         "open_qfq": 10, "high_qfq": 10.5, "low_qfq": 9.5, "close_qfq": 10.0},
        {"trade_date": "2020-01-03", "open": 20.2, "high": 20.5, "low": 19.8, "close": 20.2,
         "pre_close": 20, "volume": 100,
         "open_qfq": 10.1, "high_qfq": 10.25, "low_qfq": 9.9, "close_qfq": 10.1},
    ]
    bars = bars_from_records(records, symbol="600000")

    broker = Broker(100000, CostConfig(), PositionConfig(parts=1), symbol="600000")
    assert broker.try_buy_one_part(bars[0]) is True
    # 若 pre_close 仍是原始标度 20，limit_down_price(20, main, False)=18.0，
    # 第二日 open=10.1 会被误判成跌停（10.1 < 18.0），卖单会被无限顺延；
    # 修复后 pre_close 与 open 同为复权口径，普通交易日应能正常卖出。
    assert broker.try_sell(bars[1]) is True
