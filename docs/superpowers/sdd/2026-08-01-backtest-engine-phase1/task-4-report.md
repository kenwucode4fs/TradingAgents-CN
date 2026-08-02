# Task 4 Report: A股规则 `market_rules.py`

## 状态
✅ **完成 + 评审修复**

## Commits
1. **初始提交**: `b18beb1` — feat(backtest): A股板块/涨跌停/成本规则
2. **评审修复**: `4a801a4` — fix(backtest): 修复涨跌停价精度和板块判定

## 测试摘要
5 passed in 0.64s（全部通过）：
- `test_board_of`: 板块判定（主板/创业板/科创板/北交所 + B股 900xxx 验证）
- `test_price_limit_pct`: 涨跌幅限制（对称分支完整覆盖：ST/非ST）
- `test_limit_price_and_tradability`: 涨跌停价与开盘可交易性
- `test_float_precision_in_limit_price`: 浮点精度（Decimal 四舍五入边界测试）
- `test_costs`: 交易成本计算（买入/卖出）

## 实现概览
模块 `tradingagents/backtest/market_rules.py`（~200 行），提供纯函数 API：

| 函数 | 功能 |
|------|------|
| `board_of(symbol)` | 判定板块（返回 `Literal['main','gem','star','bse']`）|
| `price_limit_pct(symbol, is_st)` | 涨跌幅限制百分比 |
| `limit_up_price(pre_close, symbol, is_st)` | 涨停价（Decimal 精确计算）|
| `limit_down_price(pre_close, symbol, is_st)` | 跌停价（Decimal 精确计算）|
| `can_buy_at_open(open_price, pre_close, symbol, is_st)` | 开盘可买判定 |
| `can_sell_at_open(open_price, pre_close, symbol, is_st)` | 开盘可卖判定 |
| `buy_cost(amount, cost)` | 买入成本（佣金/0/过户费） |
| `sell_cost(amount, cost)` | 卖出成本（佣金/印花税/过户费） |

## 评审修复详情

### 1. Important - 浮点精度（已修复）
**问题**: `round(0.95*1.1, 2)` = 1.04，应为 1.045 → 1.05（交易所规则）  
**解决**: 改用 `Decimal(str(x)) * (Decimal("1") + Decimal(str(pct))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`  
**测试**: 新增 `test_float_precision_in_limit_price` 覆盖 0.95/0.97/0.99 等边界价位

### 2. M2 - 板块判定（已修复）
**问题**: B股 900xxx 被误判为北交所（因 startswith("9")）  
**解决**: 精确化北交所前缀为 "8"、"920"、"43"/"83"/"87"，移除裸 "9"  
**测试**: 新增断言 900001/900950 == "main"（B股不误判）

### 3. M3 - 对称分支（已补充）
**补充**: price_limit_pct 补测试覆盖：
- 创业板 ST 和非 ST（都 20%）
- 科创板 ST 和非 ST（都 20%）
- 北交所 ST 和非 ST（都 30%）

## 质量保证
- ✅ Python 3.10+ 兼容（Python 3.11 环境验证）
- ✅ 注释/Docstring 全中文
- ✅ 仅依赖 `tradingagents/backtest/types.py` 中的 `CostConfig`
- ✅ 测试位置正确（`tests/backtest/`）
- ✅ TDD 流程严格执行（失败→实现→通过→提交）
- ✅ 所有公共函数已注解返回类型（Literal 用于字符串枚举）

## 测试命令与输出

```bash
$ ./venv/bin/python -m pytest tests/backtest/test_market_rules.py -v
============================= test session starts ==============================
platform darwin -- Python 3.11.15, pytest-9.1.1, pluggy-1.6.0 -- /Users/kanewu/Projects/TradingAgents-CN/venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/kanewu/Projects/TradingAgents-CN/tests
configfile: pytest.ini
plugins: asyncio-1.4.0, langsmith-0.7.30, anyio-1.4.0, langsmith-0.7.30, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None
collecting ... collected 5 items

tests/backtest/test_market_rules.py::test_board_of PASSED                [ 20%]
tests/backtest/test_market_rules.py::test_price_limit_pct PASSED         [ 40%]
tests/backtest/test_market_rules.py::test_limit_price_and_tradability PASSED [ 60%]
tests/backtest/test_market_rules.py::test_float_precision_in_limit_price PASSED [ 80%]
tests/backtest/test_market_rules.py::test_costs PASSED                   [100%]

=============================== warnings summary ===============================
tradingagents/config/__init__.py:5
  /Users/kanewu/Projects/TradingAgents-CN/tradingagents/config/__init__.py:5: DeprecationWarning: ConfigManager is deprecated
    from .config_manager import config_manager, token_tracker, ModelConfig, PricingConfig, UsageRecord

============================= 5 passed in 0.64s =========================
```
