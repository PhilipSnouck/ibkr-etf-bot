# ------------------------------------------------------------
# ALLOCATOR REGISTRY
# ------------------------------------------------------------
# This file maps allocator names from config.py to the actual
# allocator functions.
#
# Why this exists:
# - config.py can say: "allocator": "pension"
# - main.py should not need messy if/else chains
# - adding future allocators becomes simple
#
# Pattern:
# - config chooses the allocator name
# - registry resolves that name to a callable function
# ------------------------------------------------------------

from allocator_pension import allocate_pension_portfolio
from allocator_joint import allocate_joint_portfolio
from allocator_otto import allocate_otto_portfolio


ALLOCATORS = {
    "pension": allocate_pension_portfolio,
    "joint": allocate_joint_portfolio,
    "otto": allocate_otto_portfolio,
}


def get_allocator(allocator_name):
    """
    Return the allocator function that matches the given name.

    Example:
    - "pension" -> allocate_pension_portfolio
    - "joint"   -> allocate_joint_portfolio
    - "otto"    -> allocate_otto_portfolio
    """
    if allocator_name not in ALLOCATORS:
        raise ValueError(f"Unknown allocator: {allocator_name}")

    return ALLOCATORS[allocator_name]