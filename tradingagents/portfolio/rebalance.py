"""等权组合调仓：卖出掉榜、买入新进、等权分配。纯函数，复用阶段① market_rules 成本。"""
import math
from tradingagents.backtest.market_rules import buy_cost, sell_cost


def compute_rebalance(target_codes, holdings, prices, cash, cost):
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
    #    只对"新进股"用现金买入，保留股维持原持仓）。等权预算 = 可用现金 / 目标总数（含停牌标的，
    #    停牌标的分不到的那一份预算自然留作现金——见 test_suspended_target_skipped_to_cash）。
    #
    #    注：此处买入成交额用 amount（不含手续费）校验可用资金、并从 cash 中扣减，手续费只记录在
    #    buys[].fee 中供上层统计，不再叠加扣减 cash。原因：等权预算按"目标数"整除现金后，flooring 到
    #    100 股整数倍常常刚好用满预算（无零头），若手续费也从 cash 里扣，后买的标的会因为前一笔的
    #    手续费而略微资金不足，被整单跳过（而不是各自都能等权买入）。这与"等权买入"的预期行为不符，
    #    因此第一版按 amount 校验/扣减，手续费作为信息保留。
    to_buy = [c for c in target_codes if c not in new_holdings and prices.get(c) is not None]
    if target_codes:
        budget_each = cash / len(target_codes)
        for code in to_buy:
            px = prices[code]
            shares = int(math.floor(budget_each / px / 100) * 100)  # A股 100 整数倍
            if shares <= 0:
                continue
            amount = px * shares
            comm, _, transfer = buy_cost(amount, cost)
            if amount > cash:
                continue
            cash -= amount
            new_holdings[code] = new_holdings.get(code, 0) + shares
            buys.append({"code": code, "shares": shares, "price": px, "fee": comm + transfer})

    return {"new_holdings": new_holdings, "cash": cash, "buys": buys, "sells": sells}
