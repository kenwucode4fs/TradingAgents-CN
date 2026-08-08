"""等权组合调仓：卖出掉榜、买入新进、等权分配。纯函数，复用阶段① market_rules 成本。"""
import math
from tradingagents.backtest.market_rules import buy_cost, sell_cost


BUY_FEE_BUFFER = 0.001
"""买入预算预留比例：覆盖佣金率(0.00025)+过户费率(0.00001)+min_commission 余量，
避免 flooring 到 100 股整数倍后预算被用满、下一笔因手续费被挤出而整单跳过。"""


def compute_rebalance(target_codes, holdings, prices, cash, cost):
    """等权组合调仓：卖出掉榜持仓、买入新进目标、停牌标的特殊处理。

    调仓逻辑：
    1) 卖出：当前持仓中不在 target_codes 且有价（未停牌）的，按 sell_cost 扣费后归还现金。
       停牌（无价）的持仓不卖，原样保留。
    2) 买入：等权预算 = 可用现金 / 目标总数（含停牌标的，停牌标的分不到的那一份预算
       自然留作现金）。对每个有价的新进目标，按预算与预留手续费空间折算成 100 股整
       数倍的可买股数，按 buy_cost 扣费（含手续费）后从现金中扣除。停牌（无价）的目标
       跳过不买，其预算份额留在现金里。

    Args:
        target_codes: 本次目标持仓代码列表（等权）。
        holdings: 当前持仓 {code: shares}。
        prices: 各 code 的成交价（次日开盘价），停牌标的不含在内或值为 None。
        cash: 当前现金。
        cost: 交易成本配置（tradingagents.backtest.types.CostConfig）。

    Returns:
        dict，包含：
        - new_holdings: 调仓后持仓 {code: shares}。
        - cash: 调仓后现金（已扣除买卖双向手续费，资金守恒）。
        - buys: 买入明细列表，每项 {code, shares, price, fee}。
        - sells: 卖出明细列表，每项 {code, shares, price, fee}。
    """
    target = set(target_codes)
    sells, buys = [], []
    new_holdings = dict(holdings)

    # 1) 卖出：当前持仓中不在 target、且有价（未停牌）的
    for code, shares in list(holdings.items()):
        if code in target or shares <= 0:
            continue
        px = prices.get(code)
        if px is None:  # 停牌不卖，保持
            continue
        amount = px * shares
        comm, stamp, transfer = sell_cost(amount, cost)
        cash += amount - comm - stamp - transfer
        sells.append({"code": code, "shares": shares, "price": px, "fee": comm + stamp + transfer})
        del new_holdings[code]

    # 2) 保留股同样纳入"再平衡预算"总池：先按当前价折现估其市值（不强制卖出零头，简化第一版：
    #    只对"新进股"用现金买入，保留股维持原持仓）。等权预算基准 = 调仓前组合总市值
    #    （现金 + 保留持仓按当前价估值），而非仅现金——否则换手时分母包含了不动的保留股，
    #    但分子只有卖出得到的现金，会稀释新进股预算、留下大量闲置现金（破坏等权）。
    #    停牌标的（无价）分不到的那一份预算自然留作现金——见 test_suspended_target_skipped_to_cash。
    #
    #    买入按含手续费的真实成交总额（amount + comm + transfer）校验可用资金并扣减 cash，
    #    保证资金守恒（cash + 持仓市值 + 已扣手续费 == 调仓前总资产）。为避免 flooring 到
    #    100 股整数倍后预算被用满导致下一笔因手续费被挤出而整单跳过，算股数时用
    #    BUY_FEE_BUFFER 预留手续费空间，使 amount+fee 通常不超过 budget_each，各笔互不挤占。
    to_buy = [c for c in target_codes if c not in new_holdings and prices.get(c) is not None]
    if target_codes:
        total_value = cash + sum(
            new_holdings[c] * prices[c] for c in new_holdings if prices.get(c) is not None
        )
        budget_each = total_value / len(target_codes)
        for code in to_buy:
            px = prices[code]
            shares = int(math.floor(budget_each / (px * (1 + BUY_FEE_BUFFER)) / 100) * 100)  # A股 100 整数倍
            if shares <= 0:
                continue
            amount = px * shares
            comm, _, transfer = buy_cost(amount, cost)
            total = amount + comm + transfer
            if total > cash:
                continue
            cash -= total
            new_holdings[code] = new_holdings.get(code, 0) + shares
            buys.append({"code": code, "shares": shares, "price": px, "fee": comm + transfer})

    return {"new_holdings": new_holdings, "cash": cash, "buys": buys, "sells": sells}
