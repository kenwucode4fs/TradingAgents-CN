import pytest

from app.worker.portfolio_data_sync import _month_end_dates


def test_month_end_dates_picks_last_trading_day_per_month():
    # 注入若干交易日(YYYY-MM-DD),应每月取最后一个
    dates = ["2024-01-05", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-15"]
    assert _month_end_dates(dates, "2024-01-01", "2024-03-31") == ["2024-01-31", "2024-02-29", "2024-03-15"]


def test_month_end_dates_respects_range():
    dates = ["2023-12-29", "2024-01-31", "2024-02-29"]
    assert _month_end_dates(dates, "2024-01-01", "2024-01-31") == ["2024-01-31"]


@pytest.mark.integration
def test_month_end_trade_dates_real_db():
    import asyncio
    from app.core.database import db_manager
    from app.worker.portfolio_data_sync import month_end_trade_dates

    async def _run():
        if getattr(db_manager, "mongo_db", None) is None:
            await db_manager.init_mongodb()
        ends = await month_end_trade_dates(db_manager.mongo_db, "2024-01-01", "2024-03-31")
        assert len(ends) == 3, f"应有3个月末: {ends}"
        assert all(d[:7] in ("2024-01", "2024-02", "2024-03") for d in ends)
        assert ends == sorted(ends)

    asyncio.run(_run())
