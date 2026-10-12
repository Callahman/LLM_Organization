"""Pod membership rule checks.

Pod membership requires max 1-tier spread across all members (2–6 size).
Re-exported by the `org/tiers.py` facade.
"""

from __future__ import annotations

from typing import Iterable, Tuple

from org.tier_math import tier_of, POD_MIN_ROLES, POD_MAX_ROLES, POD_MAX_SPREAD


def pod_spread(members: Iterable) -> int:
    """The tier spread of a set of pod members (max tier - min tier)."""
    tiers = [tier_of(m) for m in members]
    return max(tiers) - min(tiers)


def validate_pod(members: Iterable,
                 min_roles: int = POD_MIN_ROLES,
                 max_roles: int = POD_MAX_ROLES) -> Tuple[bool, str]:
    """Validate pod membership: `min_roles`–`max_roles` size and max 1-tier
    spread. The bounds default to the module constants but can be overridden by
    the ``POD_MIN_ROLES`` / ``POD_MAX_ROLES`` .env knobs (S20 wire-in).

    Returns (ok, reason).
    """
    members = list(members)
    if not (min_roles <= len(members) <= max_roles):
        return False, (
            f"pod size must be {min_roles}-{max_roles}, "
            f"got {len(members)}"
        )
    spread = pod_spread(members)
    if spread > POD_MAX_SPREAD:
        return False, (
            f"pod tier spread must be <= {POD_MAX_SPREAD}, got {spread}"
        )
    return True, "ok"
