# 全量A股历史数据同步任务 —— 实现报告

## 新增/改动文件

- `app/worker/tushare_sync_service.py`（改动）
  - 新增 `TushareSyncService._get_all_a_share_symbols()`：从 `sync_historical_data` 里抽出的全A股（排除退市）过滤逻辑，供两处复用。
  - `sync_historical_data` 中 `symbols is None` 分支改为调用 `_get_all_a_share_symbols()`（行为不变，纯重构）。
  - 新增 `TushareSyncService.sync_all_qfq(symbols=None, rate_limit_per_min=120, resume=True, job_id=None)`：批量补全前复权价，限流+断点续传+错误隔离，返回 `{total, done, failed, skipped}`。
  - 新增顶层 `run_full_a_share_sync(incremental=False, qfq_rate_limit_per_min=120)`：编排入口，先 `sync_historical_data` 再 `sync_all_qfq`。
  - `import` 增加 `RateLimiter`（`app.core.rate_limiter`）。
- `app/core/config.py`（改动）：新增 3 个 Settings 字段：
  - `TUSHARE_FULL_A_SHARE_SYNC_ENABLED`（默认 `False`）
  - `TUSHARE_FULL_A_SHARE_SYNC_CRON`（默认 `"0 18 * * 1-5"`，工作日18点）
  - `TUSHARE_FULL_A_SHARE_SYNC_QFQ_RATE_LIMIT_PER_MIN`（默认 `120`）
- `app/main.py`（改动）：import `run_full_a_share_sync`；在调度器启动流程中紧跟 `tushare_historical_sync` 之后注册 `tushare_full_a_share_sync` job（`kwargs={"incremental": True, "qfq_rate_limit_per_min": ...}`），遵循仓库既有的“先 add_job 再按 settings 开关决定是否 pause_job”模式。
- `tests/backtest/test_full_a_share_sync.py`（新增）：3 只真实股票（000001/600000/300750）的小批量集成测试，`@pytest.mark.integration`。

## 限流实现

复用仓库已有的 `app.core.rate_limiter.RateLimiter`（滑动窗口，内部用 `asyncio.sleep` 等待），而不是自建实现：

```python
limiter = RateLimiter(max_calls=max(1, rate_limit_per_min), time_window=60.0, name="sync_all_qfq")
...
await limiter.acquire()   # 每只股票调用一次 sync_historical_qfq 前
await self.sync_historical_qfq(symbol, start_date, end_date)
```

`rate_limit_per_min` 默认 120（对应 2000 积分账号保守限流，约 2 次/秒）。`RateLimiter` 用时间戳队列判断当前 60 秒窗口内调用次数是否超限，超限时 `await asyncio.sleep(wait_time)`，与要求的“调用间 sleep 实现”一致，只是复用了已有的滑动窗口而非固定间隔 sleep（更精确，不会因为个别慢请求把整体节奏拖垮）。

## 断点续传实现

- 新增 MongoDB collection `sync_progress`，唯一索引 `(task, symbol)`。
- 每只股票同步字段：`task="sync_all_qfq"`、`symbol`、`status`（`done`/`failed`）、`error`、`updated_at`。
- `resume=True`（默认）时，先查出 `status=="done"` 的股票集合，遍历时直接 `stats["skipped"] += 1` 跳过。
- 成功/失败都用 `update_one(..., upsert=True)` 写回 `sync_progress`，中途进程崩溃后重新调用同一批 `symbols` + `resume=True` 即可从断点继续。

## 错误隔离实现

`sync_historical_qfq` 的调用包在 `try/except Exception` 里：单只失败只 `logger.error` + 写入 `sync_progress(status="failed", error=str(e))` + `stats["failed"] += 1`，不 `raise`，循环继续处理下一只股票。写 `sync_progress` 失败本身也被单独 try/except 包住，避免"记录失败状态"这个动作本身的异常污染主循环。

## 小批量集成测试实际运行输出

```
tests/backtest/test_full_a_share_sync.py::test_sync_all_qfq_small_batch_writes_and_resumes PASSED

关键日志摘录：
✅ 000001 前复权价合并完成: 5841/5841 条记录已更新
✅ 000001 前复权价同步完成: 5841/6000 条记录已更新
✅ 600000 前复权价合并完成: 624/5886 条记录已更新
✅ 600000 前复权价同步完成: 624/6000 条记录已更新
✅ 300750 前复权价合并完成: 624/1976 条记录已更新
✅ 300750 前复权价同步完成: 624/1976 条记录已更新
📈 前复权价同步进度: 已完成 3/3 (成功: 3, 失败: 0, 跳过: 0)
✅ 前复权价批量同步完成: 总计 3, 成功 3, 失败 0, 跳过 0
（第二轮）
⏭️ 断点续传：检测到 3 只股票已完成，本轮将跳过
✅ 前复权价批量同步完成: 总计 3, 成功 0, 失败 0, 跳过 3

1 passed in 23.45s
```

断言全部通过：
1. `stock_daily_quotes` 中 000001/600000/300750 均查到 `close_qfq`/`open_qfq`/`high_qfq`/`low_qfq` 非空的记录；
2. `sync_progress` 中三只均 `status=="done"`、`error is None`；
3. 第二轮 `resume=True` 重跑，`skipped==3`、`done==0`、`failed==0`（断点续传生效）。

另外验证不回归：`tests/backtest/test_qfq_sync.py -m integration`（含原有的 `sync_historical_qfq` 单只集成测试）2 passed；`tests/backtest`全量（不含 integration）86 passed。

## 如何启动全量同步（手动，1-2小时，本次未执行）

```bash
./venv/bin/python -c "
import asyncio
from app.core import database as db_module
from app.worker.tushare_sync_service import run_full_a_share_sync

async def main():
    await db_module.db_manager.init_mongodb()
    db_module.mongo_client = db_module.db_manager.mongo_client
    db_module.mongo_db = db_module.db_manager.mongo_db
    result = await run_full_a_share_sync(incremental=False)
    print(result)

asyncio.run(main())
"
```

也可以只跑前复权价阶段（若原始日线已经全量同步过，只想补/重算复权价）：

```python
from app.worker.tushare_sync_service import get_tushare_sync_service
svc = await get_tushare_sync_service()
await svc.sync_all_qfq(rate_limit_per_min=120, resume=True)
```

中途中断后，直接重新执行同一条命令即可利用 `sync_progress` 续传（`sync_historical_data` 阶段本身也是按"每只股票最后日期"增量的，天然支持续传；`sync_all_qfq` 阶段靠 `sync_progress` 续传）。

## Scheduler 接入说明

- 已在 `app/main.py` 的 `initialize_scheduler`（调度器启动流程）里注册 job `id="tushare_full_a_share_sync"`，紧跟在 `tushare_historical_sync` 之后，CronTrigger 用 `settings.TUSHARE_FULL_A_SHARE_SYNC_CRON`（默认 `0 18 * * 1-5`，工作日18点收盘后），`kwargs={"incremental": True, "qfq_rate_limit_per_min": settings.TUSHARE_FULL_A_SHARE_SYNC_QFQ_RATE_LIMIT_PER_MIN}`。
- **默认是 paused 状态**（`TUSHARE_FULL_A_SHARE_SYNC_ENABLED=False`），与仓库里其它 Tushare/AKShare/BaoStock 任务的"先 add_job 再按开关 pause"模式一致 —— job 存在于调度器里（`GET /api/scheduler/jobs` 能看到），但不会自动触发，需要在 `.env` 里设置 `TUSHARE_FULL_A_SHARE_SYNC_ENABLED=true` 或通过调度器管理 API `resume_job("tushare_full_a_share_sync")` 手动启用。
- 之所以默认关闭：`run_full_a_share_sync(incremental=True)` 内部会在跑 `sync_all_qfq` 前**清空 `sync_progress` 里 `task=="sync_all_qfq"` 的记录**，让当天的前复权价对全市场重新计算一遍（原因见下面 concern），这意味着每天这个任务都要重新遍历全市场几千只股票，实际耗时接近"全量"级别，不是真正意义上的"轻量增量"，需要用户确认可以接受这个日常开销后再开启。

## Tushare 2000 积分下的预估耗时

- 2000 积分档：`TushareRateLimiter(standard)` 配置为 320 次/60秒（含 0.8 安全边际），但任务书要求保守限流 120 次/分钟，已作为 `sync_all_qfq` 默认值。
- 全市场A股约 5000+ 只股票（不含退市）：
  - `sync_historical_data(all_history=True)`：受 `TushareRateLimiter` 本身节流（约 320次/分钟），5000 只约 15-20 分钟量级（数据量越大单只越慢，实测 3 只/批约 2.5秒/只，含API+落库）。
  - `sync_all_qfq()`：按 `rate_limit_per_min=120` 限流，5000 只理论下限 5000/120 ≈ 42 分钟，加上单只 API 响应耗时（实测 000001 这种老股票全历史 qfq 一次调用约 5 秒，因为 `TushareAdapter.get_kline(limit=99999)` 一次性拉全部历史再本地过滤），实际更接近 **50-70 分钟**。
  - 两阶段合计 **约 1-1.5 小时**，与任务书预估的 1-2 小时量级一致。

## Concern（需要用户/后续开发关注）

1. **`sync_all_qfq` 的 resume 语义是"本轮内跳过已完成"，不是"永久跳过"**：前复权价会因除权除息事件被"回溯改写"（不是只追加最新一天），所以不能像原始日线那样用"最后日期+1天"做真正的增量。`run_full_a_share_sync(incremental=True)` 目前的做法是每天先清空 `sync_progress` 里 `task=="sync_all_qfq"` 的记录再全量重算一遍前复权价——这保证了正确性，但代价是"daily 增量"任务实际开销接近全量级别（见上面耗时预估），并不轻量。如果这个开销不可接受，需要后续优化：例如只对最近 N 个交易日重新计算前复权价（用 `sync_historical_qfq(symbol, start_date=近期, end_date=今天)` 而不是 1990-01-01 起始），代价是历史深处的复权价可能不会在日常任务里被刷新（需要定期跑一次全量 `incremental=False` 校正）。本次实现选择了"正确性优先、默认关闭"的保守方案，把决策权交给用户。
2. **`TushareAdapter.get_kline` 不支持按起止日期查询，只有 `limit` 参数**（`sync_historical_qfq` 文档字符串里已注明）：每次同步某只股票的前复权价，无论目标区间多短，都要拉取该股票近乎全部历史（`limit=99999`）再本地过滤。这是继承自现有代码的既有限制，不是本次新增的问题，但直接导致上面第1点的"daily 全量重算"开销无法通过缩小 `start_date/end_date` 来降低——除非同时改造 `sync_historical_qfq` 本身按需截断。
3. **`sync_progress` 集合目前只服务 `sync_all_qfq`（`task` 字段固定该值）**：如果未来还有其它任务想复用断点续传机制，直接按 `task` 区分即可，集合结构已经预留了这个字段。
4. 全量首次 backfill（`incremental=False`）**本次未执行**，按要求留给用户后续手动触发；已提供好可直接复制运行的命令（见上）。
