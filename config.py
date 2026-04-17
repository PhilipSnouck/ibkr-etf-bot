# ------------------------------------------------------------
# GLOBAL SETTINGS
# ------------------------------------------------------------
# Set to None to use real IBKR cash.
# Set to a number like 2100 to simulate a normal month.
TEST_CASH_OVERRIDE = 2100

# ------------------------------------------------------------
# ENVIRONMENT SWITCH
# ------------------------------------------------------------
# Main environment toggle for the whole bot.
# Change only this value when switching between paper and live.
IB_ENVIRONMENT = "paper"  # "paper" or "live"

# ------------------------------------------------------------
# EXECUTION MODE
# ------------------------------------------------------------
# preview -> never place orders
# execute -> place orders, but only when you run: python main.py buy
EXECUTION_MODE = "execute"  # "preview" or "execute"

# ------------------------------------------------------------
# IBKR CONNECTION SETTINGS
# ------------------------------------------------------------
# Settings used to connect to IBKR via IB Gateway or TWS.
# Usually no need to change these unless your setup differs.

IB_CONNECTIONS = {
    "paper": {
        "host": "127.0.0.1",
        "port": 4002,
        "client_id": 1,
    },
    "live": {
        "host": "127.0.0.1",
        "port": 4001,
        "client_id": 2,
    },
}

# ------------------------------------------------------------
# PENDING TOP-UP SETTINGS
# ------------------------------------------------------------
# If ETF3 reaches x.75 shares or higher, we skip ETF3 and
# ask for a top-up instead.
ETF3_TOPUP_TRIGGER = 0.75

# Pending top-up file name
PENDING_TOPUP_FILE = "pending_topup.json"

# Expire pending top-up items after 7 days
MAX_PENDING_TOPUP_AGE_DAYS = 7

# ------------------------------------------------------------
# ACCOUNT DEFINITIONS
# ------------------------------------------------------------
ACCOUNTS = {
    "Pension": {
        "account_ids": {
            "paper": "DUQ244285",
            "live": "U16859527",
        },
        "currency": "EUR",
        "etfs": {
            "VUAA": {
                "exchange": "BVME.ETF",
                "currency": "EUR",
                "target_weight": 0.60,
                "rounding": "nearest",
            },
            "IMAE": {
                "exchange": "AEB",
                "currency": "EUR",
                "target_weight": 0.30,
                "rounding": "force_up_if_previous_down",
            },
            "EGLN": {
                "exchange": "LSEETF",
                "currency": "EUR",
                "target_weight": 0.10,
                "rounding": "floor_remainder",
            },
        },
    }
}

# ------------------------------------------------------------
# WHICH ACCOUNT TO RUN
# ------------------------------------------------------------
TARGET_ACCOUNT_NAME = "Pension"