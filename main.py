# ------------------------------------------------------------
# MAIN ORCHESTRATOR
# ------------------------------------------------------------
# This script runs the ETF bot across all enabled accounts in
# one go.
#
# Responsibilities:
# - connect to IBKR
# - iterate through enabled accounts from config.py
# - handle pending top-up logic per account
# - fetch cash, contracts, and prices
# - run the configured allocator for each account
# - print order previews
# - check market hours
# - optionally execute approved orders
#
# Important design split:
# - allocator = what to buy
# - rules      = whether an account is eligible to proceed
# - main       = orchestration and execution flow
# ------------------------------------------------------------

import sys
from datetime import datetime, timezone

from broker import (
    connect_ib,
    get_account_cash,
    qualify_etf_contracts,
    get_etf_prices,
    is_contract_open_now,
    place_market_order,
    wait_for_order_status,
)

from allocator_registry import get_allocator

from pending_topup import (
    load_pending_topup,
    save_pending_topup,
    clear_pending_topup,
    is_pending_topup_expired,
    pending_topup_age_days,
)

from rules import (
    is_account_enabled,
    get_allocator_name,
    get_account_currency,
    get_account_id,
    passes_min_cash_rule,
    pending_topup_enabled,
    get_topup_trigger,
)

from config import (
    ACCOUNTS,
    TEST_CASH_OVERRIDE,
    EXECUTION_MODE,
    IB_ENVIRONMENT,
)


# ------------------------------------------------------------
# RUNTIME MODE
# ------------------------------------------------------------
BUY_CONFIRMED = len(sys.argv) > 1 and sys.argv[1].lower() == "buy"

print("\n--- RUN CONFIG --------------------------------------------------")
print(
    f"{'Env':<6}: {IB_ENVIRONMENT:<6} | "
    f"{'Mode':<6}: {EXECUTION_MODE:<7} | "
    f"{'Buy':<6}: {str(BUY_CONFIRMED):<5}"
)
print("---------------------------------------------------------------")

# ------------------------------------------------------------
# COLOR CONSTANTS
# ------------------------------------------------------------
GREEN = "\033[92m"
RESET = "\033[0m"

# ------------------------------------------------------------
# LIVE SAFETY GUARD
# ------------------------------------------------------------
if IB_ENVIRONMENT == "live" and TEST_CASH_OVERRIDE is not None:
    raise RuntimeError(
        "Safety stop: TEST_CASH_OVERRIDE must be None in live mode."
    )

# ------------------------------------------------------------
# CONNECT TO IBKR ONCE
# ------------------------------------------------------------
ib = connect_ib()
print(f"{'IB':<6}: connected")

execution_queue = []

# ------------------------------------------------------------
# PROCESS EACH ENABLED ACCOUNT
# ------------------------------------------------------------
for account_name, account_settings in ACCOUNTS.items():
    if not is_account_enabled(account_settings):
        continue

    print(f"\n{GREEN}============================================================")
    print(f"ACCOUNT: {account_name}")
    print(f"============================================================{RESET}")

    account_id = get_account_id(account_settings, IB_ENVIRONMENT)

    if not account_id:
        print(f"Skipping account: no {IB_ENVIRONMENT} account ID configured.")
        continue

    account_currency = get_account_currency(account_settings)
    allocator_name = get_allocator_name(account_settings)
    allocator = get_allocator(allocator_name)
    etf_config = account_settings["etfs"]

    # --------------------------------------------------------
    # CHECK FOR ACCOUNT-SPECIFIC PENDING TOP-UP
    # --------------------------------------------------------
    if pending_topup_enabled(account_settings):
        pending = load_pending_topup(account_name)

        if pending:
            if is_pending_topup_expired(pending):
                print("\nPending top-up found, but it has expired.")
                print("Deleting expired pending item and continuing with a normal run.")
                clear_pending_topup(account_name)
            else:
                print("\nPending top-up found.")

                real_cash = get_account_cash(ib, account_id, currency=account_currency)

                pending_symbol = pending["symbol"]
                qualified_contracts = qualify_etf_contracts(
                    ib,
                    etf_config,
                    symbols=[pending_symbol],
                )
                prices = get_etf_prices(ib, qualified_contracts)

                contract = qualified_contracts[pending_symbol]
                market_open, market_reason = is_contract_open_now(ib, contract)

                current_price = prices[pending_symbol]
                required_cash_now = pending["target_shares"] * current_price
                shortfall = required_cash_now - real_cash
                pending_age = pending_topup_age_days(pending)

                print("\n--- PENDING TOP-UP STATUS ---\n")

                header = (
                    f"{'ETF':5} | {'Target Shrs':>11} | {'Price':>10} | "
                    f"{'Cash Now':>10} | {'Need Total':>11} | {'Shortfall':>10} | "
                    f"{'Market':>8} | {'Age(d)':>7}"
                )
                print(header)
                print("-" * len(header))

                print(
                    f"{pending_symbol:5} | "
                    f"{pending['target_shares']:11} | "
                    f"{current_price:10.2f} | "
                    f"{real_cash:10.2f} | "
                    f"{required_cash_now:11.2f} | "
                    f"{max(shortfall, 0):10.2f} | "
                    f"{('OPEN' if market_open else 'CLOSED'):>8} | "
                    f"{pending_age:7.2f}"
                )

                print("\nStatus note:")
                print(market_reason)

                if shortfall <= 0:
                    print("\nPending top-up is now fully funded.")

                    if not market_open:
                        print("Action taken: no order placed.")
                        print("Reason: market is currently closed.")
                        print("Next step: rerun the script during market hours.")
                        print("Pending top-up file has been kept.")
                        continue

                    print("\nOrder ready:")
                    print(
                        f"{pending_symbol}: {pending['target_shares']} shares "
                        f"({account_currency} {required_cash_now:.2f})"
                    )

                    if EXECUTION_MODE != "execute":
                        print("\nPreview only: EXECUTION_MODE is not 'execute'. No order will be placed.")
                    elif not BUY_CONFIRMED:
                        print("\nPreview only: no 'buy' command given. No order will be placed.")
                    else:
                        execution_queue.append(
                            {
                                "account_name": account_name,
                                "account_id": account_id,
                                "account_currency": account_currency,
                                "orders": [
                                    {
                                        "symbol": pending_symbol,
                                        "contract": contract,
                                        "quantity": pending["target_shares"],
                                    }
                                ],
                                "pending_followup": {
                                    "type": "clear_pending_topup",
                                },
                            }
                        )
                else:
                    print("\nPending top-up is still NOT fully funded.")
                    print(f"Still missing: {account_currency} {shortfall:.2f}")

                continue

    # --------------------------------------------------------
    # GET CASH
    # --------------------------------------------------------
    real_cash = get_account_cash(ib, account_id, currency=account_currency)

    if TEST_CASH_OVERRIDE is not None:
        cash = float(TEST_CASH_OVERRIDE)
        print(f"\n{account_name} real cash: {account_currency} {real_cash:.2f}")
        print(f"{account_name} test cash override: {account_currency} {cash:.2f}")
    else:
        cash = real_cash
        print(f"\n{account_name} cash: {account_currency} {cash:.2f}")

    # --------------------------------------------------------
    # ACCOUNT-LEVEL CASH RULES
    # --------------------------------------------------------
    # Important:
    # We still continue with qualification, pricing, allocation,
    # and preview output even if the account is below the minimum
    # cash threshold.
    #
    # The min-cash rule is treated as an execution gate, not as
    # a data/preview gate.
    passes_cash_rule, min_cash_required = passes_min_cash_rule(account_settings, cash)

    # --------------------------------------------------------
    # QUALIFY ETF CONTRACTS
    # --------------------------------------------------------
    qualified_contracts = qualify_etf_contracts(ib, etf_config)

    # --------------------------------------------------------
    # FETCH ETF PRICES
    # --------------------------------------------------------
    try:
        prices = get_etf_prices(ib, qualified_contracts)
    except ValueError as e:
        print(f"\nSafety stop while fetching prices: {e}")
        continue

    invalid_price_found = False

    for symbol, price in prices.items():
        if price <= 0:
            print(f"\nSafety stop: invalid price for {symbol}: {price}")
            invalid_price_found = True

    if invalid_price_found:
        continue

    # --------------------------------------------------------
    # RUN ALLOCATOR
    # --------------------------------------------------------
    topup_trigger = get_topup_trigger(account_settings)

    result = allocator(
        cash=cash,
        etf_config=etf_config,
        prices=prices,
        topup_trigger=topup_trigger,
    )

    symbols = result["symbols"]
    shares = result["shares"]
    spent = result["spent"]
    raw = result["raw"]
    diagnostics = result.get("diagnostics", {})
    topup = result["topup"]
    totals = result["totals"]
    actual_pct = result["actual_pct"]

    # --------------------------------------------------------
    # CHECK MARKET HOURS
    # --------------------------------------------------------
    market_status = {}
    market_blocked = False

    for symbol in symbols:
        contract = qualified_contracts[symbol]
        market_open, market_reason = is_contract_open_now(ib, contract)

        market_status[symbol] = {
            "open": market_open,
            "reason": market_reason,
        }

        if shares[symbol] > 0 and not market_open:
            market_blocked = True

    # --------------------------------------------------------
    # PREVIEW
    # --------------------------------------------------------
    print("\n--- MARKET / INSTRUMENT STATUS ---\n")

    header_1 = f"{'ETF':5} | {'Qualified':>9} | {'Price':>10} | {'Market':>8} | {'Status note':<20}"
    print(header_1)
    print("-" * len(header_1))

    for symbol in symbols:
        qualified = "yes" if symbol in qualified_contracts else "no"
        price = prices.get(symbol, 0.0)
        market_open = "OPEN" if market_status[symbol]["open"] else "CLOSED"
        status_note = market_status[symbol]["reason"]

        print(
            f"{symbol:5} | "
            f"{qualified:>9} | "
            f"{price:10.2f} | "
            f"{market_open:>8} | "
            f"{status_note:<20}"
        )

    print("\n--- ORDER PREVIEW ---\n")

    header_2 = f"{'ETF':5} | {'Target%':>7} | {'Raw':>9} | {'Chosen':>6} | {'Spent':>10} | {'Note':<15}"
    print(header_2)
    print("-" * len(header_2))

    for idx, symbol in enumerate(symbols):
        target_pct = etf_config[symbol]["target_weight"] * 100
        raw_val = raw[symbol]
        chosen = shares[symbol]
        spent_val = spent[symbol]

        note = "normal"

        if topup["needed"] and symbol == topup["symbol"]:
            note = "top-up pending"
        elif len(symbols) == 3 and idx == 0:
            rounded_down = diagnostics.get(f"{symbol.lower()}_rounded_down", False)
            note = "rounded down" if rounded_down else "normal"

        print(
            f"{symbol:5} | "
            f"{target_pct:7.1f}% | "
            f"{raw_val:9.4f} | "
            f"{chosen:6} | "
            f"{spent_val:10.2f} | "
            f"{note:<15}"
        )

    print("-" * len(header_2))

    # --------------------------------------------------------
    # SUMMARY (HORIZONTAL)
    # --------------------------------------------------------
    summary_parts = []

    for symbol in symbols:
        summary_parts.append(f"{symbol}: {actual_pct[symbol]:.2f}%")

    summary_parts.append(f"TOTAL: {totals['total_spent']:.2f} {account_currency}")
    summary_parts.append(f"LEFT: {totals['leftover_cash']:.2f} {account_currency}")

    print("\nSUMMARY | " + " | ".join(summary_parts))
    print("Top-up triggered:", "YES" if topup["needed"] else "NO")

    if not passes_cash_rule:
        print("\nAccount blocked for execution.")
        print(
            f"Reason: available cash is below minimum threshold "
            f"({account_currency} {min_cash_required:.2f})."
        )

    if market_blocked:
        print("\nAccount blocked for execution.")
        print("Reason: one or more ETFs are currently outside market hours.")

    # --------------------------------------------------------
    # BUILD EXECUTION PLAN
    # --------------------------------------------------------
    orders = []

    for symbol in symbols:
        if shares[symbol] <= 0:
            continue

        orders.append(
            {
                "symbol": symbol,
                "contract": qualified_contracts[symbol],
                "quantity": shares[symbol],
            }
        )

    pending_followup = None

    if passes_cash_rule and topup["needed"] and pending_topup_enabled(account_settings):
        pending_cash_reference = topup.get(
            "remaining_cash_before_order",
            topup.get("remaining_cash_before_etf3", cash),
        )

        print("\n--- PENDING TOP-UP REQUIRED ---")
        print(f"{topup['symbol']} was NOT bought.")
        print(
            f"Remaining cash before {topup['symbol']}: "
            f"{account_currency} {pending_cash_reference:.2f}"
        )
        print(
            f"Top up needed to reach {topup['target_shares']} shares: "
            f"{account_currency} {topup['topup_amount']:.2f}"
        )

        if EXECUTION_MODE == "execute" and BUY_CONFIRMED:
            pending_data = {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "account_name": account_name,
                "account_id": account_id,
                "symbol": topup["symbol"],
                "target_shares": topup["target_shares"],
                "remaining_cash_before_order": pending_cash_reference,
                "topup_amount_at_creation": topup["topup_amount"],
                "status": "waiting_for_topup",
            }

            save_pending_topup(account_name, pending_data)
            print("A pending top-up file has been saved.")
        else:
            print("Preview only: pending top-up file was NOT saved.")

    if (
        orders
        and passes_cash_rule
        and not market_blocked
        and EXECUTION_MODE == "execute"
        and BUY_CONFIRMED
    ):
        execution_queue.append(
            {
                "account_name": account_name,
                "account_id": account_id,
                "account_currency": account_currency,
                "orders": orders,
                "pending_followup": pending_followup,
            }
        )
    elif orders:
        if EXECUTION_MODE != "execute":
            print("\nPreview only: EXECUTION_MODE is not 'execute'. No orders will be placed.")
        elif not BUY_CONFIRMED:
            print("\nPreview only: no 'buy' command given. No orders will be placed.")

# ------------------------------------------------------------
# EXECUTION PHASE
# ------------------------------------------------------------
print("\n============================================================")
print("EXECUTION PHASE")
print("============================================================")

if not execution_queue:
    print("No approved orders to place.")
else:
    for plan in execution_queue:
        print("\n------------------------------------------------------------")
        print(f"Executing account: {plan['account_name']}")
        print("------------------------------------------------------------")

        for order in plan["orders"]:
            symbol = order["symbol"]
            contract = order["contract"]
            quantity = order["quantity"]

            trade = place_market_order(
                ib=ib,
                contract=contract,
                quantity=quantity,
                account_id=plan["account_id"],
            )

            order["trade"] = trade
            order["final_status"] = wait_for_order_status(ib, trade)

        # --------------------------------------------------------
        # EXECUTION SUMMARY TABLE
        # --------------------------------------------------------
        print("\n--- EXECUTION SUMMARY ---\n")

        header = f"{'ETF':5} | {'Shares':>6} | {'Avg Price':>10} | {'Total':>10}"
        print(header)
        print("-" * len(header))

        total_spent = 0.0

        for order in plan["orders"]:
            symbol = order["symbol"]
            trade = order["trade"]

            filled = trade.orderStatus.filled
            avg_price = trade.orderStatus.avgFillPrice
            total = filled * avg_price

            total_spent += total

            print(
                f"{symbol:5} | "
                f"{filled:6.0f} | "
                f"{avg_price:10.2f} | "
                f"{total:10.2f}"
            )

        print("-" * len(header))
        print(f"{'TOTAL':5} | {'':6} | {'':10} | {total_spent:10.2f}")

        if plan["pending_followup"] and plan["pending_followup"]["type"] == "clear_pending_topup":
            clear_pending_topup(plan["account_name"])
            print("Pending top-up file cleared.")


# ------------------------------------------------------------
# CLEAN SHUTDOWN
# ------------------------------------------------------------
ib.disconnect()
print("\nDisconnected from IBKR.")