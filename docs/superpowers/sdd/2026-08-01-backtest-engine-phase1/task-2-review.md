# Task 2 代码评审：ST 历史状态服务

评审对象：`review-1d128df..a891ed0.diff`（commit `a891ed0`）
评审文件：`app/services/st_status_service.py`、`tests/backtest/test_st_status.py`

## 结论 1：Spec 合规 —— ✅

逐条核对 brief 要求：

1. **`is_st(symbol, date)` 按 `YYYY-MM-DD` 判定，`end_date=None` 表示至今，有不依赖 DB 的单测**：✅
   - `st_status_service.py:83-88` 实现与 brief 给定代码一致（字符串字典序比较，YYYY-MM-DD 格式下等价于日期序）。
   - 单测 `test_is_st_within_period`（brief 原始用例）、`test_is_st_open_ended_period_means_until_now`（`end_date=None` 边界，起始日当天/远未来/起始日前一天）、`test_is_st_unknown_symbol_returns_false`（跨股票隔离）均直接注入 `_periods_cache`，不触碰数据库。三个测试都是真实断言（非 `assert True`/无异常式弱断言）。

2. **`_to_ts_code`、`_fmt` 有单测**：✅
   - `test_to_ts_code`（600000→SH，000001→SZ，与 brief 一致）、`test_fmt_date`（8 位数字→带横线，空串→None）、`test_fmt_date_more_cases`（补充 None/"nan"/"None"/已是 YYYY-MM-DD 格式的透传）均为纯函数单测，无 DB/网络依赖。

3. **`sync_from_tushare`（拉 namechange 含 ST 区间 upsert）+ `load`（从库载入缓存）**：✅
   - `sync_from_tushare`（`st_status_service.py:90-122`）调用 `TushareAdapter()._provider.api.namechange`，用 `"ST" in name` 筛选，转格式后交给 `_save_periods` 做 `UpdateOne({symbol,start_date}, {"$set":...}, upsert=True)` + `bulk_write(ordered=False)`，符合 brief 描述。
   - `load`（`st_status_service.py:124-133`）用 `collection.find({"symbol":symbol})` 载入 `_periods_cache[symbol]`，符合接口。
   - `_save_periods` 的 upsert 调用行为有单测（用 `_FakeCollection` 注入，断言 `UpdateOne` 的 `_filter`/`_doc`/`_upsert` 三个内部属性，已用 `./venv/bin/python` 实测确认 pymongo `UpdateOne` 确实暴露这三个属性，断言真实有效），以及空列表提前返回、不触碰 `collection` 的单测。

4. **集成测试验证同步流程**：✅
   - `test_sync_from_tushare_and_load_hits_known_st_period`（`@pytest.mark.integration`）用真实标的 000980（众泰汽车，人工核实过两段真实 ST 区间：2020-06-24~2022-05-19、2022-05-20~2022-11-02）做端到端验证：`sync_from_tushare` 写入数 `>=2`、`load` 后两段区间内 `is_st` 均为 `True`、区间外为 `False`。断言强度高于"仅验证无异常"的弱断言。测试在 `try/finally` 里先清后清，不污染共享 mongo。

**结论：brief 四项目标均达成，均有真实（非空洞）测试证据。**

## 结论 2：代码质量 —— 有问题（1 个 Important，3 个 Minor，0 个 Critical）

### Important

1. **`_to_ts_code` 未处理北交所（8/4 开头）前缀，导致北交所 ST 股票同步静默失效，且该问题并非纯假设——代码库其他模块已明确支持北交所股票。**
   - `app/services/basics_sync_service.py:399-407`（及 `multi_source_basics_sync_service.py` 同构逻辑）已有明确的交易所判定：`60/68/90→.SS`、`00/30/20→.SZ`、`8/4→.BJ`；`app/services/screening_service.py:220` 的市场类型筛选里直接包含 `"北交所"`。这说明本项目的股票基础库（`stock_basic` 等）**确实包含北交所标的**，并非仅覆盖沪深。
   - 而 `StStatusService._to_ts_code`（`st_status_service.py:144-150`）沿用 brief 的简化逻辑：非 `6` 开头一律映射为 `.SZ`。对于 `8`/`4` 开头的北交所代码（如 `830799`），会被错误映射为 `830799.SZ`，这个 ts_code 在 tushare 中不存在，`namechange` 返回空 DataFrame，`sync_from_tushare` 悄悄返回 `0`，`is_st` 对该股票永远返回 `False`——**且这个"假阴性"与"该股票确实从未 ST 过"在行为上完全无法区分，不会报错、不会告警。**
   - 实际后果：如果后续回测标的池纳入北交所股票（当前系统能力上已支持,如 `screening_service` 按"北交所"筛选出的标的），对这些股票做涨跌停精确判定时会把实际 ST 状态误判为非 ST，导致回测用错误的涨跌幅限制（如按 10%/30% 而非实际 5%/30%规则），产生静默的回测结果偏差。
   - 严重级别评定为 **Important 而非 Critical**：①不会崩溃、不会影响沪深主板/创业板/科创板股票（当前 Phase 1 报告自述的场景）的正确性；②报告已在"疑虑"里如实自陈该局限，未隐藏；③是否真的阻塞取决于 Task 后续（回测引擎/涨跌停规则）的标的池是否纳入北交所——这一点 diff 本身无法确认（⚠️ 无法从 diff 确认：回测引擎最终标的池范围）。但鉴于系统其它模块已实际支持北交所标的，这不是纯理论风险，建议在北交所标的正式进入回测标的池之前修复（复用 `TushareProvider._normalize_ts_code` 或 `basics_sync_service` 里已有的判定逻辑）。

### Minor

1. **多段区间（同一 symbol 多条 ST 记录）缺少不依赖网络的纯单元测试**，只在依赖 tushare+mongo 的集成测试（000980 的两段真实区间）里被间接覆盖。`is_st` 的实现是对列表的简单遍历，逻辑风险低，但如果 CI 环境没有 tushare token / mongo 容器，这部分边界在单元测试层面实际上未被验证。建议后续补一个类似 `svc._periods_cache = {"000980": [两段区间]}` 的纯内存单测。
2. **`sync_from_tushare` 里的可用性检查与 `TushareAdapter.is_available()` 内部逻辑重复**（`st_status_service.py:102`：`not adapter.is_available() or adapter._provider is None or adapter._provider.api is None`）。查看 `tushare_adapter.py:44-56`，`is_available()` 本身就已经检查了 `_provider is not None` 和 `_provider.api is not None`，后两个条件是冗余判断（非 bug，只是多余代码，不影响正确性）。
3. **`_fmt` 对非 8 位、非空、非 "None"/"nan" 的异常值（如假设的 pandas `NaT` 字符串）会原样透传返回**，不会被识别为空值。实际风险很低（tushare `namechange` 的日期字段一贯是 8 位数字字符串或真正的空值，不会产出 `NaT` 字符串），但严格来说不是穷尽的边界处理，仅作记录。
4. **ST 名称判定用子串匹配 `"ST" in name`**，理论上如果曾用名恰好含有 "ST" 字母但不是风险警示状态会被误判为 ST。按 A 股实际命名惯例（正常上市公司名称为纯中文，不含 "ST" 英文字母；"S"/"ST"/"*ST"/"SST"/"S*ST" 均为官方风险警示/历史非流通股改革标记，语义上应视同特殊状态），这一风险在实践中可忽略，未发现由此导致的真实误判用例，标记为观察项而非缺陷。

### 其他核实点（无问题）

- **区间边界正确性**：`start<=date<=end`、`end=None` 至今、跨股票隔离，均有单测覆盖且断言正确（起始日当天命中、起始日前一天不命中、远未来仍命中）。
- **MongoDB 连接复用**：`initialize()` 完全复用 `app.core.database.get_database()`，与 `HistoricalDataService.initialize()`（`app/services/historical_data_service.py:26-38`）同构，未另起连接逻辑；`load()` 用 `AsyncIOMotorCollection.find()` + `cursor.to_list(length=None)`，与项目使用 `motor`（`app/core/database.py:9`）异步驱动的约定一致。
- **upsert 幂等性**：`_save_periods` 按 `{symbol, start_date}` 作为过滤条件 `upsert=True`，有单测验证 `UpdateOne` 的 `_filter`/`_doc`/`_upsert` 属性设置正确；集成测试报告自述"重跑一次验证幂等，无重复插入"。
- **测试真实性**：所有单测均为真实断言（值比较、属性比较），无 `assert True` 或纯粹"不抛异常"式弱断言；集成测试也做了强断言（`saved >= 2`、区间内/外的 `is_st` 结果）并在 `finally` 中清理数据，不污染共享库。
- **测试风格与位置**：位于 `tests/backtest/test_st_status.py`，pytest 风格，`@pytest.mark.integration` 标记集成测试，与 `tests/pytest.ini` 的 `addopts = -m "not integration"` 默认跳过策略一致；异步测试用 `asyncio.run(_run())` 包装，风格与已有的 `tests/backtest/test_qfq_sync.py`（Task 1）一致。
