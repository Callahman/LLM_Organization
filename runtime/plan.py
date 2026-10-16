"""Phase 4 (Plan) — the leader decomposition + the per-department head workflow.

A pure split out of the old monolithic ``runtime/dispatch.dispatch`` (Epic:
the 8-phase restructure). Phase 4 (Plan) does:

1. The **leader** decomposes the mission into **department objectives**
   (invoked with the efficiency panel; its ``leader_replacement`` /
   ``resourcing`` / ``efficiency`` side-effects are handled here, as in the
   old dispatch).
2. Every department head authors its **department POLICY** +
   **POLICY_SUMMARY** (``generate_head_policies``) BEFORE it decomposes.
3. Each department head decomposes its department objective into **team
   objectives**, and the **managers** those objectives name are hired (the
   full heads->managers chain, through the HR approver).

Phase 5 (Staff, ``runtime/staff.py``) then runs the per-team manager workflow
(IC decomposition + IC hiring), and Phase 6 (Execute, ``runtime/execute.py``)
runs the per-IC work + pod triggers + upward report.

The shared helpers live in ``runtime/dispatch_common.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import OrgState, run_leader_replacement_vote
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.timing import TimingTracker
from runtime.pods import SoloTracker
from runtime.dispatch_common import (
    mission_digest,
    _leader_ctx,
    _efficiency_panel_text,
    _head_ctx,
    _decomposition_list,
    _ensure_role,
    _fire_role,
    _process_efficiency,
    run_automation,
    generate_head_policies,
)


@dataclass
class PlanResult:
    """The output of Phase 4 (Plan) — what Phase 5 (Staff) consumes.

    - ``digest``: the bounded mission digest (carried to the head/manager/IC
      contexts).
    - ``dept_objectives``: the leader's department objectives (raw).
    - ``head_policies``: ``{head_id: {"policy", "policy_summary"}}`` (the
      pre-decomposition department policies).
    - ``departments``: one entry per resolvable department objective —
      ``{"head": Role, "objective": str, "team_objectives": [...]}`` (the
      head's team decomposition; the managers those objectives name have been
      hired and are in the org).
    """

    digest: str
    dept_objectives: List[Dict[str, Any]] = field(default_factory=list)
    head_policies: Dict[str, Dict[str, str]] = field(default_factory=dict)
    departments: List[Dict[str, Any]] = field(default_factory=list)


def run_plan(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    mission: Dict[str, Any],
    approver_fn=None,
    history: Optional[HistoryStore] = None,
    new_leader: Optional[Role] = None,
    config: Optional[Dict[str, Any]] = None,
    solo: Optional[SoloTracker] = None,
    timing: Optional[TimingTracker] = None,
) -> PlanResult:
    """Run Phase 4 (Plan): the leader decomposition + the per-department head
    workflow (policies, team decomposition, manager hiring). Returns a
    ``PlanResult`` for Phase 5 (Staff) to consume.

    ``approver_fn`` (optional) lets the plan hire the managers it decomposes
    onto when they don't exist yet (the heads->managers chain); without it,
    the plan only reaches roles already in the org.
    """
    digest = mission_digest(mission)
    head_ids = [h.id for h in org.department_heads()]
    # The Leader is invoked with the efficiency panel (per-role /
    # per-department invoke time) so it can act on an inefficient role or
    # department (Story 22).
    efficiency_panel = ""
    if timing is not None:
        efficiency_panel = _efficiency_panel_text(timing.snapshot())
    out = backend.invoke(
        leader, _leader_ctx(digest, head_ids, efficiency_panel=efficiency_panel),
        reasoning=classify_complexity(4, leader, {}), phase=4)
    # A single head's leader-replacement proposal (with reasoning) triggers the
    # per-head unanimous vote. The new-leader candidate is supplied by the
    # caller (`new_leader`); without one, the proposal is logged but no vote
    # runs (visible, not silent).
    _leader_replacement = out.get("leader_replacement")
    if (isinstance(_leader_replacement, dict)
            and _leader_replacement.get("propose")):
        if new_leader is not None:
            run_leader_replacement_vote(
                org, backend, new_leader, leader.id,
                _leader_replacement.get("reasoning", ""), phase=4)
        elif history is not None:
            history._append(
                "dispatch_skips.jsonl",
                {"reason": "leader_replacement proposal but no new-leader "
                           "candidate supplied — no vote run"},
            )
    # The leader's resourcing output can request firing roles (each `fire`
    # entry is [role_id, reason]). The fire goes through the HR approver (a
    # veto / required-role rejection / missing approver is logged, never
    # swallowed).
    _resourcing = out.get("resourcing")
    if isinstance(_resourcing, dict):
        for _fire_entry in _resourcing.get("fire", []):
            if isinstance(_fire_entry, (list, tuple)) and _fire_entry:
                _fire_role(org, leader, _fire_entry[0],
                           _fire_entry[1] if len(_fire_entry) >= 2 else "",
                           approver_fn, history)
    # The Leader's efficiency action (fire / reassign / report an inefficient
    # role or department, based on the efficiency panel it was invoked with).
    _efficiency = out.get("efficiency")
    if isinstance(_efficiency, dict):
        _process_efficiency(org, leader, _efficiency, approver_fn, history)
        # The automation action (an IC writes a Python script, is fired, and
        # the recurring task is then done by executing the script).
        if _efficiency.get("action") == "automate":
            run_automation(org, leader, _efficiency, backend, approver_fn,
                           history)
    dept_objectives = _decomposition_list(out, "department_objectives")
    if not dept_objectives:
        # The leader's Phase 4 decomposition came back empty — no work to
        # dispatch. Log it so the no-op is visible, never silent.
        if history is not None:
            history._append(
                "dispatch_skips.jsonl",
                {"reason": "leader produced no department_objectives (empty "
                           "Phase 4 decomposition)"},
            )

    # Pre-decomposition: every department head (operational AND required)
    # authors its department POLICY + POLICY_SUMMARY BEFORE any head
    # decomposes into managers, so managers/ICs have a clear instruction on
    # how their work fulfils the org's goal.
    head_policies = generate_head_policies(
        backend, org, dept_objectives, digest,
    )

    departments: List[Dict[str, Any]] = []
    for obj in dept_objectives:
        head = org.get(obj.get("head_id", ""))
        if head is None:
            # A missing head (the leader decomposed onto a department that was
            # never created in Phase 3) — log it so the skip is visible, never
            # silent.
            if history is not None:
                history._append(
                    "dispatch_skips.jsonl",
                    {"head_id": obj.get("head_id", ""),
                     "objective": obj.get("objective", ""),
                     "reason": "head not in the org (never created in Phase 3)"},
                )
            continue
        head_out = backend.invoke(
            head, _head_ctx(head, obj.get("objective", ""), digest),
            reasoning=classify_complexity(4, head, {}), phase=4)
        team_objectives = _decomposition_list(head_out, "team_objectives")
        # Solo (P4, head): record the head's decomposition (out-of-pod work)
        # so the dashboard can watch any role's solo work, not just the
        # leader's (Story 21).
        if solo is not None:
            solo.record(
                "p4", "Phase 4: head decomposition", 0, "decompose",
                {"summary": f"decomposed the department objective into "
                            f"{len(team_objectives)} team objective(s)",
                 "team_objectives": team_objectives},
                role=head,
            )
        # Hire the managers the team objectives name (the heads->managers
        # chain, through the HR approver). Phase 5 (Staff) invokes them.
        for t_obj in team_objectives:
            manager = org.get(t_obj.get("manager_id", ""))
            if manager is None and t_obj.get("manager_id"):
                # `team` becomes the team work dir
                # (departments/<dept>/<team>/). Fall back to the manager_id so
                # it is NEVER empty — an empty team leaves the ICs with no
                # concrete work root.
                _ensure_role(
                    org, head, t_obj.get("manager_id"), "manager",
                    head.department,
                    t_obj.get("team") or t_obj.get("manager_id", ""),
                    approver_fn,
                    direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                )
        departments.append({
            "head": head,
            "objective": obj.get("objective", ""),
            "team_objectives": team_objectives,
        })
    return PlanResult(
        digest=digest,
        dept_objectives=dept_objectives,
        head_policies=head_policies,
        departments=departments,
    )
