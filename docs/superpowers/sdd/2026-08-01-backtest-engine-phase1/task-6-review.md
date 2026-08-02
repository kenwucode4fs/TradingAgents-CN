# Task 6 评审：逐日技术指标序列 `indicators.py`

## 结论

- **Spec 合规**：✅
- **代码质量**：2 问题（Important x1, Minor x1）

## 依据

### Spec 合规 ✅

- `compute_indicators(bars)` 返回全部 15 个键：`ma5/10/20/60、ema12/26、macd_dif/dea/bar、rsi6/12/14、boll_up/mid/low`（`tradingagents/backtest/indicators.py:29-56`），测试 `test_all_keys_present` 逐一断言存在。
- 所有序列均由等长的 `close` Series 派生，`list` 转换保持长度不变，`test_lengths_aligned` 对全部 15 个键做了断言，可靠。
- 首段不足窗口置 `None`：MA/BOLL/RSI 由 `rolling(n)` 产生前段 NaN → 转 None，`test_ma5`/`test_ma10`/`test_boll_structure` 用手算值真断言（如 `ma5[4]==3.0`），非空断言。EMA/MACD 因 `ewm(adjust=False)` 从第一个观测值即可计算，不产生前段 None——这与 brief Step 3 参考实现行为一致，非缺陷。
- MA5/MA10 与 BOLL 三线关系测试为真实数值/关系断言；EMA、MACD、RSI 的测试仅验证长度/类型/键存在，未做手算数值断言（见"代码质量"Minor 项）。
- 未 `import app/`，文件位置正确（`tradingagents/backtest/indicators.py`、`tests/backtest/test_bt_indicators.py`）。

### 指标公式核对

- **MA**：`close.rolling(n).mean()`，简单移动平均，正确。
- **EMA**：`close.ewm(span=n, adjust=False).mean()`，正确。
- **MACD**：`dif=ema12-ema26`，`dea=dif.ewm(span=9, adjust=False).mean()`，`bar=(dif-dea)*2`（国内 ×2 惯例），正确。
- **BOLL**：中轨 = 20 日 `rolling().mean()`，上下轨 = 中轨 ± 2×`rolling().std()`（pandas 默认 `ddof=1` 样本标准差）。与 brief Step 3 参考实现完全一致，判定合规（⚠️ 若业务预期是总体标准差 `ddof=0`，需与 brief 作者确认，diff 本身无法判断"预期"是哪种）。
- **RSI**（Important，见下）：分母为 0 时未产生 inf/崩溃，但产生了偏离经典公式的结果。
- **前视偏差**：未发现。所有计算均基于 `rolling`/`ewm` 默认因果窗口，无 `shift(-1)` 等逆向偏移，指标第 i 位只使用第 i 位及之前数据。
- **NaN → None**：统一在最终字典推导式中对所有键生效（`indicators.py:62`），可靠。

## 问题清单

### Important

1. **RSI 零损失分母场景返回 `None` 而非正确值 100，导致强势行情下指标缺失。** `_rsi()` 中 `rs = gain / loss.replace(0, pd.NA)`（`indicators.py:19`）：当窗口内无下跌日（loss=0）时，经典公式应有 RS→∞ ⇒ RSI=100，但当前实现把分母替换为 `pd.NA`，最终 NaN→None。已用连续上涨序列 `range(1,21)` 实测验证：`rsi14`、`rsi6` 全部为 `None`（本应在窗口填满后为 100）。此为真实市场常见场景（连续上涨/涨停行情），并非纯理论边界。测试 `test_rsi_basic`/`test_rsi_no_nan` 均未对此断言（后者的 docstring 声称"测试 RSI 不产生 NaN"，但实际未断言非 None/非 NaN，未能捕获此问题）。注：该写法与 brief Step 3 给出的参考实现完全一致，缺陷源头在 brief 示例代码本身，但复核标准要求核实公式正确性，故仍需在此指出。

### Minor

1. **EMA/MACD/RSI 的测试未做手算数值断言，只验证长度/类型/键存在。** `TestEMA.test_ema12_length`、`TestMACD.test_macd_keys`、`TestRSI.test_rsi_basic`/`test_rsi_no_nan`（`tests/backtest/test_bt_indicators.py:83-141`）均未像 `test_ma5`/`test_ma10`/`test_boll_structure` 那样验证具体计算值，无法仅凭测试本身证伪公式错误（上述 RSI 问题即是测试盲区导致未被发现）。
