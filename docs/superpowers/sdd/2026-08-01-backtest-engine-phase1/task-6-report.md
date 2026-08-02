# Task 6 完成报告：逐日指标 indicators.py

## 状态
✅ 完成（含评审修复）

## 提交历史
- **初始**: `c361a7c` - `feat(backtest): 逐日技术指标序列`
- **修复**: `4f63973` - `fix(backtest): RSI 全涨全跌极值处理和扩充手算值测试`

## 修复内容（评审反馈）

### Important: RSI 极值处理
**问题**: 连续上涨时返回 None，应为 100（极端超买）
**根因**: `loss.replace(0, pd.NA)` 导致除零避免但结果为 NA
**修复**: 改用 `rsi.where(loss != 0, 100.0)` 分别处理：
- loss==0(全涨) → RSI=100
- gain==0(全跌) → RSI=0（已正确）
- 窗口不足 → RSI=None（通过 `rsi.mask(loss.isna())` 保证）

### Minor: 手算值测试补充
- EMA 常数序列验证：所有值收敛到常数
- MACD 常数序列验证：DIF/DEA/BAR 都收敛到 0
- MACD 结构验证：bar = (dif - dea) * 2 的数学关系
- RSI 连续上涨/下跌：窗口填满后精确为 100/0

## 测试摘要
```bash
$ ./venv/bin/python -m pytest tests/backtest/test_bt_indicators.py -v
```

```
======================== test session starts ========================
tests/backtest/test_bt_indicators.py::TestMA::test_ma5 PASSED            [  6%]
tests/backtest/test_bt_indicators.py::TestMA::test_ma10 PASSED           [ 13%]
tests/backtest/test_bt_indicators.py::TestEMA::test_ema12_length PASSED  [ 20%]
tests/backtest/test_bt_indicators.py::TestEMA::test_ema_constant_series PASSED [ 26%]
tests/backtest/test_bt_indicators.py::TestMACD::test_macd_keys PASSED    [ 33%]
tests/backtest/test_bt_indicators.py::TestMACD::test_macd_constant_series PASSED [ 40%]
tests/backtest/test_bt_indicators.py::TestMACD::test_macd_bar_structure PASSED [ 46%]
tests/backtest/test_bt_indicators.py::TestRSI::test_rsi_continuous_rise PASSED [ 53%]
tests/backtest/test_bt_indicators.py::TestRSI::test_rsi_continuous_decline PASSED [ 60%]
tests/backtest/test_bt_indicators.py::TestRSI::test_rsi_window_insufficient PASSED [ 66%]
tests/backtest/test_bt_indicators.py::TestRSI::test_rsi_basic PASSED     [ 73%]
tests/backtest/test_bt_indicators.py::TestBoll::test_boll_structure PASSED [ 80%]
tests/backtest/test_bt_indicators.py::TestComputeIndicators::test_all_keys_present PASSED [ 86%]
tests/backtest/test_bt_indicators.py::TestComputeIndicators::test_lengths_aligned PASSED [ 93%]
tests/backtest/test_bt_indicators.py::TestComputeIndicators::test_return_type PASSED [100%]

======================== 15 passed, 1 warning in 1.04s =========================
```

## 实现细节
1. **RSI 全新逻辑**：
   ```python
   rs = gain / loss                     # inf 或 nan
   rsi = 100 - 100 / (1 + rs)           # 自动处理 inf → 100
   rsi = rsi.where(loss != 0, 100.0)    # loss=0 显式设为 100
   rsi = rsi.mask(loss.isna())          # 窗口不足保持 NaN
   ```

2. **关键差异**：diff() 产生首个 NaN，rolling(n) 需要 n 个非 NaN 值，故首个有效位置在 n+1 处

3. **键齐全验证**: 15 个指标键全覆盖（ma5/10/20/60, ema12/26, macd_dif/dea/bar, rsi6/12/14, boll_up/mid/low）

4. **等长对齐**: 所有序列与 bars 长度一致，首段不足窗口填 None

## 无遗留 concern
- RSI 极值处理已验证（连涨/连跌/窗口不足）
- 手算值测试覆盖所有指标类别
- 与既有代码无冲突
