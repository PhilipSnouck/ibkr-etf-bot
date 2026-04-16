# ------------------------------------------------------------
# GLOBAL SETTINGS
# ------------------------------------------------------------
# Set to None to use real IBKR cash.
# Set to a number like 2100 to simulate a normal month.
TEST_CASH_OVERRIDE = 2100

# ------------------------------------------------------------
# EXECUTION MODE
# ------------------------------------------------------------
# For now we keep this in dry-run mode only.
# Later we can add live order execution.
EXECUTION_MODE = "dry_run"

# ------------------------------------------------------------
# IBKR CONNECTION SETTINGS
# ------------------------------------------------------------
# Settings used to connect to IBKR via IB Gateway or TWS.
# Usually no need to change these unless your setup differs.

# IP address of IB Gateway / TWS
# "127.0.0.1" = running on this computer
IB_HOST = "127.0.0.1"

# API port (depends on your setup)
# Common defaults:
# - 4001 → IB Gateway (live)
# - 4002 → IB Gateway (paper)
# - 7496 → TWS (live)
# - 7497 → TWS (paper)
IB_PORT = 4001

# Unique ID for this connection
# Use different IDs if running multiple bots
IB_CLIENT_ID = 1

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
        "account_id": "U16859527",
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