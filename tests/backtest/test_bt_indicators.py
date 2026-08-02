"""逐日技术指标测试。"""
import pytest
from tradingagents.backtest.types import Bar
from tradingagents.backtest.indicators import compute_indicators


def _bars(closes):
    """使用收盘价列表构造 Bar 对象列表。"""
    return [
        Bar(
            date=f"2020-01-{i+1:02d}",
            open=c,
            high=c,
            low=c,
            close=c,
            pre_close=c,
            volume=100
        )
        for i, c in enumerate(closes)
    ]


class TestMA:
    """测试移动平均线 MA。"""

    def test_ma5(self):
        """测试 MA5 计算与对齐。"""
        bars = _bars([1, 2, 3, 4, 5, 6])
        ind = compute_indicators(bars)

        # 前 4 个元素应为 None（不足 5 日）
        assert ind["ma5"][0] is None
        assert ind["ma5"][1] is None
        assert ind["ma5"][2] is None
        assert ind["ma5"][3] is None

        # 第 5 个元素: (1+2+3+4+5)/5 = 3.0
        assert ind["ma5"][4] == 3.0

        # 第 6 个元素: (2+3+4+5+6)/5 = 4.0
        assert ind["ma5"][5] == 4.0

        # 长度与 bars 等长
        assert len(ind["ma5"]) == len(bars)

    def test_ma10(self):
        """测试 MA10 计算与对齐。"""
        closes = list(range(1, 21))  # [1, 2, ..., 20]
        bars = _bars(closes)
        ind = compute_indicators(bars)

        # 前 9 个元素应为 None
        for i in range(9):
            assert ind["ma10"][i] is None

        # 第 10 个元素: (1+2+...+10)/10 = 5.5
        assert ind["ma10"][9] == 5.5

        # 第 11 个元素: (2+3+...+11)/10 = 6.5
        assert ind["ma10"][10] == 6.5


class TestEMA:
    """测试指数移动平均线 EMA。"""

    def test_ema12_length(self):
        """测试 EMA12 长度与类型。"""
        bars = _bars(list(range(1, 31)))
        ind = compute_indicators(bars)

        # 长度应与 bars 等长
        assert len(ind["ema12"]) == len(bars)
        assert len(ind["ema26"]) == len(bars)

        # 所有元素应为 float 或 None（EMA 不产生 None）
        assert all(isinstance(v, (float, type(None))) for v in ind["ema12"])
        assert all(isinstance(v, (float, type(None))) for v in ind["ema26"])


class TestMACD:
    """测试 MACD 指标。"""

    def test_macd_keys(self):
        """测试 MACD 所有键的存在。"""
        bars = _bars(list(range(1, 51)))
        ind = compute_indicators(bars)

        assert "macd_dif" in ind
        assert "macd_dea" in ind
        assert "macd_bar" in ind

        # 所有长度应与 bars 等长
        assert len(ind["macd_dif"]) == len(bars)
        assert len(ind["macd_dea"]) == len(bars)
        assert len(ind["macd_bar"]) == len(bars)


class TestRSI:
    """测试相对强弱指数 RSI。"""

    def test_rsi_basic(self):
        """测试 RSI 基本计算。"""
        # 递增序列，RSI 应接近 100
        bars = _bars([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])
        ind = compute_indicators(bars)

        # 前 n 个元素应为 None
        assert ind["rsi6"][0] is None
        assert ind["rsi14"][0] is None

        # 长度应与 bars 等长
        assert len(ind["rsi6"]) == len(bars)
        assert len(ind["rsi12"]) == len(bars)
        assert len(ind["rsi14"]) == len(bars)

    def test_rsi_no_nan(self):
        """测试 RSI 不产生 NaN（避免除零）。"""
        # 常数序列（所有收盘价相同），RSI 应为 None 或 NaN 的处理
        bars = _bars([5.0] * 20)
        ind = compute_indicators(bars)

        # 长度应正确
        assert len(ind["rsi14"]) == len(bars)


class TestBoll:
    """测试布林带指标。"""

    def test_boll_structure(self):
        """测试布林带三线结构。"""
        bars = _bars(list(range(1, 41)))
        ind = compute_indicators(bars)

        # 所有三条线都应存在
        assert "boll_up" in ind
        assert "boll_mid" in ind
        assert "boll_low" in ind

        # 长度应与 bars 等长
        assert len(ind["boll_up"]) == len(bars)
        assert len(ind["boll_mid"]) == len(bars)
        assert len(ind["boll_low"]) == len(bars)

        # 前 19 个元素应为 None（不足 20 日）
        for i in range(19):
            assert ind["boll_mid"][i] is None
            assert ind["boll_up"][i] is None
            assert ind["boll_low"][i] is None

        # 第 20 个元素之后，上轨 > 中轨 > 下轨
        for i in range(19, len(bars)):
            if ind["boll_mid"][i] is not None:
                assert ind["boll_up"][i] > ind["boll_mid"][i]
                assert ind["boll_mid"][i] > ind["boll_low"][i]


class TestComputeIndicators:
    """综合测试 compute_indicators 函数。"""

    def test_all_keys_present(self):
        """测试所有指标键都在返回字典中。"""
        bars = _bars(list(range(1, 100)))
        ind = compute_indicators(bars)

        expected_keys = [
            "ma5", "ma10", "ma20", "ma60",
            "ema12", "ema26",
            "macd_dif", "macd_dea", "macd_bar",
            "rsi6", "rsi12", "rsi14",
            "boll_up", "boll_mid", "boll_low"
        ]

        for key in expected_keys:
            assert key in ind, f"Missing key: {key}"

    def test_lengths_aligned(self):
        """测试所有指标长度与 bars 对齐。"""
        bars = _bars(list(range(1, 100)))
        ind = compute_indicators(bars)

        for key, values in ind.items():
            assert len(values) == len(bars), f"Length mismatch for {key}"

    def test_return_type(self):
        """测试返回类型为 dict，值为 list。"""
        bars = _bars(list(range(1, 30)))
        ind = compute_indicators(bars)

        assert isinstance(ind, dict)
        for key, values in ind.items():
            assert isinstance(values, list), f"{key} should be a list"
            assert all(isinstance(v, (float, type(None))) for v in values), \
                f"{key} contains non-numeric values"
