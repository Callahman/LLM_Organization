"""Phase 3 — Org bootstrap + resourcing (core registry).

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

**Decomposition (Phase 1):** this file keeps the core — constants, errors,
the `OrgState` registry, role-definition resolution, the 3-IC cap, and
directory creation. The approval matrix moved to `runtime/org_approvals.py`,
the bootstrap flow to `runtime/org_bootstrap.py`, hire/fire to
`runtime/org_resourcing.py`, and leader replacement to `runtime/org_leader.py`.
This file re-exports the full public API (backward-compatible facade).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from roles.base import Role

# Required departments (spun up at bootstrap; cannot be fired).
REQUIRED_DEPARTMENTS = ("hr", "safety", "morality")

# 3-IC direct-report cap for a non-manager (department head without a manager).
DIRECT_IC_CAP = 3

# Story 11 (B16): total org-size cap (default 60 roles). Enforced in the
# bootstrap (head count) and Phase 4 (hires); on exceed, refuse with a visible
# note (never silent).
MAX_ORG_ROLES = 60


class ResourcingError(ValueError):
    """A resourcing action that violates the approval matrix / caps."""


class ResourcingVetoed(ResourcingError):
    """A resourcing action vetoed by the approver (HR / the Leader)."""


class BootstrapError(ValueError):
    """Phase 3 produced no usable department-head proposal (empty, or only the
    required governance departments) — no work could be dispatched in Phase 4.
    Raised after the bounded retry budget is exhausted (never silent)."""


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
             "detail": detail or {}, "ts": time.time()}
        )

    def write_events(self) -> str:
        os.makedirs(self.history_dir, exist_ok=True)
        path = os.path.join(self.history_dir, "org_events.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.events = []
        return path

    # --- Persistence (the org chart, across runs) --------------------------

    def save(self, path: str = "state/org_chart.json") -> str:
        """Persist the org chart (every role + the role-definition catalog) to
        `path`. The event log is **not** persisted (it is already appended to
        `history/org_events.jsonl`). The write is **atomic** (Story 1, B3):
        the JSON goes to `path + ".tmp"` first, then `os.replace` swaps it in —
        a crash mid-write leaves the previous good chart intact (no partial
        JSON). Returns the path written."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {
            "roles": {rid: r.to_dict() for rid, r in self.roles.items()},
            "role_definitions": self.role_definitions,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: str = "state/org_chart.json",
             history_dir: str = "history") -> "OrgState":
        """Load an org chart from `path`. Returns a fresh `OrgState` (empty if
        the file is missing)."""
        org = cls(history_dir=history_dir)
        if not os.path.exists(path):
            return org
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return org
        for rid, data in payload.get("roles", {}).items():
            org.roles[rid] = Role.from_dict(data)
        org.role_definitions = payload.get("role_definitions", {})
        return org


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

def _check_ic_cap(org: OrgState, new_role: Role,
                  direct_ic_cap: int = DIRECT_IC_CAP) -> None:
    if new_role.architype != "ic":
        return
    boss = org.get(new_role.reports_to) if new_role.reports_to else None
    if boss is None or boss.architype != "department_head":
        return  # boss is a manager (no cap) or absent
    direct_ics = sum(
        1 for r in org.active_roles()
        if r.architype == "ic" and r.reports_to == boss.id
    )
    if direct_ics >= direct_ic_cap:
        raise ResourcingError(
            f"{direct_ic_cap}-IC direct-report cap reached under {boss.id}; "
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


# --- Backward-compatible facade --------------------------------------------
# The resourcing API moved to focused modules (Phase 1); re-export the full
# public API so `from runtime.org import hire, fire, bootstrap, ...` keeps
# working unchanged.

from runtime.org_approvals import (  # noqa: E402,F401
    _call_approver,
    _is_hr,
    required_approver,
)
from runtime.org_bootstrap import (  # noqa: E402,F401
    _bootstrap_context,
    _dept_slug,
    _ensure_required,
    _extract_department_heads,
    _has_operational_head,
    _normalize_head_spec,
    bootstrap,
)
from runtime.org_resourcing import (  # noqa: E402,F401
    _offload,
    _subtree,
    fire,
    hire,
)
from runtime.org_leader import (  # noqa: E402,F401
    replace_leader,
    run_leader_replacement_vote,
)

__all__ = [
    # core (kept here)
    "REQUIRED_DEPARTMENTS",
    "DIRECT_IC_CAP",
    "MAX_ORG_ROLES",
    "ResourcingError",
    "ResourcingVetoed",
    "BootstrapError",
    "OrgState",
    "resolve_role_definition",
    "_check_ic_cap",
    "_create_department_dirs",
    "_create_team_dir",
    # facade re-exports (moved to focused modules)
    "_call_approver",
    "_is_hr",
    "required_approver",
    "_bootstrap_context",
    "_dept_slug",
    "_ensure_required",
    "_extract_department_heads",
    "_has_operational_head",
    "_normalize_head_spec",
    "bootstrap",
    "_offload",
    "_subtree",
    "fire",
    "hire",
    "replace_leader",
    "run_leader_replacement_vote",
]
