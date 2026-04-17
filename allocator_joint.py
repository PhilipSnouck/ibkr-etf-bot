from math import floor, ceil


# ------------------------------------------------------------
# JOINT ACCOUNT ALLOCATOR
# ------------------------------------------------------------
# Purpose:
# This allocator calculates how to allocate cash for the Joint
# account, which currently consists of a single ETF.
#
# Rules:
# - 100% of available cash is allocated to the ETF
# - if the raw share count has a fractional part below the
#   top-up trigger, we round down and buy that number of shares
# - if the fractional part is at or above the top-up trigger,
#   we buy 0 shares for now and create a pending top-up instead
#
# Expected inputs:
# - cash (float): available cash to allocate
# - etf_config (dict): ETF settings from config.py
# - prices (dict): symbol -> price mapping
# - topup_trigger (float): fractional threshold (e.g. 0.75)
#
# Output format:
# Matches the shared allocator contract used by main.py
# ------------------------------------------------------------

def allocate_joint_portfolio(cash, etf_config, prices, topup_trigger=0.75):
    symbols = list(etf_config.keys())

    if len(symbols) != 1:
        raise ValueError("Joint allocator expects exactly 1 ETF.")

    symbol = symbols[0]
    settings = etf_config[symbol]
    price = prices[symbol]

    target_budget = cash * settings["target_weight"]

    raw_shares = target_budget / price
    floor_shares = floor(raw_shares)
    ceil_shares = ceil(raw_shares)
    fractional_part = raw_shares - floor_shares

    topup_needed = False
    topup_amount = 0.0
    target_shares = floor_shares

    # --------------------------------------------------------
    # TOP-UP DECISION
    # --------------------------------------------------------
    if fractional_part >= topup_trigger and raw_shares > 0:
        topup_needed = True
        target_shares = ceil_shares
        chosen_shares = 0
        spent = 0.0
        topup_amount = (target_shares * price) - cash
    else:
        chosen_shares = floor_shares
        spent = chosen_shares * price

        # Safety guard:
        # even after rounding logic, never allow spent cash
        # to exceed available cash.
        while chosen_shares > 0 and spent > cash:
            chosen_shares -= 1
            spent = chosen_shares * price

    # --------------------------------------------------------
    # FINAL TOTALS
    # --------------------------------------------------------
    leftover_cash = cash - spent
    total_spent = spent

    actual_pct = 100.0 if total_spent > 0 else 0.0

    return {
        "symbols": [symbol],
        "shares": {
            symbol: chosen_shares,
        },
        "spent": {
            symbol: spent,
        },
        "raw": {
            symbol: raw_shares,
        },
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
        "actual_pct": {
            symbol: actual_pct,
        },
    }