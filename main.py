# ------------------------------------------------------------
# MAIN ORCHESTRATOR
# ------------------------------------------------------------
# This script runs the ETF bot across all enabled accounts in
# one go.
#
# Responsibilities:
# - connect to IBKR
# - iterate through enabled accounts from config.py
# - delegate per-account processing
# - optionally execute approved orders
# ------------------------------------------------------------

import sys

from broker import (
    connect_ib,
    get_account_cash,
    qualify_etf_contracts,
    get_etf_prices,
    is_contract_open_now,
    calc_limit_price,
)

from allocator_registry import get_allocator

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
    EXECUTION_MODE,
    IB_ENVIRONMENT,
    DEFAULT_LIMIT_ORDER_MARKUP,
    ORDER_COMMISSION_BUFFER,
)

from account_processor import (
    process_pending_topup,
    print_market_status,
    print_order_preview,
    print_summary,
    execute_plan,
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
    pending_handled = process_pending_topup(
        ib=ib,
        account_name=account_name,
        account_settings=account_settings,
        account_id=account_id,
        account_currency=account_currency,
        etf_config=etf_config,
        execution_queue=execution_queue,
        EXECUTION_MODE=EXECUTION_MODE,
        BUY_CONFIRMED=BUY_CONFIRMED,
    )

    if pending_handled:
        continue

    # --------------------------------------------------------
    # GET CASH
    # --------------------------------------------------------
    real_cash = get_account_cash(ib, account_id, currency=account_currency)
    planned_allocation_cash = account_settings.get("planned_allocation_cash")

    if real_cash is None:
        print(
            f"\nSafety stop: could not retrieve cash balance for account "
            f"{account_name}."
        )
        continue

    if planned_allocation_cash is not None:
        planned_allocation_cash = float(planned_allocation_cash)

        if planned_allocation_cash <= 0:
            print(
                f"\nSafety stop: planned_allocation_cash must be greater than 0 "
                f"for account {account_name}."
            )
            continue

        if planned_allocation_cash > real_cash:
            if BUY_CONFIRMED:
                print(
                    f"\nSafety stop: planned allocation cash exceeds real available cash "
                    f"for account {account_name}."
                )
                print(f"Real cash: {account_currency} {real_cash:.2f}")
                print(
                    f"Planned allocation cash: "
                    f"{account_currency} {planned_allocation_cash:.2f}"
                )
                continue
            else:
                print(
                    f"\nWarning: planned allocation cash exceeds real available cash "
                    f"for account {account_name}."
                )
                print(
                    "Preview mode: using planned allocation cash for simulation."
                )

        cash = planned_allocation_cash
        print(f"\n{account_name} real cash: {account_currency} {real_cash:.2f}")
        print(
            f"{account_name} planned allocation cash: "
            f"{account_currency} {planned_allocation_cash:.2f}"
        )
        print(f"{account_name} usable cash for this run: {account_currency} {cash:.2f}")

    else:
        cash = real_cash
        print(f"\n{account_name} real cash: {account_currency} {real_cash:.2f}")
        print(f"{account_name} usable cash for this run: {account_currency} {cash:.2f}")

    # --------------------------------------------------------
    # ACCOUNT-LEVEL CASH RULES
    # --------------------------------------------------------
    passes_cash_rule, min_cash_required = passes_min_cash_rule(account_settings, cash)

    # --------------------------------------------------------
    # QUALIFY ETF CONTRACTS
    # --------------------------------------------------------
    qualified_contracts = qualify_etf_contracts(ib, etf_config)

    missing_symbols = [
        symbol for symbol in etf_config
        if symbol not in qualified_contracts
    ]

    if missing_symbols:
        print(
            f"\nSafety stop: could not qualify contract(s) for account "
            f"{account_name}: {', '.join(missing_symbols)}"
        )
        continue

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
        if price is None or price <= 0:
            print(
                f"\nSafety stop: no valid market price available for {symbol} "
                f"(after delayed streaming retry)."
            )
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

    limit_order_markup = account_settings.get("limit_order_markup", DEFAULT_LIMIT_ORDER_MARKUP)

    if topup["needed"]:
        topup_limit_price = calc_limit_price(prices[topup["symbol"]], limit_order_markup)
        cash_ref = topup.get("remaining_cash_before_etf3", cash)
        topup["topup_amount"] = max(
            topup["target_shares"] * topup_limit_price + ORDER_COMMISSION_BUFFER - cash_ref,
            0.0,
        )

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
    print_market_status(
        symbols=symbols,
        qualified_contracts=qualified_contracts,
        prices=prices,
        market_status=market_status,
    )

    print_order_preview(
        symbols=symbols,
        etf_config=etf_config,
        raw=raw,
        shares=shares,
        spent=spent,
        diagnostics=diagnostics,
        topup=topup,
    )

    print_summary(
        symbols=symbols,
        actual_pct=actual_pct,
        totals=totals,
        account_currency=account_currency,
        passes_cash_rule=passes_cash_rule,
        min_cash_required=min_cash_required,
        market_blocked=market_blocked,
    )

    print("Top-up triggered:", "YES" if topup["needed"] else "NO")

     # --------------------------------------------------------
    # BUILD EXECUTION PLAN
    # --------------------------------------------------------
    orders = []

    for symbol in symbols:
        if shares[symbol] <= 0:
            continue

        orders.append({
            "symbol": symbol,
            "contract": qualified_contracts[symbol],
            "quantity": shares[symbol],
            "limit_price": calc_limit_price(prices[symbol], limit_order_markup),
        })

    pending_followup = None

    if passes_cash_rule and topup["needed"] and pending_topup_enabled(account_settings):
        pending_cash_reference = topup.get("remaining_cash_before_etf3", cash)

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
            pending_followup = {
                "type": "save_pending_topup",
                "data": {
                    "account_name": account_name,
                    "account_id": account_id,
                    "symbol": topup["symbol"],
                    "target_shares": topup["target_shares"],
                    "remaining_cash_before_order": pending_cash_reference,
                    "topup_amount_at_creation": topup["topup_amount"],
                    "status": "waiting_for_topup",
                },
            }
            print("Pending top-up file will be saved only after successful execution.")
        else:
            print("Preview only: pending top-up file was NOT saved.")

    if (
        passes_cash_rule
        and not market_blocked
        and EXECUTION_MODE == "execute"
        and BUY_CONFIRMED
    ):
        if orders:
            execution_queue.append(
                {
                    "account_name": account_name,
                    "account_id": account_id,
                    "account_currency": account_currency,
                    "orders": orders,
                    "pending_followup": pending_followup,
                }
            )
        elif pending_followup:
            execution_queue.append(
                {
                    "account_name": account_name,
                    "account_id": account_id,
                    "account_currency": account_currency,
                    "orders": [],
                    "pending_followup": pending_followup,
                }
            )
    elif orders or pending_followup:
        if EXECUTION_MODE != "execute":
            print("\nPreview only: EXECUTION_MODE is not 'execute'. No orders will be placed.")
        elif not BUY_CONFIRMED:
            print("\nPreview only: no 'buy' command given. No orders will be placed.")
# ------------------------------------------------------------
# EXECUTION PHASE
# ------------------------------------------------------------
execute_plan(ib, execution_queue)

# ------------------------------------------------------------
# CLEAN SHUTDOWN
# ------------------------------------------------------------
ib.disconnect()
print("\nDisconnected from IBKR.")