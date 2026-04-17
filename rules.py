# ------------------------------------------------------------
# RULE HELPERS (CONFIG-DRIVEN LOGIC ONLY)
# ------------------------------------------------------------
# This file contains reusable rule logic that interprets values
# from config.py.
#
# IMPORTANT:
# - Do NOT hardcode thresholds or behavior here
# - All adjustable values must live in config.py
# - This file only reads and evaluates those values
# ------------------------------------------------------------


# ------------------------------------------------------------
# ACCOUNT BASICS
# ------------------------------------------------------------
# Simple helpers to extract core account configuration

def is_account_enabled(account_settings):
    """Check if this account should be processed at all."""
    return account_settings.get("enabled", False)


def get_allocator_name(account_settings):
    """Return which allocator this account should use."""
    return account_settings.get("allocator")


def get_account_currency(account_settings):
    """Return account base currency (e.g. EUR)."""
    return account_settings.get("currency")


def get_account_id(account_settings, environment):
    """
    Return the correct IBKR account ID based on environment.
    Example:
    - paper -> DUxxxx
    - live  -> Uxxxx
    """
    return account_settings["account_ids"][environment]


# ------------------------------------------------------------
# CASH RULES
# ------------------------------------------------------------
# These rules determine whether an account is allowed to execute
# based on available cash.

def get_min_cash_to_execute(account_settings):
    """
    Minimum cash required before execution is allowed.
    Defined per account in config.py.
    """
    return account_settings.get("rules", {}).get("min_cash_to_execute", 0)


def passes_min_cash_rule(account_settings, cash):
    """
    Check whether the account has enough cash to execute.

    Returns:
    - True/False
    - the minimum threshold used (for logging/debugging)
    """
    min_cash = get_min_cash_to_execute(account_settings)

    if cash >= min_cash:
        return True, min_cash

    return False, min_cash


# ------------------------------------------------------------
# TOP-UP RULES
# ------------------------------------------------------------
# These rules control whether the "ETF3 top-up" mechanism is used.

def pending_topup_enabled(account_settings):
    """
    Whether this account uses the pending top-up system.

    Example:
    - Pension: True
    - Otto: False
    """
    return account_settings.get("rules", {}).get("pending_topup_enabled", False)


def get_topup_trigger(account_settings):
    """
    Fractional threshold for triggering a top-up.

    Example:
    - 0.75 means:
      if we reach 0.75 of a share, we wait and request top-up
      instead of buying partial allocation
    """
    return account_settings.get("rules", {}).get("topup_trigger", 0.75)