from app.worker.portfolio_data_sync import _month_end_dates


def test_month_end_dates_picks_last_trading_day_per_month():
    # 注入若干交易日(YYYY-MM-DD),应每月取最后一个
    dates = ["2024-01-05", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-15"]
    assert _month_end_dates(dates, "2024-01-01", "2024-03-31") == ["2024-01-31", "2024-02-29", "2024-03-15"]


def test_month_end_dates_respects_range():
    dates = ["2023-12-29", "2024-01-31", "2024-02-29"]
    assert _month_end_dates(dates, "2024-01-01", "2024-01-31") == ["2024-01-31"]
