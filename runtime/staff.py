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
from runtime.org import OrgState, fire
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.pods import (
    SoloTracker,
    form_pod,
    log_devils_advocate_listening,
)
from runtime.plan import PlanResult
from runtime.dispatch_common import (
    _manager_ctx,
    _decomposition_list,
    _ensure_role,
    _run_contained_pod,
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


# ---: the headcount cap chain (Phase 5 — enforce the team/IC cap) ---

def _team_cap_ok(org: OrgState, department: str, team: str) -> bool:
    """whether a hire into the team is allowed (the current active IC
    count + 1 ≤ the team cap). If the team has no cap allotted, the hire is
    allowed (the org then falls back to the per-manager IC cap, ``DIRECT_IC_CAP``)."""
    cap = org.team_caps.get((department, team))
    if not cap:
        return True
    current = sum(
        1 for r in org.active_roles()
        if r.architype == "ic" and r.department == department
        and r.team == team
    )
    return current + 1 <= cap


def run_staff(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    plan: PlanResult,
    approver_fn=None,
    config: Optional[Dict[str, Any]] = None,
    solo: Optional[SoloTracker] = None,
    history: Optional[HistoryStore] = None,
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
                # the **head+manager clarification pod** (per team) —
                # a 2-member parent+child pod that clarifies the team's
                # mission. It runs BEFORE the manager decomposes (the
                # IC tasks reflect the clarified team mission), and is
                # **contained** (a pod failure is logged, never takes down the
                # phase).
                pod = form_pod(
                    org.roles, head.id, [head.id, manager.id],
                    f"Clarify the team's mission (team "
                    f"{t_obj.get('team') or manager.team})",
                    kind="clarification",
                )
                # the devil's advocate "listens" to the head+manager
                # clarification pod (the head is a member — visible, never
                # silent).
                log_devils_advocate_listening(org, pod, org.roles)
                _run_contained_pod(backend, org, pod,
                                   max_rounds=(config or {}).get(
                                       "clarification_pod_rounds"),
                                   transcripts_dir=(config or {}).get(
                                       "pod_transcripts_dir",
                                       "pods/transcripts"),
                                   phase=5)
                # Manager branch: the manager decomposes its team objective
                # into IC tasks (invoked with the department POLICY + the
                # bounded mission digest + the clarification pod's outcome
                # ). The manager is shown the team's **existing ICs** so it
                # REUSES them (names them in `ic_tasks`) instead of inventing
                # new ids every cycle — an existing IC it does not reuse is
                # fired / flagged for firing (below).
                existing_ics = [
                    r.id for r in org.active_roles()
                    if r.architype == "ic" and r.reports_to == manager.id
                ]
                mgr_ctx = _manager_ctx(
                    manager, t_obj.get("objective", ""),
                    policy=head_policies.get(head.id, {}).get("policy", ""),
                    digest=digest,
                    clarification=pod.decision or "")
                if existing_ics:
                    mgr_ctx += (
                        f" EXISTING ICs in your team (REUSE them — name each "
                        f"one in `ic_tasks` with its task, or it will be "
                        f"fired as unused; do NOT invent a new id for work an "
                        f"existing IC can do): {', '.join(existing_ics)}.")
                mgr_out = backend.invoke(
                    manager, mgr_ctx,
                    reasoning=classify_complexity(5, manager, {}), phase=5)
                ic_tasks = _decomposition_list(mgr_out, "ic_tasks")
                # Solo (P4, manager): record the manager's decomposition
                # (out-of-pod work) so the dashboard can watch any role's solo
                # work, not just the leader's.
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
                # enforce the **team/IC cap** (a hire that would
                # exceed the team cap is blocked — a visible note, never
                # silent). (The manager+ic clarification pod runs in Phase 6
                # (Execute), AFTER the IC's work — see run_execute.)
                for task in ic_tasks:
                    ic_id = task.get("ic_id", "")
                    if not ic_id:
                        continue
                    ic = org.get(ic_id)
                    if ic is not None:
                        # Re-link a reused IC to the current manager so its
                        # reporting line matches the plan (the communication
                        # gate in run_execute requires ic.reports_to ==
                        # manager.id). Without this, an IC hired under a
                        # different manager in a previous cycle breaks the
                        # manager+IC clarification pod (PodMembershipError).
                        # Log the re-link (visible, never silent).
                        if ic.reports_to != manager.id:
                            org.log_event("ic_relinked", manager.id, ic_id,
                                          {"old_reports_to": ic.reports_to,
                                           "new_reports_to": manager.id})
                            ic.reports_to = manager.id
                            ic.department = manager.department
                            ic.team = manager.team
                    else:
                        if not _team_cap_ok(org, manager.department, manager.team):
                            org.log_event(
                                "team_cap_reached", manager.id, ic_id,
                                {"department": manager.department,
                                 "team": manager.team},
                            )
                            continue
                        _ensure_role(
                            org, manager, ic_id, "ic",
                            manager.department, manager.team, approver_fn,
                            direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                            backend=backend, phase=5,
                            history=history,
                        )
                # Fire / flag the existing ICs the manager did NOT reuse (they
                # have no current task — the manager's decomposition did not
                # name them). This keeps the team's headcount bounded across
                # cycles (the manager reuses its ICs instead of the org
                # accumulating one new IC per cycle). Goes through HR (a veto
                # is logged, never swallowed); a missing approver / veto flags
                # the IC for firing instead (visible, never silent).
                reused_ids = {
                    t.get("ic_id", "") for t in ic_tasks
                    if isinstance(t, dict)
                }
                for ic_id in existing_ics:
                    if ic_id in reused_ids:
                        continue
                    ic = org.get(ic_id)
                    if ic is None or ic.status != "active":
                        continue
                    # IC conflict: if this IC was re-linked to a DIFFERENT
                    # manager in this cycle (another team's decomposition
                    # named it), it is in use — do not fire it (the re-link to
                    # the other manager is the resolution).
                    if ic.reports_to != manager.id:
                        org.log_event("ic_reused_elsewhere", manager.id, ic_id,
                                      {"reports_to": ic.reports_to,
                                       "reason": "named by another team's "
                                                 "decomposition — in use, "
                                                 "not fired"})
                        continue
                    fired = False
                    if approver_fn is not None:
                        try:
                            fire(org, manager, ic_id, approver_fn,
                                 history=history)
                            org.log_event("ic_fired_unused", manager.id, ic_id,
                                          {"reason": "not reused by the "
                                                     "manager's decomposition "
                                                     "(no current task)"})
                            fired = True
                        except Exception as e:
                            org.log_event("ic_flagged_for_firing",
                                          manager.id, ic_id,
                                          {"reason": "not reused; firing "
                                                     "failed: " + str(e)})
                    if not fired:
                        org.log_event("ic_flagged_for_firing", manager.id, ic_id,
                                      {"reason": "not reused by the manager's "
                                                 "decomposition (no current "
                                                 "task)"})
                teams.append({
                    "t_obj": t_obj,
                    "manager": manager,
                    "ic_tasks": ic_tasks,
                })
            else:
                # Head-directed branch (no manager — the head directs an IC
                # directly): the single IC the team objective names is hired.
                ic_id = t_obj.get("ic_id", "")
                if ic_id:
                    ic = org.get(ic_id)
                    if ic is not None:
                        # Re-link a reused IC to the current head (the
                        # communication gate requires ic.reports_to ==
                        # head.id). Log the re-link (visible, never silent).
                        if ic.reports_to != head.id:
                            org.log_event("ic_relinked", head.id, ic_id,
                                          {"old_reports_to": ic.reports_to,
                                           "new_reports_to": head.id})
                            ic.reports_to = head.id
                            ic.department = head.department
                            ic.team = t_obj.get("team") or ic.team
                    else:
                        # `team` becomes the team work dir
                        # (departments/<dept>/<team>/). Fall back to the ic_id
                        # so it is NEVER empty — an empty team leaves the IC
                        # with no concrete work root.
                        team = t_obj.get("team") or ic_id
                        # enforce the team/IC cap (a hire that would
                        # exceed the team cap is blocked — a visible note).
                        if not _team_cap_ok(org, head.department, team):
                            org.log_event(
                                "team_cap_reached", head.id, ic_id,
                                {"department": head.department, "team": team},
                            )
                        else:
                            _ensure_role(
                                org, head, ic_id, "ic",
                                head.department, team, approver_fn,
                                direct_ic_cap=(config or {}).get(
                                    "direct_ic_cap", 3),
                                backend=backend, phase=5,
                                history=history,
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
