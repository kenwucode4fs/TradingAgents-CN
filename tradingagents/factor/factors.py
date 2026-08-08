# tradingagents/factor/factors.py
"""15 个因子计算函数 + FACTORS 注册表。全部纯函数，数据不足/非法返回 None。

约定：closes 为前复权收盘价升序序列（已过滤 None）；volumes 与之对齐；
cross 为该股截面字段（pe/pb/total_mv/amount/close 等）。
"""
import math
from statistics import pstdev
from typing import List, Optional


def _ret_series(closes: List[float]) -> List[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def _boll_pos(closes: List[float], period: int = 20) -> Optional[float]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    mid = sum(window) / period
    sd = pstdev(window)
    up, low = mid + 2 * sd, mid - 2 * sd
    if up == low:
        return None
    return (closes[-1] - low) / (up - low)


# --- 估值类（截面）---
def _pe(cross, closes, volumes):
    v = cross.get("pe")
    return v if (v is not None and v > 0) else None

def _pb(cross, closes, volumes):
    v = cross.get("pb")
    return v if (v is not None and v > 0) else None

def _total_mv(cross, closes, volumes):
    return cross.get("total_mv")

# --- 动量/趋势类（前复权序列）---
def _mom(closes, lookback):
    if len(closes) < lookback + 1 or not closes[-lookback - 1]:
        return None
    return closes[-1] / closes[-lookback - 1] - 1

def _mom_20(cross, closes, volumes): return _mom(closes, 20)
def _mom_60(cross, closes, volumes): return _mom(closes, 60)
def _mom_120(cross, closes, volumes): return _mom(closes, 120)
def _rev_5(cross, closes, volumes): return _mom(closes, 5)

def _high_250_prox(cross, closes, volumes):
    if len(closes) < 60:  # 至少要一段历史才有意义
        return None
    window = closes[-250:]
    hi = max(window)
    return closes[-1] / hi if hi else None

# --- 波动/风险类 ---
def _vol_60(cross, closes, volumes):
    if len(closes) < 61:
        return None
    rets = _ret_series(closes[-61:])
    return pstdev(rets) if len(rets) >= 2 else None

def _mdd_120(cross, closes, volumes):
    if len(closes) < 60:
        return None
    window = closes[-120:]
    peak, mdd = window[0], 0.0
    for p in window:
        peak = max(peak, p)
        if peak:
            mdd = max(mdd, (peak - p) / peak)
    return mdd

# --- 技术类 ---
def _ma20_bias(cross, closes, volumes):
    if len(closes) < 20:
        return None
    ma = sum(closes[-20:]) / 20
    return closes[-1] / ma - 1 if ma else None

def _rsi14(cross, closes, volumes): return _rsi(closes, 14)
def _boll_pos_f(cross, closes, volumes): return _boll_pos(closes, 20)

# --- 流动性类 ---
def _turnover_proxy(cross, closes, volumes):
    a, mv = cross.get("amount"), cross.get("total_mv")
    if a is None or not mv:
        return None
    return a / mv

def _vol_ratio(cross, closes, volumes):
    if len(volumes) < 60:
        return None
    short = sum(volumes[-5:]) / 5
    long = sum(volumes[-60:]) / 60
    return short / long if long else None


FACTORS = {
    "pe":            {"name": "市盈率",       "category": "估值",  "default_direction": "asc",  "fn": _pe},
    "pb":            {"name": "市净率",       "category": "估值",  "default_direction": "asc",  "fn": _pb},
    "total_mv":      {"name": "总市值",       "category": "估值",  "default_direction": "asc",  "fn": _total_mv},
    "mom_20":        {"name": "20日动量",     "category": "动量",  "default_direction": "desc", "fn": _mom_20},
    "mom_60":        {"name": "60日动量",     "category": "动量",  "default_direction": "desc", "fn": _mom_60},
    "mom_120":       {"name": "120日动量",    "category": "动量",  "default_direction": "desc", "fn": _mom_120},
    "rev_5":         {"name": "5日反转",      "category": "动量",  "default_direction": "asc",  "fn": _rev_5},
    "high_250_prox": {"name": "52周高接近度", "category": "动量",  "default_direction": "desc", "fn": _high_250_prox},
    "vol_60":        {"name": "60日波动率",   "category": "波动",  "default_direction": "asc",  "fn": _vol_60},
    "mdd_120":       {"name": "120日最大回撤","category": "波动",  "default_direction": "asc",  "fn": _mdd_120},
    "ma20_bias":     {"name": "均线偏离",     "category": "技术",  "default_direction": "asc",  "fn": _ma20_bias},
    "rsi14":         {"name": "RSI14",        "category": "技术",  "default_direction": "asc",  "fn": _rsi14},
    "boll_pos":      {"name": "布林位置",     "category": "技术",  "default_direction": "asc",  "fn": _boll_pos_f},
    "turnover_proxy":{"name": "换手率代理",   "category": "流动性","default_direction": "asc",  "fn": _turnover_proxy},
    "vol_ratio":     {"name": "量比",         "category": "流动性","default_direction": "asc",  "fn": _vol_ratio},
}
