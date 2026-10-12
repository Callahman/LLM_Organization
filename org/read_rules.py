"""Read-scope rule checks.

A role can only read its team's department directory; department heads and the
leader cannot read any code (they see work only as it is brought to them).
Cross-team reads (sibling team dir in the same department) are allowed but must
be logged. Re-exported by the `org/tiers.py` facade.
"""

from __future__ import annotations

from org.tier_math import is_leader, is_head


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
