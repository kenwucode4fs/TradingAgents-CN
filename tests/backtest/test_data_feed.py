"""data_feed 单元测试（不依赖数据库/网络）。"""
import pytest

from tradingagents.backtest.data_feed import bars_from_records, load_bars


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
