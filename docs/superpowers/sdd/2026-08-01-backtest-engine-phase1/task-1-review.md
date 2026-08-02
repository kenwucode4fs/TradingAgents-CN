# Task 1 代码评审：历史库补前复权价

评审对象：`review-cac8a1b..07c54bc.diff`（3 commits: e9a5d88 / 98a0847 / 07c54bc）

---

## 一、Spec 合规：✅ 达成

Brief 的三个目标逐条核对：

### 目标 1：`_standardize_record` 透传 4 个复权字段并有单测

✅ 达成。

- `app/services/historical_data_service.py` `_standardize_record`（新增于原 line 320 之后）追加：
  ```python
  doc.update({
      "open_qfq": self._safe_float(row.get('open_qfq')),
      "high_qfq": self._safe_float(row.get('high_qfq')),
      "low_qfq": self._safe_float(row.get('low_qfq')),
      "close_qfq": self._safe_float(row.get('close_qfq')),
  })
  ```
- `tests/backtest/test_qfq_sync.py::test_standardize_record_keeps_qfq_fields`：断言 4 个字段透传正确（`assert rec["close_qfq"] == 8.16` 等，非空断言，真实校验值）。
- 额外补了 `test_standardize_record_qfq_fields_none_when_missing`（brief 未要求，边界用例，合理）。
- 两个单测都不初始化 DB（`HistoricalDataService()` 未调用 `initialize()`），`_standardize_record` 本身是纯函数，符合"单元测试不依赖数据库/网络"的约束。已验证：`_standardize_record` 真实签名是 `(self, symbol, row, data_source, market, period="daily", date_index=None)`，测试按真实签名以关键字调用，正确。

### 目标 2：有把某股前复权日线写入/更新 `stock_daily_quotes` 复权字段的同步方法

✅ 达成，且实现方式比 brief 草稿更严谨。

- `HistoricalDataService.merge_qfq_prices(symbol, records, data_source="tushare", period="daily")`：按 `symbol + trade_date + data_source + period` 精确匹配（与 `stock_daily_quotes` 现有唯一索引 `symbol_date_source_period_unique` 完全一致，见 `historical_data_service.py:46-51`），`UpdateOne(upsert=False)` 只 `$set` 复权字段，不新建文档，复用 `_execute_bulk_write_with_retry`。日期用 `_format_date` 归一化为 `YYYY-MM-DD`，与落库时的 `trade_date` 格式一致（已核对 `_format_date` 对 8 位紧凑日期的转换逻辑）。
- `TushareSyncService.sync_historical_qfq(symbol, start_date, end_date)`：复用 `TushareAdapter.get_kline(adj="qfq")` 取数（`adj="qfq"` 时返回的 `open/high/low/close` 本身就是前复权价，代码正确地把它们映射进 `records` 的 `xxx_qfq` 字段，而不是错误地去读取不存在的 `xxx_qfq` 列——已核对 `get_kline` 源码确认这个理解正确），本地按日期过滤后调用 `merge_qfq_prices` 落库。

### 目标 3：集成测试验证 000001 复权字段落库

✅ 达成（但断言方式偏弱，见下方 Important #3）。

- `test_sync_qfq_writes_fields`（`@pytest.mark.integration`）：真实调用 `sync_historical_qfq("000001", "20260101", "20260731")`，断言 `saved > 0`。
- `tests/pytest.ini` 已注册 `integration` marker 且默认 `-m "not integration"` 跳过，符合"集成测试标记、默认不跑"的约束。
- 报告里有额外的原生 pymongo 手工核对（`close_qfq=11.63` 等具体值 + `count=139`），证明数据确实落库且数值合理，这部分证据充分。
- 测试本身对"落库成功"的判定完全依赖 `merge_qfq_prices` 返回的 `saved` 计数，没有在测试内部反查数据库确认字段值，加上 `saved` 计数本身有 MongoDB `$set` 语义的脆弱性（见 Important #3），这是本目标里唯一的薄弱环节。

---

## 二、代码质量：有 3 个问题（Important x3，Minor x4，Critical x0）

### Important #1：`ReplaceOne` 全量重写会冲掉复权价——隐患属实，报告披露基本准确

**结论：真实存在，严重级别评为 Important（非 Critical）。**

验证过程：
- `save_historical_data`（`historical_data_service.py:148-153`）用 `ReplaceOne(filter=filter_doc, replacement=doc, upsert=True)` **整份替换**文档；`doc` 现在总是携带 `open_qfq/high_qfq/low_qfq/close_qfq`（缺省写 `None`，见 `_standardize_record` 新增代码）。
- 常规路径（`sync_historical_data(incremental=True)`，即默认调度路径）通过 `_get_last_sync_date` 只从"该股票最后日期 + 1 天"开始拉取（`tushare_sync_service.py:647-650`），**不会**重新 `ReplaceOne` 已存在且已合并过复权价的历史日期，因此默认增量同步路径下这个风险不会触发。
- 但 `all_history=True`（全量重跑，`tushare_sync_service.py:618-619` 会把起始日期定为 `"1990-01-01"`）会对所有历史日期重新走 `ReplaceOne`，而常规 `provider.get_historical_data()` 取回的普通日线 DataFrame 不含 `open_qfq` 等列，`_standardize_record` 会把它们写成 `None`，从而把 `merge_qfq_prices` 之前写入的复权价整体覆盖为空。

判定 Important 而非 Critical 的理由：触发条件是运维显式选择 `all_history=True`，不是本任务新增的默认执行路径；报告在"自查发现"里如实披露了这个问题、给出了缓解建议（重跑全量后需再补一次 `sync_historical_qfq`），没有试图隐瞒。但代码层面**没有任何防护**（例如 merge 时不覆盖已有值为 `None`，或者提供一个"保留已有复权字段"的合并选项），也没有回归测试覆盖这个场景，属于遗留给后续任务的真实技术债，建议在 Phase 2 之前明确排期，而不是无限期搁置。

### Important #2：顺手修复的 `get_kline` bug 有未经验证的生产行为副作用

**结论：修复本身是对的，但报告"无负面影响"的结论证据不足，副作用范围超出本任务描述。**

验证过程：
- `hasattr(prov, "_normalize_symbol")` 确认在整个代码库中匹配不到任何定义（`grep` 全仓库无结果），真正存在的方法是 `_normalize_ts_code`（`tradingagents/dataflows/providers/china/tushare.py:1229`），修复方向正确。
- 但这个 bug **影响 `get_kline` 的所有调用**（不限于 `adj="qfq"`，任何 `period` 组合都会命中同一行代码），意味着修复前 `TushareAdapter.get_kline` 对**所有** K 线请求都静默返回 `None`。
- `DataSourceManager.get_kline_with_fallback`（`app/services/data_sources/manager.py:282-294`）是 `app/routers/stocks.py:540` 的 `/kline` 端点唯一入口，按 adapter 优先级依次尝试；已核对 `TushareAdapter._get_default_priority() = 3`，是三个 adapter 里最高优先级。也就是说：**修复前，`/kline` 端点的 tushare 分支一直静默失败，实际上一直靠 akshare 兜底**；**修复后，tushare 会重新成为该端点的有效主数据源**，这是一次真实的生产行为变更。
- 报告声称"已确认修复前后...对现有测试无负面影响"，但依据只是 `grep` 搜索"是否有用例依赖旧（错误）行为"，并未实际验证 `/kline` 端点切换回 tushare 数据源后返回内容（字段完整性、单位、空值处理等）是否符合预期，这个结论证据不足。

建议：要么把这个 fix 拆成独立提交并显式说明"这会改变 /kline 端点的默认数据源"供后续单独评审，要么在本次改动里为 `get_kline_with_fallback` 或 `/kline` 端点补一个覆盖 tushare 分支成功路径的测试。

### Important #3：集成测试 `saved > 0` 断言依赖 `$set` 的 `modified_count` 语义，非幂等

**结论：真实的测试脆弱性问题，会导致同一环境重跑该集成测试大概率失败。**

验证过程：
- `merge_qfq_prices` 用 `result.upserted_count + result.modified_count` 作为 `saved` 返回值（复用 `_execute_bulk_write_with_retry`，`upsert=False` 所以 `upserted_count` 恒为 0）。
- MongoDB 对 `$set` 操作的标准行为：如果目标字段值与已存在的值完全相同（no-op update），该文档会被 `matched` 但不计入 `modified_count`。
- 也就是说：`test_sync_qfq_writes_fields` 第一次运行时（字段从无到有）会得到 `saved > 0`（如报告记录的 139 条），**但如果在同一批数据已经合并过一次之后再跑同一个测试**（例如开发者本地重跑、或未来 CI 里意外重复执行），由于复权价数值不会变化，`modified_count` 会是 0，`assert r["saved"] > 0` 就会失败——尽管功能本身完全正常（数据已经是正确状态）。
- 这既是测试设计脆弱性问题（不是幂等测试，容易被误判为回归），也是 `merge_qfq_prices` 返回值语义设计问题：调用方（`sync_historical_qfq` 及未来的 scheduler）真正想知道的是"这批复权数据是否已经成功同步/文档是否匹配"，而不是"这次调用底层是否发生了字节级变化"。更稳健的做法是用 `matched_count`（或者在集成测试里额外做一次读回校验，直接断言 `stock_daily_quotes` 里 `close_qfq is not None`，而不是间接依赖 `saved` 计数）。

---

### Minor 问题

1. **`tests/backtest/conftest.py` 用模块级 `os.environ.setdefault` 全局注入 Mongo 环境变量，作用域过宽**。这段代码在导入时对整个 `tests/backtest` 目录下所有测试（包括两个完全不需要 DB 的纯单元测试）生效，且在整个 pytest 进程生命周期内不会被清理。如果和 `tests/backtest` 一起被收集的其它目录（例如跑全量 `pytest tests/` 时的 `tests/test_env_config.py`）里有用例依赖"未配置 Mongo 账号密码"的默认状态且没有用 `monkeypatch` 保护自身，可能被意外影响。报告的回归检查只跑了 `tests/test_tushare_unified/ tests/services/ tests/backtest/` 三个目录对比，没有验证跑全量 `tests/` 时是否有交叉污染。
   ⚠️ 无法从 diff 单独确认是否真的会导致其它测试失败——取决于 `tests/` 目录里未在本次评审范围内展示的测试内容，只能确认这是一个真实存在、未被验证排除的风险点。更干净的做法是把这段环境变量注入收窄到集成测试自己的 setup 里（比如放进 `_run()` 内部或用 fixture），而不是整个目录级 import-time 全局生效。

2. **YAGNI 检查：`merge_qfq_prices` 硬编码限定 `data_source="tushare"` / `period="daily"`**——报告"疑虑"章节第 1 条已自陈这一点，是合理的最小化实现（复权价目前也只从 tushare 取），不算过度设计，不需要整改。

3. **同样的 `hasattr(x, "_normalize_symbol")` bug 在同文件 `get_news`（`tushare_adapter.py:256`）里仍然存在，未被这次"顺手修"覆盖**。不在本任务范围内，仅作记录，不算本次 diff 的减分项，但如果后续任务涉及新闻/公告功能，这里会遇到同样的静默失败问题。

4. **qfq 字段落库时没有做 `round(x, 2)` 处理**（`_safe_float` 只做类型转换，无舍入），但这与现有 `open/high/low/close` 等价字段的处理方式完全一致（这些字段同样不 round，只有 `change`/`pct_chg` 才 `round(..., 4)`），不是本次改动引入的新不一致。项目全局约束"金额计算 round(x, 2)"在当前整个价格落库路径上本来就没有被严格执行，若要统一需要跨越整个 `historical_data_service.py`，不属于本任务范围，仅作记录。

---

## 三、结论摘要

- **Spec 合规：✅** 三个目标（透传字段+单测 / 同步方法落库 / 集成测试验证）均有对应代码和真实断言，证据充分。
- **代码质量：有 3 个问题** —— Critical x0 / Important x3 / Minor x4。
  - Important #1：`ReplaceOne` 全量重写覆盖复权价，隐患属实（触发条件为 `all_history=True`，非默认路径，报告已披露但代码无防护）。
  - Important #2：`get_kline` 修复改变了 `/kline` 端点的实际数据源优先级，副作用未经验证。
  - Important #3：集成测试 `saved > 0` 依赖 `$set` 的 `modified_count` 语义，非幂等，重跑可能误报失败。
