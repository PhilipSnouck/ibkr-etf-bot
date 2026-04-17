from math import floor, ceil

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
# - handle remainder via ETF3
# - trigger top-up instead of buying ETF3 when threshold is met
#
# Expected inputs:
# - cash (float): available cash to allocate
# - etf_config (dict): ETF settings from config.py
# - prices (dict): symbol -> price mapping
# - topup_trigger (float): fractional threshold (e.g. 0.75)
#
# Expected output (IMPORTANT — standard format):
# A dict containing:
# - symbols: list of ETF symbols
# - shares: dict symbol -> number of shares to buy
# - spent: dict symbol -> cash spent per ETF
# - raw: raw (pre-rounding) share calculations
# - diagnostics: rounding/debug info
# - topup: info about whether top-up is needed
# - totals: total spent and leftover cash
# - actual_pct: achieved allocation percentages
#
# Notes:
# - This function does NOT:
#   - check market hours
#   - check account rules (min cash, etc.)
#   - execute orders
# - It only computes the ideal allocation plan.
#
# This separation is intentional:
# - allocator = "what to buy"
# - rules/main = "whether to buy"
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
    settings_3 = etf_config[symbol_3]

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

    if spent_1 > cash:
        shares_1 -= 1
        spent_1 = shares_1 * price_1

    remaining_after_1 = cash - spent_1

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

    while shares_2 > 0 and spent_2 > remaining_after_1:
        shares_2 -= 1
        spent_2 = shares_2 * price_2

    remaining_after_2 = remaining_after_1 - spent_2

    # --------------------------------------------------------
    # ETF 3
    # --------------------------------------------------------
    raw_3 = remaining_after_2 / price_3
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
        topup_amount = (target_shares_3 * price_3) - remaining_after_2
    else:
        shares_3 = floor_3
        spent_3 = shares_3 * price_3

    # --------------------------------------------------------
    # FINAL TOTALS
    # --------------------------------------------------------
    total_spent = spent_1 + spent_2 + spent_3
    leftover_cash = cash - total_spent

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