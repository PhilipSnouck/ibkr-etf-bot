# ------------------------------------------------------------
# ENVIRONMENT SWITCH
# ------------------------------------------------------------
# Main environment toggle for the whole bot.
# Change only this value when switching between paper and live.
IB_ENVIRONMENT = "live"  # "paper" or "live"

# ------------------------------------------------------------
# EXECUTION MODE
# ------------------------------------------------------------
# preview -> never place orders
# execute -> place orders, but only when you run: python main.py buy
EXECUTION_MODE = "execute"  # "preview" or "execute"

# ------------------------------------------------------------
# IBC AUTO-START SETTINGS
# ------------------------------------------------------------
# Set to the full path of StartIBCWin.bat to auto-start IB Gateway
# when the bot cannot connect. Set to None to disable.
IBC_SCRIPT_PATH = r"C:\IBC\StartIBCWin.bat"

# ------------------------------------------------------------
# IBKR CONNECTION SETTINGS
# ------------------------------------------------------------
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
# Each account gets its own pending file.
PENDING_TOPUP_FILE_TEMPLATE = "pending_topup_{account_key}.json"
MAX_PENDING_TOPUP_AGE_DAYS = 7

# NOTE:
# Pending top-up completion uses real account cash, not
# planned_allocation_cash. The cap only affects the initial
# allocation decision for a run.


# ------------------------------------------------------------
# ORDER CASH BUFFER SETTINGS
# ------------------------------------------------------------
# IBKR charges commission per order.
# This amount is reserved for every order the bot plans to place.
ORDER_COMMISSION_BUFFER = 1.25

# ------------------------------------------------------------
# LIMIT ORDER SETTINGS
# ------------------------------------------------------------
# Used only for accounts with:
# "order_type": "limit"
#
# Limit price = detected price * (1 + limit_order_markup)
#
# Example:
# price = 116.60
# limit_order_markup = 0.005
# limit price = 117.18
DEFAULT_LIMIT_ORDER_MARKUP = 0.005

# ------------------------------------------------------------
# ACCOUNT DEFINITIONS
# ------------------------------------------------------------
# All adjustable account behavior lives here.
# enabled:
#   Whether this account is processed by the bot.
#
# account_ids:
#   IBKR account IDs per environment.
#   - paper: paper trading account ID
#   - live : live trading account ID
#
# currency:
#   Base currency used for cash checks and reporting.
#
# allocator:
#   Name of the allocator to use.
#   Must match a key in allocator_registry.py.
#
# planned_allocation_cash:
#   Optional cash cap for this strategy run.
#   - None: use full real available cash
#   - number: use up to this amount, but never above real cash
#
# rules.min_cash_to_execute:
#   Minimum usable cash required before execution is allowed.
#
# rules.pending_topup_enabled:
#   Whether this account uses the pending top-up system.
#
# rules.topup_trigger:
#   Fractional-share threshold that triggers a pending top-up
#   instead of immediate purchase.
#
# etfs:
#   ETF definitions used by the allocator for this account.
ACCOUNTS = {
    "Pension": {
        "enabled": True,
        "account_ids": {
            "paper": "DUQ244285",
            "live": "U16859527",
        },
        "currency": "EUR",
        "allocator": "pension",
        "limit_order_markup": 0.005,
        "planned_allocation_cash": None,
        "rules": {
            "min_cash_to_execute": 0,
            "pending_topup_enabled": True,
            "topup_trigger": 0.75,
        },
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
    },
    "Samen investeren": {
        "enabled": True,
        "account_ids": {
            "paper": None,
            "live": "U24635357",
        },
        "currency": "EUR",
        "allocator": "joint",
        "limit_order_markup": 0.005,
        "planned_allocation_cash": None,
        "rules": {
            "min_cash_to_execute": 100,
            "pending_topup_enabled": True,
            "topup_trigger": 0.75,
        },
        "etfs": {
            "IWDA": {
                "exchange": "AEB",
                "currency": "EUR",
                "target_weight": 1.00,
                "name": "ISHARES CORE MSCI WORLD",
            },
        },
    },
    "Otto": {
        "enabled": True,
        "account_ids": {
            "paper": None,
            "live": "U25477636",
        },
        "currency": "EUR",
        "allocator": "otto",
        "limit_order_markup": 0.005,
        "planned_allocation_cash": None,
        "rules": {
            "min_cash_to_execute": 100,
            "pending_topup_enabled": True,
            "topup_trigger": 0.75,
        },
        "etfs": {
            "IWDA": {
                "exchange": "AEB",
                "currency": "EUR",
                "target_weight": 1.00,
                "name": "ISHARES CORE MSCI WORLD",
            },
        },
    },
}