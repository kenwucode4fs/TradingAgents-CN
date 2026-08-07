"""前端回测请求 payload 映射为 Plan 1 引擎参数。"""
from tradingagents.backtest import BacktestConfig, CostConfig, PositionConfig, Condition

_VALID_OP = {">", "<", "cross_up", "cross_down"}
_VALID_LOGIC = {"AND", "OR"}
_VALID_REDUCE = {"reduce_one", "clear_all"}


def _rules(raw: list) -> list:
    """解析规则列表，转换为 Condition 对象列表。

    Args:
        raw: 原始规则列表，每个规则是 {"left": str, "op": str, "right": any} 格式。

    Returns:
        Condition 对象列表。

    Raises:
        ValueError: 当比较符非法时。
    """
    out = []
    for r in raw or []:
        op = r.get("op")
        if op not in _VALID_OP:
            raise ValueError(f"非法比较符: {op}")
        out.append(Condition(left=r["left"], op=op, right=r["right"]))
    return out


def build_backtest_args(payload: dict) -> dict:
    """将前端回测请求 payload 映射为 Plan 1 引擎参数对象。

    Args:
        payload: 前端回测请求 payload，包含以下字段：
            - symbol (str): 股票代码，必填
            - start_date (str): 开始日期，必填
            - end_date (str): 结束日期，必填
            - initial_capital (float, 可选): 初始资金，默认 100000
            - cost (dict, 可选): 成本配置
                - commission_rate (float): 佣金率，默认 0.00025
                - min_commission (float): 最低佣金，默认 5.0
                - stamp_tax_rate (float): 印花税率，默认 0.001
                - transfer_fee_rate (float): 过户费率，默认 0.00001
            - position (dict, 可选): 持仓配置
                - parts (int): 分仓数，默认 3
                - reduce_mode (str): 减仓模式，默认 "reduce_one"
            - buy_rules (list, 可选): 买入规则列表
            - buy_logic (str, 可选): 买入规则逻辑，默认 "AND"
            - sell_rules (list, 可选): 卖出规则列表
            - sell_logic (str, 可选): 卖出规则逻辑，默认 "OR"

    Returns:
        包含以下键的字典：
            - config: BacktestConfig 对象
            - buy_rules: Condition 对象列表
            - buy_logic: 买入逻辑字符串
            - sell_rules: Condition 对象列表
            - sell_logic: 卖出逻辑字符串

    Raises:
        ValueError: 当参数非法时。
    """
    # 验证必填参数
    for k in ("symbol", "start_date", "end_date"):
        if not payload.get(k):
            raise ValueError(f"缺少必填参数: {k}")

    # 获取并验证逻辑值
    buy_logic = payload.get("buy_logic", "AND")
    sell_logic = payload.get("sell_logic", "OR")
    if buy_logic not in _VALID_LOGIC or sell_logic not in _VALID_LOGIC:
        raise ValueError("buy_logic/sell_logic 必须是 AND 或 OR")

    # 获取成本和持仓配置
    c = payload.get("cost", {}) or {}
    p = payload.get("position", {}) or {}

    # 验证减仓模式
    reduce_mode = p.get("reduce_mode", "reduce_one")
    if reduce_mode not in _VALID_REDUCE:
        raise ValueError(f"非法减仓模式: {reduce_mode}")

    # 构建 BacktestConfig 对象
    cfg = BacktestConfig(
        symbol=payload["symbol"],
        start_date=payload["start_date"],
        end_date=payload["end_date"],
        initial_capital=float(payload.get("initial_capital", 100000)),
        cost=CostConfig(
            commission_rate=float(c.get("commission_rate", 0.00025)),
            min_commission=float(c.get("min_commission", 5.0)),
            stamp_tax_rate=float(c.get("stamp_tax_rate", 0.001)),
            transfer_fee_rate=float(c.get("transfer_fee_rate", 0.00001)),
        ),
        position=PositionConfig(
            parts=int(p.get("parts", 3)),
            reduce_mode=reduce_mode
        ),
    )

    return {
        "config": cfg,
        "buy_rules": _rules(payload.get("buy_rules")),
        "buy_logic": buy_logic,
        "sell_rules": _rules(payload.get("sell_rules")),
        "sell_logic": sell_logic,
    }
