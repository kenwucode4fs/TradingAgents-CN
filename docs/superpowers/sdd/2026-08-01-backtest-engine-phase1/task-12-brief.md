### Task 12: 真实数据冒烟（可选，需容器）

**Files:**
- Test: `tests/backtest/test_smoke_real.py`

- [ ] **Step 1: 写冒烟测试**（用库里已有的 000001，需先跑 Task 1 复权同步）

```python
# tests/backtest/test_smoke_real.py
import pytest
@pytest.mark.integration
def test_real_000001_double_ma():
    from tradingagents.backtest import run_backtest, BacktestConfig, Condition
    cfg = BacktestConfig(symbol="000001", start_date="2023-01-01", end_date="2024-12-31")
    res = run_backtest(
        cfg,
        buy_rules=[Condition("ma5", "cross_up", "ma20")], buy_logic="AND",
        sell_rules=[Condition("ma5", "cross_down", "ma20")], sell_logic="AND",
    )
    d = res.to_dict()
    assert len(d["equity_curve"]) > 100
    print("总收益:", d["metrics"]["total_return"], "基准:", d["metrics"]["benchmark_return"])
```

- [ ] **Step 2: 跑冒烟（确认端到端接库跑通）**

Run: `./venv/bin/python -m pytest tests/backtest/test_smoke_real.py -v -m integration -s`
Expected: PASS，打印出总收益与基准收益

- [ ] **Step 3: 提交**

```bash
git add tests/backtest/test_smoke_real.py
git commit -m "test(backtest): 真实数据端到端冒烟"
```

---

## Self-Review（作者自查记录）

- **Spec 覆盖**：数据层(复权/ST)→Task1-2、data_feed→Task5；策略条件积木/SignalSource→Task7；固定份数分批/减仓模式→Task8；T+1/停牌/精确涨跌停/成本→Task4+Task8+Task9；绩效+基准→Task10；结果序列化→Task11。Web 接入不在本计划（Plan 2）。✅
- **占位符**：无 "TBD/add error handling" 等；各步给了真实测试与实现代码。✅
- **类型一致**：`Action/Bar/Trade/CostConfig/PositionConfig/BacktestConfig` 在 Task3 定义，后续 Task 一致引用；`try_buy_one_part/try_sell/in_position/market_value`、`compute_indicators`、`RuleStrategy(...)`、`run_loop`、`compute_metrics`、`run_backtest` 签名前后一致。✅
- **已知取舍**：Task9 顺延逻辑较微妙，Step4 专门修正并加涨停顺延测试；涨跌停"一字板"以开盘价触板近似（日线数据下无法知盘中）。

## 后续（Plan 2 预告：Web 接入）

- `app/routers/backtest.py`（`POST /api/backtest/run`，异步任务）、`app/services/backtest_service.py`（调 `run_backtest`）、`frontend/src/views/Backtest/`（条件积木编辑器 + 净值曲线图 + 指标卡 + 交易明细表）。
