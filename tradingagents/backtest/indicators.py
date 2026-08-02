"""逐日技术指标序列，与 bars 等长对齐。"""
import pandas as pd
from typing import List
from .types import Bar


def _rsi(close: pd.Series, n: int) -> pd.Series:
    """计算 RSI 指标。

    Args:
        close: 收盘价序列
        n: RSI 周期

    Returns:
        RSI 序列
    """
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - 100 / (1 + rs)


def compute_indicators(bars: List[Bar]) -> dict:
    """计算与 bars 等长对齐的技术指标。

    参数:
        bars: K线数据列表

    返回:
        字典，包含以下键（每个值为与 bars 等长的 list，首段不足窗口置 None）:
        - ma5, ma10, ma20, ma60: 移动平均线
        - ema12, ema26: 指数移动平均线
        - macd_dif, macd_dea, macd_bar: MACD 指标
        - rsi6, rsi12, rsi14: 相对强弱指数
        - boll_up, boll_mid, boll_low: 布林带
    """
    close = pd.Series([b.close for b in bars], dtype="float64")
    out = {}

    # 简单移动平均线 MA
    for n in (5, 10, 20, 60):
        out[f"ma{n}"] = close.rolling(n).mean()

    # 指数移动平均线 EMA 和 MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["ema12"], out["ema26"] = ema12, ema26

    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    out["macd_dif"], out["macd_dea"], out["macd_bar"] = dif, dea, (dif - dea) * 2

    # 相对强弱指数 RSI
    for n in (6, 12, 14):
        out[f"rsi{n}"] = _rsi(close, n)

    # 布林带 BOLL
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out["boll_mid"], out["boll_up"], out["boll_low"] = mid, mid + 2 * std, mid - 2 * std

    # 转换为 list，NaN → None
    return {k: [None if pd.isna(v) else float(v) for v in s] for k, s in out.items()}
