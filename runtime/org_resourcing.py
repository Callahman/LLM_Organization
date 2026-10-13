"""Phase 3 — Hire / fire resourcing actions.

The hire/fire flow (Organization_Outline.md §2.5): approval matrix +
role-definition resolution + the **3-IC direct-report cap** + the approver's
decision (HR / the Leader). Firing includes HR's **firing review +
offloading** (automations stay intact; another team continues validating the
offloaded workflows) and the **firing cascade** (Story 22: firing a role
with its own reports fires the entire report subtree, with the cascade size
included in the single HR approval request).

**Decomposition (Phase 1):** extracted from `runtime/org.py` (the core
registry, constants, and errors stay there).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from roles.base import Role
from runtime.org import (
    DIRECT_IC_CAP,
    ResourcingError,
    ResourcingVetoed,
    OrgState,
    _check_ic_cap,
    _create_department_dirs,
    _create_team_dir,
    resolve_role_definition,
)
from runtime.org_approvals import _call_approver, required_approver


def hire(
    org: OrgState,
    initiator: Role,
    new_role: Role,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
    direct_ic_cap: int = DIRECT_IC_CAP,
) -> Role:
    """Hire a role through the approval matrix + role-definition resolution +
    the 3-IC cap + the approver's decision (HR / the Leader)."""
    approver_type, ok, reason = required_approver(initiator, new_role)
    if not ok:
        raise ResourcingError(reason)
    def_key = resolve_role_definition(org, new_role)
    _check_ic_cap(org, new_role, direct_ic_cap=direct_ic_cap)
    decision = approver_fn(approver_type, "hire", new_role)
    if decision.get("decision") != "approve":
        org.log_event("hire_vetoed", initiator.id, new_role.id, decision)
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    org.add_role(new_role)
    if new_role.architype == "department_head":
        _create_department_dirs(new_role, departments_dir)
    _create_team_dir(new_role, departments_dir)
    org.log_event("hired", initiator.id, new_role.id,
                  {"approver": approver_type, "def_key": def_key,
                   "department": new_role.department})
    return new_role


def _offload(org: OrgState, target: Role, departments_dir: str) -> Dict[str, Any]:
    """HR's offloading: the team's automations remain intact; another team is
    assigned to continue validating the offloaded workflows. The plan is
    written to `reports/offloading/`."""
    offload_dir = os.path.join(os.path.dirname(departments_dir), "reports", "offloading")
    os.makedirs(offload_dir, exist_ok=True)
    # Find a continuing team (any other active department head's dept).
    continuing = [
        h.department for h in org.department_heads()
        if h.department != target.department
    ]
    plan = {
        "target": target.id,
        "department": target.department,
        "automations_preserved": True,
        "continuing_team": continuing[0] if continuing else None,
        "plan_path": os.path.join(offload_dir, f"{target.id}.md"),
    }
    with open(plan["plan_path"], "w", encoding="utf-8") as f:
        f.write(
            f"# Offloading plan — {target.id}\n\n"
            f"- automations preserved: {plan['automations_preserved']}\n"
            f"- continuing team: {plan['continuing_team']}\n"
        )
    return plan


def _subtree(org: OrgState, root_id: str) -> List[str]:
    """The ``root`` + all of its **transitive reports** (the firing cascade,
    Story 22). Computed over the active roles via their ``reports_to`` links:
    firing a role that has its own reports fires the entire subtree, not just
    the top. Returns a list of role ids (the root first)."""
    children: Dict[str, List[str]] = {}
    for r in org.active_roles():
        if r.reports_to:
            children.setdefault(r.reports_to, []).append(r.id)
    seen: List[str] = [root_id]
    stack: List[str] = [root_id]
    while stack:
        cur = stack.pop()
        for ch in children.get(cur, []):
            if ch not in seen:
                seen.append(ch)
                stack.append(ch)
    return seen


def fire(
    org: OrgState,
    initiator: Role,
    target_id: str,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
    cascade: bool = True,
) -> Dict[str, Any]:
    """Fire a role through the approval matrix + the approver's decision (HR
    determines whether the firing is needed) + offloading. Required
    departments cannot be fired.

    **Cascading** (Story 22): when ``cascade`` is True (the default), firing a
    role that has its own reports fires the **entire report subtree** (the
    target + all transitive reports), not just the top. The **cascade size**
    (the number of roles that will be fired) is included in the **single** HR
    approval request (via a 4th ``detail`` argument — not raised separately per
    cascaded role). Set ``cascade`` to False to fire only the target (the
    legacy behavior)."""
    target = org.get(target_id)
    if target is None:
        raise ResourcingError(f"unknown role: {target_id}")
    if target.is_required:
        raise ResourcingError(
            f"{target.department} is a required department and cannot be fired"
        )
    approver_type, ok, reason = required_approver(initiator, target)
    if not ok:
        raise ResourcingError(reason)
    # The firing cascade (the target + its transitive reports).
    subtree_ids = _subtree(org, target.id) if cascade else [target.id]
    detail = {"cascade_size": len(subtree_ids), "cascade_role_ids": subtree_ids}
    # The single HR approval request includes the cascade size.
    decision = _call_approver(approver_fn, approver_type, "fire", target, detail)
    if decision.get("decision") != "approve":
        org.log_event("fire_vetoed", initiator.id, target_id,
                      {**decision, **detail})
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    plan = _offload(org, target, departments_dir)
    # Fire the whole subtree (the target first, then its reports).
    for rid in subtree_ids:
        org.mark_inactive(rid)
    org.log_event("fired", initiator.id, target_id,
                  {"approver": approver_type, "offloading": plan,
                   "department": target.department, **detail})
    return plan


__all__ = ["hire", "fire", "_offload", "_subtree"]
