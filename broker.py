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


# ------------------------------------------------------------
# CONNECT TO IBKR
# ------------------------------------------------------------
_MAX_CONNECT_ATTEMPTS = 10
_CONNECT_RETRY_DELAY  = 5  # seconds


def connect_ib():
    ib = IB()
    connection = IB_CONNECTIONS[IB_ENVIRONMENT]
    gateway_started = False

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
                print("IB Gateway not running — starting via IBC...")
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

    # Use delayed data if live market data is unavailable
    ib.reqMarketDataType(3)

    # After a fresh IBC-triggered start, give Gateway extra time to establish
    # its market data connections before the bot starts requesting prices.
    if gateway_started:
        print("  Gateway initializing market data connections...")
        time.sleep(15)

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

    Returns float or None.
    """
    candidates = []

    try:
        mp = ticker.marketPrice()
        if mp is not None and isfinite(mp) and mp > 0:
            candidates.append(mp)
    except Exception:
        pass

    try:
        if ticker.last is not None and isfinite(ticker.last) and ticker.last > 0:
            candidates.append(ticker.last)
    except Exception:
        pass

    try:
        if (
            ticker.bid is not None and isfinite(ticker.bid) and ticker.bid > 0 and
            ticker.ask is not None and isfinite(ticker.ask) and ticker.ask > 0
        ):
            candidates.append((ticker.bid + ticker.ask) / 2)
    except Exception:
        pass

    return candidates[0] if candidates else None


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


def _request_prices_once(ib, contract_list, wait_seconds=2.0):
    """
    Request delayed streaming prices once.
    Returns {symbol: price_or_None}.
    """
    prices = {}

    ib.reqMarketDataType(3)
    tickers = [ib.reqMktData(contract, "", False, False) for contract in contract_list]
    ib.sleep(wait_seconds)

    for contract, ticker in zip(contract_list, tickers):
        prices[contract.symbol] = get_ticker_price(ticker)

    _safe_cancel_market_data(ib, tickers)
    return prices


def get_etf_prices(ib, contracts):
    """
    Fetch ETF prices using a simple robust strategy:

    1. Warm-up pass using delayed streaming data
    2. Real pass using delayed streaming data

    No delayed frozen fallback.
    No historical fallback.

    Returns {symbol: price_or_None}
    """
    contract_list = _normalize_contracts(contracts)

    # Warm-up pass
    _ = _request_prices_once(ib, contract_list, wait_seconds=1.5)
    ib.sleep(0.5)

    # Real pass
    prices = _request_prices_once(ib, contract_list, wait_seconds=2.0)

    return prices

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
# PLACE ORDER
# ------------------------------------------------------------
def place_order(ib, contract, quantity, account_id, limit_price):
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")

    if limit_price is None or limit_price <= 0:
        raise ValueError("Limit price must be greater than 0.")

    order = LimitOrder("BUY", quantity, round(limit_price, 2))
    order.account = account_id
    order.tif = "DAY"

    trade = ib.placeOrder(contract, order)
    return trade


