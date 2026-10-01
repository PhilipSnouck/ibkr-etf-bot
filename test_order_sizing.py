"""
Offline regression test for order sizing against available cash.

No Gateway, no network, no orders. Run it any time with:

    python test_order_sizing.py

Covers Error 201, "Available settled cash ... Cash needed for this order":
the allocators used to count shares at the last traded price while the order
was placed at price x (1 + markup), so a plan could cost more cash than the
account held. It bit whenever the leftover after flooring was smaller than
the markup, which is why it looked intermittent.

The invariant: whatever the allocator decides to buy must be payable at the
price the order will actually use.
"""

from config import ORDER_COMMISSION_BUFFER
from broker import calc_limit_price
from allocator_registry import get_allocator

MARKUP = 0.005


def plan(allocator_name, cash, etf_config, market_prices, topup_trigger=0.75):
    """Mirror what main.py does: size against the limit price, not the quote."""
    order_prices = {s: calc_limit_price(p, MARKUP) for s, p in market_prices.items()}
    allocator = get_allocator(allocator_name)
    result = allocator(
        cash=cash,
        etf_config=etf_config,
        prices=order_prices,
        topup_trigger=topup_trigger,
    )
    return result, order_prices


def assert_affordable(result, order_prices, cash, label):
    """The cash IBKR will reserve must not exceed the cash that exists."""
    needed = 0.0

    for symbol, shares in result["shares"].items():
        if shares > 0:
            needed += shares * order_prices[symbol] + ORDER_COMMISSION_BUFFER

    assert needed <= cash + 1e-9, (
        f"{label}: plan needs {needed:.2f} at limit prices "
        f"but only {cash:.2f} is available"
    )
    return needed


SINGLE_ETF = {"IWDA": {"exchange": "AEB", "currency": "EUR", "target_weight": 1}}

PENSION_ETFS = {
    "VUAA": {"exchange": "BVME.ETF", "currency": "EUR",
             "target_weight": 0.6, "rounding": "nearest"},
    "IMAE": {"exchange": "AEB", "currency": "EUR",
             "target_weight": 0.3, "rounding": "force_up_if_previous_down"},
    "EGLN": {"exchange": "LSEETF", "currency": "EUR",
             "target_weight": 0.1, "rounding": "floor_remainder"},
}


def test_the_live_rejection_no_longer_happens():
    """
    The exact case IBKR rejected on 2026-10-01:
      cash 4261.40, IWDA at 128.71, 33 shares planned at the raw price.
    At the limit price those 33 shares cost more than the cash available.
    """
    cash = 4261.40
    result, order_prices = plan("joint", cash, SINGLE_ETF, {"IWDA": 128.71})

    assert_affordable(result, order_prices, cash, "live rejection case")
    assert result["shares"]["IWDA"] == 0, \
        "33 shares are not affordable at the limit price, so none should be ordered"
    assert result["topup"]["needed"], \
        "being just short of one more share is exactly what the top-up is for"

    print(f"  live case: top up {result['topup']['target_shares']} shares, "
          f"no order placed                OK")


def test_no_plan_ever_exceeds_cash():
    """
    Sweep the danger band. The old bug only appeared when the leftover after
    flooring was smaller than the markup, so a single example proves little.
    """
    checked = 0

    for cents in range(0, 400):
        cash = 4000.00 + cents * 0.97
        for price in (128.71, 101.90, 71.31, 7.03):
            result, order_prices = plan("joint", cash, SINGLE_ETF, {"IWDA": price})
            assert_affordable(result, order_prices, cash, f"cash={cash} price={price}")
            checked += 1

    print(f"  {checked} single-ETF plans, none exceeds available cash          OK")


def test_pension_three_etfs_stay_within_cash():
    checked = 0

    for cents in range(0, 300):
        cash = 1800.00 + cents * 1.03
        prices = {"VUAA": 131.28, "IMAE": 101.91, "EGLN": 71.31}
        result, order_prices = plan("pension", cash, PENSION_ETFS, prices)
        assert_affordable(result, order_prices, cash, f"pension cash={cash}")
        checked += 1

    print(f"  {checked} three-ETF plans, none exceeds available cash           OK")


def test_sizing_uses_the_limit_price_not_the_quote():
    """Guard against a future refactor quietly passing raw prices back in."""
    cash = 4261.40
    _, order_prices = plan("joint", cash, SINGLE_ETF, {"IWDA": 128.71})

    assert order_prices["IWDA"] > 128.71, "the markup was not applied"
    assert abs(order_prices["IWDA"] - 129.35) < 0.01, order_prices

    print("  the price used for sizing is the marked-up limit price          OK")


if __name__ == "__main__":
    print("\nOrder sizing against available cash\n" + "-" * 62)
    test_the_live_rejection_no_longer_happens()
    test_sizing_uses_the_limit_price_not_the_quote()
    test_no_plan_ever_exceeds_cash()
    test_pension_three_etfs_stay_within_cash()
    print("-" * 62)
    print("All order-sizing tests passed.\n")
