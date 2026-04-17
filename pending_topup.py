import json
import os
from datetime import datetime, timedelta, timezone

from config import PENDING_TOPUP_FILE_TEMPLATE, MAX_PENDING_TOPUP_AGE_DAYS


# ------------------------------------------------------------
# PENDING TOP-UP FILE HELPERS
# ------------------------------------------------------------
# This module manages pending ETF purchases that require a
# small additional cash top-up before execution.
#
# Each account has its own pending top-up file, so multiple
# accounts can be processed independently in a single run.
#
# Responsibilities:
# - determine the correct file name per account
# - load/save pending top-up data
# - delete pending files when completed
# - check expiration of pending items
# - calculate age of pending items
#
# This module does NOT:
# - decide whether a top-up is needed (allocator does that)
# - decide whether to execute trades (rules/main do that)
# ------------------------------------------------------------


# ------------------------------------------------------------
# FILE NAME RESOLUTION
# ------------------------------------------------------------
# Convert an account name into a safe filename key and then build
# the correct pending top-up filename from config.py.

def get_account_key(account_name):
    """
    Convert a display account name into a filesystem-safe key.

    Example:
    - "Pension" -> "pension"
    - "Joint Account" -> "joint_account"
    """
    return account_name.strip().lower().replace(" ", "_")


def get_pending_topup_filename(account_name):
    """
    Return the account-specific pending top-up filename using the
    template defined in config.py.
    """
    account_key = get_account_key(account_name)
    return PENDING_TOPUP_FILE_TEMPLATE.format(account_key=account_key)


# ------------------------------------------------------------
# LOAD PENDING TOP-UP FILE
# ------------------------------------------------------------

def load_pending_topup(account_name):
    """
    Load the pending top-up file for a specific account.
    Return None if no file exists.
    """
    filename = get_pending_topup_filename(account_name)

    if not os.path.exists(filename):
        return None

    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------
# SAVE PENDING TOP-UP FILE
# ------------------------------------------------------------

def save_pending_topup(account_name, data):
    """
    Save pending top-up data for a specific account.
    """
    filename = get_pending_topup_filename(account_name)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ------------------------------------------------------------
# DELETE PENDING TOP-UP FILE
# ------------------------------------------------------------

def clear_pending_topup(account_name):
    """
    Delete the pending top-up file for a specific account if it exists.
    """
    filename = get_pending_topup_filename(account_name)

    if os.path.exists(filename):
        os.remove(filename)


# ------------------------------------------------------------
# CHECK WHETHER PENDING TOP-UP HAS EXPIRED
# ------------------------------------------------------------

def is_pending_topup_expired(data):
    """
    Return True if the pending top-up item is older than the maximum
    allowed age defined in config.py.
    """
    created_at_str = data["created_at_utc"]
    created_at = datetime.fromisoformat(created_at_str)

    expiry_time = created_at + timedelta(days=MAX_PENDING_TOPUP_AGE_DAYS)
    now = datetime.now(timezone.utc)

    return now > expiry_time


# ------------------------------------------------------------
# CALCULATE HOW MANY DAYS OLD THE PENDING ITEM IS
# ------------------------------------------------------------

def pending_topup_age_days(data):
    """
    Return the age of a pending top-up item in days.
    """
    created_at_str = data["created_at_utc"]
    created_at = datetime.fromisoformat(created_at_str)

    now = datetime.now(timezone.utc)
    age = now - created_at

    return age.total_seconds() / 86400