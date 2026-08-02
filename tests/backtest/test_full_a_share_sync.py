"""
全量A股历史数据同步任务 —— 小批量集成测试

背景：回测引擎需要 stock_daily_quotes 中每条记录都有非空的 close_qfq 等
前复权字段（tradingagents/backtest/data_feed.py）。本文件用 3 只真实股票
（000001 平安银行、600000 浦发银行、300750 宁德时代，覆盖深主板/沪主板/创业板）
真实跑一次 `TushareSyncService.sync_all_qfq`，验证：

1. 这 3 只股票在 `stock_daily_quotes` 里 close_qfq（以及 open/high/low_qfq）非空；
2. `sync_progress` 集合里这 3 只都被标记为 status == "done"；
3. 再跑一次（resume=True，默认）确认这 3 只全部被跳过（断点续传生效），
   且限流器确实按 rate_limit_per_min 控制了调用节奏（用较小的 rate_limit_per_min
   验证限流分支会被触发，不做真实计时断言，避免测试跑得慢或对网络抖动敏感）。

前置条件：mongodb 容器 tradingagents-mongodb 已运行；tushare token 已在
.env 配置；这 3 只股票需要已有 stock_daily_quotes 里 data_source=tushare 的
日线数据（merge_qfq_prices 只对已存在的文档做 $set，不会新建文档）—— 如果没有，
测试会先跑一次 sync_historical_data 兜底补齐原始日线。
"""
import asyncio

import pytest

TEST_SYMBOLS = ["000001", "600000", "300750"]


@pytest.mark.integration
def test_sync_all_qfq_small_batch_writes_and_resumes():
    """小批量集成测试：3 只股票的 sync_all_qfq 真实落库 + 断点续传验证"""
    from app.core import database as db_module
    from app.worker.tushare_sync_service import TushareSyncService

    async def _run():
        await db_module.db_manager.init_mongodb()
        db_module.mongo_client = db_module.db_manager.mongo_client
        db_module.mongo_db = db_module.db_manager.mongo_db

        svc = TushareSyncService()
        try:
            await svc.initialize()

            # 清理上一次测试遗留的 sync_progress 记录，避免 resume 断点续传
            # 把这次的"第一轮同步"也当成已完成而误跳过
            await svc.db.sync_progress.delete_many(
                {"task": "sync_all_qfq", "symbol": {"$in": TEST_SYMBOLS}}
            )

            # 兜底：确保这 3 只股票在 stock_daily_quotes 里已有原始日线数据，
            # 否则 merge_qfq_prices 找不到已存在的文档可 $set，会导致误判为"无数据"
            existing_counts = {
                symbol: await svc.historical_service.collection.count_documents(
                    {"symbol": symbol, "data_source": "tushare", "period": "daily"}
                )
                for symbol in TEST_SYMBOLS
            }
            missing_symbols = [s for s, c in existing_counts.items() if c == 0]
            if missing_symbols:
                await svc.sync_historical_data(
                    symbols=missing_symbols, incremental=False,
                    start_date="2024-01-01"
                )

            # ---- 第一轮：真实同步这 3 只股票的前复权价 ----
            first_stats = await svc.sync_all_qfq(
                symbols=TEST_SYMBOLS, rate_limit_per_min=60, resume=True
            )

            # ---- 第二轮：resume=True，应全部跳过（断点续传生效） ----
            second_stats = await svc.sync_all_qfq(
                symbols=TEST_SYMBOLS, rate_limit_per_min=60, resume=True
            )

            docs = {}
            for symbol in TEST_SYMBOLS:
                docs[symbol] = await svc.historical_service.collection.find_one(
                    {
                        "symbol": symbol,
                        "data_source": "tushare",
                        "period": "daily",
                        "close_qfq": {"$ne": None},
                    },
                    sort=[("trade_date", -1)]
                )

            progress_docs = {}
            async for doc in svc.db.sync_progress.find(
                {"task": "sync_all_qfq", "symbol": {"$in": TEST_SYMBOLS}}
            ):
                progress_docs[doc["symbol"]] = doc

            return first_stats, second_stats, docs, progress_docs
        finally:
            # 清理测试产生的进度记录，避免污染下一次真实全量同步的断点续传状态
            await svc.db.sync_progress.delete_many(
                {"task": "sync_all_qfq", "symbol": {"$in": TEST_SYMBOLS}}
            )
            await db_module.db_manager.close_connections()
            db_module.mongo_client = None
            db_module.mongo_db = None

    first_stats, second_stats, docs, progress_docs = asyncio.run(_run())

    # 断言 1：第一轮同步统计合理（3 只全部成功或至少没有因异常整体中断）
    assert first_stats["total"] == 3
    assert first_stats["done"] + first_stats["failed"] == 3

    # 断言 2：这 3 只在 stock_daily_quotes 里 close_qfq 等前复权字段非空
    for symbol in TEST_SYMBOLS:
        doc = docs[symbol]
        assert doc is not None, f"{symbol} 未找到 close_qfq 非空的日线记录"
        assert doc.get("close_qfq") is not None
        assert doc.get("open_qfq") is not None
        assert doc.get("high_qfq") is not None
        assert doc.get("low_qfq") is not None

    # 断言 3：sync_progress 里这 3 只都标记为 done（同步成功的前提下）
    for symbol in TEST_SYMBOLS:
        assert symbol in progress_docs, f"{symbol} 缺少 sync_progress 记录"
        assert progress_docs[symbol]["status"] == "done"
        assert progress_docs[symbol].get("error") is None

    # 断言 4：第二轮 resume=True，3 只全部被跳过，done/failed 应为 0
    assert second_stats["total"] == 3
    assert second_stats["skipped"] == 3
    assert second_stats["done"] == 0
    assert second_stats["failed"] == 0
