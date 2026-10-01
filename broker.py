# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from ib_async import IB, Stock, LimitOrder
from config import IB_CONNECTIONS, IB_ENVIRONMENT, IBC_SCRIPT_PATH
from price_diagnostics import DIAG


# ------------------------------------------------------------
# CONNECT TO IBKR
# ------------------------------------------------------------
_MAX_CONNECT_ATTEMPTS = 10
_CONNECT_RETRY_DELAY  = 5  # seconds

# IBKR market data type the bot asks for: 3 = delayed.
# Named rather than inlined so the diagnostics can report what was requested
# alongside what was actually received.
REQUESTED_MARKET_DATA_TYPE = 3

# 4 = delayed frozen: the last known quote, served when the live delayed
# stream has nothing to give. Used only as a fallback, never as the first ask.
FROZEN_MARKET_DATA_TYPE = 4


def connect_ib():
    ib = IB()
    connection = IB_CONNECTIONS[IB_ENVIRONMENT]
    gateway_started = False

    # Subscribe to IBKR messages before connecting. The market data farm
    # status messages arrive during the handshake itself, so attaching after
    # ib.connect() returns misses them and makes a healthy connection look
    # like one that never brought its data session up.
    DIAG.attach(ib)

    ib_log = logging.getLogger('ib_async')
    orig_level = ib_log.level

    for attempt in range(1, _MAX_CONNECT_ATTEMPTS + 1):
        try:
            ib_log.setLevel(logging.CRITICAL)
            ib.connect(
                connection["host"],
                connection["port"],
                clientId=connection["client_id"],
            )
            break
        except Exception:
            ib_log.setLevel(orig_level)
            if attempt == 1 and IBC_SCRIPT_PATH:
                if not os.path.exists(IBC_SCRIPT_PATH):
                    print(f"\nIBC script not found at: {IBC_SCRIPT_PATH}")
                    print("Update IBC_SCRIPT_PATH in config.py or start IB Gateway manually.")
                    raise SystemExit(1)
                print("IB Gateway not running - starting via IBC...")
                subprocess.Popen(IBC_SCRIPT_PATH, shell=True)
                gateway_started = True
                print("Approve the 2FA prompt on your phone.")
            elif attempt == _MAX_CONNECT_ATTEMPTS:
                print(f"\nCould not connect to IBKR after {_MAX_CONNECT_ATTEMPTS} attempts.")
                print(f"  Environment : {IB_ENVIRONMENT}")
                print(f"  Host        : {connection['host']}")
                print(f"  Port        : {connection['port']}")
                if not gateway_started:
                    print("\nIs IB Gateway running and logged in?")
                raise SystemExit(1)
            else:
                print(f"  Waiting for Gateway... ({attempt}/{_MAX_CONNECT_ATTEMPTS})")
            time.sleep(_CONNECT_RETRY_DELAY)

    ib_log.setLevel(orig_level)

    # Start recording diagnostics immediately, BEFORE the market data type is
    # set and before any settling sleep. The market data farm status messages
    # (2104 / 2106 / 2158) arrive in exactly that window, and whether they
    # arrive before the first price request is the key signal when a fetch
    # later fails with Error 354.
    DIAG.on_connect(
        ib,
        env=IB_ENVIRONMENT,
        host=connection["host"],
        port=connection["port"],
        client_id=connection["client_id"],
        attempts=attempt,
        gateway_started=gateway_started,
    )

    # Use delayed data if live market data is unavailable
    ib.reqMarketDataType(REQUESTED_MARKET_DATA_TYPE)

    # After a fresh IBC-triggered start, give Gateway extra time to establish
    # its market data connections before the bot starts requesting prices.
    if gateway_started:
        print("  Gateway initializing market data connections...")
        time.sleep(15)

    # Record the connection's own parameters in the run log. clientId and
    # mode in particular matter: preview and execute are separate processes
    # that reconnect on the same clientId, and that is visible here.
    print(DIAG.connection_line())

    return ib


# ------------------------------------------------------------
# GET TOTAL CASH VALUE FOR A SPECIFIC ACCOUNT
# ------------------------------------------------------------
def get_account_cash(ib, account_id, currency="EUR"):
    summary = ib.accountSummary()

    for item in summary:
        if item.account == account_id and item.tag == "TotalCashValue" and item.currency == currency:
            return float(item.value)

    return None


# ------------------------------------------------------------
# QUALIFY ETF CONTRACTS FROM CONFIG
# ------------------------------------------------------------
def qualify_etf_contracts(ib, etf_config, symbols=None):
    qualified = {}

    if symbols is None:
        symbols = list(etf_config.keys())

    for symbol in symbols:
        settings = etf_config[symbol]
        contract = Stock(symbol, settings["exchange"], settings["currency"])
        result = ib.qualifyContracts(contract)

        if result:
            qualified[symbol] = result[0]

    return qualified


# ------------------------------------------------------------
# FETCH ETF PRICES
# ------------------------------------------------------------
def get_ticker_price(ticker):
    """
    Extract the best usable price from an IBKR ticker object.

    Preference order:
    1. marketPrice()
    2. last
    3. midpoint of bid/ask

    Returns (price, source) where source names which of the three was used,
    or (None, None) when the ticker carried no usable price. The source is
    reported in the run log so a filled order can always be traced back to
    the kind of quote it was priced from.
    """
    candidates = []

    try:
        mp = ticker.marketPrice()
        if mp is not None and isfinite(mp) and mp > 0:
            candidates.append((mp, "marketPrice"))
    except Exception:
        pass

    try:
        if ticker.last is not None and isfinite(ticker.last) and ticker.last > 0:
            candidates.append((ticker.last, "last"))
    except Exception:
        pass

    try:
        if (
            ticker.bid is not None and isfinite(ticker.bid) and ticker.bid > 0 and
            ticker.ask is not None and isfinite(ticker.ask) and ticker.ask > 0
        ):
            candidates.append(((ticker.bid + ticker.ask) / 2, "bid/ask midpoint"))
    except Exception:
        pass

    return candidates[0] if candidates else (None, None)


def _normalize_contracts(contracts):
    if isinstance(contracts, dict):
        return list(contracts.values())
    return list(contracts)


def _safe_cancel_market_data(ib, tickers):
    for ticker in tickers:
        try:
            contract = getattr(ticker, "contract", None)
            if contract is not None:
                ib.cancelMktData(contract)
        except Exception:
            pass


def _smart_routed(contract):
    """
    A copy of the contract with market data requested through SMART instead of
    its listing venue, keeping primaryExchange so IBKR still identifies it.

    Orders already route this way (see place_order). Price requests did not,
    and a venue-specific feed can be refused where the SMART composite is
    served, so this is a genuinely different path rather than a retry.
    """
    from copy import copy

    routed = copy(contract)
    routed.primaryExchange = getattr(contract, "primaryExchange", "") or contract.exchange
    routed.exchange = "SMART"
    return routed


def _historical_close(ib, contract, what_to_show):
    """
    Last daily close from IBKR's historical service.

    A separate data path from streaming quotes, with its own entitlements, so
    it can succeed when a streaming subscription is refused. Returns a float
    or None, and never raises.
    """
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="5 D",
            barSizeSetting="1 day",
            whatToShow=what_to_show,
            useRTH=True,
            formatDate=1,
        )
    except Exception:
        return None

    if not bars:
        return None

    close = getattr(bars[-1], "close", None)

    if close is None or not isfinite(close) or close <= 0:
        return None

    return float(close)


def _request_prices_once(
    ib, contract_list, wait_seconds=2.0, pass_name="pass", market_data_type=None
):
    """
    Request delayed streaming prices once.
    Returns {symbol: (price_or_None, source_or_None)}.

    Every ticker is handed to the diagnostics collector before its
    subscription is cancelled, so a later failure report can show exactly
    which fields IBKR populated on each pass.
    """
    prices = {}

    ib.reqMarketDataType(market_data_type or REQUESTED_MARKET_DATA_TYPE)
    tickers = [ib.reqMktData(contract, "", False, False) for contract in contract_list]
    ib.sleep(wait_seconds)

    for contract, ticker in zip(contract_list, tickers):
        DIAG.record_pass(pass_name, contract.symbol, ticker, wait_seconds)
        prices[contract.symbol] = get_ticker_price(ticker)

    _safe_cancel_market_data(ib, tickers)
    return prices


def get_etf_prices(ib, contracts):
    """
    Fetch ETF prices using a simple robust strategy:

    1. Warm-up pass using delayed streaming data
    2. Real pass using delayed streaming data

    Each rung is a genuinely different request path at IBKR rather than a
    retry of the same one, because a refusal (Error 354) is immediate and
    repeating it changes nothing:

      1. delayed streaming on the listing venue, warm-up pass then real pass
      2. delayed streaming routed via SMART
      3. delayed FROZEN, the last known quote
      4. last daily close from the historical service (TRADES, then MIDPOINT)

    Why a stale price is safe here: orders are LIMIT orders priced off this
    number. If the price is stale high, the limit sits above the market and
    fills at the market price. If it is stale low, the limit sits below the
    market and simply does not fill. The downside of an old price is a missed
    fill, never an overpay.

    Every rung used is printed, so a run always says what it priced from.

    Returns {symbol: price_or_None}
    """
    contract_list = _normalize_contracts(contracts)

    DIAG.start_fetch(contract_list, REQUESTED_MARKET_DATA_TYPE)

    prices = {}
    sources = {}

    def absorb(detailed, step_label):
        """Take any prices this rung produced, record the rest as misses."""
        for symbol, (price, field) in detailed.items():
            DIAG.record_step(step_label, symbol, price, field or "")

            if price is not None and prices.get(symbol) is None:
                prices[symbol] = price
                sources[symbol] = f"{step_label}, {field}" if field else step_label

    def still_missing():
        return [c for c in contract_list if prices.get(c.symbol) is None]

    # --- rung 1: delayed streaming on the listing venue ------------------
    # The warm-up exists because IBKR sometimes fails the first delayed
    # request for a contract while the next one succeeds.
    _ = _request_prices_once(
        ib, contract_list, wait_seconds=1.5, pass_name="pass 1 warm-up"
    )
    ib.sleep(0.5)

    absorb(
        _request_prices_once(
            ib, contract_list, wait_seconds=2.0, pass_name="pass 2 real"
        ),
        "delayed streaming",
    )

    # --- rung 2: delayed streaming via SMART -----------------------------
    missing = still_missing()

    if missing:
        print(
            f"  No delayed quote for {', '.join(c.symbol for c in missing)}; "
            f"retrying via SMART."
        )
        routed = [_smart_routed(c) for c in missing]
        absorb(
            _request_prices_once(
                ib, routed, wait_seconds=2.5, pass_name="pass 3 SMART"
            ),
            "delayed streaming via SMART",
        )

    # --- rung 3: delayed frozen ------------------------------------------
    missing = still_missing()

    if missing:
        print(
            f"  Still no quote for {', '.join(c.symbol for c in missing)}; "
            f"trying frozen data."
        )
        absorb(
            _request_prices_once(
                ib,
                missing,
                wait_seconds=2.5,
                pass_name="pass 4 frozen",
                market_data_type=FROZEN_MARKET_DATA_TYPE,
            ),
            "delayed frozen",
        )
        # Leave the session back on delayed for anything that follows.
        ib.reqMarketDataType(REQUESTED_MARKET_DATA_TYPE)

    # --- rung 4: historical daily close ----------------------------------
    missing = still_missing()

    if missing:
        print(
            f"  Still no quote for {', '.join(c.symbol for c in missing)}; "
            f"falling back to last daily close."
        )

        for contract in missing:
            for what_to_show in ("TRADES", "MIDPOINT"):
                close = _historical_close(ib, contract, what_to_show)
                label = f"historical close ({what_to_show})"
                DIAG.record_step(label, contract.symbol, close)

                if close is not None:
                    prices[contract.symbol] = close
                    sources[contract.symbol] = label
                    break

    # --- record and report -----------------------------------------------
    for contract in contract_list:
        symbol = contract.symbol
        prices.setdefault(symbol, None)
        DIAG.record_result(symbol, prices[symbol], sources.get(symbol))

    # One line per fetch, on success as well as failure, so a run always
    # records which path and which quote field each price came from. That is
    # what makes a later regression diagnosable by comparison.
    summary = DIAG.summary_line()

    if summary:
        print(summary)

    return prices


def describe_price_failure(symbol, ib=None):
    """
    Full explanation of why `symbol` has no price: contract, connection,
    market hours, per-pass ticker fields, the IBKR messages received, the
    market data farm status, and what the codes mean.
    """
    return DIAG.describe_failure(symbol, ib=ib)

# ------------------------------------------------------------
# GET CONTRACT DETAILS
# ------------------------------------------------------------
def get_contract_details(ib, contract):
    details = ib.reqContractDetails(contract)

    if not details:
        return None

    return details[0]


# ------------------------------------------------------------
# PARSE IBKR HOURS
# ------------------------------------------------------------
def parse_ibkr_datetime_token(token, default_date_str, tz):
    token = token.strip()

    if ":" in token:
        dt = datetime.strptime(token, "%Y%m%d:%H%M")
    else:
        dt = datetime.strptime(f"{default_date_str}:{token}", "%Y%m%d:%H%M")

    return dt.replace(tzinfo=tz)


def parse_ibkr_hours(hours_str, tz_name):
    if not hours_str:
        return []

    tz = ZoneInfo(tz_name)
    windows = []

    for day_part in hours_str.split(";"):
        day_part = day_part.strip()

        if not day_part:
            continue

        if day_part.endswith(":CLOSED"):
            continue

        if ":" not in day_part:
            continue

        date_str, sessions_str = day_part.split(":", 1)

        for session in sessions_str.split(","):
            session = session.strip()

            if not session or "-" not in session:
                continue

            start_token, end_token = session.split("-", 1)

            try:
                start_dt = parse_ibkr_datetime_token(start_token, date_str, tz)
                end_dt = parse_ibkr_datetime_token(end_token, date_str, tz)
            except ValueError:
                continue

            if end_dt < start_dt:
                end_dt += timedelta(days=1)

            windows.append((start_dt, end_dt))

    return windows


# ------------------------------------------------------------
# CHECK IF CONTRACT IS OPEN NOW
# ------------------------------------------------------------
def is_contract_open_now(ib, contract):
    details = get_contract_details(ib, contract)

    if details is None:
        return False, "No contract details returned from IBKR."

    tz_name = details.timeZoneId
    liquid_hours = details.liquidHours

    now_local = datetime.now(ZoneInfo(tz_name))
    windows = parse_ibkr_hours(liquid_hours, tz_name)

    for start_dt, end_dt in windows:
        if start_dt <= now_local <= end_dt:
            return True, f"Market is open now."

    return False, f"Market is closed now."


# ------------------------------------------------------------
# LIMIT PRICE HELPER
# ------------------------------------------------------------
def calc_limit_price(price, markup):
    return round(price * (1 + markup), 2)


# ------------------------------------------------------------
# TICK SIZE ROUNDING
# ------------------------------------------------------------
def round_up_to_tick(price: float, min_tick: float) -> float:
    """
    Round price UP to the nearest valid tick increment.
    Uses Decimal arithmetic to avoid floating point precision errors (Error 110).
    For BUY limit orders we always round up so the order has a good fill chance.
    """
    from decimal import Decimal, ROUND_CEILING
    if not min_tick or min_tick <= 0:
        return round(price, 2)
    tick_d = Decimal(str(min_tick))
    price_d = Decimal(str(price))
    rounded = (price_d / tick_d).to_integral_value(rounding=ROUND_CEILING) * tick_d
    return float(rounded)


def get_price_increment(ib, contract, price, routing_exchange=None):
    """
    Return the exact tick size IBKR enforces for this contract AT THIS PRICE,
    on the venue the order is actually sent to.

    European venues use MiFID II price bands: the valid tick grows with the
    price (e.g. EUR 0.01 below EUR 50, EUR 0.02 around EUR 100, ...). The
    contract's `minTick` reports only the smallest possible tick, so rounding
    to minTick alone still produces prices IBKR rejects with Error 110. We
    therefore read the contract's market rule, which lists the increment per
    price band, and return the increment for the band the price falls into.

    `routing_exchange` is the venue the order is routed to (SMART for this bot).
    That rule, not the listing exchange's, is the one IBKR validates the price
    against, and the two can differ: IMAE reports a flat 0.005 tick on AEB but
    a banded rule on SMART where EUR 100-200 requires 0.02. Reading the listing
    rule alone therefore still produced Error 110 for IMAE.

    Falls back to `minTick`, then to EUR 0.01, if the market rule can't be
    read, so this can never make order placement worse than before.
    """
    details = get_contract_details(ib, contract)

    fallback = 0.01
    if details and details.minTick:
        fallback = details.minTick

    if not details or not details.marketRuleIds or not details.validExchanges:
        return fallback

    exchanges = [e.strip() for e in details.validExchanges.split(",")]
    rule_ids = [r.strip() for r in str(details.marketRuleIds).split(",")]
    rule_map = dict(zip(exchanges, rule_ids))

    # Prefer the exchange the order is routed to, then the listing (primary)
    # exchange, then whatever the contract itself names.
    rule_id = None
    for name in (
        routing_exchange,
        getattr(contract, "primaryExchange", ""),
        getattr(contract, "exchange", ""),
    ):
        if name and rule_map.get(name):
            rule_id = rule_map[name]
            break

    if not rule_id:
        rule_id = rule_ids[0] if rule_ids else None

    if not rule_id:
        return fallback

    try:
        increments = ib.reqMarketRule(int(rule_id))
    except Exception:
        return fallback

    if not increments:
        return fallback

    # Walk the bands low-to-high and keep the increment of the highest band
    # whose lowEdge is still at or below our price.
    applicable = None
    for inc in sorted(increments, key=lambda x: x.lowEdge):
        if price >= inc.lowEdge:
            applicable = inc.increment
        else:
            break

    if applicable and applicable > 0:
        return applicable
    return fallback


# ------------------------------------------------------------
# ROUTING CONTRACT
# ------------------------------------------------------------
def build_routing_contract(ib, contract):
    """
    The contract an order is sent on: the same instrument, routed via SMART.

    SMART is a routing destination, not an instrument chooser. We route that
    way to avoid Error 10311 (the direct-routing restriction in Gateway's
    precautionary settings, which resets on every Gateway restart).

    The previous version copied the qualified contract and swapped only the
    exchange, which left `localSymbol` and `tradingClass` from the listing
    venue attached. One ETF is listed as several lines, each with different
    values for those fields, so the request effectively said "route this
    anywhere, but it must be the line whose local symbol is EGLN on LSE".
    IBKR resolved SMART to its own composite line, saw the mismatch, and
    cancelled the order with Error 478.

    `conId` is IBKR's unique key for an instrument and `qualifyContracts`
    has already filled it in, so conId + SMART + currency is unambiguous.
    We still verify rather than trust: we ask IBKR what that routed contract
    resolves to and refuse to place the order if it is not the same
    instrument we priced. Buying the wrong ETF is the one failure mode this
    function must make impossible.
    """
    from ib_async import Contract

    if not getattr(contract, "conId", None):
        raise ValueError(
            f"Cannot route {contract.symbol} via SMART: the contract has no conId. "
            f"It was not qualified against IBKR."
        )

    def minimal():
        return Contract(
            secType=getattr(contract, "secType", "") or "STK",
            conId=contract.conId,
            exchange="SMART",
            currency=contract.currency,
        )

    resolved = ib.qualifyContracts(minimal())

    if not resolved:
        raise ValueError(
            f"Cannot route {contract.symbol} via SMART: IBKR did not resolve "
            f"conId {contract.conId} to any contract."
        )

    check = resolved[0]
    mismatches = []

    if check.conId != contract.conId:
        mismatches.append(f"conId {check.conId} != {contract.conId}")

    if (check.symbol or "").upper() != (contract.symbol or "").upper():
        mismatches.append(f"symbol {check.symbol!r} != {contract.symbol!r}")

    if (check.currency or "").upper() != (contract.currency or "").upper():
        mismatches.append(f"currency {check.currency!r} != {contract.currency!r}")

    if mismatches:
        raise ValueError(
            f"Refusing to order {contract.symbol}: routing it via SMART resolves to a "
            f"different instrument than the one that was priced ({'; '.join(mismatches)}). "
            f"No order was placed."
        )

    print(
        f"  Routing {contract.symbol} via SMART as conId {check.conId} "
        f"({check.symbol} {check.currency}, localSymbol {check.localSymbol or '-'})."
    )

    # Send the minimal contract, not the one IBKR just filled in: the
    # resolved copy carries venue-specific fields again, which is exactly
    # what caused Error 478.
    return minimal()


# ------------------------------------------------------------
# PLACE ORDER
# ------------------------------------------------------------
def place_order(ib, contract, quantity, account_id, limit_price):
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")

    if limit_price is None or limit_price <= 0:
        raise ValueError("Limit price must be greater than 0.")

    routing_contract = build_routing_contract(ib, contract)

    # Snap limit price to the tick IBKR enforces for this price band, to avoid
    # Error 110 (price does not conform to the minimum price variation). We use
    # the contract's market rule rather than minTick alone, because the enforced
    # tick can be larger than minTick (e.g. 0.02 around EUR 100). The rule that
    # counts is the one of the venue we route to, not the listing exchange: for
    # IMAE those differ (0.005 on AEB, 0.02 on SMART at EUR 100-200). We read
    # details from the original (exchange-specific) contract for accuracy.
    original_price = limit_price
    tick = get_price_increment(
        ib, contract, limit_price, routing_exchange=routing_contract.exchange
    )
    limit_price = round_up_to_tick(limit_price, tick)
    if limit_price != original_price:
        print(
            f"  Adjusted {contract.symbol} limit price "
            f"{original_price:.2f} -> {limit_price:.2f} (tick {tick}) to conform to IBKR."
        )

    order = LimitOrder("BUY", quantity, limit_price)
    order.account = account_id
    order.tif = "DAY"

    trade = ib.placeOrder(routing_contract, order)
    return trade


