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
        "enabled": False,
        "account_ids": {
            "paper": None,
            "live": None,
        },
        "currency": "EUR",
        "allocator": "otto",
        "planned_allocation_cash": None,
        "rules": {
            "min_cash_to_execute": 300,
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