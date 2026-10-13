"""Phase 3 — Approval matrix for resourcing actions.

The hire/fire **approval matrix** (Organization_Outline.md §2.5): ICs
**cannot initiate** hiring/firing; HR's own decisions require the Leader;
only the Leader can hire/fire a department head (HR-approved); a manager /
department head resourcing a direct report requires HR. Plus the
backward-compatible approver-call helper (`_call_approver`).

**Decomposition (Phase 1):** extracted from `runtime/org.py` (the core
registry, constants, and errors stay there).
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Optional

from roles.base import Role


def _is_hr(role: Role) -> bool:
    return role.department == "hr"


def required_approver(initiator: Role, target: Role):
    """Return `(approver_type, ok, reason)` for a hire/fire.

    - ICs cannot initiate.
    - HR's own decisions require the Leader.
    - Only the Leader can hire/fire a department head (HR-approved).
    - A manager / department head resourcing a direct report requires HR.
    """
    if initiator is None:
        return None, False, "unknown initiator (the role is not in the org)"
    if initiator.architype == "ic":
        return None, False, "ICs cannot initiate hiring/firing"
    if _is_hr(initiator):
        return "leader", True, "HR's own decisions require the Leader's approval"
    if target.architype == "department_head":
        if initiator.architype != "leader":
            return None, False, "only the Leader can hire/fire a department head"
        return "hr", True, "the Leader's department-head decisions require HR"
    return "hr", True, "direct-report resourcing requires HR"


def _call_approver(approver_fn, approver_type: str, action: str, target: Role,
                   detail: Optional[Dict[str, Any]] = None):
    """Call the HR approver, passing the ``detail`` (e.g. the firing cascade
    size, Story 22) as a 4th argument **when the approver accepts it**.
    Backward compatible with 3-arg approvers (``detail`` is omitted) — so a
    user-supplied ``approver_fn(approver_type, action, target)`` keeps working.

    The cascade size is included in the **single** firing approval request
    (not raised separately per cascaded role): one approver call covers the
    whole subtree."""
    accepts_detail = False
    try:
        params = inspect.signature(approver_fn).parameters
        accepts_detail = (
            any(p.kind == p.VAR_POSITIONAL for p in params.values())
            or len(params) >= 4
        )
    except (TypeError, ValueError):
        accepts_detail = False
    if accepts_detail and detail is not None:
        return approver_fn(approver_type, action, target, detail)
    return approver_fn(approver_type, action, target)


__all__ = ["_is_hr", "required_approver", "_call_approver"]
