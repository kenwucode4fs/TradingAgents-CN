# Task 5 评审：data_feed 前复权行情加载

## 1. Spec 合规

**结论：✅**

`bars_from_records`：
- 升序排序正确。排序 key 用 `_to_dash_date(r["trade_date"])`（先统一成 `YYYY-MM-DD` 再比较字符串），不是直接对原始 `trade_date` 排序，因此即使记录混有 `YYYYMMDD`/`YYYY-MM-DD` 两种格式也能正确排序，不存在"先按原始字符串排序"的隐患。
- 价格确实取 `*_qfq` 字段（`open_qfq`/`high_qfq`/`low_qfq`/`close_qfq`），而非原始 `open`/`close` 等。
- `suspended` 用 `vol = r.get("volume") or 0` 后判 `vol == 0`：`volume` 为 `0`、`None`、缺 key 三种情况都归一到 `vol=0 → suspended=True`，符合 brief "成交量为 0 或缺失日推断"的要求。
- `is_st` 由 `st_service.is_st(symbol, date)` 按日判定，`st_service=None` 时恒 False；与 `app/services/st_status_service.py::StStatusService.is_st(symbol, date)` 的实际签名一致。
- 日期统一为 `YYYY-MM-DD`，`Bar.date` 输出即为标准化后的值。

`load_bars`：
- 用 `asyncio.run` 包住内部 `async def _run()`（`await svc.initialize(); await svc.get_historical_data(...)`），符合"内部把 async 接口用 asyncio.run 包成同步"的要求。
- 无数据（`records` 为空）抛 `ValueError`；已验证 `HistoricalDataService.get_historical_data` 查询异常时返回 `[]` 而非抛异常（`app/services/historical_data_service.py:570-572`），因此该分支也能兜住底层查询失败的情况。
- 仅对 `records[0].get("close_qfq") is None` 判空并抛错（复权价缺失提示），与 brief Step 3 参考实现逐字一致。
- 传入 `st_service` 时会先 `asyncio.run(st_service.load(symbol))`，与 `StStatusService.load(symbol)` 签名一致。

`tests/backtest/test_data_feed.py::test_bars_from_records_sorted_and_qfq` 的断言是真断言（非 tautology）：分别验证升序顺序、复权价数值、`suspended is True`、`is_st` 在两条记录上一真一假，覆盖了 brief Step 1 要求的全部检查点。测试文件头部注释明确"不依赖数据库/网络"，符合约束。

## 2. 代码质量

**结论：Approved，1 问题：Important x1 / Minor x2**

- **Important**：`load_bars` 只校验 `records[0]["close_qfq"] is None`，`bars_from_records` 内部对每条记录的 `*_qfq` 字段没有做 None 校验，直接 `r.get("open_qfq")` 等透传进 `Bar`。这不是纯理论风险——`historical_data_service.py:130-150`（`_get_existing_qfq_map`/合并逻辑）显示同一 symbol 下不同交易日的 qfq 字段可能因增量同步/合并顺序而部分缺失，即首条记录有复权价、中间某天缺失是可能出现的真实状态。届时该日 `Bar.close`（等）会静默变成 `None`，后续策略/指标计算大概率在别处才报错或产生 NaN，而不是在数据加载层给出清晰的"缺复权价"提示。建议在 `bars_from_records`（或 `load_bars` 遍历所有记录时）对逐行的 `close_qfq is None` 也做校验或至少记录日志。

- **Minor**：`data_feed.py` 顶部 `from typing import List, Optional` 中 `Optional` 未被使用（全文件未出现 `Optional[...]`）。仓库近期刚有一次 "去掉没有引用的包" 的清理提交（`bd59960`），这里属于同类应清理的死代码。

- **Minor（非阻塞 gap）**：report 提到 `load_bars` 无集成测试。`load_bars` 的 async 包装本身（`asyncio.run` + 真实 DB 调用）确实难以脱离 DB/网络单测，但其内部两个 `raise ValueError` 分支和 `st_service.load` 调用属于可以通过 monkeypatch `HistoricalDataService`（不接触真实 DB）来验证的纯逻辑，目前完全没有测试覆盖。鉴于 brief Step 1 明确只要求测试 `bars_from_records`，且这部分逻辑足够薄（三四行错误处理），判断为非阻塞的可选补充项，不需要在本 task 内强制补齐。
