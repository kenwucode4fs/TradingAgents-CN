"""
历史行情库补前复权价 —— 单元测试 + 集成测试

背景：回测引擎需要前复权（qfq）价格，避免除权除息导致的价格跳变影响策略回测。
本文件覆盖：
1. `HistoricalDataService._standardize_record` 是否正确透传 open_qfq/high_qfq/low_qfq/close_qfq 四个字段（单元测试，无需数据库）。
2. `TushareProvider._normalize_ts_code` 的交易所归属是否正确，以及 `TushareAdapter.get_kline`
   是否真的把标准化后的 ts_code 传给了 pro_bar（单元测试，mock pro_bar，无需网络）。
3. `HistoricalDataService.save_historical_data` 常规重跑是否会冲掉已落库的复权价（集成测试，需要 mongodb）。
4. `TushareSyncService.sync_historical_qfq` 是否能把某只股票的前复权日线真正写入 `stock_daily_quotes`（集成测试，需要 mongodb + tushare）。

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


# ==================== Important (b)：get_kline ts_code 标准化回归测试 ====================

def test_normalize_ts_code_maps_exchange_suffix_correctly():
    """
    直接验证 TushareProvider._normalize_ts_code 的交易所归属（无需网络/数据库）：
    - 60xxxx/68xxxx/90xxxx -> .SH（上交所，含科创板 688）
    - 其余 6 位代码（含创业板 300xxx、深主板 000xxx）-> .SZ
    - 已带后缀的代码原样返回
    """
    from tradingagents.dataflows.providers.china.tushare import TushareProvider

    provider = TushareProvider()

    assert provider._normalize_ts_code("600000") == "600000.SH"   # 上交所主板
    assert provider._normalize_ts_code("000001") == "000001.SZ"   # 深交所主板
    assert provider._normalize_ts_code("300750") == "300750.SZ"   # 创业板（深）
    assert provider._normalize_ts_code("688981") == "688981.SH"   # 科创板（沪）
    assert provider._normalize_ts_code("000001.SZ") == "000001.SZ"  # 已带后缀，原样返回


def test_get_kline_calls_pro_bar_with_normalized_ts_code(monkeypatch):
    """
    回归测试（Important b）：get_kline 之前误判 hasattr(prov, "_normalize_symbol")
    （该方法不存在，provider 上真实方法名是 _normalize_ts_code），导致传给
    pro_bar 的 ts_code 一直是裸代码（如 "600000"），pro_bar 无法识别、静默
    返回空数据。这里 mock pro_bar，验证修复后 get_kline 确实把标准化后的
    ts_code（带 .SH/.SZ 后缀）传了进去，且不需要真实网络/tushare token。
    """
    import pandas as pd
    import tushare.pro.data_pro as data_pro_mod
    from app.services.data_sources.tushare_adapter import TushareAdapter
    from tradingagents.dataflows.providers.china.tushare import TushareProvider

    captured = {}

    def _fake_pro_bar(ts_code=None, api=None, freq=None, adj=None, limit=None, fields=None):
        captured["ts_code"] = ts_code
        captured["adj"] = adj
        return pd.DataFrame([{
            "trade_date": "20260731", "open": 10.0, "high": 10.5,
            "low": 9.8, "close": 10.2, "vol": 100.0, "amount": 1000.0,
        }])

    monkeypatch.setattr(data_pro_mod, "pro_bar", _fake_pro_bar)

    # 绕开 TushareAdapter.__init__ 里通过全局单例 get_tushare_provider() 发起的
    # 真实网络连接（那是网络相关的初始化逻辑，不是本测试要验证的对象），
    # 直接注入一个"已连接"的 provider 桩，只用它真实的 _normalize_ts_code 方法。
    adapter = TushareAdapter.__new__(TushareAdapter)
    fake_provider = TushareProvider()
    fake_provider.connected = True
    fake_provider.api = object()  # 只需非 None；pro_bar 已被 mock，不会真正发请求
    adapter._provider = fake_provider

    bars = adapter.get_kline(code="600000", period="day", limit=5, adj="qfq")

    assert captured.get("ts_code") == "600000.SH"
    assert bars is not None and len(bars) == 1
    assert bars[0]["close"] == 10.2


# ==================== Important (a)：常规重跑不应冲掉已落库的复权价 ====================

@pytest.mark.integration
def test_save_historical_data_preserves_qfq_on_regular_resync():
    """
    回归测试（Important a）：save_historical_data 用 ReplaceOne 整份替换文档，
    如果常规行情重跑（本次同步的数据不带复权价）不做保护，会把 merge_qfq_prices
    之前写入的复权价冲成 None。

    用一个独立的测试专用股票代码（不触碰真实行情数据），验证：
    1) 先常规同步一条不带复权价的行情
    2) merge_qfq_prices 补上复权价
    3) 再常规同步一次同一天的行情（依然不带复权价，模拟"全量重跑原始行情"）
    4) 复权价字段应仍然保留，且普通字段（如 close）确实按新数据更新了
    """
    import pandas as pd
    from app.core import database as db_module

    test_symbol = "TESTQFQPRESERVE"
    trade_date = "2026-07-30"

    async def _run():
        await db_module.db_manager.init_mongodb()
        db_module.mongo_client = db_module.db_manager.mongo_client
        db_module.mongo_db = db_module.db_manager.mongo_db

        svc = HistoricalDataService()
        try:
            await svc.initialize()
            # 防止上次测试异常退出留下脏数据
            await svc.collection.delete_many({"symbol": test_symbol})

            df1 = pd.DataFrame([{
                "date": trade_date, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
                "volume": 1000000, "amount": 10000000,
            }])
            saved1 = await svc.save_historical_data(
                test_symbol, df1, data_source="tushare", market="CN", period="daily"
            )
            assert saved1 == 1

            merged = await svc.merge_qfq_prices(test_symbol, [{
                "trade_date": trade_date,
                "open_qfq": 8.0, "high_qfq": 8.4, "low_qfq": 7.85, "close_qfq": 8.16,
            }])
            assert merged == 1

            # 常规重跑：同一天，依然不带复权价，但普通行情数值变了（模拟重新拉取原始行情）
            df2 = pd.DataFrame([{
                "date": trade_date, "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.3,
                "volume": 1000000, "amount": 10000000,
            }])
            saved2 = await svc.save_historical_data(
                test_symbol, df2, data_source="tushare", market="CN", period="daily"
            )
            assert saved2 == 1

            return await svc.collection.find_one({"symbol": test_symbol, "trade_date": trade_date})
        finally:
            if svc.collection is not None:
                await svc.collection.delete_many({"symbol": test_symbol})
            await db_module.db_manager.close_connections()
            db_module.mongo_client = None
            db_module.mongo_db = None

    doc = asyncio.run(_run())
    assert doc is not None
    assert doc["close"] == 10.3          # 常规字段确实按新数据更新，没有被"保护"逻辑误伤
    assert doc["close_qfq"] == 8.16      # 复权价没有被常规重跑冲掉
    assert doc["open_qfq"] == 8.0
    assert doc["high_qfq"] == 8.4
    assert doc["low_qfq"] == 7.85


# ==================== 集成测试：真实同步 000001 前复权价并落库 ====================

@pytest.mark.integration
def test_sync_qfq_writes_fields():
    """
    集成测试：真实同步 000001 的前复权日线，验证 stock_daily_quotes 中已存在的
    tushare 日线文档被补上 close_qfq 等复权字段。

    需要：mongodb 容器（tradingagents-mongodb）在运行，且已有 000001 的
    tushare 日线历史数据（否则 merge 时无匹配文档）。
    tushare token 需已配置（.env 中的 TUSHARE_TOKEN）。

    注意（幂等性，Important c）：不用 sync_historical_qfq 返回的 saved（即本次
    写入触发的 modified_count）做断言 —— 同一批复权价第二次同步时，如果数值
    与库里已有值完全相同，MongoDB 的 $set 不会把它算作"被修改"，
    modified_count 会是 0，用 `saved > 0` 断言会导致重复执行本测试时误报失败。
    这里改为直接从数据库读回 000001 的记录，断言 close_qfq 等字段确实有值。

    注意（Redis）：这里没有直接调用 app.core.database.init_database()，因为它
    会同时初始化 Redis（本地容器需要额外的 Redis 鉴权，与本测试无关），改为
    只做 sync_historical_qfq 真正依赖的 MongoDB 初始化，避免引入无关依赖。
    """
    from app.core import database as db_module
    from app.worker.tushare_sync_service import TushareSyncService

    async def _run():
        await db_module.db_manager.init_mongodb()
        db_module.mongo_client = db_module.db_manager.mongo_client
        db_module.mongo_db = db_module.db_manager.mongo_db
        try:
            svc = TushareSyncService()
            await svc.initialize()
            await svc.sync_historical_qfq("000001", "20260101", "20260731")

            return await svc.historical_service.collection.find_one(
                {
                    "symbol": "000001",
                    "data_source": "tushare",
                    "period": "daily",
                    "trade_date": {"$gte": "2026-01-01", "$lte": "2026-07-31"},
                    "close_qfq": {"$ne": None},
                },
                sort=[("trade_date", -1)]
            )
        finally:
            await db_module.db_manager.close_connections()
            db_module.mongo_client = None
            db_module.mongo_db = None

    doc = asyncio.run(_run())
    assert doc is not None
    assert doc.get("close_qfq") is not None
    assert doc.get("open_qfq") is not None
    assert doc.get("high_qfq") is not None
    assert doc.get("low_qfq") is not None
