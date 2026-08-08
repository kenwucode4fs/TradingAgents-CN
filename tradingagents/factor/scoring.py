"""因子打分核心纯函数：横截面百分位标准化、加权合成、排序取 TopN。不触库。"""
from typing import List, Optional, Dict


def percentile_normalize(values: List[Optional[float]], direction: str) -> List[Optional[float]]:
    """对一列因子值做横截面百分位标准化，返回 [0,1]（越大越好），None 原样保留。

    direction='desc' 越大越好；'asc' 越小越好。并列取相同百分位（小于该值的个数占比）。
    有效值 N==1 记 1.0；N==0 全 None。
    """
    if direction not in ("asc", "desc"):
        raise ValueError(f"非法 direction: {direction!r}，期望 'asc' 或 'desc'")
    valid = [v for v in values if v is not None]
    n = len(valid)
    out: List[Optional[float]] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        if n == 1:
            out.append(1.0)
            continue
        # 以「严格小于该值的个数」定 rank（并列共享），rank ∈ [0, n-1]
        less = sum(1 for x in valid if x < v)
        p = less / (n - 1)  # p: 值小→0，值大→1（此为 asc-越小分越低 的原始百分位）
        out.append(p if direction == "desc" else 1.0 - p)
    return out


def weighted_score(norm_by_factor: Dict[str, float], weights: Dict[str, float]) -> float:
    """加权归一：Σ(w·norm)/Σ(w)。norm_by_factor 的值须全部非 None。"""
    wsum = sum(weights[k] for k in norm_by_factor)
    if wsum <= 0:
        raise ValueError("权重之和必须为正")
    return sum(weights[k] * norm_by_factor[k] for k in norm_by_factor) / wsum


def rank_topn(scored: List[dict], n: int) -> List[dict]:
    """按 score 降序，赋 rank（从 1 起），取前 n。"""
    ordered = sorted(scored, key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(ordered):
        item["rank"] = i + 1
    return ordered[:n]
