from math import floor, ceil

from config import ORDER_COMMISSION_BUFFER, MARKET_ORDER_BUFFER


def allocate_joint_portfolio(cash, etf_config, prices, topup_trigger=0.75):
    symbols = list(etf_config.keys())

    if len(symbols) != 1:
        raise ValueError("Joint allocator expects exactly 1 ETF.")

    symbol = symbols[0]
    settings = etf_config[symbol]
    price = prices[symbol]

    effective_cash = cash - ORDER_COMMISSION_BUFFER - MARKET_ORDER_BUFFER
    effective_cash = max(effective_cash, 0)

    target_budget = effective_cash * settings["target_weight"]

    raw_shares = target_budget / price
    floor_shares = floor(raw_shares)
    ceil_shares = ceil(raw_shares)
    fractional_part = raw_shares - floor_shares

    topup_needed = False
    topup_amount = 0.0
    target_shares = floor_shares

    if fractional_part >= topup_trigger and raw_shares > 0:
        topup_needed = True
        target_shares = ceil_shares
        chosen_shares = 0
        spent = 0.0

        topup_amount = (
            target_shares * price
            + ORDER_COMMISSION_BUFFER
            + MARKET_ORDER_BUFFER
            - cash
        )
    else:
        chosen_shares = floor_shares
        spent = chosen_shares * price

        required_cash = (
            spent
            + ORDER_COMMISSION_BUFFER
            + MARKET_ORDER_BUFFER
        )

        while chosen_shares > 0 and required_cash > cash:
            chosen_shares -= 1
            spent = chosen_shares * price
            required_cash = (
                spent
                + ORDER_COMMISSION_BUFFER
                + MARKET_ORDER_BUFFER
            )

    leftover_cash = cash - spent
    total_spent = spent
    actual_pct = 100.0 if total_spent > 0 else 0.0

    return {
        "symbols": [symbol],
        "shares": {symbol: chosen_shares},
        "spent": {symbol: spent},
        "raw": {symbol: raw_shares},
        "diagnostics": {
            f"{symbol.lower()}_fractional_part": fractional_part,
        },
        "topup": {
            "needed": topup_needed,
            "symbol": symbol,
            "target_shares": target_shares,
            "topup_amount": topup_amount,
            "remaining_cash_before_etf3": cash,
        },
        "totals": {
            "total_spent": total_spent,
            "leftover_cash": leftover_cash,
        },
        "actual_pct": {symbol: actual_pct},
    }