"""
Offline regression test for the pre-flight gate.

No Gateway, no network, no real orders. Run it any time with:

    python test_preflight.py

An account's orders are placed together, so a leg IBKR refuses at placement
time leaves the account holding only the legs that succeeded and off its
target weights. That happened on 2026-10-01: Pension filled VUAA and IMAE
while EGLN was cancelled with Error 478.

Pre-flight resolves and checks every leg before any of them is sent, and the
account places nothing if any check fails.
"""

from ib_async import Stock, Contract

import account_processor
from config import ORDER_COMMISSION_BUFFER


# ------------------------------------------------------------
# FAKES
# ------------------------------------------------------------
class FakeDetails:
    minTick = 0.01
    marketRuleIds = ""
    validExchanges = ""


class FakeIB:
    """
    `bad_symbol` is the leg whose SMART routing resolves to another
    instrument, reproducing the Error 478 shape. `cash` is what the account
    holds.
    """

    def __init__(self, cash=10_000.0, bad_symbol=None, cash_unreadable=False):
        self.cash = cash
        self.bad_symbol = bad_symbol
        self.cash_unreadable = cash_unreadable
        self.placed = []

    def qualifyContracts(self, contract):
        resolved = Contract(
            secType=contract.secType,
            conId=contract.conId,
            exchange="SMART",
            currency=contract.currency,
        )
        resolved.symbol = SYMBOL_BY_CONID[contract.conId]

        if resolved.symbol == self.bad_symbol:
            resolved.symbol = "PPFB"  # a different instrument

        return [resolved]

    def reqContractDetails(self, contract):
        return [FakeDetails()]

    def accountSummary(self):
        if self.cash_unreadable:
            return []

        class Item:
            account = "U1"
            tag = "TotalCashValue"
            currency = "EUR"
            value = str(self.cash)

        return [Item()]

    def placeOrder(self, contract, order):
        self.placed.append((contract.conId, order.totalQuantity, order.lmtPrice))

        class Trade:
            class orderStatus:
                status = "Filled"
                filled = order.totalQuantity
                avgFillPrice = order.lmtPrice

        return Trade()

    def sleep(self, seconds):
        pass


LEGS = [("VUAA", 1), ("IMAE", 2), ("EGLN", 3)]
SYMBOL_BY_CONID = {conid: sym for sym, conid in LEGS}


def make_plan(prices_and_qty):
    orders = []

    for symbol, quantity, limit_price in prices_and_qty:
        contract = Stock(symbol, "SMART", "EUR")
        contract.conId = dict(LEGS)[symbol]
        contract.primaryExchange = "AEB"
        orders.append({
            "symbol": symbol,
            "contract": contract,
            "quantity": quantity,
            "limit_price": limit_price,
        })

    return {
        "account_name": "Pension",
        "account_id": "U1",
        "account_currency": "EUR",
        "orders": orders,
        "pending_followup": None,
    }


PENSION = [("VUAA", 9, 131.28), ("IMAE", 6, 101.91), ("EGLN", 1, 71.31)]


# ------------------------------------------------------------
# TESTS
# ------------------------------------------------------------
def test_healthy_account_places_every_leg():
    ib = FakeIB(cash=10_000.0)
    account_processor.execute_plan(ib, [make_plan(PENSION)])

    assert len(ib.placed) == 3, ib.placed
    assert {c for c, _, _ in ib.placed} == {1, 2, 3}
    print("  a healthy account places every leg                              OK")


def test_one_bad_leg_places_nothing():
    """The 2026-10-01 case: EGLN unroutable, VUAA and IMAE fine."""
    ib = FakeIB(cash=10_000.0, bad_symbol="EGLN")
    account_processor.execute_plan(ib, [make_plan(PENSION)])

    assert ib.placed == [], \
        f"placed {len(ib.placed)} legs despite a failing leg, account is now unbalanced"
    print("  one unroutable leg stops the whole account, nothing placed      OK")


def test_insufficient_cash_places_nothing():
    """
    Cash that covers the quote but not the tick-snapped limit prices.
    main.py sizes on the unsnapped price, so this is the gap pre-flight closes.
    """
    cost = sum(q * p for _, q, p in PENSION) + ORDER_COMMISSION_BUFFER * 3
    ib = FakeIB(cash=cost - 5.00)
    account_processor.execute_plan(ib, [make_plan(PENSION)])

    assert ib.placed == [], f"placed orders the account cannot pay for: {ib.placed}"
    print("  a plan that exceeds available cash places nothing               OK")


def test_unreadable_cash_places_nothing():
    ib = FakeIB(cash_unreadable=True)
    account_processor.execute_plan(ib, [make_plan(PENSION)])

    assert ib.placed == [], "placed orders without being able to check the cash"
    print("  an unreadable cash balance places nothing                       OK")


def test_one_account_failing_does_not_block_another():
    """Accounts stay independent: Otto filled while Pension was skipped."""
    ib = FakeIB(cash=10_000.0, bad_symbol="EGLN")

    otto = make_plan([("IMAE", 1, 101.91)])
    otto["account_name"] = "Otto"

    account_processor.execute_plan(ib, [make_plan(PENSION), otto])

    assert len(ib.placed) == 1 and ib.placed[0][0] == 2, ib.placed
    print("  a failed account does not stop the next one                     OK")


if __name__ == "__main__":
    print("\nPre-flight gate\n" + "-" * 66)
    test_healthy_account_places_every_leg()
    test_one_bad_leg_places_nothing()
    test_insufficient_cash_places_nothing()
    test_unreadable_cash_places_nothing()
    test_one_account_failing_does_not_block_another()
    print("-" * 66)
    print("All pre-flight tests passed.\n")
