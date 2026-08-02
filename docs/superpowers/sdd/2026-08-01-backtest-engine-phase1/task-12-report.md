# Task 12 报告：真实数据端到端冒烟

## 区间选择

Brief 建议的 2023-01-01~2024-12-31 在当前库里没有数据（容器内的 tushare 数据是围绕
"当前日期" 2026-08-02 同步的，历史深度有限）。先查库确认 000001 在
`stock_daily_quotes`（`data_source=tushare, period=daily`）里 `close_qfq` 等前复权字段
非空的实际范围：

```bash
docker exec tradingagents-mongodb mongo -u admin -p tradingagents123 \
  --authenticationDatabase admin tradingagents --quiet --eval '
var min = db.stock_daily_quotes.find({symbol:"000001", data_source:"tushare", period:"daily", close_qfq:{$ne:null}}).sort({trade_date:1}).limit(1).toArray();
var max = db.stock_daily_quotes.find({symbol:"000001", data_source:"tushare", period:"daily", close_qfq:{$ne:null}}).sort({trade_date:-1}).limit(1).toArray();
var count = db.stock_daily_quotes.count({symbol:"000001", data_source:"tushare", period:"daily", close_qfq:{$ne:null}});
printjson({min:min, max:max, count:count});
'
```

结果：最早 `2026-01-05`，最晚 `2026-07-31`，共 **139** 条前复权记录；进一步核对
`2026-01-01~2026-07-31` 区间内总记录数与 `close_qfq` 非空记录数均为 139，无缺口。
这批数据是 Task 1（`TushareSyncService.sync_historical_qfq`）此前跑集成测试
（`tests/backtest/test_qfq_sync.py::test_sync_qfq_writes_fields`，同步范围
`20260101~20260731`）时已经写入的，**本任务无需再跑一次复权同步**，直接把回测区间
定在 `2026-01-01~2026-07-31`。

## 冒烟测试

新增 `tests/backtest/test_smoke_real.py::test_real_000001_double_ma`（`@pytest.mark.integration`）：
用 000001 + 双均线（MA5 上穿 MA20 买 / 下穿卖）跑 `run_backtest(bars=None)`，
断言 `equity_curve` 长度 > 100，`metrics` 含 `total_return` 与 `benchmark_return`，
并 print 出总收益与基准收益。

### 一个需要绕开的坑：跨事件循环

`run_backtest(bars=None)` 是同步函数，内部由 `data_feed.load_bars` 自己
`asyncio.run(...)` 发起查询——真正执行 MongoDB 查询的事件循环，是
`run_backtest` 被调用那一刻才新建、调用结束就关闭的那个循环。

若照抄 `test_qfq_sync.py`/`test_st_status.py` 里"先 `asyncio.run(db_manager.init_mongodb())`
建连接、再另起一个 `asyncio.run` 做查询"的两段式写法，会在 `init_mongodb()` 里的
`await mongo_client.admin.command("ping")` 这一步把 motor 的 `AsyncIOMotorClient`
实际绑定到"建连接"用的那个事件循环上；等这个 `asyncio.run` 返回、循环被关闭后，
`load_bars` 内部另开的新循环再复用同一个 client 发请求，就会报
`RuntimeError: Event loop is closed`（本测试最初就是这样失败的，见下方"排错过程"）。

解决办法：测试里只构造 `AsyncIOMotorClient`（构造本身不需要运行中的事件循环，不
触发网络 I/O）并挂到 `db_manager`/`app.core.database` 的全局变量上，不在测试里主动
ping；client 与运行中事件循环的绑定，留到 `load_bars` 内部那唯一一次 `asyncio.run`
里首次真正查询时才发生，保证"建连接"和"用连接"在同一个事件循环里。

## 运行命令与输出

```bash
./venv/bin/python -m pytest tests/backtest/test_smoke_real.py -v -m integration -s
```

关键输出：

```
tests/backtest/test_smoke_real.py::test_real_000001_double_ma
...
| app.services.historical_data_service | INFO | 📊 查询历史数据: 000001 返回 139 条记录
总收益: 0.0015403999999998863 基准: 0.0449236298292901
PASSED

======================== 1 passed, 1 warning in 1.19s ========================
```

**总收益 ≈ 0.154%，基准收益 ≈ 4.49%**（区间 2026-01-01~2026-07-31，000001，双均线策略
仅触发极少次交易，跑输了买入持有基准——这本身也符合双均线在这段单边上涨行情里
"少交易、错过大部分涨幅"的直觉，不是 bug）。

另外跑了一遍非集成测试作为回归确认，未受影响：

```bash
./venv/bin/python -m pytest tests/backtest/ -q -m "not integration"
# 77 passed, 4 deselected, 1 warning in 2.15s
```

## 排错过程（简述）

1. 第一次直接调用 `run_backtest`（未初始化 db）：`RuntimeError: MongoDB客户端未初始化`。
2. 仿照其余集成测试用 `asyncio.run(db_manager.init_mongodb())` 先建连接：
   变成 `无历史数据：000001 2026-01-01~2026-07-31，请先同步`，日志显示真实原因是
   `❌ 查询历史数据失败 000001: Event loop is closed`（`get_historical_data` 内部
   吞掉异常返回空列表，`load_bars` 据此误判为"库里没数据"）。
3. 改为只构造 `AsyncIOMotorClient` 不主动 ping，让 `load_bars` 内部唯一一次
   `asyncio.run` 完成"建连接+查询"，问题解决，139 条记录被正确读出。

## 提交

- commit: `d7860dd` — `test(backtest): 真实数据端到端冒烟`
- 仅 `git add tests/backtest/test_smoke_real.py`（工作区另有与本任务无关的
  `docker-compose*.yml`/`tradingagents/default_config.py` 改动，未触碰、未提交）。
