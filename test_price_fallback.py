"""
Offline regression test for the price fallback chain.

No Gateway, no network, no orders. Run it any time with:

    python test_price_fallback.py

Reproduces the live failure shape seen on 2026-10-01: VUAA on BVME.ETF is
refused on every streaming path with Error 354 while the other ETFs on the
same connection price normally. Before the fallback chain existed, that one
refusal killed the whole account for the run.
"""

from ib_async import Stock

import broker
from price_diagnostics import DIAG


# ------------------------------------------------------------
# FAKES
# ------------------------------------------------------------
class FakeTicker:
    def __init__(self, contract, price=None):
        self.contract = contract
        self.marketDataType = 3
        self.last = None
        self.bid = None
        self.ask = None
        self.close = None
        self._price = price

    def marketPrice(self):
        return self._price if self._price is not None else float("nan")


class FakeIB:
    """
    Refuses every streaming request for `refused`, prices everything else.
    Records what was asked for so the test can assert on the order of rungs.
    """

    class _Event:
        def __iadd__(self, handler):
            return self

    def __init__(self, refused=("VUAA",), historical_works=True):
        self.refused = set(refused)
        self.historical_works = historical_works
        self.calls = []
        self.market_data_types = []
        self.errorEvent = self._Event()

    def reqMarketDataType(self, value):
        self.market_data_types.append(value)

    def reqMktData(self, contract, *args, **kwargs):
        self.calls.append(("mkt", contract.symbol, contract.exchange))
        price = None if contract.symbol in self.refused else 101.66
        return FakeTicker(contract, price)

    def reqHistoricalData(self, contract, **kwargs):
        self.calls.append(("hist", contract.symbol, kwargs["whatToShow"]))

        if not self.historical_works:
            return []

        class Bar:
            close = 128.35

        return [Bar()]

    def sleep(self, seconds):
        pass

    def cancelMktData(self, contract):
        pass


def contracts():
    vuaa = Stock("VUAA", "BVME.ETF", "EUR")
    vuaa.conId = 399364021
    vuaa.primaryExchange = "BVME.ETF"

    imae = Stock("IMAE", "AEB", "EUR")
    imae.conId = 1
    imae.primaryExchange = "AEB"

    return [vuaa, imae]


def fresh_ib(**kwargs):
    ib = FakeIB(**kwargs)
    DIAG.attach(ib)
    DIAG.on_connect(
        ib, env="live", host="127.0.0.1", port=4001,
        client_id=2, attempts=1, gateway_started=False,
    )
    return ib


# ------------------------------------------------------------
# TESTS
# ------------------------------------------------------------
def test_historical_rescues_the_run():
    ib = fresh_ib(historical_works=True)
    prices = broker.get_etf_prices(ib, contracts())

    assert prices["IMAE"] == 101.66, prices
    assert prices["VUAA"] == 128.35, "historical close should have rescued VUAA"

    assert broker.FROZEN_MARKET_DATA_TYPE in ib.market_data_types, \
        "the frozen rung was never tried"
    assert ib.market_data_types[-1] == broker.REQUESTED_MARKET_DATA_TYPE, \
        "session was left on frozen data, which would affect later requests"

    smart = [c for c in ib.calls if c[0] == "mkt" and c[2] == "SMART"]
    assert smart, "the SMART rung was never tried"
    assert all(c[1] == "VUAA" for c in smart), \
        "a symbol that already had a price was escalated to SMART"

    print("  rungs escalate in order, only for the symbol that is missing   OK")


def test_gives_up_cleanly_when_everything_is_refused():
    ib = fresh_ib(historical_works=False)
    prices = broker.get_etf_prices(ib, contracts())

    assert prices["VUAA"] is None, prices
    assert prices["IMAE"] == 101.66, "one refusal must not take the others down"

    historical = [c[2] for c in ib.calls if c[0] == "hist"]
    assert historical == ["TRADES", "MIDPOINT"], historical

    report = broker.describe_price_failure("VUAA")
    assert "Fallback chain tried" in report
    assert "historical close (MIDPOINT)" in report
    assert "VERDICT" in report

    print("  all rungs tried, then a clean stop with a full report          OK")


def test_healthy_run_touches_no_fallback():
    ib = fresh_ib(refused=())
    prices = broker.get_etf_prices(ib, contracts())

    assert prices["VUAA"] == 101.66 and prices["IMAE"] == 101.66, prices
    assert not [c for c in ib.calls if c[0] == "hist"], \
        "historical was requested although streaming worked"
    assert not [c for c in ib.calls if c[0] == "mkt" and c[2] == "SMART"], \
        "SMART was requested although streaming worked"
    assert broker.FROZEN_MARKET_DATA_TYPE not in ib.market_data_types, \
        "frozen was requested although streaming worked"

    print("  a working run costs no extra requests                          OK")


if __name__ == "__main__":
    print("\nPrice fallback chain\n" + "-" * 62)
    test_historical_rescues_the_run()
    test_gives_up_cleanly_when_everything_is_refused()
    test_healthy_run_touches_no_fallback()
    print("-" * 62)
    print("All price-fallback tests passed.\n")
