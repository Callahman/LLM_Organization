"""Tier math + the read-scope / communication / pod rule checks.

This module is deliberately dependency-light: it operates on any object that
exposes the attributes of a `roles.base.Role` (architype, department, team,
reports_to). That keeps the invariants testable in isolation and reusable by
the runtime.

Worked examples encoded here (Organization_Outline.md §2.4, §2.8):

- an IC (tier 3) may pod with managers (tier 2) and other ICs (tier 3) — but
  NOT a department head (tier 1), which would be a 2-tier spread;
- a manager (tier 2) may pod with the department head (tier 1) and other
  managers (tier 2) — but NOT ICs (tier 3);
- same-tier pods are allowed (0-tier spread);
- a role can only read its team's department directory;
- department heads and the leader cannot read any code.

**Decomposition (Phase A):** the implementation now lives in focused modules —
`org/tier_math.py` (the base), `org/read_rules.py`, `org/communication.py`, and
`org/pod_rules.py`. This file is a backward-compatible facade that re-exports
the full public API, so `from org import tiers` and `tiers.<name>` keep working
unchanged.
"""

from __future__ import annotations

# Base tier math (no intra-org dependencies).
from org.tier_math import (
    TIER_LEADER,
    TIER_HEAD,
    TIER_MANAGER,
    TIER_IC,
    ARCHITYPE_TIER,
    POD_MIN_ROLES,
    POD_MAX_ROLES,
    POD_MAX_SPREAD,
    architype_to_tier,
    tier_of,
    is_leader,
    is_head,
)

# Read-scope rules.
from org.read_rules import (
    policy_path,
    is_code_path,
    can_read,
    can_read_code,
    cross_team_read,
)

# Communication rules.
from org.communication import (
    _same_team,
    can_communicate,
)

# Pod membership rules.
from org.pod_rules import (
    pod_spread,
    validate_pod,
)

__all__ = [
    # tiers
    "TIER_LEADER",
    "TIER_HEAD",
    "TIER_MANAGER",
    "TIER_IC",
    "ARCHITYPE_TIER",
    "POD_MIN_ROLES",
    "POD_MAX_ROLES",
    "POD_MAX_SPREAD",
    "architype_to_tier",
    "tier_of",
    "is_leader",
    "is_head",
    # read scope
    "policy_path",
    "is_code_path",
    "can_read",
    "can_read_code",
    "cross_team_read",
    # communication
    "_same_team",
    "can_communicate",
    # pod membership
    "pod_spread",
    "validate_pod",
]
