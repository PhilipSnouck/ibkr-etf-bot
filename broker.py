# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ib_async import IB, Stock, MarketOrder
from config import IB_CONNECTIONS, IB_ENVIRONMENT


# ------------------------------------------------------------
# CONNECT TO IBKR
# ------------------------------------------------------------
def connect_ib():
    ib = IB()

    connection = IB_CONNECTIONS[IB_ENVIRONMENT]

    ib.connect(
        connection["host"],
        connection["port"],
        clientId=connection["client_id"],
    )

    # Use delayed data if live market data is unavailable
    ib.reqMarketDataType(3)

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
def get_etf_prices(ib, qualified_contracts):
    tickers = ib.reqTickers(*qualified_contracts.values())

    prices = {}
    invalid_symbols = []

    for t in tickers:
        symbol = t.contract.symbol

        candidates = [
            t.marketPrice(),
            t.last,
            t.close,
        ]

        valid_price = None
        for candidate in candidates:
            if candidate is None:
                continue

            try:
                candidate = float(candidate)
            except (TypeError, ValueError):
                continue

            if candidate <= 0:
                continue

            valid_price = candidate
            break

        if valid_price is None:
            invalid_symbols.append(symbol)
        else:
            prices[symbol] = valid_price

    if invalid_symbols:
        raise ValueError(
            f"No valid positive price received for: {', '.join(invalid_symbols)}"
        )

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
# PLACE MARKET ORDER
# ------------------------------------------------------------
def place_market_order(ib, contract, quantity, account_id):
    if quantity <= 0:
        raise ValueError("Quantity must be greater than 0.")

    order = MarketOrder("BUY", quantity)
    order.account = account_id

    trade = ib.placeOrder(contract, order)
    return trade


# ------------------------------------------------------------
# WAIT FOR ORDER STATUS
# ------------------------------------------------------------
def wait_for_order_status(ib, trade, timeout_seconds=15):
    start = datetime.now()

    while True:
        status = trade.orderStatus.status

        if status in {"Filled", "Cancelled", "ApiCancelled", "Inactive"}:
            return status

        elapsed = (datetime.now() - start).total_seconds()
        if elapsed >= timeout_seconds:
            return status

        ib.sleep(1)