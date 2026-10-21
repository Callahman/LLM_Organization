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
from runtime.org import OrgState, run_leader_replacement_vote, _invoke_contained
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.timing import TimingTracker
from runtime.pods import (
    SoloTracker,
    form_pod,
    run_pod,
    log_devils_advocate_listening,
)
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
    _run_contained_pod,
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


# ---: the headcount cap chain (Phase 4 — the head allots teams) ---

def _allot_team_caps_ctx(head: Role, teams: List[str], dept_cap: int,
                         team_cap_default: Optional[float] = None) -> str:
    """The context for the head's team-cap allotment (Phase 4)."""
    default_hint = ""
    if team_cap_default is not None:
        default_hint = (
            f" The default team cap is {team_cap_default:.0%} of the "
            f"department cap (a resourcing hint — adjust per team as needed)."
        )
    return (
        f"ORG {head.id}: Phase 4 — allot the team headcount caps for your "
        f"department. The department cap is {dept_cap}. Allot a cap to each "
        f"team; the sum of the team caps must be ≤ {dept_cap}."
        f"{default_hint} Teams: "
        f"{', '.join(teams) or '(none)'}. Return `team_caps` as a "
        f"{{team: cap}} mapping."
    )


def _parse_team_caps(out: Dict[str, Any], teams: List[str],
                     dept_cap: int) -> Dict[str, int]:
    """Parse the head's `team_caps` output into a {team: cap} mapping,
    clamping so the sum is ≤ the department cap (a visible note if clamped —
    never silent)."""
    raw = out.get("team_caps")
    caps: Dict[str, int] = {}
    if isinstance(raw, dict):
        for team in teams:
            val = raw.get(team)
            if isinstance(val, (int, float)) and val > 0:
                caps[team] = int(val)
    s = sum(caps.values())
    if s > dept_cap and caps:
        scale = dept_cap / s
        caps = {t: max(1, int(c * scale)) for t, c in caps.items()}
    return caps


def _allot_team_caps(org: OrgState, backend, head: Role,
                     team_objectives: List[Dict[str, Any]],
                     config: Optional[Dict[str, Any]] = None) -> None:
    """the head allots the **team/IC caps** (a cap per team, bounded
    by the department cap), then **Pod B** (all managers + the head) finalizes
    them — the **head has final say**. The finalized caps are stored on the
    org (``org.team_caps``). A no-op if the department has no cap allotted
    (the org then falls back to the per-manager IC cap).

    **Error containment** (a headcount hiccup must not kill the run): the
    head's allotment gets one corrective retry, and a final failure is
    contained (a visible org event; the org falls back to the per-manager IC
    cap). A Pod B failure is likewise contained (a visible org event; the
    head's allotment stands — the head has final say, and a headcount pod
    must not take down the phase it sizes)."""
    dept_cap = org.department_caps.get(head.department, 0)
    if not dept_cap:
        return
    teams = [t.get("team") or t.get("manager_id", "") for t in team_objectives]
    # 1. The head allots the team caps (a resourcing decision), with one
    # corrective retry on a failure. The `TEAM_CAP_DEFAULT` knob (if set) is a
    # resourcing hint in the context. A final failure is contained (a visible
    # org event; the org falls back to the per-manager IC cap).
    ctx = _allot_team_caps_ctx(head, teams, int(dept_cap),
                               (config or {}).get("team_cap_default"))
    out, err = _invoke_contained(
        backend, head, ctx,
        classify_complexity(4, head, {"is_decision": True}), phase=4)
    if err is not None:
        org.log_event("headcount_allotment_failed", head.id, None,
                      {"error": err})
        return
    caps = _parse_team_caps(out, teams, int(dept_cap))
    # 2. Pod B (all managers + the head) finalizes the team caps — the head
    # has final say (the pod deliberates; the head's allotment is the final).
    # The head is a member (like Pod A's leader) so a single-manager
    # department still forms a valid pod (the 2-member minimum). A pod
    # failure is contained (a visible org event; the head's allotment stands).
    managers = [org.get(t.get("manager_id", "")) for t in team_objectives]
    managers = [m for m in managers if m is not None]
    if managers:
        pod = form_pod(
            org.roles, head.id, [head.id] + [m.id for m in managers],
            f"Finalize the manager/IC headcount per team (department cap "
            f"{int(dept_cap)})",
            # Pod B is a headcount deliberation (all managers + the head) — the
            # managers are peers (not in one reporting line), so skip the
            # communication gate (cross_team) and relax the size bound (it can
            # legitimately exceed the 6-member working-group bound).
            cross_team=True,
            max_roles=12,
            kind="headcount",
        )
        try:
            run_pod(backend, pod,
                    max_rounds=(config or {}).get("headcount_pod_rounds"),
                    phase=4)
        except Exception as e:
            # A pod failure (e.g. a manager's malformed / free-form reply) is
            # contained — a visible org event; the head's allotment stands
            # (the head has final say).
            org.log_event("headcount_pod_failed", head.id, None,
                          {"pod": pod.id, "kind": pod.kind, "error": str(e)})
    # 3. Store on the org (the head's caps are the final — the head has final
    # say).
    for team, cap in caps.items():
        org.team_caps[(head.department, team)] = cap


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
    # department.
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

    # the **leader+head clarification pods** (per operational
    # department) — a 2-member parent+child pod that clarifies the
    # department's mission. It runs BEFORE the head authors its policy
    # (the policy reflects the clarified mission), and is **contained**
    # (a pod failure is logged, never takes down the phase). Required
    # governance depts get no clarification pod. The leader is not a member of
    # `org.roles` — add it so the pod can be formed (starter = the leader).
    roles_with_leader = {**org.roles, leader.id: leader}
    clarifications: Dict[str, str] = {}
    for obj in dept_objectives:
        head = org.get(obj.get("head_id", ""))
        if head is None or head.is_required:
            continue
        pod = form_pod(
            roles_with_leader, leader.id, [leader.id, head.id],
            f"Clarify the department's mission (department {head.department})",
            kind="clarification",
        )
        # the devil's advocate "listens" to the leader+head pod
        # (visible, never silent).
        log_devils_advocate_listening(org, pod, roles_with_leader)
        _run_contained_pod(backend, org, pod,
                           max_rounds=(config or {}).get(
                               "clarification_pod_rounds"),
                           phase=4)
        if pod.decision:
            clarifications[head.id] = pod.decision

    # Pre-decomposition: every department head (operational AND required)
    # authors its department POLICY + POLICY_SUMMARY. **:** the policy
    # is authored AFTER the leader+head clarification pod, so it reflects the
    # clarified mission (the pod → policy sequencing is strict).
    head_policies = generate_head_policies(
        backend, org, dept_objectives, digest,
        clarifications=clarifications,
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
        # leader's.
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
                    backend=backend, phase=4,
                )
        # (The head+manager clarification pod runs in Phase 5 (Staff), AFTER
        # the manager decomposes — see run_staff.)
        # the head allots the **team/IC caps** (Phase 4) +:
        # **Pod B** (all managers + the head) finalizes them (the head has final
        # say).
        _allot_team_caps(org, backend, head, team_objectives, config)
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
