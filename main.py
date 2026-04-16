from datetime import datetime, timezone

from broker import connect_ib, get_account_cash, qualify_etf_contracts, get_etf_prices
from allocator import allocate_three_etf_portfolio
from pending_topup import (
    load_pending_topup,
    save_pending_topup,
    clear_pending_topup,
    is_pending_topup_expired,
    pending_topup_age_days,
)
from config import (
    ACCOUNTS,
    TARGET_ACCOUNT_NAME,
    TEST_CASH_OVERRIDE,
    ETF3_TOPUP_TRIGGER,
    EXECUTION_MODE,
)

# ------------------------------------------------------------
# LOAD ACCOUNT SETTINGS FROM CONFIG
# ------------------------------------------------------------
account_settings = ACCOUNTS[TARGET_ACCOUNT_NAME]
account_id = account_settings["account_id"]
account_currency = account_settings["currency"]
etf_config = account_settings["etfs"]

print(f"Running bot for account: {TARGET_ACCOUNT_NAME}")

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

        # Only fetch the pending ETF price
        pending_symbol = pending["symbol"]
        qualified_contracts = qualify_etf_contracts(ib, etf_config, symbols=[pending_symbol])
        prices = get_etf_prices(ib, qualified_contracts)

        current_price = prices[pending_symbol]
        required_cash_now = pending["target_shares"] * current_price
        shortfall = required_cash_now - real_cash

        print(f"\nCurrent {pending_symbol} price: {account_currency} {current_price:.2f}")
        print(f"Cash needed now for {pending['target_shares']} shares: {account_currency} {required_cash_now:.2f}")

        if shortfall <= 0:
            print("\nPending top-up is now fully funded.")
            print("Would buy:")
            print(f"{pending_symbol}: {pending['target_shares']} shares ({account_currency} {required_cash_now:.2f})")

            if EXECUTION_MODE == "dry_run":
                print("\nDry-run mode: simulating successful EGLN follow-up.")
                clear_pending_topup()
                print("Pending top-up file has been deleted.")
            else:
                print("\nLive execution not implemented yet.")
        else:
            print("\nPending top-up is still NOT fully funded.")
            print(f"Additional cash still needed: {account_currency} {shortfall:.2f}")

        ib.disconnect()
        raise SystemExit


print("Connecting to IBKR...")
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
# GET ETF PRICES
# ------------------------------------------------------------
print("\nQualifying ETF contracts...")
qualified_contracts = qualify_etf_contracts(ib, etf_config)

for symbol in qualified_contracts:
    print(f"{symbol}: OK")

print("\nFetching ETF prices...")
prices = get_etf_prices(ib, qualified_contracts)

for symbol, price in prices.items():
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

print("\n--- DRY RUN ALLOCATION ---")
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

print("\nAchieved allocation of invested amount:")
print(f"{symbol_1}: {actual_pct[symbol_1]:.2f}%")
print(f"{symbol_2}: {actual_pct[symbol_2]:.2f}%")
print(f"{symbol_3}: {actual_pct[symbol_3]:.2f}%")

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