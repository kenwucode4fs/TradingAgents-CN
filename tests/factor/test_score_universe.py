import pytest
from tradingagents.factor import score_universe


def _stock(code, pe, closes):
    return {"code": code, "name": code, "industry": "银行",
            "cross": {"pe": pe}, "closes": closes, "volumes": [1.0] * len(closes)}


def test_score_universe_ranks_by_weighted_percentile():
    # 单因子 pe(asc,越小越好)：pe 越小 score 越高
    stocks = [_stock("A", 30, [1.0]), _stock("B", 10, [1.0]), _stock("C", 20, [1.0])]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    top = score_universe(stocks, cfg, top_n=3)
    assert [x["code"] for x in top] == ["B", "C", "A"]  # pe 10<20<30
    assert top[0]["rank"] == 1
    assert top[0]["factors"]["pe"]["value"] == 10


def test_missing_factor_excludes_stock():
    # C 的 pe 非法(<=0) → 缺失 → 被剔除，不出现在榜单
    stocks = [_stock("A", 30, [1.0]), _stock("B", 10, [1.0]), _stock("C", -1, [1.0])]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    codes = [x["code"] for x in score_universe(stocks, cfg, top_n=10)]
    assert "C" not in codes and set(codes) == {"A", "B"}


def test_topn_truncates():
    stocks = [_stock(c, pe, [1.0]) for c, pe in [("A", 30), ("B", 10), ("C", 20)]]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    assert len(score_universe(stocks, cfg, top_n=2)) == 2


def test_empty_config_raises():
    with pytest.raises(ValueError):
        score_universe([_stock("A", 10, [1.0])], [], top_n=5)


def test_topn_nonpositive_raises():
    stocks = [_stock("A", 10, [1.0])]
    cfg = [{"key": "pe", "weight": 1, "direction": "asc"}]
    with pytest.raises(ValueError):
        score_universe(stocks, cfg, top_n=0)
