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
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

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


# --- Read scope -------------------------------------------------------------

def policy_path(dept: str) -> str:
    """The path of a department's policy markdown, e.g.
    `departments/analytics/ANALYTICS_POLICY.md`."""
    return f"departments/{dept}/{dept.upper()}_POLICY.md"


def is_code_path(path: str) -> bool:
    """A *code* (work-product) path — anything that is not the global mission
    markdown and not a department policy markdown."""
    return path != "MISSION.md" and not path.endswith("_POLICY.md")


def can_read(role, path: str) -> bool:
    """Can `role` directly read this file path?

    - leader: only `MISSION.md` (which it owns/edits).
    - department head: only its own department policy markdown (governance,
      not work).
    - manager / ic: only within its own team's department directory.
    """
    if is_leader(role):
        return path == "MISSION.md"
    if is_head(role):
        return path == policy_path(role.department)
    # manager / ic
    return path.startswith(f"departments/{role.department}/")


def can_read_code(role, path: str) -> bool:
    """Can `role` directly read *code* (work products)?

    Department heads and the leader **cannot read any code at all** — they see
    work only as it is brought to them (reports, summaries, decision
    artifacts). Managers and ICs can read code within their own department.

    **Enforced (Story 14):** this invariant is wired into the live path via the
    read gate — `runtime/permissions.py::read_file` refuses a code read for a
    head/leader (and any out-of-scope read) with a visible `PermissionError`,
    and the dispatch's self-edit flow pre-reads the code an IC is about to
    change through that gate.
    """
    if is_leader(role) or is_head(role):
        return False
    return can_read(role, path) and is_code_path(path)


def cross_team_read(role, path: str) -> bool:
    """True when a role is reading a *sibling team directory in the same
    department* (the duplication-check purpose, §2.4). This is the read that
    must be logged in the audit trail.

    **Enforced (Story 14):** this invariant is wired into the live path via the
    read gate — `runtime/permissions.py::read_file` **logs** a cross-team read
    (visible, not silent) when a role reads a sibling team dir in the same
    department, so the audit shows the duplication-check read.
    """
    if is_leader(role) or is_head(role):
        return False
    if not can_read(role, path):
        return False
    # same department, but a different team's subdirectory
    dept_prefix = f"departments/{role.department}/"
    if not path.startswith(dept_prefix):
        return False
    rest = path[len(dept_prefix):]
    first_seg = rest.split("/", 1)[0]
    return role.team and first_seg != role.team


# --- Communication ----------------------------------------------------------

def _same_team(a, b) -> bool:
    return (
        a.department and a.department == b.department
        and a.team and a.team == b.team
    )


def can_communicate(a, b) -> bool:
    """Can `a` directly communicate with `b`?

    - The leader is the apex: any sub-agent may communicate with the leader,
      and vice versa.
    - Otherwise communication is allowed only within your own line: your boss,
      your reports, or team-mates (same team). No reaching into another
      sub-agent's direct reports.
    """
    if is_leader(a) or is_leader(b):
        return True
    if b.id == a.reports_to:  # b is a's boss
        return True
    if a.id == b.reports_to:  # a is b's boss
        return True
    if _same_team(a, b):
        return True
    return False


# --- Pod membership ---------------------------------------------------------

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
