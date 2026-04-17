# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------

# Standard library
import sys
from datetime import datetime, timezone

# Internal modules
from broker import (
    connect_ib,
    get_account_cash,
    qualify_etf_contracts,
    get_etf_prices,
    is_contract_open_now,
    place_market_order,
    wait_for_order_status,
)
from allocator import allocate_three_etf_portfolio
from pending_topup import (
    load_pending_topup,
    save_pending_topup,
    clear_pending_topup,
    is_pending_topup_expired,
    pending_topup_age_days,
)

# Configuration
from config import (
    ACCOUNTS,
    TARGET_ACCOUNT_NAME,
    TEST_CASH_OVERRIDE,
    ETF3_TOPUP_TRIGGER,
    EXECUTION_MODE,
    IB_ENVIRONMENT,
)


# ------------------------------------------------------------
# LOAD ACCOUNT SETTINGS FROM CONFIG
# ------------------------------------------------------------
account_settings = ACCOUNTS[TARGET_ACCOUNT_NAME]
account_id = account_settings["account_ids"][IB_ENVIRONMENT]
account_currency = account_settings["currency"]
etf_config = account_settings["etfs"]


# ------------------------------------------------------------
# RUNTIME MODE
# ------------------------------------------------------------
# Usage:
# - python main.py      -> preview only
# - python main.py buy  -> preview + execute (if enabled)
BUY_CONFIRMED = len(sys.argv) > 1 and sys.argv[1].lower() == "buy"

print(f"Running bot for account: {TARGET_ACCOUNT_NAME}")
print(f"Environment: {IB_ENVIRONMENT}")
print(f"Execution mode: {EXECUTION_MODE}")
print(f"Buy confirmed: {BUY_CONFIRMED}")


# ------------------------------------------------------------
# CHECK FOR A PENDING TOP-UP FIRST
# ------------------------------------------------------------
# If a pending top-up exists and is still valid, we do NOT
# recalculate ETF1 and ETF2. We only check whether ETF3 can
# now be completed.
pending = load_pending_topup()

if pending and pending["account_name"] == TARGET_ACCOUNT_NAME:
    if is_pending_topup_expired(pending):
        print("\nPending top-up found, but it has expired.")
        print("Deleting expired pending item and continuing with a normal run.")
        clear_pending_topup()
    else:
        print("\nPending top-up found.")
        print(f"Pending symbol: {pending['symbol']}")
        print(f"Target shares: {pending['target_shares']}")
        print(f"Pending age: {pending_topup_age_days(pending):.2f} days")

        print("\nConnecting to IBKR...")
        ib = connect_ib()
        print("Connected!")

        # For pending follow-up, always use REAL cash.
        # We do not use the test override here.
        real_cash = get_account_cash(ib, account_id, currency=account_currency)
        print(f"\n{TARGET_ACCOUNT_NAME} real cash: {account_currency} {real_cash:.2f}")

        pending_symbol = pending["symbol"]
        qualified_contracts = qualify_etf_contracts(ib, etf_config, symbols=[pending_symbol])
        prices = get_etf_prices(ib, qualified_contracts)

        current_price = prices[pending_symbol]
        required_cash_now = pending["target_shares"] * current_price
        shortfall = required_cash_now - real_cash

        print(f"\nCurrent {pending_symbol} price: {account_currency} {current_price:.2f}")
        print(f"Total needed for {pending_symbol}: {account_currency} {required_cash_now:.2f}")
        print(f"Current cash: {account_currency} {real_cash:.2f}")

        if shortfall <= 0:
            print("\nPending top-up is now fully funded.")

            contract = qualified_contracts[pending_symbol]
            market_open, market_reason = is_contract_open_now(ib, contract)

            print(f"\nMarket check for {pending_symbol}: {'OPEN' if market_open else 'CLOSED'}")
            print(market_reason)

            if not market_open:
                print("Action taken: no order placed.")
                print("Reason: market is currently closed.")
                print("Next step: rerun the script during market hours.")
                print("Pending top-up file has been kept.")
                ib.disconnect()
                raise SystemExit

            print("\nWould buy:")
            print(f"{pending_symbol}: {pending['target_shares']} shares ({account_currency} {required_cash_now:.2f})")

            if EXECUTION_MODE != "execute":
                print("\nPreview only: EXECUTION_MODE is not 'execute'. No orders will be placed.")
            elif not BUY_CONFIRMED:
                print("\nPreview only: no 'buy' command given. No order will be placed.")
            else:
                print("\nBuy command detected and execute mode enabled.")
                print(f"Submitting market order for {pending_symbol}...")

                trade = place_market_order(
                    ib=ib,
                    contract=contract,
                    quantity=pending["target_shares"],
                    account_id=account_id,
                )

                status = wait_for_order_status(ib, trade)

                print(f"{pending_symbol} order status: {status}")
                print(f"{pending_symbol} filled: {trade.orderStatus.filled}")
                print(f"{pending_symbol} remaining: {trade.orderStatus.remaining}")

                if trade.orderStatus.avgFillPrice:
                    print(
                        f"{pending_symbol} avg fill price: "
                        f"{account_currency} {trade.orderStatus.avgFillPrice:.2f}"
                    )

                if status in {"Filled", "Submitted", "PreSubmitted", "PendingSubmit"}:
                    clear_pending_topup()
                    print("Pending top-up file cleared.")
                else:
                    print("Pending top-up file kept because order did not complete cleanly.")
        else:
            print("\nPending top-up is still NOT fully funded.")
            print(f"Still missing: {account_currency} {shortfall:.2f}")

        ib.disconnect()
        raise SystemExit


# ------------------------------------------------------------
# CONNECT TO IBKR
# ------------------------------------------------------------
print("\nConnecting to IBKR...")
ib = connect_ib()
print("Connected!")


# ------------------------------------------------------------
# GET CASH
# ------------------------------------------------------------
real_cash = get_account_cash(ib, account_id, currency=account_currency)

if TEST_CASH_OVERRIDE is not None:
    cash = float(TEST_CASH_OVERRIDE)
    print(f"\n{TARGET_ACCOUNT_NAME} real cash: {account_currency} {real_cash:.2f}")
    print(f"{TARGET_ACCOUNT_NAME} test cash override: {account_currency} {cash:.2f}")
else:
    cash = real_cash
    print(f"\n{TARGET_ACCOUNT_NAME} cash: {account_currency} {cash:.2f}")


# ------------------------------------------------------------
# QUALIFY ETF CONTRACTS
# ------------------------------------------------------------
print("\nQualifying ETF contracts...")
qualified_contracts = qualify_etf_contracts(ib, etf_config)

for symbol in qualified_contracts:
    print(f"{symbol}: OK")


# ------------------------------------------------------------
# FETCH ETF PRICES
# ------------------------------------------------------------
print("\nFetching ETF prices...")

try:
    prices = get_etf_prices(ib, qualified_contracts)
except ValueError as e:
    print(f"\nSafety stop while fetching prices: {e}")
    ib.disconnect()
    raise SystemExit

for symbol, price in prices.items():
    if price <= 0:
        print(f"\nSafety stop: invalid price for {symbol}: {price}")
        ib.disconnect()
        raise SystemExit

    print(f"{symbol}: {account_currency} {price:.2f}")


# ------------------------------------------------------------
# RUN ALLOCATION
# ------------------------------------------------------------
result = allocate_three_etf_portfolio(
    cash=cash,
    etf_config=etf_config,
    prices=prices,
    etf3_topup_trigger=ETF3_TOPUP_TRIGGER,
)

symbols = result["symbols"]
symbol_1, symbol_2, symbol_3 = symbols

shares = result["shares"]
spent = result["spent"]
raw = result["raw"]
diagnostics = result["diagnostics"]
topup = result["topup"]
totals = result["totals"]
actual_pct = result["actual_pct"]

print("\n--- ORDER PREVIEW ---")
print(f"{symbol_1} target: {etf_config[symbol_1]['target_weight']*100:.0f}%")
print(f"{symbol_2} target: {etf_config[symbol_2]['target_weight']*100:.0f}%")
print(f"{symbol_3} target: {etf_config[symbol_3]['target_weight']*100:.0f}%")

print("\nRounding diagnostics:")
print(f"{symbol_1} raw shares: {raw[symbol_1]:.4f}")
print(f"{symbol_1} chosen shares: {shares[symbol_1]}")
print(f"{symbol_1} rounded down: {diagnostics[f'{symbol_1.lower()}_rounded_down']}")

print(f"{symbol_2} raw shares: {raw[symbol_2]:.4f}")
print(f"{symbol_2} chosen shares: {shares[symbol_2]}")

print(f"{symbol_3} raw shares from remainder: {raw[symbol_3]:.4f}")
print(f"{symbol_3} fractional part: {diagnostics[f'{symbol_3.lower()}_fractional_part']:.4f}")

print("\nWould buy:")
print(f"{symbol_1}: {shares[symbol_1]} shares ({account_currency} {spent[symbol_1]:.2f})")
print(f"{symbol_2}: {shares[symbol_2]} shares ({account_currency} {spent[symbol_2]:.2f})")
print(f"{symbol_3}: {shares[symbol_3]} shares ({account_currency} {spent[symbol_3]:.2f})")

print(f"\nTotal spent: {account_currency} {totals['total_spent']:.2f}")
print(f"Leftover cash: {account_currency} {totals['leftover_cash']:.2f}")
print(f"Planned spend check vs available cash: {account_currency} {cash:.2f}")

if totals["total_spent"] > cash:
    print("\nSafety stop: planned spend exceeds available cash.")
    ib.disconnect()
    raise SystemExit

print("\nAchieved allocation of invested amount:")
print(f"{symbol_1}: {actual_pct[symbol_1]:.2f}%")
print(f"{symbol_2}: {actual_pct[symbol_2]:.2f}%")
print(f"{symbol_3}: {actual_pct[symbol_3]:.2f}%")


# ------------------------------------------------------------
# CHECK MARKET HOURS FOR PLANNED BUYS
# ------------------------------------------------------------
planned_symbols = [symbol for symbol in symbols if shares[symbol] > 0]

if planned_symbols:
    print("\n--- MARKET HOURS CHECK ---")
    closed_symbols = []

    for symbol in planned_symbols:
        contract = qualified_contracts[symbol]
        market_open, market_reason = is_contract_open_now(ib, contract)

        print(f"{symbol}: {'OPEN' if market_open else 'CLOSED'}")
        print(f"  {market_reason}")

        if not market_open:
            closed_symbols.append(symbol)

    if BUY_CONFIRMED and EXECUTION_MODE == "execute" and closed_symbols:
        print("\nBuy request blocked.")
        print("Reason: one or more ETFs are currently outside market hours.")
        print("Action taken: no orders placed.")
        print(f"Blocked ETFs: {', '.join(closed_symbols)}")

        ib.disconnect()
        raise SystemExit


# ------------------------------------------------------------
# FINAL EXECUTION DECISION
# ------------------------------------------------------------
if EXECUTION_MODE != "execute":
    print("\nPreview only: EXECUTION_MODE is not 'execute'. No orders will be placed.")
elif not BUY_CONFIRMED:
    print("\nPreview only: no 'buy' command given. No orders will be placed.")
else:
    print("\nBuy command detected and execute mode enabled.")
    print("Submitting market orders...")

    execution_plan = []

    for symbol in symbols:
        if shares[symbol] <= 0:
            continue

        # If ETF3 triggered top-up logic, do not buy it now
        if symbol == topup["symbol"] and topup["needed"]:
            continue

        execution_plan.append(symbol)

    if not execution_plan:
        print("No orders to place.")
    else:
        for symbol in execution_plan:
            contract = qualified_contracts[symbol]
            quantity = shares[symbol]

            print(f"\nPlacing BUY order for {symbol}: {quantity} shares")

            trade = place_market_order(
                ib=ib,
                contract=contract,
                quantity=quantity,
                account_id=account_id,
            )

            status = wait_for_order_status(ib, trade)

            print(f"{symbol} order status: {status}")
            print(f"{symbol} filled: {trade.orderStatus.filled}")
            print(f"{symbol} remaining: {trade.orderStatus.remaining}")

            if trade.orderStatus.avgFillPrice:
                print(
                    f"{symbol} avg fill price: "
                    f"{account_currency} {trade.orderStatus.avgFillPrice:.2f}"
                )


# ------------------------------------------------------------
# CREATE A PENDING TOP-UP IF ETF3 HIT THE X.75+ RULE
# ------------------------------------------------------------
if topup["needed"]:
    pending_data = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "account_name": TARGET_ACCOUNT_NAME,
        "account_id": account_id,
        "symbol": topup["symbol"],
        "target_shares": topup["target_shares"],
        "remaining_cash_before_etf3": topup["remaining_cash_before_etf3"],
        "topup_amount_at_creation": topup["topup_amount"],
        "status": "waiting_for_topup",
    }

    save_pending_topup(pending_data)

    print("\n--- PENDING TOP-UP CREATED ---")
    print(f"{topup['symbol']} was NOT bought.")
    print(f"Remaining cash before {topup['symbol']}: {account_currency} {topup['remaining_cash_before_etf3']:.2f}")
    print(f"Top up needed to reach {topup['target_shares']} shares: {account_currency} {topup['topup_amount']:.2f}")
    print("A pending top-up file has been saved.")
    print("When you rerun the script later, it will only check this pending ETF.")

ib.disconnect()