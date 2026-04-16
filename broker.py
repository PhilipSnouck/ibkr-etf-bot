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
def qualify_etf_contracts(ib, etf_config):
    qualified = {}

    for symbol, settings in etf_config.items():
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