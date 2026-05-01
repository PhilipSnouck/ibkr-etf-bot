from math import floor, ceil

from config import ORDER_COMMISSION_BUFFER

# ------------------------------------------------------------
# PENSION ALLOCATOR
# ------------------------------------------------------------
# Purpose:
# This allocator calculates how to allocate cash across a
# 3-ETF portfolio for the Pension account.
#
# Responsibilities:
# - split cash according to target weights
# - apply rounding rules
# - reserve IBKR commission per order
# - reserve market-order buffer for ETF3 only
# - handle remainder via ETF3
# - trigger top-up instead of buying ETF3 when threshold is met
#
# Notes:
# - Commission buffer applies to every planned order.
# - Market-order buffer only applies to the final cash-limiting order.
# - For Pension, that final cash-limiting order is ETF3.
# ------------------------------------------------------------

def allocate_pension_portfolio(cash, etf_config, prices, topup_trigger=0.75):
    symbols = list(etf_config.keys())

    if len(symbols) != 3:
        raise ValueError("Pension allocator expects exactly 3 ETFs.")

    symbol_1 = symbols[0]
    symbol_2 = symbols[1]
    symbol_3 = symbols[2]

    settings_1 = etf_config[symbol_1]
    settings_2 = etf_config[symbol_2]

    price_1 = prices[symbol_1]
    price_2 = prices[symbol_2]
    price_3 = prices[symbol_3]

    target_budget_1 = cash * settings_1["target_weight"]
    target_budget_2 = cash * settings_2["target_weight"]

    # --------------------------------------------------------
    # ETF 1
    # --------------------------------------------------------
    raw_1 = target_budget_1 / price_1
    shares_1 = round(raw_1)
    spent_1 = shares_1 * price_1
    required_cash_1 = spent_1 + ORDER_COMMISSION_BUFFER

    if required_cash_1 > cash:
        shares_1 -= 1
        spent_1 = shares_1 * price_1
        required_cash_1 = spent_1 + ORDER_COMMISSION_BUFFER

    remaining_after_1 = cash - required_cash_1
    rounded_down_1 = shares_1 < raw_1

    # --------------------------------------------------------
    # ETF 2
    # --------------------------------------------------------
    raw_2 = target_budget_2 / price_2
    rounding_rule_2 = settings_2["rounding"]

    if rounding_rule_2 == "force_up_if_previous_down" and rounded_down_1:
        shares_2 = ceil(raw_2)
    else:
        shares_2 = round(raw_2)

    spent_2 = shares_2 * price_2
    required_cash_2 = spent_2 + ORDER_COMMISSION_BUFFER

    while shares_2 > 0 and required_cash_2 > remaining_after_1:
        shares_2 -= 1
        spent_2 = shares_2 * price_2
        required_cash_2 = spent_2 + ORDER_COMMISSION_BUFFER

    remaining_after_2 = remaining_after_1 - required_cash_2

    # --------------------------------------------------------
    # ETF 3
    # --------------------------------------------------------
    cash_available_for_etf_3 = remaining_after_2 - ORDER_COMMISSION_BUFFER

    raw_3 = max(cash_available_for_etf_3, 0) / price_3
    floor_3 = floor(raw_3)
    ceil_3 = ceil(raw_3)
    fractional_part_3 = raw_3 - floor_3

    topup_needed = False
    topup_amount = 0.0
    target_shares_3 = floor_3

    if fractional_part_3 >= topup_trigger and raw_3 > 0:
        topup_needed = True
        target_shares_3 = ceil_3
        shares_3 = 0
        spent_3 = 0.0
        topup_amount = (
            target_shares_3 * price_3
            + ORDER_COMMISSION_BUFFER
            - remaining_after_2
        )
    else:
        shares_3 = floor_3
        spent_3 = shares_3 * price_3

        required_cash_3 = spent_3 + ORDER_COMMISSION_BUFFER

        while shares_3 > 0 and required_cash_3 > remaining_after_2:
            shares_3 -= 1
            spent_3 = shares_3 * price_3
            required_cash_3 = spent_3 + ORDER_COMMISSION_BUFFER

    # --------------------------------------------------------
    # FINAL TOTALS
    # --------------------------------------------------------
    total_spent = spent_1 + spent_2 + spent_3
    orders_placed = sum(1 for s in [shares_1, shares_2, shares_3] if s > 0)
    leftover_cash = cash - total_spent - (orders_placed * ORDER_COMMISSION_BUFFER)

    if total_spent > 0:
        actual_pct_1 = (spent_1 / total_spent) * 100
        actual_pct_2 = (spent_2 / total_spent) * 100
        actual_pct_3 = (spent_3 / total_spent) * 100
    else:
        actual_pct_1 = 0
        actual_pct_2 = 0
        actual_pct_3 = 0

    return {
        "symbols": [symbol_1, symbol_2, symbol_3],
        "shares": {
            symbol_1: shares_1,
            symbol_2: shares_2,
            symbol_3: shares_3,
        },
        "spent": {
            symbol_1: spent_1,
            symbol_2: spent_2,
            symbol_3: spent_3,
        },
        "raw": {
            symbol_1: raw_1,
            symbol_2: raw_2,
            symbol_3: raw_3,
        },
        "diagnostics": {
            f"{symbol_1.lower()}_rounded_down": rounded_down_1,
            f"{symbol_3.lower()}_fractional_part": fractional_part_3,
        },
        "topup": {
            "needed": topup_needed,
            "symbol": symbol_3,
            "target_shares": target_shares_3,
            "topup_amount": topup_amount,
            "remaining_cash_before_etf3": remaining_after_2,
        },
        "totals": {
            "total_spent": total_spent,
            "leftover_cash": leftover_cash,
        },
        "actual_pct": {
            symbol_1: actual_pct_1,
            symbol_2: actual_pct_2,
            symbol_3: actual_pct_3,
        },
    }