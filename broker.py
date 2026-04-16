from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ib_async import IB, Stock
from config import IB_HOST, IB_PORT, IB_CLIENT_ID


# ------------------------------------------------------------
# CONNECT TO IBKR
# ------------------------------------------------------------
def connect_ib():
    ib = IB()
    ib.connect(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID)

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
# If symbols is None, qualify all ETFs in the config.
# If symbols is a list, qualify only those symbols.
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
    for t in tickers:
        prices[t.contract.symbol] = float(t.marketPrice())

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
# PARSE A SINGLE IBKR DATETIME TOKEN
# Supports:
# - HHMM
# - YYYYMMDD:HHMM
# ------------------------------------------------------------
def parse_ibkr_datetime_token(token, default_date_str, tz):
    token = token.strip()

    if ":" in token:
        dt = datetime.strptime(token, "%Y%m%d:%H%M")
    else:
        dt = datetime.strptime(f"{default_date_str}:{token}", "%Y%m%d:%H%M")

    return dt.replace(tzinfo=tz)


# ------------------------------------------------------------
# PARSE IBKR HOURS STRING
# Examples:
#   20260416:0900-1730;20260417:CLOSED
#   20260416:0900-1200,1300-1730
#   20260416:0900-20260416:1750
# ------------------------------------------------------------
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
            start_token = start_token.strip()
            end_token = end_token.strip()

            try:
                start_dt = parse_ibkr_datetime_token(start_token, date_str, tz)
                end_dt = parse_ibkr_datetime_token(end_token, date_str, tz)
            except ValueError:
                continue

            # Handle overnight sessions if end is earlier than start
            if end_dt < start_dt:
                end_dt += timedelta(days=1)

            windows.append((start_dt, end_dt))

    return windows


# ------------------------------------------------------------
# CHECK IF CONTRACT IS OPEN NOW
# Uses IBKR liquidHours for execution safety
# ------------------------------------------------------------
def is_contract_open_now(ib, contract):
    details = get_contract_details(ib, contract)

    if details is None:
        return False, "No contract details returned from IBKR."

    tz_name = details.timeZoneId
    liquid_hours = details.liquidHours

    if not tz_name:
        return False, "No timeZoneId returned from IBKR."

    if not liquid_hours:
        return False, "No liquidHours returned from IBKR."

    now_local = datetime.now(ZoneInfo(tz_name))
    windows = parse_ibkr_hours(liquid_hours, tz_name)

    if not windows:
        return False, f"Could not parse liquidHours returned by IBKR for timezone {tz_name}."

    for start_dt, end_dt in windows:
        if start_dt <= now_local <= end_dt:
            return True, (
                f"Market is open now in {tz_name}. "
                f"Current session: {start_dt.strftime('%Y-%m-%d %H:%M')} "
                f"to {end_dt.strftime('%Y-%m-%d %H:%M')}."
            )

    next_window = None
    for start_dt, end_dt in windows:
        if now_local < start_dt:
            next_window = (start_dt, end_dt)
            break

    if next_window:
        return False, (
            f"Market is closed now in {tz_name}. "
            f"Next session: {next_window[0].strftime('%Y-%m-%d %H:%M')} "
            f"to {next_window[1].strftime('%Y-%m-%d %H:%M')}."
        )

    return False, f"Market is closed now in {tz_name}."