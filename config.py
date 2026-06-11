import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config_store.json"

def _load():
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))

_s = _load()

# ------------------------------------------------------------
# ENVIRONMENT SWITCH
# ------------------------------------------------------------
IB_ENVIRONMENT = _s["ib_environment"]

# ------------------------------------------------------------
# EXECUTION MODE
# ------------------------------------------------------------
EXECUTION_MODE = _s["execution_mode"]

# ------------------------------------------------------------
# IBC AUTO-START SETTINGS
# ------------------------------------------------------------
# Loaded from config_store.json (editable via the Settings page).
# Full path to StartGateway.bat to auto-start IB Gateway when the bot
# cannot connect.
IBC_SCRIPT_PATH = _s["ibc_script_path"]

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
PENDING_TOPUP_FILE_TEMPLATE = "pending_topup_{account_key}.json"
MAX_PENDING_TOPUP_AGE_DAYS = _s["max_pending_topup_age_days"]

# ------------------------------------------------------------
# ORDER CASH BUFFER SETTINGS
# ------------------------------------------------------------
ORDER_COMMISSION_BUFFER = _s["order_commission_buffer"]

# ------------------------------------------------------------
# LIMIT ORDER SETTINGS
# ------------------------------------------------------------
DEFAULT_LIMIT_ORDER_MARKUP = _s["default_limit_order_markup"]

# ------------------------------------------------------------
# ACCOUNT DEFINITIONS
# ------------------------------------------------------------
ACCOUNTS = _s["accounts"]
