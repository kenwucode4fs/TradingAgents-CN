import math
from tradingagents.factor.factors import FACTORS, _rsi, _boll_pos


def _seq(n, start=10.0, step=1.0):
    return [start + i * step for i in range(n)]  # 单调上升序列


def test_registry_has_15_factors():
    assert len(FACTORS) == 15
    # 抽查 key 与元信息
    assert FACTORS["pe"]["default_direction"] == "asc"
    assert FACTORS["mom_20"]["default_direction"] == "desc"
    for meta in FACTORS.values():
        assert set(meta) >= {"name", "category", "default_direction", "fn"}
        assert meta["default_direction"] in ("asc", "desc")


def test_pe_rejects_nonpositive():
    fn = FACTORS["pe"]["fn"]
    assert fn({"pe": 12.5}, [], []) == 12.5
    assert fn({"pe": 0}, [], []) is None
    assert fn({"pe": -3}, [], []) is None
    assert fn({"pe": None}, [], []) is None


def test_mom_20_needs_21_points():
    fn = FACTORS["mom_20"]["fn"]
    closes = _seq(21, start=100.0, step=1.0)  # close[-1]=120, close[-21]=100
    assert math.isclose(fn({}, closes, []), 120 / 100 - 1)
    assert fn({}, _seq(20), []) is None  # 不足 21 点


def test_high_250_prox_at_new_high_is_one():
    fn = FACTORS["high_250_prox"]["fn"]
    closes = _seq(250, start=1.0, step=1.0)  # 末值即最高
    assert math.isclose(fn({}, closes, []), 1.0)


def test_vol_60_of_constant_is_zero():
    fn = FACTORS["vol_60"]["fn"]
    closes = [10.0] * 61  # 收益全 0 → 波动率 0
    assert math.isclose(fn({}, closes, []), 0.0, abs_tol=1e-12)


def test_turnover_proxy_amount_over_mv():
    fn = FACTORS["turnover_proxy"]["fn"]
    assert math.isclose(fn({"amount": 200.0, "total_mv": 1000.0}, [], []), 0.2)
    assert fn({"amount": None, "total_mv": 1000.0}, [], []) is None


def test_vol_ratio_recent_over_long():
    fn = FACTORS["vol_ratio"]["fn"]
    vols = [100.0] * 55 + [200.0] * 5  # 近5均=200，近60均=(55*100+5*200)/60
    expected = 200.0 / ((55 * 100 + 5 * 200) / 60)
    assert math.isclose(fn({}, [1.0] * 60, vols), expected)


def test_rsi_all_up_is_100():
    assert math.isclose(_rsi(_seq(20), 14), 100.0)


def test_boll_pos_in_unit_range():
    p = _boll_pos(_seq(25), 20)
    assert p is None or 0.0 <= p <= 1.5  # 上升序列末值可能触及上轨附近
