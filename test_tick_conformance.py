"""
Regression test for IBKR Error 110 ("price does not conform to the minimum
price variation for this contract").

Runs offline: no IB Gateway, no orders. The market-rule data below was read
from the live Gateway on 2026-09-01 with reqContractDetails + reqMarketRule,
and is frozen here so the test keeps working without a connection.

The bug it guards against: the bot routes every order via SMART, but looked up
the tick size on the *listing* exchange. For IMAE those rules differ (flat
0.005 on AEB, banded on SMART where EUR 100-200 requires 0.02), so a limit
price of 105.83 passed the bot's own check and was then rejected by IBKR.

Run:  python test_tick_conformance.py
"""

from copy import copy
from decimal import Decimal

from broker import calc_limit_price, get_price_increment, round_up_to_tick


# ------------------------------------------------------------
# FROZEN IBKR DATA (read from the live Gateway, 2026-09-01)
# ------------------------------------------------------------
MARKET_RULES = {
    145: [(0.0, 0.005)],
    983: [(0.0, 0.0005), (0.1, 0.001), (5.0, 0.0025), (10.0, 0.005), (25.0, 0.01)],
    1874: [
        (0.0, 0.0001), (1.0, 0.0002), (2.0, 0.0005), (5.0, 0.001), (10.0, 0.002),
        (20.0, 0.005), (50.0, 0.01), (100.0, 0.02), (200.0, 0.05), (500.0, 0.1),
        (1000.0, 0.2), (2000.0, 0.5), (5000.0, 1.0), (10000.0, 2.0),
        (20000.0, 5.0), (50000.0, 10.0),
    ],
    2077: [
        (0.0, 0.0001), (1.0, 0.0002), (2.0, 0.0005), (5.0, 0.001),
        (10.0, 0.002), (20.0, 0.005), (50.0, 0.01),
    ],
}

CONTRACTS = {
    # symbol: (listing exchange, minTick, {exchange: market rule id})
    "IMAE": ("AEB",      0.005,  {"AEB": 145,       "SMART": 1874}),
    "IWDA": ("AEB",      0.0001, {"AEB": 2077,      "SMART": 2077}),
    "VUAA": ("BVME.ETF", 0.0001, {"BVME.ETF": 2077, "SMART": 2077}),
    "EGLN": ("LSEETF",   0.0005, {"LSEETF": 983,    "SMART": 983}),
}

# Market prices from the run where IMAE was rejected.
MARKET_PRICES = {"IMAE": 105.30, "IWDA": 126.73, "VUAA": 127.71, "EGLN": 73.39}
MARKUP = 0.005


# ------------------------------------------------------------
# STUBS
# ------------------------------------------------------------
class FakeIncrement:
    def __init__(self, low_edge, increment):
        self.lowEdge = low_edge
        self.increment = increment


class FakeDetails:
    def __init__(self, min_tick, rule_map):
        self.minTick = min_tick
        self.validExchanges = ",".join(rule_map)
        self.marketRuleIds = ",".join(str(r) for r in rule_map.values())


class FakeContract:
    def __init__(self, symbol, exchange):
        self.symbol = symbol
        self.exchange = exchange
        self.primaryExchange = exchange


class FakeIB:
    def __init__(self, min_tick, rule_map):
        self._details = FakeDetails(min_tick, rule_map)

    def reqContractDetails(self, contract):
        return [self._details]

    def reqMarketRule(self, rule_id):
        return [FakeIncrement(low, inc) for low, inc in MARKET_RULES[int(rule_id)]]


def conforms(price, tick):
    quotient = Decimal(str(price)) / Decimal(str(tick))
    return quotient == quotient.to_integral_value()


def enforced_tick(symbol, price):
    """The tick IBKR actually validates against: the SMART rule's band."""
    rule_id = CONTRACTS[symbol][2]["SMART"]
    applicable = None
    for low, inc in sorted(MARKET_RULES[rule_id]):
        if price >= low:
            applicable = inc
        else:
            break
    return applicable


# ------------------------------------------------------------
# TESTS
# ------------------------------------------------------------
def price_the_bot_sends(symbol):
    """Reproduce exactly what place_order() computes, without placing anything."""
    exchange, min_tick, rule_map = CONTRACTS[symbol]
    ib = FakeIB(min_tick, rule_map)
    contract = FakeContract(symbol, exchange)

    routing_contract = copy(contract)
    routing_contract.primaryExchange = contract.exchange
    routing_contract.exchange = "SMART"

    raw = calc_limit_price(MARKET_PRICES[symbol], MARKUP)
    tick = get_price_increment(
        ib, contract, raw, routing_exchange=routing_contract.exchange
    )
    return raw, tick, round_up_to_tick(raw, tick)


def test_all_etfs_conform_to_the_routed_venue():
    failures = []
    print(f"{'ETF':6} {'raw':>9} {'tick used':>10} {'sent':>9} {'IBKR tick':>10}  result")
    print("-" * 60)

    for symbol in CONTRACTS:
        raw, tick, sent = price_the_bot_sends(symbol)
        ibkr_tick = enforced_tick(symbol, sent)
        ok = conforms(sent, ibkr_tick) and sent >= raw
        if not ok:
            failures.append(f"{symbol}: sends {sent} but IBKR tick is {ibkr_tick}")
        print(f"{symbol:6} {raw:>9.4f} {tick:>10} {sent:>9.4f} {ibkr_tick:>10}  "
              f"{'OK' if ok else 'REJECTED BY IBKR'}")

    print("-" * 60)
    assert not failures, "Error 110 would occur for: " + "; ".join(failures)


def test_imae_no_longer_sends_the_rejected_price():
    """The exact price IBKR cancelled on 2026-09-01 must not be sent again."""
    _, tick, sent = price_the_bot_sends("IMAE")
    assert tick == 0.02, f"expected the SMART band tick 0.02 for IMAE, got {tick}"
    assert sent != 105.83, "IMAE is still sending the price IBKR rejected"
    assert sent == 105.84, f"expected 105.84 (rounded up to 0.02), got {sent}"
    print("IMAE: 105.83 (rejected) is now sent as 105.84 on a 0.02 tick.  OK")


def test_listing_exchange_rule_would_still_fail():
    """Documents the bug: the AEB rule alone does not catch the 0.02 band."""
    exchange, min_tick, rule_map = CONTRACTS["IMAE"]
    ib = FakeIB(min_tick, rule_map)
    contract = FakeContract("IMAE", exchange)

    raw = calc_limit_price(MARKET_PRICES["IMAE"], MARKUP)
    listing_tick = get_price_increment(ib, contract, raw, routing_exchange="AEB")
    listing_price = round_up_to_tick(raw, listing_tick)

    assert listing_tick == 0.005, f"expected AEB tick 0.005, got {listing_tick}"
    assert listing_price == 105.83
    assert not conforms(listing_price, 0.02), "test data no longer reproduces the bug"
    print("Listing-exchange lookup reproduces the old 105.83 rejection.        OK")


if __name__ == "__main__":
    test_all_etfs_conform_to_the_routed_venue()
    test_imae_no_longer_sends_the_rejected_price()
    test_listing_exchange_rule_would_still_fail()
    print("\nAll tick-conformance tests passed.")
