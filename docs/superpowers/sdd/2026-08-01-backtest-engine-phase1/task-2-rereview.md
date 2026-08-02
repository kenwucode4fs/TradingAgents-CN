# Task 2 复审报告（commit 585581d）

## Important 项：`_to_ts_code` 未处理北交所导致静默失败

**ADDRESSED**

证据：`app/services/st_status_service.py:157-161`

```python
if symbol.startswith(("8", "4", "920")):
    return f"{symbol}.BJ"
if symbol.startswith("6"):
    return f"{symbol}.SH"
return f"{symbol}.SZ"
```

- 前缀判定完整：8/4 开头（含历史新三板转板代码 43/83/87）以及 920 开头（2023 年后北交所直接
  IPO 新股）均正确映射到 `.BJ`；判定顺序不会误伤沪深代码——沪市 6 开头、深市 0/3 开头均不以
  8/4/920 打头，两组前缀互斥，`if/elif` 顺序调换也不影响结果。
- 沪深原有映射未回归：6 开头（含科创板 688）仍映射 `.SH`，0/3 开头仍映射 `.SZ`。
- 单元测试真实断言了 `.BJ` 结果：`tests/backtest/test_st_status.py:99-114`
  (`test_to_ts_code_beijing_exchange`) 分别断言 `830799→.BJ`、`430047→.BJ`、`870656→.BJ`、
  `920819→.BJ`，并同时断言 `600000→.SH`、`688981→.SH`、`000001→.SZ`、`300750→.SZ` 未回归。
- 实测运行：`python3 -m pytest tests/backtest/test_st_status.py -v`，
  `test_to_ts_code_beijing_exchange` PASSED、`test_to_ts_code` PASSED。

## 随修 minor：多段 ST 区间纯单元测试

**已补上，断言正确**

证据：`tests/backtest/test_st_status.py:69-89`（`test_is_st_multiple_non_adjacent_periods`）

- 不依赖 DB：直接给 `svc._periods_cache` 赋值两段不相邻区间（2003-04-10~2003-05-11 与
  2020-06-24~2022-05-19）。
- 真断言两段内为 True（含各自起止边界日）：`000980` 在 `2003-04-10`/`2003-05-11`/
  `2020-06-24`/`2021-06-15`/`2022-05-19` 均为 `True`。
- 真断言段间与段外为 False：`2003-05-12`、`2010-01-01`（两段之间空档）以及 `2022-05-20`
  （第二段之后）均为 `False`。
- 实测运行：PASSED。

## fix diff 内有无引入新的 Critical/Important 破坏

**无**。本次 diff 只涉及 `app/services/st_status_service.py` 的 `_to_ts_code` 方法体与文档字符串、
以及 `tests/backtest/test_st_status.py` 新增两个测试用例，未触碰其他逻辑、无新依赖、无新的数据库/
网络调用。docstring 中标注"参考 `basics_sync_service.py` 的 `_generate_full_symbol`"，核对该函数
（`app/services/basics_sync_service.py:399-406`）确认前缀约定一致（8/4 开头 -> BJ），本次修复额外
补充了 920 前缀，属于更完整而非偏离约定，不构成新问题。

运行 `tests/backtest/test_st_status.py` 全量用例：9 passed, 1 failed；失败用例
`test_save_periods_upserts_each_period_by_symbol_and_start_date` 是因当前环境缺少 `pymongo`
模块导致（`ModuleNotFoundError: No module named 'pymongo'`），与本次 fix diff 无关、且该用例/代码路径
未被本次 diff 触碰，判定为环境问题而非本次改动引入的破坏。

## 总体 Verdict

**通过**
