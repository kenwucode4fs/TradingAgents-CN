# Task 1 限定范围复审：3 个 Important 问题修复核对

复审对象：`review-07c54bc..1d128df.diff`（单一提交 `1d128df`）
方法：逐项读 diff + 读周边未改动代码确认边界正确性 + 实际运行测试验证（非仅静态审查）。

## (a) ReplaceOne 全量重跑冲掉复权价 —— ADDRESSED

`app/services/historical_data_service.py` 新增 `_get_existing_qfq_map()`（约 L72-121）：在 `save_historical_data` 构建 `ReplaceOne` 操作前，用 `$or: [{f: {"$exists": True, "$ne": None}} for f in qfq_fields]` 查询该 symbol 已落库的非空复权字段，按 `trade_date` 建索引；循环内（L45-49）仅当当前标准化出的 `doc` 四个 qfq 字段**全部为 None**（即本次同步未带复权价）时才 `doc.update(existing_qfq)`。

边界核对：
- 目标文档原本没有 qfq：`existing_qfq_map.get(trade_date)` 返回 `None`，`if existing_qfq` 为假，不更新，`doc` 保持 `_standardize_record` 产出的 None，不会误覆盖（本身也没有可覆盖的值）。
- 部分字段为 None：projection 是字段级 include，只有实际存在于原文档上的 key 才会出现在 `row` 里，`doc.update()` 只会覆盖那些 key，不会把"未查到"的字段强行置为 None。

测试 `test_save_historical_data_preserves_qfq_on_regular_resync`（新增，`@pytest.mark.integration`）真实断言了字段保留：先写入不带 qfq 的行情 → `merge_qfq_prices` 补 qfq → 再次常规同步同一天（仍不带 qfq，但 `close` 变了）→ 断言 `close == 10.3`（常规字段确实更新，证明"保护"没有误伤正常更新语义）且 `close_qfq/open_qfq/high_qfq/low_qfq` 仍是 merge 时写入的值。

**实测复核**：本地 `tradingagents-mongodb` 容器在运行，独立执行该测试：
```
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_save_historical_data_preserves_qfq_on_regular_resync -v -m integration
→ 1 passed
```

## (b) get_kline ts_code 标准化修复未验证 —— ADDRESSED

production fix 已确认存在于此前一个提交 `98a0847`（`app/services/data_sources/tushare_adapter.py`：`prov._normalize_symbol(...)` → `prov._normalize_ts_code(...)`，旧代码 `hasattr` 恒假导致裸代码传给 `pro_bar`）。本次 fix diff 新增的是补验证：

- `test_normalize_ts_code_maps_exchange_suffix_correctly`：直接调用 `TushareProvider()._normalize_ts_code`，断言 `600000→600000.SH`、`000001→000001.SZ`、`300750→300750.SZ`（创业板归深）、`688981→688981.SH`（科创板归沪）、带后缀原样返回。真断言了标准化结果，不是只调用不检查。
- `test_get_kline_calls_pro_bar_with_normalized_ts_code`：monkeypatch `tushare.pro.data_pro.pro_bar`，注入已连接的 provider 桩，调用 `adapter.get_kline(code="600000", adj="qfq")`，断言 `captured["ts_code"] == "600000.SH"`，证明修复后的代码路径（不只是方法本身）真的把标准化后的 ts_code 传给了 pro_bar。

**实测复核**：两个测试均无网络/DB依赖，独立运行：
```
./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py -v -m "not integration"
→ 4 passed（含上述两个）
```

## (c) 集成测试 saved>0 非幂等 —— ADDRESSED

`test_sync_qfq_writes_fields` 不再断言 `sync_historical_qfq` 返回值里依赖 `modified_count` 的 `saved`，改为调用后从 `svc.historical_service.collection` 按 `symbol/data_source/period/trade_date区间/close_qfq: {"$ne": None}` 读回最新一条记录，断言其 `close_qfq/open_qfq/high_qfq/low_qfq` 均非 None。这是对数据库最终状态的断言，与 `modified_count`（本次是否真正发生了变更）解耦。

**实测复核**：真实连续运行两次，验证幂等（第二次数值不变、`$set` 触发的 `modified_count` 应为 0，但断言不依赖它）：
```
run 1: ./venv/bin/python -m pytest tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields -v -m integration → 1 passed (8.34s)
run 2: 同上，重复执行                                                                                              → 1 passed (11.86s)
```
两次均通过，未出现因幂等性问题导致的误报失败。

## fix diff 内是否引入新的 Critical/Important 破坏

未发现新的 Critical/Important 破坏。核对要点：

- `_get_existing_qfq_map` 的 `$or` 查询语义正确（`$exists + $ne None` 组合避免历史上从未写过该字段的旧文档被误纳入），异常时 `except` 兜底返回空字典并仅 `logger.warning`，不会阻断正常写入流程。
- 新增的查询调用点在 `save_historical_data` 里位于"空数据提前 return”之后、构建操作列表之前（L131 附近），不会对空 DataFrame 场景产生多余查询；但会对**每一次** `save_historical_data` 调用（不论 market/period/data_source，是否曾经写过 qfq）无条件多发一次 `find` 查询 —— 这是一处轻微的性能开销（非正确性问题，也是报告第五节已知悉的既有 `ReplaceOne` 整份替换架构局限之外的新增开销），够不上 Important，仅作记录。
- 合并条件用的是"新 doc 四个 qfq 字段是否全为 None"来决定是否整体合并旧值，而非逐字段判断——如果未来出现某数据源只提供部分 qfq 字段（如只有 close_qfq）的场景，另外三个字段不会被旧值填补。这是设计取舍的边界（不属于本次要求核对的范围，也不比修复前更差：修复前是全部字段都会被覆盖成 None），仅作记录，不算新引入的破坏。

## 总体 Verdict

**通过**（PASS）。3 项 Important 均 ADDRESSED，且均通过实际运行测试复核（非仅静态审查）；fix diff 范围内未发现新的 Critical/Important 破坏。
