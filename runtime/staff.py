"""Phase 5 (Staff) — the per-team manager workflow (IC decomposition + hiring).

A pure split out of the old monolithic ``runtime/dispatch.dispatch`` (Epic:
the 8-phase restructure). Phase 5 (Staff) consumes the ``PlanResult`` from
Phase 4 (Plan) and does, per team objective:

- **Manager branch** (the team objective names a manager, hired in Plan): the
  manager decomposes its team objective into **IC tasks**, and the **ICs**
  those tasks name are hired (the managers->ICs chain, through the HR
  approver).
- **Head-directed branch** (no manager — the head directs an IC directly):
  the single IC the team objective names is hired.

Phase 6 (Execute, ``runtime/execute.py``) then runs the per-IC work + pod
triggers + the upward report.

The shared helpers live in ``runtime/dispatch_common.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import OrgState
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.pods import SoloTracker
from runtime.plan import PlanResult
from runtime.dispatch_common import (
    _manager_ctx,
    _decomposition_list,
    _ensure_role,
)


@dataclass
class StaffResult:
    """The output of Phase 5 (Staff) — what Phase 6 (Execute) consumes.

    - ``plan``: the ``PlanResult`` (carried so Execute can read the
      ``digest`` + ``head_policies``).
    - ``departments``: one entry per department — ``{"head": Role,
      "objective": str, "teams": [...]}`` where each team is
      ``{"t_obj": dict, "manager": Role or None, "ic_tasks": [...]}``.
      The ICs those tasks name have been hired and are in the org.
    """

    plan: PlanResult
    departments: List[Dict[str, Any]] = field(default_factory=list)


def run_staff(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    plan: PlanResult,
    approver_fn=None,
    config: Optional[Dict[str, Any]] = None,
    solo: Optional[SoloTracker] = None,
) -> StaffResult:
    """Run Phase 5 (Staff): the per-team manager workflow (IC decomposition +
    IC hiring). Consumes the ``PlanResult`` from Phase 4 (Plan) and returns a
    ``StaffResult`` for Phase 6 (Execute) to consume.

    ``approver_fn`` (optional) lets the staff hire the ICs it decomposes onto
    when they don't exist yet (the managers->ICs chain); without it, the staff
    only reaches roles already in the org.
    """
    digest = plan.digest
    head_policies = plan.head_policies
    departments: List[Dict[str, Any]] = []
    for dept in plan.departments:
        head = dept["head"]
        teams: List[Dict[str, Any]] = []
        for t_obj in dept["team_objectives"]:
            manager = org.get(t_obj.get("manager_id", ""))
            if manager is not None:
                # Manager branch: the manager decomposes its team objective
                # into IC tasks (invoked with the department POLICY + the
                # bounded mission digest).
                mgr_out = backend.invoke(
                    manager,
                    _manager_ctx(
                        manager, t_obj.get("objective", ""),
                        policy=head_policies.get(head.id, {}).get("policy", ""),
                        digest=digest),
                    reasoning=classify_complexity(5, manager, {}), phase=5)
                ic_tasks = _decomposition_list(mgr_out, "ic_tasks")
                # Solo (P4, manager): record the manager's decomposition
                # (out-of-pod work) so the dashboard can watch any role's solo
                # work, not just the leader's (Story 21).
                if solo is not None:
                    solo.record(
                        "p5", "Phase 5: manager decomposition", 0, "decompose",
                        {"summary": f"decomposed the team objective into "
                                    f"{len(ic_tasks)} IC task(s)",
                         "ic_tasks": ic_tasks},
                        role=manager,
                    )
                # Hire the ICs the tasks name (the managers->ICs chain, through
                # the HR approver). Phase 6 (Execute) invokes them.
                for task in ic_tasks:
                    ic = org.get(task.get("ic_id", ""))
                    if ic is None and task.get("ic_id"):
                        _ensure_role(
                            org, manager, task.get("ic_id"), "ic",
                            manager.department, manager.team, approver_fn,
                            direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                        )
                teams.append({
                    "t_obj": t_obj,
                    "manager": manager,
                    "ic_tasks": ic_tasks,
                })
            else:
                # Head-directed branch (no manager — the head directs an IC
                # directly): the single IC the team objective names is hired.
                ic = org.get(t_obj.get("ic_id", ""))
                if ic is None and t_obj.get("ic_id"):
                    # `team` becomes the team work dir
                    # (departments/<dept>/<team>/). Fall back to the ic_id so
                    # it is NEVER empty — an empty team leaves the IC with no
                    # concrete work root.
                    _ensure_role(
                        org, head, t_obj.get("ic_id"), "ic",
                        head.department,
                        t_obj.get("team") or t_obj.get("ic_id", ""),
                        approver_fn,
                        direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                    )
                teams.append({
                    "t_obj": t_obj,
                    "manager": None,
                    # The head-directed IC does the team objective directly.
                    "ic_tasks": [
                        {"ic_id": t_obj.get("ic_id", ""),
                         "task": t_obj.get("objective", "")},
                    ],
                })
        departments.append({
            "head": head,
            "objective": dept["objective"],
            "teams": teams,
        })
    return StaffResult(plan=plan, departments=departments)
