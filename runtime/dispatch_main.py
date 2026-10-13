"""Phase 4 — The top-down dispatch runner.

The leader decomposes the mission into **department objectives** →
department heads decompose into **team objectives** → managers decompose into
**IC tasks** → ICs do the work in their team directories. Work propagates
**up** in **structured reports** (bounded summaries + artifact pointers) —
the leader never reads code; its synthesis reflects IC-level work **via the
chain of command**. No tier is skipped in assignments.

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there; this file holds the `dispatch` runner).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import run_leader_replacement_vote
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.timing import TimingTracker
from runtime.pods import Pod, SoloTracker
from runtime.dispatch import (
    mission_digest,
    _leader_ctx,
    _head_ctx,
    _manager_ctx,
    _ic_ctx,
    _decomposition_list,
    generate_head_policies,
)
from runtime.dispatch_efficiency import _efficiency_panel_text, _process_efficiency
from runtime.dispatch_role_work import (
    _ensure_role,
    _fire_role,
    _invoke_ic,
    _work_path,
    _upward_report,
)
from runtime.dispatch_self_edits import _apply_ic_self_edits
from runtime.dispatch_automation import run_automation
from runtime.dispatch_pod_triggers import _check_pod_triggers


def dispatch(
    backend: LLMBackend,
    org,
    leader: Role,
    mission: Dict[str, Any],
    approver_fn=None,
    pods_out: Optional[List[Pod]] = None,
    history: Optional[HistoryStore] = None,
    routing_rules: Optional[List[str]] = None,
    artifacts_dir: str = "pods/artifacts",
    transcripts_dir: str = "pods/transcripts",
    ic_timeout_seconds: Optional[float] = None,
    new_leader: Optional[Role] = None,
    config: Optional[Dict[str, Any]] = None,
    solo: Optional[SoloTracker] = None,
    timing: Optional[TimingTracker] = None,
) -> List[Dict[str, Any]]:
    """Run the Phase 4 top-down dispatch. Returns the leader's view: a list of
    department reports (each carrying the chain of team/IC reports up).

    `ic_timeout_seconds` (optional) gives the IC work invokes a larger per-
    invoke timeout than the session default — the ICs do the actual work, so
    they are the heaviest invokes and the ones most likely to hit the flat
    budget. `None` uses the session default.

    `approver_fn` (optional) lets the dispatch hire the managers/ICs it
    decomposes onto when they don't exist yet (the full heads->managers->ICs
    chain); without it, the dispatch only reaches roles already in the org.

    **Pods A/B/C multi-trigger** (an add-on, not a replacement): after each
    team's IC work, a pod forms when any trigger fires — A (disagreement
    across the IC work outputs), B (a `cross_team`-marked objective), C (a
    routing-rule task type). The formed pods are appended to `pods_out`
    (when supplied) so the session can carry their decisions up to the
    leader's Phase 5 synthesis; the decision is also written to
    `pods/artifacts/` (+ the `history` decision journal when supplied) and
    seeded into the members' memory as a cross-team `pod:<id>` entry (via
    `MemoryBackend.seed_cross_team` — a no-op for a plain stub)."""
    digest = mission_digest(mission)
    head_ids = [h.id for h in org.department_heads()]
    # Story 22: the Leader is invoked with the efficiency panel (per-role /
    # per-department invoke time) so it can act on an inefficient role or
    # department.
    efficiency_panel = ""
    if timing is not None:
        efficiency_panel = _efficiency_panel_text(timing.snapshot())
    out = backend.invoke(
        leader, _leader_ctx(digest, head_ids, efficiency_panel=efficiency_panel),
        reasoning=classify_complexity(4, leader, {}), phase=4)
    # Story 5 (A1): a single head's leader-replacement proposal (with
    # reasoning) triggers the per-head unanimous vote. The new-leader
    # candidate is supplied by the caller (`new_leader`); without one, the
    # proposal is logged but no vote runs (visible, not silent).
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
    # Story 6 (R7): the leader's resourcing output can request firing roles
    # (each `fire` entry is [role_id, reason]). The fire goes through the HR
    # approver (a veto / required-role rejection / missing approver is logged,
    # never swallowed).
    _resourcing = out.get("resourcing")
    if isinstance(_resourcing, dict):
        for _fire_entry in _resourcing.get("fire", []):
            if isinstance(_fire_entry, (list, tuple)) and _fire_entry:
                _fire_role(org, leader, _fire_entry[0],
                           _fire_entry[1] if len(_fire_entry) >= 2 else "",
                           approver_fn, history)
    # Story 22: the Leader's efficiency action (fire / reassign / report an
    # inefficient role or department, based on the efficiency panel it was
    # invoked with).
    _efficiency = out.get("efficiency")
    if isinstance(_efficiency, dict):
        _process_efficiency(org, leader, _efficiency, approver_fn, history)
        # S22: the automation action (an IC writes a Python script, is fired,
        # and the recurring task is then done by executing the script).
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
    # authors its department POLICY + POLICY_SUMMARY BEFORE any head decomposes
    # into managers, so managers/ICs have a clear instruction on how their work
    # fulfils the org's goal.
    head_policies = generate_head_policies(
        backend, org, dept_objectives, digest,
    )

    results: List[Dict[str, Any]] = []
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
        head_out = backend.invoke(head, _head_ctx(head, obj.get("objective", ""), digest),
                          reasoning=classify_complexity(4, head, {}),
                          phase=4)
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

        team_reports: List[Dict[str, Any]] = []
        for t_obj in team_objectives:
            manager = org.get(t_obj.get("manager_id", ""))
            if manager is None and t_obj.get("manager_id"):
                # `team` becomes the team work dir (departments/<dept>/<team>/).
                # Fall back to the manager_id so it is NEVER empty — an empty
                # team leaves the ICs with no concrete work root (the exact
                # bug that got every self-edit refused as out_of_scope).
                manager = _ensure_role(
                    org, head, t_obj.get("manager_id"), "manager",
                    head.department,
                    t_obj.get("team") or t_obj.get("manager_id", ""),
                    approver_fn,
                    direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                )
            if manager is not None:
                mgr_out = backend.invoke(manager, _manager_ctx(manager, t_obj.get("objective", ""),
                          policy=head_policies.get(head.id, {}).get("policy", "")),
                         reasoning=classify_complexity(4, manager, {}),
                         phase=4)
                ic_tasks = _decomposition_list(mgr_out, "ic_tasks")
                # Solo (P4, manager): record the manager's decomposition
                # (out-of-pod work) so the dashboard can watch any role's solo
                # work, not just the leader's (Story 21).
                if solo is not None:
                    solo.record(
                        "p4", "Phase 4: manager decomposition", 0, "decompose",
                        {"summary": f"decomposed the team objective into "
                                    f"{len(ic_tasks)} IC task(s)",
                         "ic_tasks": ic_tasks},
                        role=manager,
                    )
                ic_reports: List[Dict[str, Any]] = []
                ic_outputs: List[Dict[str, Any]] = []  # full IC outputs (trigger A)
                ic_ids: List[str] = []
                for task in ic_tasks:
                    ic = org.get(task.get("ic_id", ""))
                    if ic is None and task.get("ic_id"):
                        ic = _ensure_role(
                            org, manager, task.get("ic_id"), "ic",
                            manager.department, manager.team, approver_fn,
                            direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                        )
                    if ic is None:
                        continue
                    ic_out, ic_err = _invoke_ic(
                        backend, ic, _ic_ctx(ic, task.get("task", ""),
                                              policy_summary=head_policies.get(
                                                  head.id, {}).get(
                                                  "policy_summary", "")),
                        reasoning=classify_complexity(4, ic, {}),
                        timeout=ic_timeout_seconds,
                        phase=4,
                    )
                    if ic_err is not None:
                        # Error containment: the corrective retry also
                        # failed. Record the IC's failure visibly in the
                        # upward report and continue with the other ICs (one
                        # hiccup must not kill the run). It joins no pod (it
                        # produced no output).
                        ic_reports.append(
                            {"from": ic.id,
                             "summary": f"FAILED: {ic_err}",
                             "pointer": ""}
                        )
                        continue
                    ic_outputs.append(ic_out)
                    ic_ids.append(ic.id)
                    # Solo (P4, IC): record the IC's work (out-of-pod work) so
                    # the dashboard can watch any role's solo work, not just
                    # the leader's (Story 21).
                    if solo is not None:
                        solo.record(
                            "p4", "Phase 4: IC work", 0, "work",
                            {"summary": ic_out.get("summary", ""),
                             "work_path": ic_out.get("work_path", "")},
                            role=ic,
                        )
                    pointer = ic_out.get("work_path", _work_path(ic, task))
                    ic_reports.append(
                        {"from": ic.id, "summary": ic_out.get("summary", ""),
                         "pointer": pointer}
                    )
                    # Self-edit: the IC may propose code edits (repaired,
                    # gated by the permission layer, one corrective retry on
                    # refusal).
                    _apply_ic_self_edits(ic, ic_out, history, backend, phase=4)
                # Pods A/B/C (an add-on): disagreement / cross-team / routing.
                _check_pod_triggers(
                    backend, org, manager, ic_ids, t_obj, ic_outputs, ic_tasks,
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=True,
                    config=config,
                )
                team_reports.append(_upward_report(manager, ic_reports))
            else:
                # The head directs ICs directly (a department without managers).
                ic = org.get(t_obj.get("ic_id", ""))
                if ic is None and t_obj.get("ic_id"):
                    # Fall back to the ic_id so the team (work dir) is never
                    # empty (see the manager branch above).
                    ic = _ensure_role(
                        org, head, t_obj.get("ic_id"), "ic",
                        head.department,
                        t_obj.get("team") or t_obj.get("ic_id", ""),
                        approver_fn,
                        direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                    )
                if ic is None:
                    continue
                ic_out, ic_err = _invoke_ic(
                    backend, ic, _ic_ctx(ic, t_obj.get("objective", ""),
                                         policy_summary=head_policies.get(
                                             head.id, {}).get(
                                             "policy_summary", "")),
                    reasoning=classify_complexity(4, ic, {}),
                    timeout=ic_timeout_seconds,
                    phase=4,
                )
                if ic_err is not None:
                    # Error containment: the corrective retry also failed.
                    # Record the IC's failure visibly in the upward report
                    # and continue (one hiccup must not kill the run). It
                    # joins no pod (it produced no output).
                    team_reports.append(
                        _upward_report(
                            ic,
                            [{"from": ic.id, "summary": f"FAILED: {ic_err}",
                              "pointer": ""}],
                        )
                    )
                    continue
                # Solo (P4, IC): record the IC's work (out-of-pod work) so the
                # dashboard can watch any role's solo work, not just the
                # leader's (Story 21).
                if solo is not None:
                    solo.record(
                        "p4", "Phase 4: IC work", 0, "work",
                        {"summary": ic_out.get("summary", ""),
                         "work_path": ic_out.get("work_path", "")},
                        role=ic,
                    )
                # Self-edit: the IC may propose code edits (repaired, gated by
                # the permission layer, one corrective retry on refusal).
                _apply_ic_self_edits(ic, ic_out, history, backend, phase=4)
                # Pods A/B/C (an add-on): the head is the starter; the ICs are
                # the members (an IC podding with a department head would be a
                # 2-tier spread — a membership failure skips the pod).
                _check_pod_triggers(
                    backend, org, head, [ic.id], t_obj, [ic_out], [],
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=False,
                    config=config,
                )
                team_reports.append(
                    _upward_report(
                        ic,
                        [{"from": ic.id, "summary": ic_out.get("summary", ""),
                          "pointer": ic_out.get("work_path", _work_path(ic, t_obj))}],
                    )
                )
        results.append({"head": head.id, "report": _upward_report(head, team_reports)})
    return results


__all__ = ["dispatch"]
