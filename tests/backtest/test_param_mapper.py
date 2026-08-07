"""回测参数映射测试模块。"""
from app.services.backtest_param_mapper import build_backtest_args
from tradingagents.backtest import BacktestConfig, Condition


def test_maps_payload_to_engine_args():
    """测试将前端 payload 映射到引擎参数对象。"""
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
    assert isinstance(cfg, BacktestConfig)
    assert cfg.symbol == "000001" and cfg.position.parts == 3
    assert cfg.cost.stamp_tax_rate == 0.001
    assert args["buy_rules"][0].left == "ma5" and args["buy_rules"][0].op == "cross_up"
    assert args["buy_logic"] == "AND" and args["sell_logic"] == "OR"


def test_rejects_bad_logic():
    """测试非法的 logic 值会抛出异常。"""
    import pytest
    with pytest.raises(ValueError):
        build_backtest_args({"symbol":"000001","start_date":"2020-01-01","end_date":"2021-01-01",
                             "buy_rules":[], "buy_logic":"XOR", "sell_rules":[], "sell_logic":"AND"})
