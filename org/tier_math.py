"""Tier math — the base of the `org/` rule checks.

This is the dependency-light core that the read-scope / communication / pod
rule modules import. It operates on any object that exposes the attributes of
a `roles.base.Role` (architype, department, team, reports_to), which keeps the
invariants testable in isolation and reusable by the runtime.

`org/tiers.py` is a backward-compatible facade that re-exports everything
defined here plus the rule modules (`read_rules`, `communication`,
`pod_rules`).
"""

from __future__ import annotations

# --- Tiers -----------------------------------------------------------------

TIER_LEADER = 0
TIER_HEAD = 1
TIER_MANAGER = 2
TIER_IC = 3

ARCHITYPE_TIER = {
    "leader": TIER_LEADER,
    "department_head": TIER_HEAD,
    "manager": TIER_MANAGER,
    "ic": TIER_IC,
}

# --- Pod membership bounds --------------------------------------------------

POD_MIN_ROLES = 2
POD_MAX_ROLES = 6
POD_MAX_SPREAD = 1  # max tier spread across all pod members


# --- Tier math -------------------------------------------------------------

def architype_to_tier(architype: str) -> int:
    """Map an architype to its tier. Raises on an unknown architype."""
    try:
        return ARCHITYPE_TIER[architype]
    except KeyError:
        raise ValueError(f"unknown architype: {architype!r}") from None


def tier_of(role) -> int:
    """The tier of a role (leader=0, head=1, manager=2, ic=3)."""
    return architype_to_tier(role.architype)


def is_leader(role) -> bool:
    return role.architype == "leader"


def is_head(role) -> bool:
    return role.architype == "department_head"
