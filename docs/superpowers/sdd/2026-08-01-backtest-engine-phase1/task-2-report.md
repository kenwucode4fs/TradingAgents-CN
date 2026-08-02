# Task 2 报告：ST 历史状态落库与按日查询

## 做了什么

新增 `StStatusService`，供后续回测引擎的精确涨跌停判定按日查询某股票是否处于 ST（含 *ST）状态。数据来源为 tushare `namechange` 接口（曾用名及生效区间），名称含 "ST" 的区间即视为 ST 期，落库到 MongoDB collection `stock_st_periods`，并提供内存缓存 + `is_st(symbol, date)` 快速判定。

严格按 TDD 流程执行：先写失败测试（Step1 brief 给定的 `test_is_st_within_period`）→ 确认 `ModuleNotFoundError` → 最小实现 → 全部测试通过 → 补充边界测试与集成测试 → 提交。

## 改动的文件

- 新建 `app/services/st_status_service.py`（`StStatusService` 类）
- 新建 `tests/backtest/test_st_status.py`（8 个单元测试 + 1 个集成测试）
- 未改动 `tests/backtest/conftest.py`（沿用上一任务已补的本地 mongo 鉴权环境变量）

commit: `a891ed0` — `feat(backtest): 新增 ST 历史状态同步与按日查询服务`

（工作目录里另有 `docker-compose.yml` / `tradingagents/default_config.py` 的未暂存改动及 `docker-compose-host.yml` / `docker-compose-network.yml` 两个未跟踪文件，均是任务开始前就存在的、与本任务无关的改动，本次未触碰、未提交。）

## 实现内容

`app/services/st_status_service.py` 提供：

- `__init__`：`_periods_cache: Dict[str, List[dict]]` 内存缓存 + `db`/`collection` 延迟初始化（模式与 `HistoricalDataService` 一致）。
- `is_st(symbol, date) -> bool`：按 `YYYY-MM-DD` 判定，`end_date` 为 `None` 表示"至今"。
- `initialize()`：用 `app.core.database.get_database()` 拿 db（与 `HistoricalDataService.initialize()` 完全同构），并对 `stock_st_periods` 建 `(symbol, start_date)` 唯一索引。
- `sync_from_tushare(symbol) -> int`：通过 `TushareAdapter()._provider.api.namechange(...)` 拉取曾用名区间，筛出含 "ST" 的区间，调用 `_save_periods` upsert 入库，返回写入数。
- `load(symbol) -> None`：从 `stock_st_periods` 查询该 symbol 的区间，写入 `_periods_cache[symbol]`。
- `_save_periods(periods) -> int`：`periods` 为空直接返回 0（不触碰数据库）；否则用 `pymongo.UpdateOne({symbol, start_date}, {"$set": p}, upsert=True)` + `collection.bulk_write(ordered=False)`，与 `HistoricalDataService` 里 bulk_write 的用法风格一致。
- `_to_ts_code(symbol)` / `_fmt(v)`：静态纯函数，行为与 brief 给定代码一致。

## 与 brief 不符处及适配

1. **tushare namechange 真实调用方式**：已用 tushare MCP 的 `namechange` 工具对 `000980.SZ` 做了人工核实（见下方"集成测试验证方式"），确认默认返回字段确实是 `ts_code, name, start_date, end_date, ann_date, change_reason`，`start_date`/`end_date` 为 `YYYYMMDD` 字符串，"至今"的区间 `end_date` 为 `null`（对应 DataFrame 里的空值/NaN）。brief 里 `adapter._provider.api.namechange(ts_code=..., fields="name,start_date,end_date")` 的调用方式和字段假设是对的，未做调整。

2. **`sync_from_tushare` 增加了可用性检查**：brief 原代码直接用 `adapter._provider.api` 调用，未做任何可用性判断。参照 `TushareAdapter.get_daily_basic` 等现有方法的写法（先 `is_available()` 检查），我在 `sync_from_tushare` 里加了：
   ```python
   if not adapter.is_available() or adapter._provider is None or adapter._provider.api is None:
       logger.warning(...)
       return 0
   ```
   这是为了避免 tushare 未连接时抛出 `AttributeError`（`.api` 为 `None`），使同步失败时优雅降级为返回 0 并记录日志，而不是让调用方拿到异常。这是对 brief 的增强，不影响接口签名和核心测试断言。

3. **MongoDB 连接方式**：完全复用 `app.core.database.get_database()`（即 `db_manager.mongo_client.tradingagents`），与 `HistoricalDataService.initialize()` 同构，未另起一套连接逻辑。brief 里未给出具体连接代码（只写了 `...`），此处按现有 service 的模式补全。

4. **`_to_ts_code` 的已知局限**：保留了 brief 给定的简化逻辑（`6` 开头 -> `.SH`，其余 -> `.SZ`），未替换为 `TushareProvider._normalize_ts_code`（后者对 `90` 开头的 B 股也映射到 `.SH`，更完整）。因为 brief 明确给出了单测断言（`600000` -> `SH`，`000001` -> `SZ`），两种实现在这两个用例上结果一致，为忠实执行 brief 未做替换，仅在 docstring 里注明了该局限（不覆盖北交所等小众前缀）。

## 每步测试命令与结果

1. 写失败测试后：
   ```
   ./venv/bin/python -m pytest tests/backtest/test_st_status.py -v
   ```
   结果：`ModuleNotFoundError: No module named 'app.services.st_status_service'`（collection error），符合预期的 FAIL。

2. 最小实现（`is_st` + Step1 测试）后，同一命令：8 个单测全部 PASS（此时已包含后续补充的所有单测，一次性写完后统一跑）。

3. 补充 `_to_ts_code` / `_fmt` 单测、`_save_periods` upsert 行为单测（用假 `_FakeCollection` 注入，不连数据库）、`is_st` 边界情况（`end_date=None` 至今、未知 symbol）后：
   ```
   ./venv/bin/python -m pytest tests/backtest/test_st_status.py -v
   ```
   结果：`8 passed, 1 deselected in 0.54s`（集成测试被默认 `-m "not integration"` 排除）。

4. 集成测试：
   ```
   ./venv/bin/python -m pytest tests/backtest/test_st_status.py -v -m integration
   ```
   结果：`1 passed, 8 deselected in 36.61s`（首次运行，真实连接 tushare + 本地 mongo 容器）。又重跑一次验证幂等（upsert 不重复插入、清理逻辑正确）：`1 passed, 8 deselected in 11.82s`。

5. 全量回归（`tests/backtest/` 目录，默认跳过 integration）：
   ```
   ./venv/bin/python -m pytest tests/backtest/ -v
   ```
   结果：`12 passed, 3 deselected in 3.94s`（含已有的 `test_qfq_sync.py` 4 个单测 + 本任务新增 8 个单测）。

6. 自查：跑完集成测试后手动查询 `stock_st_periods` collection，确认 `symbol=000980` 及全集合均为 0 条残留文档，确认测试的 `finally` 清理逻辑生效，不污染数据库。

## 集成测试验证方式（重要）

brief 允许"若不确定哪只股票有 ST 历史，可仅断言流程无异常"，但我在实现前先用 tushare MCP 的 `namechange` 工具对 `000980.SZ`（众泰汽车）做了真实查询，人工确认其曾用名历史中存在两段真实 ST 区间：

- `*ST众泰`：`2020-06-24` ~ `2022-05-19`
- `ST众泰`：`2022-05-20` ~ `2022-11-02`

因此集成测试 `test_sync_from_tushare_and_load_hits_known_st_period` **没有采用"仅验证无异常"的弱断言**，而是做了更强的断言：

- `sync_from_tushare("000980")` 返回的写入区间数 `>= 2`
- `load("000980")` 后，`is_st("000980", "2021-01-01")` 为 `True`（落在第一段区间内）
- `is_st("000980", "2022-08-01")` 为 `True`（落在第二段区间内）
- `is_st("000980", "2023-01-01")` 为 `False`（已恢复"众泰汽车"，非 ST）

测试在 `_run()` 的 `try`/`finally` 里对 `stock_st_periods` 做了先清后清（开始前 `delete_many` 防止上次异常退出留脏数据，结束后 `delete_many` 清理本次写入），不污染数据库；重复运行验证过幂等性（upsert 按 `symbol+start_date` 去重，不会重复插入）。

## 自查发现

- 检查了 `is_st` 对"未知 symbol"（不在缓存里）和"区间开放至今"（`end_date=None`）两种边界情况，均已补充单测覆盖（brief 原始测试未覆盖这两点）。
- `_save_periods` 传入空列表时会提前返回 0，不会触碰 `self.collection`（此时仍为 `None`），已用专门单测验证，避免调用方在没有 ST 区间时意外触发数据库初始化。
- 集成测试跑完后用独立脚本核对了 `stock_st_periods` 全集合文档数为 0，确认没有污染共享的本地 mongo 容器。
- 未新建/修改 `app/services/st_status_service.py` 之外的生产代码，未触碰任务开始前已存在的、与本任务无关的未提交改动（`docker-compose.yml`、`tradingagents/default_config.py`、`docker-compose-host.yml`、`docker-compose-network.yml`）。

## 疑虑

- `sync_from_tushare` 目前是"一次拉全部曾用名、筛 ST、全量 upsert"，没有做增量/限流控制；如果未来要批量同步大量股票的 ST 历史，可能需要加限流或分批（参考 `HistoricalDataService` 里的重试/批量写入模式），当前任务范围内未要求，未实现。

---

## 评审修复轮（2026-08-02）

评审结论：Spec ✅，1 个 Important 需修复，另补一个 Minor 测试覆盖。

### Important：`_to_ts_code` 未处理北交所，静默失败

**问题**：原实现只做"6 开头 -> `.SH`，其余 -> `.SZ`"的二分映射，把北交所代码（8/4 开头，含历史新三板转板 43/83/87，以及 2023 年后北交所直接 IPO 的 920 开头新股）错误映射成 `.SZ`。这会导致 `sync_from_tushare` 对北交所 ST 股票调用 `namechange(ts_code="xxxxxx.SZ", ...)` 查不到对应记录，静默返回 0（不报错），进而 `is_st` 对这些股票恒为 `False`，与"从未 ST"无法区分，造成静默的涨跌停判定偏差。

**修复**：参考 `app/services/basics_sync_service.py` 中 `_generate_full_symbol` 的现有约定（`code.startswith(('8', '4'))` -> `.BJ`），并按评审要求补上 `920` 开头新股前缀，重写 `_to_ts_code`：

```python
@staticmethod
def _to_ts_code(symbol: str) -> str:
    if symbol.startswith(("8", "4", "920")):
        return f"{symbol}.BJ"
    if symbol.startswith("6"):
        return f"{symbol}.SH"
    return f"{symbol}.SZ"
```

`startswith(("8", "4", "920"))` 中 `"8"`/`"4"` 已经覆盖了历史三板转板代码 `43`/`83`/`87`（均以 `4`/`8` 开头），`"920"` 单独覆盖新股前缀（不以 `8`/`4` 开头，需要显式列出）。原有沪深映射逻辑（6 开头 -> SH，其余 -> SZ）保持不变，置于北交所判断之后，不影响原有行为。

修改文件：`app/services/st_status_service.py`（`_to_ts_code`，约 L146-160）。

### Minor（随手补）：多段 ST 区间纯单测

新增 `test_is_st_multiple_non_adjacent_periods`（`tests/backtest/test_st_status.py`），直接向 `_periods_cache` 注入某股两段不相邻的 ST 区间（参考 000980 真实历史：2003 年 `ST金马` 区间 + 2020 年 `*ST众泰` 区间），断言：
- 两段区间各自的起止边界日均判定为 `True`；
- 两段之间的空档（含区间结束后一天、区间中段的任意日期）判定为 `False`；
- 第二段结束后一天判定为 `False`。

不依赖数据库/网络。

### 同时新增的回归测试

`test_to_ts_code_beijing_exchange`（`tests/backtest/test_st_status.py`）：
- 北交所新映射：`830799` -> `830799.BJ`（8 开头常规代码）、`430047` -> `430047.BJ`（4 开头历史新三板代码）、`870656` -> `870656.BJ`（87 开头三板转北交所）、`920819` -> `920819.BJ`（920 开头北交所直接 IPO 新股）；
- 回归确认原有沪深映射未被破坏：`600000` -> `.SH`、`688981`（科创板）-> `.SH`、`000001` -> `.SZ`、`300750`（创业板）-> `.SZ`。

### 测试命令与结果

1. `tests/backtest/test_st_status.py` 单元测试（默认跳过 integration）：
   ```
   ./venv/bin/python -m pytest tests/backtest/test_st_status.py -v
   ```
   结果：
   ```
   collected 11 items / 1 deselected / 10 selected
   test_is_st_within_period PASSED
   test_is_st_open_ended_period_means_until_now PASSED
   test_is_st_unknown_symbol_returns_false PASSED
   test_is_st_multiple_non_adjacent_periods PASSED
   test_to_ts_code PASSED
   test_to_ts_code_beijing_exchange PASSED
   test_fmt_date PASSED
   test_fmt_date_more_cases PASSED
   test_save_periods_empty_list_returns_zero_without_touching_db PASSED
   test_save_periods_upserts_each_period_by_symbol_and_start_date PASSED
   10 passed, 1 deselected in 2.78s
   ```

2. 集成测试（确认修复未影响原有沪深股票的真实同步链路，000980 仍是 `.SZ`）：
   ```
   ./venv/bin/python -m pytest tests/backtest/test_st_status.py -v -m integration
   ```
   结果：
   ```
   test_sync_from_tushare_and_load_hits_known_st_period PASSED
   1 passed, 10 deselected in 15.97s
   ```

3. `tests/backtest/` 全量回归（默认跳过 integration）：
   ```
   ./venv/bin/python -m pytest tests/backtest/ -v
   ```
   结果：
   ```
   collected 17 items / 3 deselected / 14 selected
   ... (test_qfq_sync.py 4 项 + test_st_status.py 10 项均 PASSED)
   14 passed, 3 deselected in 6.82s
   ```

### 本轮未处理项（已记 ledger，交最终评审）

- `sync_from_tushare` 里 `is_available()` 检查的冗余判断（Minor）
- `_fmt` 对 tushare NaT 值的透传行为（Minor）
- ST 判定用 `"ST" in name` 子串匹配（Minor，例如极端情况下可能误匹配含 "ST" 字样但非风险警示的曾用名）

以上三项按评审要求本轮不动。

commit: `585581d` — fix(backtest): 修复 ST 状态服务北交所代码映射静默失败问题
