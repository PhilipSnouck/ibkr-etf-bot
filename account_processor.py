# ------------------------------------------------------------
# ACCOUNT PROCESSOR HELPERS
# ------------------------------------------------------------

from datetime import datetime, timezone
from config import (
    ORDER_COMMISSION_BUFFER,
    MARKET_ORDER_BUFFER,
    DEFAULT_LIMIT_ORDER_MARKUP,
)
from broker import (
    get_account_cash,
    qualify_etf_contracts,
    get_etf_prices,
    is_contract_open_now,
    place_order,
    wait_for_order_status,
)

from pending_topup import (
    load_pending_topup,
    save_pending_topup,
    clear_pending_topup,
    is_pending_topup_expired,
    pending_topup_age_days,
)

from rules import (
    passes_min_cash_rule,
    pending_topup_enabled,
)


# ------------------------------------------------------------
# PENDING TOP-UP HANDLER
# ------------------------------------------------------------
def process_pending_topup(
    ib,
    account_name,
    account_settings,
    account_id,
    account_currency,
    etf_config,
    execution_queue,
    EXECUTION_MODE,
    BUY_CONFIRMED,
):
    if not pending_topup_enabled(account_settings):
        return False

    pending = load_pending_topup(account_name)

    if not pending:
        return False

    if is_pending_topup_expired(pending):
        print("\nPending top-up found, but it has expired.")
        print("Deleting expired pending item and continuing with a normal run.")
        clear_pending_topup(account_name)
        return False

    print("\nPending top-up found.")

    real_cash = get_account_cash(ib, account_id, currency=account_currency)

    pending_symbol = pending["symbol"]
    qualified_contracts = qualify_etf_contracts(
        ib,
        etf_config,
        symbols=[pending_symbol],
    )

    if pending_symbol not in qualified_contracts:
        print(
            f"\nSafety stop: could not qualify contract for pending ETF "
            f"{pending_symbol}."
        )
        print("Pending top-up file has been kept.")
        return True

    prices = get_etf_prices(ib, qualified_contracts)

    contract = qualified_contracts[pending_symbol]
    market_open, market_reason = is_contract_open_now(ib, contract)

    current_price = prices.get(pending_symbol)

    if current_price is None or current_price <= 0:
        print(
            f"\nSafety stop: no valid market price available for pending ETF "
            f"{pending_symbol} (after delayed streaming retry)."
        )
        print("Pending top-up file has been kept.")
        return True

    order_type = account_settings.get("order_type", "market")

    if order_type == "limit":
        limit_order_markup = account_settings.get(
            "limit_order_markup",
            DEFAULT_LIMIT_ORDER_MARKUP,
        )
        effective_order_price = round(
            current_price * (1 + limit_order_markup),
            2,
        )
        extra_order_buffer = 0.0
    else:
        effective_order_price = current_price
        extra_order_buffer = MARKET_ORDER_BUFFER

    required_cash_now = (
        pending["target_shares"] * effective_order_price
        + ORDER_COMMISSION_BUFFER
        + extra_order_buffer
    )
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
            return True

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
                            "order_type": account_settings.get("order_type", "market"),
                            "limit_price": round(
                                current_price
                                * (
                                    1
                                    + account_settings.get(
                                        "limit_order_markup",
                                        DEFAULT_LIMIT_ORDER_MARKUP,
                                    )
                                ),
                                2,
                            )
                            if account_settings.get("order_type", "market") == "limit"
                            else None,
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

    return True


# ------------------------------------------------------------
# PRINT HELPERS
# ------------------------------------------------------------
def print_market_status(symbols, qualified_contracts, prices, market_status):
    print("\n--- MARKET / INSTRUMENT STATUS ---\n")

    header = f"{'ETF':5} | {'Qualified':>9} | {'Price':>10} | {'Market':>8} | {'Status note':<20}"
    print(header)
    print("-" * len(header))

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


def print_order_preview(symbols, etf_config, raw, shares, spent, diagnostics, topup):
    print("\n--- ORDER PREVIEW ---\n")

    header = f"{'ETF':5} | {'Target%':>7} | {'Raw':>9} | {'Chosen':>6} | {'Spent':>10} | {'Note':<15}"
    print(header)
    print("-" * len(header))

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

    print("-" * len(header))


def print_summary(symbols, actual_pct, totals, account_currency, passes_cash_rule, min_cash_required, market_blocked):
    summary_parts = []

    for symbol in symbols:
        summary_parts.append(f"{symbol}: {actual_pct[symbol]:.2f}%")

    summary_parts.append(f"TOTAL: {totals['total_spent']:.2f} {account_currency}")
    summary_parts.append(f"LEFT: {totals['leftover_cash']:.2f} {account_currency}")

    print("\nSUMMARY | " + " | ".join(summary_parts))

    if not passes_cash_rule:
        print("\nAccount blocked for execution.")
        print(
            f"Reason: available cash is below minimum threshold "
            f"({account_currency} {min_cash_required:.2f})."
        )

    if market_blocked:
        print("\nAccount blocked for execution.")
        print("Reason: one or more ETFs are currently outside market hours.")


# ------------------------------------------------------------
# EXECUTION HELPER
# ------------------------------------------------------------
def execute_plan(ib, execution_queue):
    BLUE = "\033[94m"
    RESET = "\033[0m"

    print(f"\n{BLUE}============================================================")
    print("EXECUTION PHASE")
    print(f"============================================================{RESET}")

    if not execution_queue:
        print("No approved orders to place.")
        return

    for plan in execution_queue:
        print("\n------------------------------------------------------------")
        print(f"Executing account: {plan['account_name']}")
        print("------------------------------------------------------------")

        if not plan["orders"]:
            print("No immediate orders to place for this account.")

        for order in plan["orders"]:
            trade = place_order(
                ib=ib,
                contract=order["contract"],
                quantity=order["quantity"],
                account_id=plan["account_id"],
                order_type=order.get("order_type", "market"),
                limit_price=order.get("limit_price"),
            )

            order["trade"] = trade
            order["final_status"] = wait_for_order_status(ib, trade)

        if plan["orders"]:
            print("\n--- EXECUTION SUMMARY ---\n")

            header = f"{'ETF':5} | {'Shares':>6} | {'Avg Price':>10} | {'Total':>10}"
            print(header)
            print("-" * len(header))

            total_spent = 0.0

            for order in plan["orders"]:
                trade = order["trade"]
                filled = trade.orderStatus.filled
                avg_price = trade.orderStatus.avgFillPrice
                total = filled * avg_price

                total_spent += total

                print(
                    f"{order['symbol']:5} | "
                    f"{filled:6.0f} | "
                    f"{avg_price:10.2f} | "
                    f"{total:10.2f}"
                )

            print("-" * len(header))
            print(f"{'TOTAL':5} | {'':6} | {'':10} | {total_spent:10.2f}")

        all_orders_filled = all(
            order.get("final_status") == "Filled"
            for order in plan["orders"]
        )

        if plan["pending_followup"]:
            followup_type = plan["pending_followup"]["type"]

            if followup_type == "save_pending_topup":
                if all_orders_filled:
                    pending_data = {
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                        **plan["pending_followup"]["data"],
                    }
                    save_pending_topup(plan["account_name"], pending_data)
                    print("Pending top-up file saved.")
                else:
                    print("Pending top-up file NOT saved because execution was not fully filled.")

            elif followup_type == "clear_pending_topup":
                if all_orders_filled:
                    clear_pending_topup(plan["account_name"])
                    print("Pending top-up file cleared.")
                else:
                    print("Pending top-up file kept because execution was not fully filled.")