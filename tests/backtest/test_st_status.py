"""
ST 历史状态服务 —— 单元测试 + 集成测试

背景：回测引擎需要按日精确判定某只股票当天是否处于 ST（含 *ST）状态，
用于 market_rules 的精确涨跌停判定（ST 股票涨跌幅限制与普通股票不同）。
数据来源是 tushare `namechange` 接口返回的曾用名及生效区间，名称中含
"ST" 的区间即视为 ST 期，落库到 MongoDB collection `stock_st_periods`。

本文件覆盖：
1. `StStatusService.is_st` 按区间判定是否命中（单元测试，注入内存区间，无需数据库）。
2. `StStatusService._to_ts_code` / `_fmt` 的纯函数行为（单元测试）。
3. `StStatusService._save_periods` 的 upsert 调用行为（单元测试，注入假 collection，无需真实数据库）。
4. `StStatusService.sync_from_tushare` + `load` 端到端同步某只曾经 ST 的股票
   （集成测试，需要 mongodb 容器 + tushare token）。

验证标的选择说明：本文件实现前先用 tushare namechange 接口人工核实了
000980（众泰汽车）的曾用名历史，确认其包含两段真实 ST 区间：
    *ST众泰  2020-06-24 ~ 2022-05-19
    ST众泰   2022-05-20 ~ 2022-11-02
因此集成测试不仅断言"同步流程无异常"，还进一步断言同步得到的 ST 区间数
>= 2，且区间内的已知日期确实判定为 ST、区间外日期判定为非 ST。
"""
import asyncio

import pytest

from app.services.st_status_service import StStatusService


# ==================== Step 1：区间判定（无需数据库） ====================

def test_is_st_within_period():
    svc = StStatusService()
    # 直接注入内存区间，避开数据库
    svc._periods_cache = {"000001": [{"start_date": "2020-01-01", "end_date": "2020-12-31"}]}
    assert svc.is_st("000001", "2020-06-15") is True
    assert svc.is_st("000001", "2021-06-15") is False
    assert svc.is_st("600000", "2020-06-15") is False


def test_is_st_open_ended_period_means_until_now():
    """end_date 为 None 表示"至今"，边界之后的任意日期都应命中"""
    svc = StStatusService()
    svc._periods_cache = {"000980": [{"start_date": "2022-05-20", "end_date": None}]}
    assert svc.is_st("000980", "2022-05-20") is True  # 起始日当天
    assert svc.is_st("000980", "2099-01-01") is True  # 远未来仍算"至今"
    assert svc.is_st("000980", "2022-05-19") is False  # 起始日前一天


def test_is_st_unknown_symbol_returns_false():
    svc = StStatusService()
    svc._periods_cache = {"000001": [{"start_date": "2020-01-01", "end_date": "2020-12-31"}]}
    assert svc.is_st("999999", "2020-06-15") is False


# ==================== Step 6：_to_ts_code / _fmt 纯函数单测 ====================

def test_to_ts_code():
    assert StStatusService._to_ts_code("600000") == "600000.SH"
    assert StStatusService._to_ts_code("000001") == "000001.SZ"


def test_fmt_date():
    assert StStatusService._fmt("20200101") == "2020-01-01"
    assert StStatusService._fmt("") is None


def test_fmt_date_more_cases():
    """补充边界情况：None、纯 nan 字符串、已经是 YYYY-MM-DD 格式"""
    assert StStatusService._fmt(None) is None
    assert StStatusService._fmt("nan") is None
    assert StStatusService._fmt("None") is None
    assert StStatusService._fmt("2020-01-01") == "2020-01-01"


# ==================== _save_periods：upsert 行为（假 collection，无需真实数据库） ====================

class _FakeBulkWriteResult:
    def __init__(self, n: int):
        self.upserted_count = n
        self.modified_count = 0


class _FakeCollection:
    """记录 bulk_write 调用参数，模拟 motor 异步集合，无需真实数据库连接"""

    def __init__(self):
        self.calls = []

    async def bulk_write(self, operations, ordered=False):
        self.calls.append(operations)
        return _FakeBulkWriteResult(len(operations))


def test_save_periods_empty_list_returns_zero_without_touching_db():
    """periods 为空时应直接返回 0，不应触碰 self.collection（此时仍为 None）"""
    svc = StStatusService()
    saved = asyncio.run(svc._save_periods([]))
    assert saved == 0
    assert svc.collection is None


def test_save_periods_upserts_each_period_by_symbol_and_start_date():
    svc = StStatusService()
    svc.collection = _FakeCollection()
    periods = [
        {"symbol": "000980", "start_date": "2020-06-24", "end_date": "2022-05-19", "name": "*ST众泰"},
        {"symbol": "000980", "start_date": "2022-05-20", "end_date": "2022-11-02", "name": "ST众泰"},
    ]

    saved = asyncio.run(svc._save_periods(periods))

    assert saved == 2
    assert len(svc.collection.calls) == 1
    operations = svc.collection.calls[0]
    assert len(operations) == 2
    # UpdateOne 按 symbol+start_date 作为过滤条件去重 upsert
    for op, period in zip(operations, periods):
        assert op._filter == {"symbol": period["symbol"], "start_date": period["start_date"]}
        assert op._doc == {"$set": period}
        assert op._upsert is True


# ==================== 集成测试：真实同步 000980 的 ST 曾用名区间并落库 ====================

@pytest.mark.integration
def test_sync_from_tushare_and_load_hits_known_st_period():
    """
    集成测试：真实调用 tushare namechange 同步 000980（众泰汽车）的曾用名区间，
    筛出含 ST 的区间写入 stock_st_periods，再 load 回内存缓存并按日判定。

    需要：mongodb 容器（tradingagents-mongodb）在运行，tushare token 已配置。
    """
    from app.core import database as db_module

    symbol = "000980"

    async def _run():
        await db_module.db_manager.init_mongodb()
        db_module.mongo_client = db_module.db_manager.mongo_client
        db_module.mongo_db = db_module.db_manager.mongo_db

        svc = StStatusService()
        try:
            await svc.initialize()
            # 防止上次测试异常退出留下脏数据，保证本次断言可靠
            await svc.collection.delete_many({"symbol": symbol})

            saved = await svc.sync_from_tushare(symbol)
            await svc.load(symbol)

            return {
                "saved": saved,
                "in_period": svc.is_st(symbol, "2021-01-01"),   # 落在 *ST众泰 区间内
                "in_period_2": svc.is_st(symbol, "2022-08-01"),  # 落在 ST众泰 区间内
                "after_period": svc.is_st(symbol, "2023-01-01"),  # 已恢复"众泰汽车"，非 ST
            }
        finally:
            if svc.collection is not None:
                await svc.collection.delete_many({"symbol": symbol})
            await db_module.db_manager.close_connections()
            db_module.mongo_client = None
            db_module.mongo_db = None

    result = asyncio.run(_run())

    # 000980 已人工核实存在两段真实 ST 区间，因此这里按非空断言校验，而非仅校验流程无异常
    assert result["saved"] >= 2
    assert result["in_period"] is True
    assert result["in_period_2"] is True
    assert result["after_period"] is False
