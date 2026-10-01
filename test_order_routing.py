"""
Offline regression test for the SMART routing contract.

No Gateway, no network, no real orders. Run it any time with:

    python test_order_routing.py

Covers Error 478, "Parameters in request conflicts with contract parameters
received by contract id: requested ibLocalSymbol EGLN, from contract PPFB".
place_order used to copy the qualified contract and swap only the exchange,
leaving localSymbol and tradingClass from the listing venue attached. One ETF
is listed as several lines with different values for those fields, so IBKR
saw a contradiction and cancelled the order.

The invariant that matters most here: the bot must never place an order on a
different instrument than the one it priced.
"""

from ib_async import Stock, Contract

import broker


# ------------------------------------------------------------
# FAKES
# ------------------------------------------------------------
class FakeDetails:
    minTick = 0.01
    marketRuleIds = ""
    validExchanges = ""


class FakeIB:
    """
    `resolves_to` controls what IBKR claims the routed conId actually is.
    None means it resolves correctly to the same instrument.
    """

    def __init__(self, resolves_to=None, resolves_nothing=False):
        self.resolves_to = resolves_to
        self.resolves_nothing = resolves_nothing
        self.placed = []

    def qualifyContracts(self, contract):
        if self.resolves_nothing:
            return []

        if self.resolves_to is not None:
            return [self.resolves_to]

        resolved = Contract(
            secType=contract.secType,
            conId=contract.conId,
            exchange="SMART",
            currency=contract.currency,
        )
        resolved.symbol = "EGLN"
        # IBKR fills venue-specific fields back in. The bot must not send these.
        resolved.localSymbol = "EGLN"
        resolved.tradingClass = "ECE3"
        return [resolved]

    def reqContractDetails(self, contract):
        return [FakeDetails()]

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))
        return f"trade:{contract.conId}"


def egln():
    c = Stock("EGLN", "LSEETF", "EUR")
    c.conId = 257200855
    c.primaryExchange = "LSEETF"
    c.localSymbol = "EGLN"
    c.tradingClass = "ECE3"
    return c


# ------------------------------------------------------------
# TESTS
# ------------------------------------------------------------
def test_routed_order_carries_conid_and_no_venue_fields():
    ib = FakeIB()
    broker.place_order(ib, egln(), quantity=1, account_id="U1", limit_price=71.67)

    assert len(ib.placed) == 1, "exactly one order should have been placed"
    sent, order = ib.placed[0]

    assert sent.conId == 257200855, "conId is what pins the instrument"
    assert sent.exchange == "SMART", sent.exchange
    assert sent.currency == "EUR", sent.currency

    # The Error 478 cause: these must not travel with the order.
    assert not getattr(sent, "localSymbol", ""), \
        f"localSymbol {sent.localSymbol!r} was sent, this is what caused Error 478"
    assert not getattr(sent, "tradingClass", ""), \
        f"tradingClass {sent.tradingClass!r} was sent, this is what caused Error 478"
    assert not getattr(sent, "primaryExchange", ""), \
        f"primaryExchange {sent.primaryExchange!r} was sent"

    assert order.action == "BUY" and order.totalQuantity == 1
    print("  routed order sends conId + SMART only, no venue-specific fields  OK")


def test_refuses_when_smart_resolves_to_another_instrument():
    """The failure this function exists to make impossible."""
    impostor = Contract(secType="STK", conId=999999, exchange="SMART", currency="EUR")
    impostor.symbol = "PPFB"

    ib = FakeIB(resolves_to=impostor)

    try:
        broker.place_order(ib, egln(), quantity=1, account_id="U1", limit_price=71.67)
    except ValueError as exc:
        assert "different instrument" in str(exc), str(exc)
        assert not ib.placed, "an order was placed despite the mismatch"
        print("  a SMART resolution to another instrument is refused            OK")
        return

    raise AssertionError("placed an order on a different instrument, no error raised")


def test_refuses_on_currency_mismatch():
    wrong_ccy = Contract(secType="STK", conId=257200855, exchange="SMART", currency="GBP")
    wrong_ccy.symbol = "EGLN"

    ib = FakeIB(resolves_to=wrong_ccy)

    try:
        broker.place_order(ib, egln(), quantity=1, account_id="U1", limit_price=71.67)
    except ValueError as exc:
        assert "currency" in str(exc), str(exc)
        assert not ib.placed
        print("  the same ticker in another currency is refused                 OK")
        return

    raise AssertionError("placed an order in the wrong currency, no error raised")


def test_refuses_when_unqualified_or_unresolvable():
    bare = Stock("EGLN", "LSEETF", "EUR")  # never qualified, so no conId

    try:
        broker.place_order(FakeIB(), bare, quantity=1, account_id="U1", limit_price=71.67)
    except ValueError as exc:
        assert "conId" in str(exc), str(exc)
    else:
        raise AssertionError("routed a contract with no conId")

    ib = FakeIB(resolves_nothing=True)

    try:
        broker.place_order(ib, egln(), quantity=1, account_id="U1", limit_price=71.67)
    except ValueError as exc:
        assert "did not resolve" in str(exc), str(exc)
        assert not ib.placed
        print("  an unqualified or unresolvable contract is refused             OK")
        return

    raise AssertionError("placed an order IBKR could not resolve")


if __name__ == "__main__":
    print("\nSMART order routing\n" + "-" * 64)
    test_routed_order_carries_conid_and_no_venue_fields()
    test_refuses_when_smart_resolves_to_another_instrument()
    test_refuses_on_currency_mismatch()
    test_refuses_when_unqualified_or_unresolvable()
    print("-" * 64)
    print("All order-routing tests passed.\n")
