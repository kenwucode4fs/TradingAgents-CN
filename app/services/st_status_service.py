#!/usr/bin/env python3
"""ST 历史状态服务：按日判定某股是否处于 ST（含 *ST）状态。

背景：回测引擎的精确涨跌停判定需要区分 ST 股票（涨跌幅限制通常为 5%）与
普通股票（10%/20%），因此需要按日查询"某股票在某天是否处于 ST 状态"。

数据来源：tushare `namechange` 接口返回股票的曾用名及生效区间，名称中含
"ST"（覆盖 ST / *ST 两种风险警示状态）的区间即视为 ST 期。同步后落库到
MongoDB collection `stock_st_periods`（字段：symbol、start_date、end_date
（可空表示至今）、name），供 `is_st` 从内存缓存快速按日判定。
"""
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class StStatusService:
    """ST 历史状态服务"""

    COLLECTION_NAME = "stock_st_periods"

    def __init__(self):
        """初始化服务：内存缓存 + 延迟初始化的数据库连接"""
        # symbol -> [{"start_date": "YYYY-MM-DD", "end_date": Optional[str], "name": str}, ...]
        self._periods_cache: Dict[str, List[dict]] = {}
        self.db = None
        self.collection = None

    async def initialize(self) -> None:
        """初始化数据库连接（沿用 app.core.database 的连接方式，与其他 service 保持一致）"""
        from app.core.database import get_database

        try:
            self.db = get_database()
            self.collection = self.db[self.COLLECTION_NAME]
            await self._ensure_indexes()
            logger.info("✅ ST 历史状态服务初始化成功")
        except Exception as e:
            logger.error(f"❌ ST 历史状态服务初始化失败: {e}")
            raise

    async def _ensure_indexes(self) -> None:
        """确保 symbol+start_date 唯一索引存在（用于 upsert 去重）"""
        try:
            await self.collection.create_index(
                [("symbol", 1), ("start_date", 1)],
                unique=True,
                name="symbol_start_date_unique",
                background=True,
            )
        except Exception as e:
            # 索引创建失败不应阻塞服务，可能是索引已存在
            logger.warning(f"⚠️ 创建 stock_st_periods 索引时出现警告（可能已存在）: {e}")

    def is_st(self, symbol: str, date: str) -> bool:
        """按日判定某股是否处于 ST 期。

        Args:
            symbol: 股票代码（不带交易所后缀），如 "000001"
            date: 判定日期，格式 YYYY-MM-DD

        Returns:
            该日期是否落在某段 ST 区间内；区间的 end_date 为 None 表示"至今"。
        """
        for p in self._periods_cache.get(symbol, []):
            start = p["start_date"]
            end = p.get("end_date")
            if start <= date and (end is None or date <= end):
                return True
        return False

    async def sync_from_tushare(self, symbol: str) -> int:
        """从 tushare namechange 拉取该股票曾用名区间，筛出含 ST 的区间并 upsert 入库。

        Args:
            symbol: 股票代码（不带交易所后缀），如 "000980"

        Returns:
            实际写入（新增+更新）的 ST 区间数量；tushare 不可用或无 ST 区间时返回 0。
        """
        from app.services.data_sources.tushare_adapter import TushareAdapter

        adapter = TushareAdapter()
        if not adapter.is_available() or adapter._provider is None or adapter._provider.api is None:
            logger.warning(f"⚠️ Tushare 不可用，跳过同步 {symbol} 的 ST 历史")
            return 0

        api = adapter._provider.api
        ts_code = self._to_ts_code(symbol)
        df = api.namechange(ts_code=ts_code, fields="name,start_date,end_date")

        periods: List[dict] = []
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                name = str(r.get("name") or "")
                if "ST" in name:
                    periods.append({
                        "symbol": symbol,
                        "start_date": self._fmt(r.get("start_date")),
                        "end_date": self._fmt(r.get("end_date")),  # 空值即 None，表示至今
                        "name": name,
                    })

        return await self._save_periods(periods)

    async def load(self, symbol: str) -> None:
        """从 stock_st_periods 载入该股票的 ST 区间到内存缓存 `_periods_cache`。"""
        if self.collection is None:
            await self.initialize()

        cursor = self.collection.find(
            {"symbol": symbol}, {"_id": 0, "start_date": 1, "end_date": 1, "name": 1}
        )
        periods = await cursor.to_list(length=None)
        self._periods_cache[symbol] = periods

    async def _save_periods(self, periods: List[dict]) -> int:
        """把 ST 区间 upsert 到 stock_st_periods（按 symbol+start_date 去重）。

        Args:
            periods: 待写入的区间列表，每项至少包含 symbol、start_date

        Returns:
            实际写入（新增+更新）的记录数；periods 为空时直接返回 0，不触碰数据库。
        """
        if not periods:
            return 0

        if self.collection is None:
            await self.initialize()

        from pymongo import UpdateOne

        operations = [
            UpdateOne(
                {"symbol": p["symbol"], "start_date": p["start_date"]},
                {"$set": p},
                upsert=True,
            )
            for p in periods
        ]
        result = await self.collection.bulk_write(operations, ordered=False)
        return result.upserted_count + result.modified_count

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        """股票代码 -> tushare ts_code。

        前缀判定与项目现有约定保持一致（参考 `app/services/basics_sync_service.py`
        的 `_generate_full_symbol`）：
        - 北交所：8/4 开头（含历史新三板转板代码 43/83/87），以及 2023 年后
          北交所直接 IPO 的 920 开头新股 -> `.BJ`
        - 上交所：6 开头（含科创板 688） -> `.SH`
        - 其余（深交所主板/创业板等 0/3 开头） -> `.SZ`
        """
        if symbol.startswith(("8", "4", "920")):
            return f"{symbol}.BJ"
        if symbol.startswith("6"):
            return f"{symbol}.SH"
        return f"{symbol}.SZ"

    @staticmethod
    def _fmt(v) -> Optional[str]:
        """把 tushare 返回的日期值统一格式化为 YYYY-MM-DD；空值/None/nan 返回 None。"""
        s = str(v).strip() if v is not None else ""
        if not s or s in ("None", "nan", "NaT"):
            return None
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s
