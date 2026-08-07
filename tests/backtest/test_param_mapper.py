"""回测参数映射测试模块。"""
import pytest
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import BacktestConfig, Condition


def test_maps_payload_to_engine_args():
    """测试将前端 payload 映射到引擎参数对象（完整返回值断言）。"""
    payload = {
        "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
        "initial_capital": 100000,
        "cost": {"commission_rate": 0.00025, "min_commission": 5, "stamp_tax_rate": 0.001, "transfer_fee_rate": 0.00001},
        "position": {"parts": 3, "reduce_mode": "reduce_one"},
        "buy_rules": [{"left": "ma5", "op": "cross_up", "right": "ma20"}], "buy_logic": "AND",
        "sell_rules": [{"left": "close", "op": "<", "right": 10}], "sell_logic": "OR",
    }
    args = build_backtest_args(payload)
    cfg = args["config"]

    # 完整断言：BacktestConfig 对象
    assert isinstance(cfg, BacktestConfig)
    assert cfg.symbol == "000001"
    assert cfg.start_date == "2020-01-01"
    assert cfg.end_date == "2021-01-01"
    assert cfg.initial_capital == 100000

    # 完整断言：成本配置
    assert cfg.cost.commission_rate == 0.00025
    assert cfg.cost.min_commission == 5
    assert cfg.cost.stamp_tax_rate == 0.001
    assert cfg.cost.transfer_fee_rate == 0.00001

    # 完整断言：持仓配置
    assert cfg.position.parts == 3
    assert cfg.position.reduce_mode == "reduce_one"

    # 完整断言：买入规则
    assert len(args["buy_rules"]) == 1
    assert isinstance(args["buy_rules"][0], Condition)
    assert args["buy_rules"][0].left == "ma5"
    assert args["buy_rules"][0].op == "cross_up"
    assert args["buy_rules"][0].right == "ma20"
    assert args["buy_logic"] == "AND"

    # 完整断言：卖出规则
    assert len(args["sell_rules"]) == 1
    assert isinstance(args["sell_rules"][0], Condition)
    assert args["sell_rules"][0].left == "close"
    assert args["sell_rules"][0].op == "<"
    assert args["sell_rules"][0].right == 10
    assert args["sell_logic"] == "OR"


def test_missing_symbol():
    """测试缺少 symbol 抛出 ValueError。"""
    with pytest.raises(ValueError, match="缺少必填参数: symbol"):
        build_backtest_args({"start_date": "2020-01-01", "end_date": "2021-01-01"})


def test_missing_start_date():
    """测试缺少 start_date 抛出 ValueError。"""
    with pytest.raises(ValueError, match="缺少必填参数: start_date"):
        build_backtest_args({"symbol": "000001", "end_date": "2021-01-01"})


def test_missing_end_date():
    """测试缺少 end_date 抛出 ValueError。"""
    with pytest.raises(ValueError, match="缺少必填参数: end_date"):
        build_backtest_args({"symbol": "000001", "start_date": "2020-01-01"})


def test_bad_logic():
    """测试非法的 logic 值会抛出异常。"""
    with pytest.raises(ValueError, match="buy_logic/sell_logic 必须是 AND 或 OR"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "buy_rules": [], "buy_logic": "XOR", "sell_rules": [], "sell_logic": "AND"
        })


def test_bad_op_in_rules():
    """测试非法的 op 抛出 ValueError。"""
    with pytest.raises(ValueError, match="规则 0 非法比较符"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "buy_rules": [{"left": "ma5", "op": "invalid_op", "right": "ma20"}],
            "sell_rules": []
        })


def test_bad_reduce_mode():
    """测试非法的 reduce_mode 抛出 ValueError。"""
    with pytest.raises(ValueError, match="非法减仓模式"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "position": {"reduce_mode": "invalid_mode"},
            "buy_rules": [], "sell_rules": []
        })


def test_missing_left_in_rule():
    """测试规则缺少 left 字段抛出 ValueError。"""
    with pytest.raises(ValueError, match="规则 0 缺少字段: left"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "buy_rules": [{"op": "cross_up", "right": "ma20"}],
            "sell_rules": []
        })


def test_missing_right_in_rule():
    """测试规则缺少 right 字段抛出 ValueError。"""
    with pytest.raises(ValueError, match="规则 0 缺少字段: right"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "buy_rules": [{"left": "ma5", "op": "cross_up"}],
            "sell_rules": []
        })


def test_invalid_initial_capital():
    """测试 initial_capital 非数字时抛出 ValueError。"""
    with pytest.raises(ValueError, match="initial_capital 必须是数字"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "initial_capital": "abc",
            "buy_rules": [], "sell_rules": []
        })


def test_invalid_parts():
    """测试 parts 非整数时抛出 ValueError。"""
    with pytest.raises(ValueError, match="parts 必须是整数"):
        build_backtest_args({
            "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
            "position": {"parts": "invalid"},
            "buy_rules": [], "sell_rules": []
        })


def test_default_values():
    """测试默认值是否正确应用。"""
    payload = {
        "symbol": "000001",
        "start_date": "2020-01-01",
        "end_date": "2021-01-01",
    }
    args = build_backtest_args(payload)
    cfg = args["config"]

    # 断言默认值
    assert cfg.initial_capital == 100000
    assert cfg.cost.commission_rate == 0.00025
    assert cfg.cost.min_commission == 5.0
    assert cfg.cost.stamp_tax_rate == 0.001
    assert cfg.cost.transfer_fee_rate == 0.00001
    assert cfg.position.parts == 3
    assert cfg.position.reduce_mode == "reduce_one"
    assert args["buy_logic"] == "AND"
    assert args["sell_logic"] == "OR"
    assert args["buy_rules"] == []
    assert args["sell_rules"] == []


def test_clear_all_reduce_mode():
    """测试 clear_all 减仓模式被正确接受。"""
    payload = {
        "symbol": "000001", "start_date": "2020-01-01", "end_date": "2021-01-01",
        "position": {"reduce_mode": "clear_all"},
        "buy_rules": [], "sell_rules": []
    }
    args = build_backtest_args(payload)
    assert args["config"].position.reduce_mode == "clear_all"
