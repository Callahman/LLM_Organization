"""Phase 3 — Org bootstrap + resourcing.

The Leader proposes department heads → **HR redundancy review** → registry
creation → department directories + policy markdowns + team directories.
Required departments (**HR, Safety, Morality**) are spun up at bootstrap and
**cannot be fired**.

The hire/fire flow enforces (Organization_Outline.md §2.5):
- the **approval matrix** — ICs **cannot initiate** hiring/firing;
- **role-definition resolution** — adopt an existing definition, or
  create-then-adopt (logged);
- the **3-IC direct-report cap** — a manager is hired at the cap;
- HR's **firing review + offloading** — automations stay intact; another team
  continues validating the offloaded workflows;
- every event is logged to `history/org_events.jsonl`.

The HR-resilience initial pass (§2.5.1) is represented by the backup gate: if
HR is non-functional, resourcing escalates to the user.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role
from runtime.mission import MissionResult
from runtime.complexity import classify_complexity

# Required departments (spun up at bootstrap; cannot be fired).
REQUIRED_DEPARTMENTS = ("hr", "safety", "morality")

# 3-IC direct-report cap for a non-manager (department head without a manager).
DIRECT_IC_CAP = 3


class ResourcingError(ValueError):
    """A resourcing action that violates the approval matrix / caps."""


class ResourcingVetoed(ResourcingError):
    """A resourcing action vetoed by the approver (HR / the Leader)."""


# --- The org state (registry) ---------------------------------------------

class OrgState:
    """The org chart: every role + the role-definition catalog + the event log."""

    def __init__(self, history_dir: str = "history"):
        self.roles: Dict[str, Role] = {}
        self.role_definitions: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.history_dir = history_dir

    def add_role(self, role: Role) -> None:
        self.roles[role.id] = role

    def get(self, role_id: str) -> Optional[Role]:
        return self.roles.get(role_id)

    def mark_inactive(self, role_id: str) -> None:
        if role_id in self.roles:
            self.roles[role_id].status = "inactive"

    def active_roles(self) -> List[Role]:
        return [r for r in self.roles.values() if r.status == "active"]

    def department_heads(self) -> List[Role]:
        return [
            r for r in self.active_roles() if r.architype == "department_head"
        ]

    def log_event(self, kind: str, initiator: Optional[str], target: Optional[str],
                  detail: Optional[Dict[str, Any]] = None) -> None:
        self.events.append(
            {"kind": kind, "initiator": initiator, "target": target,
             "detail": detail or {}}
        )

    def write_events(self) -> str:
        os.makedirs(self.history_dir, exist_ok=True)
        path = os.path.join(self.history_dir, "org_events.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.events = []
        return path


# --- Approval matrix -------------------------------------------------------

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


# --- Role-definition resolution -------------------------------------------

def resolve_role_definition(org: OrgState, role: Role) -> str:
    """Adopt an existing role definition, or create-then-adopt (logged)."""
    key = f"{role.architype}:{role.sub_architype}"
    if key in org.role_definitions:
        return key  # adopt existing
    org.role_definitions[key] = {
        "architype": role.architype,
        "sub_architype": role.sub_architype,
        "mandate_template": role.mandate,
    }
    org.log_event("role_definition_created", None, key, org.role_definitions[key])
    return key


# --- 3-IC direct-report cap -----------------------------------------------

def _check_ic_cap(org: OrgState, new_role: Role) -> None:
    if new_role.architype != "ic":
        return
    boss = org.get(new_role.reports_to) if new_role.reports_to else None
    if boss is None or boss.architype != "department_head":
        return  # boss is a manager (no cap) or absent
    direct_ics = sum(
        1 for r in org.active_roles()
        if r.architype == "ic" and r.reports_to == boss.id
    )
    if direct_ics >= DIRECT_IC_CAP:
        raise ResourcingError(
            f"{DIRECT_IC_CAP}-IC direct-report cap reached under {boss.id}; "
            f"hire a manager to organize the ICs"
        )


# --- Directories -----------------------------------------------------------

def _create_department_dirs(head: Role, departments_dir: str) -> None:
    dept_dir = os.path.join(departments_dir, head.department)
    os.makedirs(dept_dir, exist_ok=True)
    policy = os.path.join(
        dept_dir, f"{head.department.upper()}_POLICY.md"
    )
    if not os.path.exists(policy):
        with open(policy, "w", encoding="utf-8") as f:
            f.write(
                f"# {head.department.upper()} POLICY\n\n"
                f"_(owned by {head.id}; sections per team)_\n"
            )


def _create_team_dir(role: Role, departments_dir: str) -> None:
    if role.team and role.department:
        team_dir = os.path.join(departments_dir, role.department, role.team)
        os.makedirs(team_dir, exist_ok=True)


# --- Bootstrap -------------------------------------------------------------

def _bootstrap_context(mission_result: MissionResult) -> str:
    return (
        "PHASE 3: propose the initial department heads for the mission. "
        "Produce org_recommendation.department_heads: a list of "
        "{id, department, sub_architype, required, mandate}. Required "
        "departments (hr, safety, morality) must be included."
    )


def _ensure_required(org: OrgState, departments_dir: str) -> List[Role]:
    """Ensure the required departments (hr, safety, morality) exist and are
    marked non-fireable."""
    created = []
    for dept in REQUIRED_DEPARTMENTS:
        existing = [
            r for r in org.active_roles()
            if r.architype == "department_head" and r.department == dept
        ]
        if existing:
            existing[0].is_required = True
            continue
        head = Role(
            id=f"head_{dept}",
            architype="department_head",
            sub_architype=f"head_of_{dept}",
            department=dept,
            mandate=f"Head of {dept.upper()}.",
            is_required=True,
        )
        org.add_role(head)
        _create_department_dirs(head, departments_dir)
        org.log_event("required_department_bootstrapped", None, head.id,
                      {"department": dept})
        created.append(head)
    return created


def bootstrap(
    org: OrgState,
    backend,
    leader: Role,
    mission_result: MissionResult,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
) -> List[Role]:
    """Phase 3: Leader proposes department heads → HR redundancy review →
    registry creation → directories. Required departments are always present."""
    out = backend.invoke(
        leader, _bootstrap_context(mission_result),
        # The Leader's head proposal is a resourcing decision -> thinking on.
        reasoning=classify_complexity(3, leader, {"is_decision": True}),
    )
    proposed = (
        out.get("org_recommendation", {}).get("department_heads", [])
    )
    created: List[Role] = []
    for spec in proposed:
        head = Role(
            id=spec["id"],
            architype="department_head",
            sub_architype=spec.get("sub_architype", ""),
            department=spec.get("department", ""),
            mandate=spec.get("mandate", ""),
            is_required=spec.get("required", False),
        )
        # HR redundancy review (vetoes redundant hires).
        decision = approver_fn("hr", "hire", head)
        if decision.get("decision") != "approve":
            org.log_event("bootstrap_vetoed", leader.id, head.id, decision)
            continue
        org.add_role(head)
        _create_department_dirs(head, departments_dir)
        org.log_event("bootstrapped", leader.id, head.id,
                      {"required": head.is_required})
        created.append(head)

    # Required departments are always spun up (and cannot be fired).
    created.extend(_ensure_required(org, departments_dir))
    return created


# --- Hire / fire -----------------------------------------------------------

def hire(
    org: OrgState,
    initiator: Role,
    new_role: Role,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
) -> Role:
    """Hire a role through the approval matrix + role-definition resolution +
    the 3-IC cap + the approver's decision (HR / the Leader)."""
    approver_type, ok, reason = required_approver(initiator, new_role)
    if not ok:
        raise ResourcingError(reason)
    def_key = resolve_role_definition(org, new_role)
    _check_ic_cap(org, new_role)
    decision = approver_fn(approver_type, "hire", new_role)
    if decision.get("decision") != "approve":
        org.log_event("hire_vetoed", initiator.id, new_role.id, decision)
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    org.add_role(new_role)
    if new_role.architype == "department_head":
        _create_department_dirs(new_role, departments_dir)
    _create_team_dir(new_role, departments_dir)
    org.log_event("hired", initiator.id, new_role.id,
                  {"approver": approver_type, "def_key": def_key})
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


def fire(
    org: OrgState,
    initiator: Role,
    target_id: str,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
) -> Dict[str, Any]:
    """Fire a role through the approval matrix + the approver's decision (HR
    determines whether the firing is needed) + offloading. Required
    departments cannot be fired."""
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
    decision = approver_fn(approver_type, "fire", target)
    if decision.get("decision") != "approve":
        org.log_event("fire_vetoed", initiator.id, target_id, decision)
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    plan = _offload(org, target, departments_dir)
    org.mark_inactive(target_id)
    org.log_event("fired", initiator.id, target_id,
                  {"approver": approver_type, "offloading": plan})
    return plan


# --- Leader replacement ----------------------------------------------------

def replace_leader(
    org: OrgState,
    new_leader: Role,
    agreeing_head_ids: List[str],
) -> Role:
    """Unanimous department-head vote replaces the Leader (§2.2.1). The
    original prompt/goal is still abided by. Logged."""
    heads = org.department_heads()
    if not heads:
        raise ResourcingError("no department heads to vote")
    if set(agreeing_head_ids) != {h.id for h in heads}:
        raise ResourcingError("leader replacement requires UNANIMOUS heads")
    # The old leader is marked inactive (a firing by this special rule).
    old = org.get("leader")
    if old is not None:
        old.status = "inactive"
    org.add_role(new_leader)
    org.log_event("leader_replaced", None, new_leader.id,
                  {"agreeing_heads": agreeing_head_ids})
    return new_leader
