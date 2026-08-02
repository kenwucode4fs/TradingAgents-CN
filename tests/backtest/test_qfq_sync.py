"""
历史行情库补前复权价 —— 单元测试 + 集成测试

背景：回测引擎需要前复权（qfq）价格，避免除权除息导致的价格跳变影响策略回测。
本文件覆盖两部分：
1. `HistoricalDataService._standardize_record` 是否正确透传 open_qfq/high_qfq/low_qfq/close_qfq 四个字段（单元测试，无需数据库）。
2. `TushareSyncService.sync_historical_qfq` 是否能把某只股票的前复权日线真正写入 `stock_daily_quotes`（集成测试，需要 mongodb + tushare）。

注意：`HistoricalDataService._standardize_record` 的真实签名是
    _standardize_record(self, symbol, row, data_source, market, period="daily", date_index=None)
与最初计划文档中假设的 `svc._standardize_record(row, symbol=..., market=..., data_source=...)` 不一致，
这里按真实签名调用。
"""
import asyncio

import pytest

from app.services.historical_data_service import HistoricalDataService


def test_standardize_record_keeps_qfq_fields():
    """_standardize_record 应原样透传 tushare 前复权价字段（open_qfq/high_qfq/low_qfq/close_qfq）"""
    svc = HistoricalDataService()
    row = {
        "trade_date": "20260731",
        "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
        "open_qfq": 8.0, "high_qfq": 8.4, "low_qfq": 7.85, "close_qfq": 8.16,
    }

    rec = svc._standardize_record(
        symbol="000001",
        row=row,
        data_source="tushare",
        market="CN",
    )

    assert rec["close_qfq"] == 8.16
    assert rec["open_qfq"] == 8.0
    assert rec["high_qfq"] == 8.4
    assert rec["low_qfq"] == 7.85


def test_standardize_record_qfq_fields_none_when_missing():
    """不传复权字段时，qfq 字段应为 None，而不是抛异常或缺失 key"""
    svc = HistoricalDataService()
    row = {"trade_date": "20260731", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2}

    rec = svc._standardize_record(
        symbol="000001",
        row=row,
        data_source="tushare",
        market="CN",
    )

    assert rec["open_qfq"] is None
    assert rec["close_qfq"] is None


@pytest.mark.integration
def test_sync_qfq_writes_fields():
    """
    集成测试：真实同步 000001 的前复权日线，验证 stock_daily_quotes 中已存在的
    tushare 日线文档被补上 close_qfq 等复权字段。

    需要：mongodb 容器（tradingagents-mongodb）在运行，且已有 000001 的
    tushare 日线历史数据（否则 merge 时无匹配文档，saved 恒为 0）。
    tushare token 需已配置（.env 中的 TUSHARE_TOKEN）。
    """
    from app.core.database import init_database, close_database
    from app.worker.tushare_sync_service import TushareSyncService

    async def _run():
        await init_database()
        try:
            svc = TushareSyncService()
            await svc.initialize()
            return await svc.sync_historical_qfq("000001", "20260101", "20260731")
        finally:
            await close_database()

    r = asyncio.run(_run())
    assert r["saved"] > 0
