"""因子打分选股（子项目 2a）开源打分层。"""
from typing import List

from .factors import FACTORS
from .scoring import percentile_normalize, weighted_score, rank_topn

__all__ = ["FACTORS", "score_universe", "percentile_normalize", "weighted_score", "rank_topn"]


def score_universe(stocks: List[dict], factor_configs: List[dict], top_n: int) -> List[dict]:
    """对候选股按选中因子做横截面标准化加权打分，剔除缺失，返回 TopN 榜单。"""
    if not factor_configs:
        raise ValueError("至少选择一个因子")
    if top_n <= 0:
        raise ValueError("top_n 必须为正")

    keys = [c["key"] for c in factor_configs]
    directions = {c["key"]: c.get("direction") or FACTORS[c["key"]]["default_direction"]
                  for c in factor_configs}
    weights = {c["key"]: c["weight"] for c in factor_configs}

    # 1) 每股每因子原始值
    raw = {k: [] for k in keys}   # key -> [每股原始值(可 None)]
    for s in stocks:
        for k in keys:
            fn = FACTORS[k]["fn"]
            raw[k].append(fn(s.get("cross", {}), s.get("closes", []), s.get("volumes", [])))

    # 2) 每因子横截面标准化
    norm = {k: percentile_normalize(raw[k], directions[k]) for k in keys}

    # 3) 组装每股，剔除任一因子缺失者
    scored = []
    for i, s in enumerate(stocks):
        norm_by_factor = {}
        factors_detail = {}
        missing = False
        for k in keys:
            nv = norm[k][i]
            if nv is None:
                missing = True
                break
            norm_by_factor[k] = nv
            factors_detail[k] = {"value": raw[k][i], "norm": nv, "direction": directions[k]}
        if missing:
            continue
        scored.append({
            "code": s["code"], "name": s.get("name", ""), "industry": s.get("industry", ""),
            "score": weighted_score(norm_by_factor, weights),
            "factors": factors_detail,
        })

    # 4) 排序取 TopN
    return rank_topn(scored, top_n)
