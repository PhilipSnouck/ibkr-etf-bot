import json
import os
from datetime import datetime, timedelta, timezone

from config import PENDING_TOPUP_FILE, MAX_PENDING_TOPUP_AGE_DAYS


# ------------------------------------------------------------
# LOAD PENDING TOP-UP FILE
# ------------------------------------------------------------
def load_pending_topup():
    if not os.path.exists(PENDING_TOPUP_FILE):
        return None

    with open(PENDING_TOPUP_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------
# SAVE PENDING TOP-UP FILE
# ------------------------------------------------------------
def save_pending_topup(data):
    with open(PENDING_TOPUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ------------------------------------------------------------
# DELETE PENDING TOP-UP FILE
# ------------------------------------------------------------
def clear_pending_topup():
    if os.path.exists(PENDING_TOPUP_FILE):
        os.remove(PENDING_TOPUP_FILE)


# ------------------------------------------------------------
# CHECK WHETHER PENDING TOP-UP HAS EXPIRED
# ------------------------------------------------------------
def is_pending_topup_expired(data):
    created_at_str = data["created_at_utc"]
    created_at = datetime.fromisoformat(created_at_str)

    expiry_time = created_at + timedelta(days=MAX_PENDING_TOPUP_AGE_DAYS)
    now = datetime.now(timezone.utc)

    return now > expiry_time


# ------------------------------------------------------------
# CALCULATE HOW MANY DAYS OLD THE PENDING ITEM IS
# ------------------------------------------------------------
def pending_topup_age_days(data):
    created_at_str = data["created_at_utc"]
    created_at = datetime.fromisoformat(created_at_str)

    now = datetime.now(timezone.utc)
    age = now - created_at

    return age.total_seconds() / 86400