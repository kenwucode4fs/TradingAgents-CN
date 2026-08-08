import pytest
from tradingagents.factor.scoring import percentile_normalize, weighted_score, rank_topn


def test_percentile_desc_larger_is_better():
    # 值 [10,20,30]，desc：30 最好=1.0，10 最差=0.0，20 居中=0.5
    assert percentile_normalize([10, 20, 30], "desc") == [0.0, 0.5, 1.0]


def test_percentile_asc_smaller_is_better():
    # 值 [10,20,30]，asc：10 最好=1.0，30 最差=0.0
    assert percentile_normalize([10, 20, 30], "asc") == [1.0, 0.5, 0.0]


def test_percentile_keeps_none_and_excludes_from_rank():
    # None 不参与排名，返回位置仍是 None；有效值 [10,30] → 10=0.0,30=1.0
    assert percentile_normalize([10, None, 30], "desc") == [0.0, None, 1.0]


def test_percentile_single_valid_is_one():
    assert percentile_normalize([None, 42, None], "desc") == [None, 1.0, None]


def test_percentile_ties_share_rank():
    # 并列：[10,10,30] desc → 两个 10 同为最差 0.0，30=1.0
    assert percentile_normalize([10, 10, 30], "desc") == [0.0, 0.0, 1.0]


def test_weighted_score_normalizes_by_weight_sum():
    # norm{a:1.0,b:0.0}, weights{a:3,b:1} → (3*1+1*0)/4 = 0.75
    assert weighted_score({"a": 1.0, "b": 0.0}, {"a": 3, "b": 1}) == 0.75


def test_rank_topn_sorts_and_truncates():
    scored = [{"code": "A", "score": 0.2}, {"code": "B", "score": 0.9}, {"code": "C", "score": 0.5}]
    top = rank_topn(scored, 2)
    assert [x["code"] for x in top] == ["B", "C"]
    assert [x["rank"] for x in top] == [1, 2]


def test_percentile_invalid_direction_raises():
    with pytest.raises(ValueError):
        percentile_normalize([1.0, 2.0], "bad")


def test_percentile_all_none_returns_all_none():
    assert percentile_normalize([None, None], "desc") == [None, None]


def test_weighted_score_nonpositive_weight_raises():
    with pytest.raises(ValueError):
        weighted_score({"a": 0.5}, {"a": 0})
