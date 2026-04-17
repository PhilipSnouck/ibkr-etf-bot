# ------------------------------------------------------------
# OTTO ACCOUNT ALLOCATOR (PLACEHOLDER)
# ------------------------------------------------------------
# This allocator will later contain the logic for the Otto account.
#
# Planned behavior (to be defined):
# - account-specific allocation logic
# - execution only if minimum cash rule is met
#
# Important:
# - the minimum cash threshold itself belongs in config.py
# - this allocator should only calculate what to buy
# - main.py + rules.py decide whether buying is allowed
#
# For now:
# - this is a placeholder to complete the architecture
# - it raises an error if accidentally used
# ------------------------------------------------------------

def allocate_otto_portfolio(cash, etf_config, prices, **kwargs):
    raise NotImplementedError("Otto allocator is not implemented yet.")