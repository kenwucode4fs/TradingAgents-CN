"""data_feed.bars_from_records 单元测试（不依赖数据库/网络）。"""
from tradingagents.backtest.data_feed import bars_from_records


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
