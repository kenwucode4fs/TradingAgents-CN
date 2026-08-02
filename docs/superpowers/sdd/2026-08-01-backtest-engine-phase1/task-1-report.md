# Task 1 报告：历史库补前复权价

分支：`feature/backtest-engine`

## 一、做了什么

按 brief 的目标实现了三件事：

1. `HistoricalDataService._standardize_record` 透传 `open_qfq/high_qfq/low_qfq/close_qfq` 四个字段。
2. 新增 `HistoricalDataService.merge_qfq_prices(symbol, records, data_source="tushare", period="daily")`：按 `symbol + trade_date`（限定 `data_source`/`period`）对**已存在**的 `stock_daily_quotes` 文档做 `$set` 更新（`UpdateOne(upsert=False)` + `bulk_write`，复用 `_execute_bulk_write_with_retry`），只补复权字段、不新建文档。
3. 新增 `TushareSyncService.sync_historical_qfq(symbol, start_date, end_date)`：复用 `TushareAdapter.get_kline(adj='qfq')` 拉前复权日线，本地按日期范围过滤后调用 `merge_qfq_prices` 落库。

顺带修了一个阻塞该目标的既有 bug：`TushareAdapter.get_kline` 里 `hasattr(prov, "_normalize_symbol")` 恒为 `False`（provider 上真实方法名是 `_normalize_ts_code`），导致传给 `pro_bar` 的 `ts_code` 一直是裸代码（如 `"000001"`），`pro_bar` 无法识别、静默返回 `None`。不修这个，`sync_historical_qfq` 永远拿不到数据，集成测试无法通过其本意（"真实同步落库"），所以判断为必须修。

## 二、改了哪些文件

- `app/services/historical_data_service.py`
  - `_standardize_record` 追加四个 qfq 字段透传（缺省写 `None`）
  - 新增 `merge_qfq_prices`
- `app/worker/tushare_sync_service.py`
  - 新增 `sync_historical_qfq`（放在"前复权价同步（回测引擎）"小节，`_get_last_sync_date` 之后、财务数据同步之前）
- `app/services/data_sources/tushare_adapter.py`
  - `get_kline` 里 `_normalize_symbol` → `_normalize_ts_code`（bug fix）
- `tests/backtest/test_qfq_sync.py`（新建）
  - `test_standardize_record_keeps_qfq_fields`：复权字段透传成功
  - `test_standardize_record_qfq_fields_none_when_missing`：缺省时字段为 `None`（brief 未要求，顺手补的边界用例）
  - `test_sync_qfq_writes_fields`（`@pytest.mark.integration`）：真实同步 000001 并验证落库
- `tests/backtest/conftest.py`（新建）
  - 为本地 mongodb 容器补齐鉴权环境变量默认值（见下文"与 brief 不符之处"）

## 三、每步测试命令与结果

```
# Step 2：写完失败测试后确认失败
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v
→ 2 failed（KeyError: 'close_qfq' / 'open_qfq'），符合预期

# Step 4：实现 _standardize_record 透传后
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v
→ 2 passed

# Step 7：实现 merge_qfq_prices + sync_historical_qfq 后跑集成测试
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v -m integration
→ 1 passed（真实调用 tushare + mongodb，耗时约 8 秒）

# 落库核对（用原生 pymongo 直连，不经过被测代码）
db.stock_daily_quotes.find_one({symbol:'000001', close_qfq:{$exists:true}})
→ 有值：trade_date=2026-07-31, close=11.63, close_qfq=11.63, open_qfq=11.5, high_qfq=11.63, low_qfq=11.28
count({symbol:'000001', close_qfq:{$ne:null}}) → 139 条

# 最终整体确认（非 integration + integration 都跑一遍）
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v          → 2 passed, 1 deselected
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v -m integration → 1 passed, 2 deselected

# 回归检查：改动是否影响其它测试
./venv/bin/python -m pytest tests/test_tushare_unified/ tests/services/ tests/backtest/ \
  --ignore=tests/test_tushare_unified/test_tushare_provider.py
→ 5 failed, 17 passed（对比 git stash 后跑同样命令：baseline 也是 5 failed / 15 passed，
  失败用例完全相同且与本任务改动无关，见下文"自查发现"）
```

## 四、遇到的与 brief 不符之处及如何适配

1. **`_standardize_record` 真实签名不同**
   brief 假设 `svc._standardize_record(row, symbol=..., market=..., data_source=...)`；
   真实签名是 `_standardize_record(self, symbol, row, data_source, market, period="daily", date_index=None)`。
   测试按真实签名以关键字参数调用：`svc._standardize_record(symbol="000001", row=row, data_source="tushare", market="CN")`。

2. **`self.stock_service` 不是历史数据服务**
   `TushareSyncService.__init__` 里 `self.stock_service = get_stock_data_service()`，对应股票基础信息/行情服务，不是 `HistoricalDataService`。真正管理 `stock_daily_quotes` 的是 `self.historical_service`（`initialize()` 时才赋值，来自 `get_historical_data_service()`）。
   `merge_qfq_prices` 按 brief 的意图加在了 `HistoricalDataService` 上，`sync_historical_qfq` 里调用的是 `self.historical_service.merge_qfq_prices(...)`（并在为 `None` 时兜底 `await get_historical_data_service()`）。

3. **`TushareAdapter.get_kline` 不接受 `start_date/end_date`**
   签名是 `get_kline(self, code, period="day", limit=120, adj=None)`，没有日期区间参数。
   适配方式：用较大的 `limit=99999` 一次性拉取，再在 `sync_historical_qfq` 里按 `start_date`/`end_date`（转成紧凑 `YYYYMMDD` 后做字符串比较）本地过滤。

4. **`get_kline` 返回结构确认**
   与 brief 假设一致：`list of {time, open, high, low, close, volume, amount}`；`adj='qfq'` 时 `open/high/low/close` 本身就是前复权价（不是单独的 `xxx_qfq` 字段），所以 `sync_historical_qfq` 里是把 `bar["close"]` 映射成 `records` 里的 `close_qfq`，不是直接透传字段名。

5. **`get_kline` 存在阻塞性 bug（已修复，见上文）**
   `_normalize_symbol` 属性不存在（真实方法是 `_normalize_ts_code`），导致 `ts_code` 不带交易所后缀，`pro_bar` 静默返回空。这是独立于本任务目标的既有缺陷，但不修就无法达成"集成测试验证真实落库"的目标，所以判断为必须修，且已确认修复前后对 `app/services/data_sources/manager.py`（另一处 `get_kline` 调用方）及现有测试（`grep` 未发现依赖旧（错误）行为的用例）无负面影响。

6. **集成测试的数据库/Redis 初始化方式**
   brief 草稿里 `TushareSyncService()` 直接构造再 `asyncio.run(svc.initialize())`。但实测发现：
   - `TushareSyncService.__init__` 里同步调用 `get_mongo_db()`，要求 `app.core.database` 模块级全局 `mongo_db` 已被 `init_database()`（或等价初始化）设置好，否则抛 `RuntimeError("MongoDB数据库未初始化")`；
   - `app.core.database.init_database()` 会同时初始化 Redis，而本地 Redis 容器同样需要鉴权，与本任务无关却会导致测试因为 `redis.exceptions.AuthenticationError` 失败。
   适配：集成测试改为只调用 `db_manager.init_mongodb()` 并同步模块级 `mongo_client`/`mongo_db` 全局变量，跳过 Redis 初始化；结束后 `close_connections()` 并清空全局变量，避免污染其它测试进程状态。

7. **本地 `.env` 缺少可用的 Mongo 账号密码**
   仓库根目录 `.env` 是"最小化配置"（`MONGODB_ENABLED=false`，无 `MONGODB_USERNAME/PASSWORD`），而本地通过 docker-compose 起的 `tradingagents-mongodb` 容器要求账号密码鉴权（`admin`/`tradingagents123`，与 `docker-compose.yml` 里 `MONGO_INITDB_ROOT_USERNAME/PASSWORD` 一致）。
   适配：新增 `tests/backtest/conftest.py`，用 `os.environ.setdefault(...)` 在导入 `app.core.config` 之前补上 `MONGODB_HOST=localhost`、`MONGODB_USERNAME=admin`、`MONGODB_PASSWORD=tradingagents123`、`MONGODB_AUTH_SOURCE=admin`、`MONGODB_DATABASE=tradingagents`。`setdefault` 保证外部若已设置这些环境变量（CI/容器内运行）不会被覆盖。没有修改仓库根目录的 `.env`，避免影响用户本地其它场景的行为。

## 五、自查发现

- **潜在的字段覆盖风险（设计取舍，非 bug，需要知悉）**：`save_historical_data` 用 `ReplaceOne(filter, replacement=doc, upsert=True)` **整份替换**文档。由于 `_standardize_record` 现在总是写入 `open_qfq` 等四个字段（没有复权数据时为 `None`），如果之后对同一批历史日期重新跑一次"全量"（`all_history=True`）历史同步，会把 `merge_qfq_prices` 之前写入的复权价再次替换成 `None`，即复权价会被"冲掉"。这是遵照 brief step 3 的字面要求（透传 + `_safe_float`）得到的结果，也是现有 `ReplaceOne` 整份替换架构的固有特性，不是我引入的新问题。**建议**：后续如果有全量重跑历史数据的场景，要记得在其后重新跑一次 `sync_historical_qfq`；或者作为 Phase 2 的改进项，把 `save_historical_data` 的写入方式从 `ReplaceOne` 改成 `UpdateOne($set)` 做字段级合并（超出本任务范围，未改动）。
- **回归检查**：对比 `git stash` 前后跑 `tests/test_tushare_unified/` + `tests/services/`，两次都是同样的 5 个失败用例（`test_initialize_success`、`test_sync_realtime_quotes_success`、`test_offhours_backfill_when_empty`、`test_quotes_ingestion_run_once_writes_bulk`、`test_scheduler_adds_quotes_job`），确认是分支既有失败（与交易时间判断、mock 细节相关），与本次改动无关，未引入新的回归。
- **`tests/test_tushare_unified/test_tushare_provider.py` 现有的模块收集错误**（`ModuleNotFoundError: tradingagents.dataflows.providers.tushare_provider`）是既有问题，运行 `tests/test_tushare_unified/` 整个目录时需要 `--ignore` 掉它，与本任务无关，未修复（不在任务范围）。
- 本地 venv 里之前没有装 `pytest`/`pytest-asyncio`，已 `pip install` 补上（未写回任何 requirements 文件，只是本地环境补全）。

## 六、疑虑 / 需要你知道的

1. `merge_qfq_prices` 的匹配条件里限定了 `data_source="tushare"` 且 `period="daily"`。如果将来某只股票的日线数据源不是 `tushare`（比如全靠 akshare 落库），`sync_historical_qfq` 不会给它补复权价（这是设计上的选择——复权价本身也只从 tushare 取，逻辑上自洽，但如果回测引擎要覆盖非 tushare 数据源的股票，需要另外处理）。
2. 上面"字段覆盖风险"那条：目前是已知但未修的架构性问题，请知悉，必要时后续任务里评估要不要顺手把 `save_historical_data` 改造成字段级合并。
3. `sync_historical_qfq` 目前用 `limit=99999` 一次性拉全部历史再本地过滤，对于上市很久的老股票可能会拉不必要的数据量（性能，不是正确性问题）；因为 `TushareAdapter.get_kline` 本身不支持日期区间参数，这是在不改动 `get_kline` 签名前提下最小的适配方式。如果后续要优化，可以考虑给 `get_kline`/`pro_bar` 调用加 `start_date`/`end_date` 透传。

---

## 七、评审回归：3 个 Important 问题的修复（commit `1d128df`）

评审结论：Spec ✅，但有 3 个 Important 问题要修。逐项处理如下。

### (a) `ReplaceOne` 全量重跑会把复权价冲掉为 None

**判断**：评估了 brief 建议的两个方向——①把 `save_historical_data` 整体从 `ReplaceOne` 改成 `UpdateOne($set)`；②在整份替换前读出已有 qfq 合并回去。选了②，理由：
- `save_historical_data` 是所有数据源（tushare/akshare/baostock）、所有周期共用的底层写入方法，改动语义（①）会影响 `optional_fields`（`turnover_rate/pe/pb/ps/adjustflag/tradestatus/isST`）等字段的"过期字段是否保留"行为，波及面大、需要更全面的回归验证，风险明显高于本次评审的诉求。
- ②只在整份替换前，针对 `open_qfq/high_qfq/low_qfq/close_qfq` 这 4 个字段做保护性合并，其余写入路径（含 upsert、批量写入、重试）完全不变，风险面最小，且直接对症（评审给的第二个建议方向）。

**改法**：`app/services/historical_data_service.py`
- 新增 `_get_existing_qfq_map(symbol, data_source, period)`：查询该 symbol 已落库、且至少一个 qfq 字段"存在且非空"（`$exists: True, $ne: None`，避免 `$ne: null` 把历史上从未写过该字段的旧文档也误匹配进来）的记录，按 `trade_date` 建索引返回。
- `save_historical_data` 在构建批量操作前调用一次该方法；对每一行标准化出的 `doc`，如果它的 4 个 qfq 字段全部是 `None`（即本次同步数据没带复权价，常规同步的通常情况），就从 `existing_qfq_map` 里按 `trade_date` 取出旧值合并回 `doc`，再送入 `ReplaceOne`。如果本次同步的行确实带了复权价（数值不全为 None），则以新值为准，不做覆盖式合并。

**新增测试**（`tests/backtest/test_qfq_sync.py::test_save_historical_data_preserves_qfq_on_regular_resync`，`@pytest.mark.integration`）：用独立测试代码 `TESTQFQPRESERVE`（不触碰真实行情数据，测试首尾均 `delete_many` 清理）：
1. `save_historical_data` 写入一条不带复权价的行情
2. `merge_qfq_prices` 补上复权价
3. 再次 `save_historical_data`（同一天，依然不带复权价，模拟"全量重跑原始行情"）
4. 断言：复权价字段仍在（未被冲掉），且普通字段 `close` 确实按新数据更新了（证明"保护"没有误伤正常更新语义）

```
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_save_historical_data_preserves_qfq_on_regular_resync -v -m integration
→ 1 passed (7.5s 左右)

# 落库残留检查（测试自清理是否生效）
db.stock_daily_quotes.count_documents({symbol: "TESTQFQPRESERVE"}) → 0
```

### (b) `get_kline` bug 修复的生产副作用未验证

**补的证据**：

1）单元测试 `test_normalize_ts_code_maps_exchange_suffix_correctly`：直接调用 `TushareProvider()._normalize_ts_code(...)`（无需网络/DB），验证：
   - `600000` → `600000.SH`（沪市主板）
   - `000001` → `000001.SZ`（深市主板）
   - `300750` → `300750.SZ`（创业板，深）
   - `688981` → `688981.SH`（科创板，沪）
   - `000001.SZ` → `000001.SZ`（已带后缀原样返回）

2）单元测试 `test_get_kline_calls_pro_bar_with_normalized_ts_code`：`monkeypatch` 替换 `tushare.pro.data_pro.pro_bar` 为一个记录调用参数的 fake 函数，给 `TushareAdapter` 注入一个"已连接"的 provider 桩（`TushareAdapter.__new__` 绕开真实的 `get_tushare_provider()` 全局单例，避免触发真实网络连接），调用 `adapter.get_kline(code="600000", adj="qfq")`，断言 `pro_bar` 实际收到的 `ts_code == "600000.SH"`。这直接证明了**代码路径**（不只是 `_normalize_ts_code` 这个方法本身）在修复后是通的。

3）生产路径证据（旁证，不是新测试）：Task 1 的集成测试 `test_sync_qfq_writes_fields` 走的正是这条被修复的路径——`TushareAdapter.get_kline(code="000001", adj="qfq")` → 内部 `pro_bar(ts_code="000001.SZ", ...)`，已经实测成功拿到并落库了 139 条 000001 的前复权日线（详见第三节）。这说明修复后 tushare kline 路径（含 `adj=qfq`）在真实 tushare 账号下确实可用，不是只在 mock 层面正确。

```
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_normalize_ts_code_maps_exchange_suffix_correctly tests/backtest/test_qfq_sync.py::test_get_kline_calls_pro_bar_with_normalized_ts_code -v
→ 2 passed（无网络、无数据库依赖，约 1.9s）
```

**关于"是否把 `/kline` 从 akshare 兜底切回以 tushare 为主"**：这个 bug 本来就属于"应该生效但实际没生效"的既有缺陷——`TushareAdapter` 在 `manager.py` 里的优先级本来就是最高（`_get_default_priority` 返回 3，数字越大优先级越高），只是因为 `get_kline` 内部的 ts_code 标准化恒为裸代码导致 `pro_bar` 静默返回空，才被动"退化"成事实上依赖 akshare 兜底。修复后是让**既定的优先级设计生效**，不是引入新的优先级变更；`app/services/data_sources/manager.py` 里对 `get_kline` 返回 `None`/空列表本来就有 fallback 到下一优先级数据源的逻辑（未改动），所以即便 tushare 这次因为某些股票没权限/数据缺失返回空，也不会破坏 fallback 链路。

### (c) 集成测试 `assert r["saved"] > 0` 非幂等

**改法**：`test_sync_qfq_writes_fields` 不再断言 `sync_historical_qfq` 返回值里的 `saved`（即 `$set` 触发的 `modified_count`），改为调用 `sync_historical_qfq` 后，直接从 `svc.historical_service.collection` 读回 000001 在目标日期区间内、`close_qfq` 非 None 的最新一条记录，断言该记录存在且 `close_qfq/open_qfq/high_qfq/low_qfq` 均非 None。

**验证幂等性**（连续跑两次，第二次数值不变、`modified_count` 应为 0，但断言应仍然通过）：

```
=== run 1 ===
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields -v -m integration
→ 1 passed (7.69s)

=== run 2（重复执行，验证不再因 modified_count=0 误报失败）===
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields -v -m integration
→ 1 passed (7.75s)
```

### 覆盖测试（本轮修复后完整跑一遍）

```
# 全部单元测试（不依赖数据库/网络）
./venv/bin/python -m pytest tests/backtest/ -v
→ tests/backtest/test_qfq_sync.py::test_standardize_record_keeps_qfq_fields PASSED
→ tests/backtest/test_qfq_sync.py::test_standardize_record_qfq_fields_none_when_missing PASSED
→ tests/backtest/test_qfq_sync.py::test_normalize_ts_code_maps_exchange_suffix_correctly PASSED
→ tests/backtest/test_qfq_sync.py::test_get_kline_calls_pro_bar_with_normalized_ts_code PASSED
→ 4 passed, 2 deselected

# 全部集成测试
./venv/bin/python -m pytest tests/backtest/ -v -m integration
→ tests/backtest/test_qfq_sync.py::test_save_historical_data_preserves_qfq_on_regular_resync PASSED
→ tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields PASSED
→ 2 passed, 4 deselected

# 回归检查：与本任务改动无关的既有失败用例数量不变（5 个，逐一核对与本次改动无关）
./venv/bin/python -m pytest tests/test_tushare_unified/ tests/services/ tests/backtest/ \
  --ignore=tests/test_tushare_unified/test_tushare_provider.py -m "not integration"
→ 5 failed, 19 passed, 2 deselected
  （5 个失败与 e9a5d88 之前的 baseline 完全一致：test_initialize_success、
  test_sync_realtime_quotes_success、test_offhours_backfill_when_empty、
  test_quotes_ingestion_run_once_writes_bulk、test_scheduler_adds_quotes_job；
  19 passed 比修复前的 17 多了 2 个，正是本轮新增的两个 ts_code 单元测试）
```

### 落库残留检查

测试用完即清理，未在共享开发库里留下测试脏数据：

```
db.stock_daily_quotes.count_documents({symbol: "TESTQFQPRESERVE"}) → 0
```

### Minor 问题

评审提到的 Minor 问题（conftest mongo 注入作用域、`merge_qfq_prices` 硬编码 `data_source="tushare"` 等）本轮未处理，按评审要求记入 ledger，交最终评审 triage。
