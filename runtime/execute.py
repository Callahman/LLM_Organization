"""Phase 6 (Execute) — the per-IC work + pod triggers + the upward report.

A pure split out of the old monolithic ``runtime/dispatch.dispatch`` (Epic:
the 8-phase restructure). Phase 6 (Execute) consumes the ``StaffResult`` from
Phase 5 (Staff) and does, per team:

- **Manager branch** (the team names a manager): the ICs do the work in their
  team directories (invoked with the bounded POLICY_SUMMARY + the mission
  digest); their **self-edits** (``edit_code`` / ``write_file``) are applied
  through the edit gate; the **A/B/C pod triggers** fire (always — even if the
  IC work failed); the **manager** reports the IC work up the line.
- **Head-directed branch** (no manager — the head directs an IC directly): the
  single IC does the team objective; on a work failure a FAILED report
  propagates up (no pod trigger); on success the pod triggers fire (the head
  is the starter) and the IC reports its own work up the line.

The work propagates **up** in structured reports (bounded summaries + artifact
pointers); no tier is skipped. The shared helpers live in
``runtime/dispatch_common.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import OrgState
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.pods import SoloTracker, form_pod
from runtime.staff import StaffResult
from runtime.dispatch_common import (
    _ic_ctx,
    _work_path,
    _upward_report,
    _invoke_ic,
    _apply_ic_self_edits,
    _check_pod_triggers,
    _run_contained_pod,
)


@dataclass
class ExecuteResult:
    """The output of Phase 6 (Execute) — the leader's view of the work.

    - ``reports``: one entry per department — ``{"head": str, "report":
      dict}`` (the bounded upward report: the head's bounded summary of the
      team work below it + artifact pointers). This is the same shape the old
      ``dispatch()`` returned.
    """

    reports: List[Dict[str, Any]]


def run_execute(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    staff: StaffResult,
    approver_fn=None,
    pods_out: Optional[List[Any]] = None,
    history: Optional[HistoryStore] = None,
    routing_rules: Optional[List[str]] = None,
    artifacts_dir: str = "pods/artifacts",
    transcripts_dir: str = "pods/transcripts",
    ic_timeout_seconds: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
    solo: Optional[SoloTracker] = None,
) -> ExecuteResult:
    """Run Phase 6 (Execute): the per-IC work + self-edits + the A/B/C pod
    triggers + the upward report. Consumes the ``StaffResult`` from Phase 5
    (Staff) and returns an ``ExecuteResult`` (the leader's view — the same
    shape the old ``dispatch()`` returned).

    ``pods_out`` (optional) collects the pods formed by the A/B/C triggers
    (for the leader's synthesis + the session's pod records).
    """
    plan = staff.plan
    digest = plan.digest
    head_policies = plan.head_policies
    results: List[Dict[str, Any]] = []
    for dept in staff.departments:
        head = dept["head"]
        team_reports: List[Dict[str, Any]] = []
        for team in dept["teams"]:
            t_obj = team["t_obj"]
            manager = team["manager"]
            ic_tasks = team["ic_tasks"]
            if manager is not None:
                # Manager branch: the ICs do the work; the manager reports up.
                ic_reports: List[Dict[str, Any]] = []
                ic_outputs: List[Dict[str, Any]] = []
                ic_ids: List[str] = []
                for task in ic_tasks:
                    ic = org.get(task.get("ic_id", ""))
                    if ic is None:
                        continue
                    # Story 4: the **manager+ic clarification pod** (per IC) —
                    # a 2-member parent+child pod that clarifies the IC's
                    # task. It runs BEFORE the IC's work (Story 5: the work
                    # reflects the clarified task), and is **contained** (a pod
                    # failure is logged, never takes down the phase).
                    pod = form_pod(
                        org.roles, manager.id, [manager.id, ic.id],
                        f"Clarify the IC's task (task "
                        f"{str(task.get('task', ''))[:80]})",
                        kind="clarification",
                    )
                    _run_contained_pod(backend, org, pod,
                                       max_rounds=(config or {}).get(
                                           "clarification_pod_rounds"),
                                       phase=6)
                    ic_out, ic_err = _invoke_ic(
                        backend, ic,
                        _ic_ctx(
                            ic, task.get("task", ""),
                            policy_summary=head_policies.get(
                                head.id, {}).get("policy_summary", ""),
                            digest=digest,
                            clarification=pod.decision or ""),
                        reasoning=classify_complexity(6, ic, {}),
                        timeout=ic_timeout_seconds, phase=6)
                    if ic_err is not None:
                        # The IC's work step FAILED (a timeout / a malformed
                        # output). A FAILED report propagates up the line (the
                        # failure is visible, never silent) — the work is NOT
                        # silently dropped.
                        ic_reports.append({
                            "from": ic.id,
                            "summary": f"FAILED: {ic_err}",
                            "pointer": "",
                        })
                        continue
                    # Keep the full IC outputs for the pod triggers
                    # (disagreement detection needs the recommendations, not
                    # just the upward reports).
                    ic_outputs.append(ic_out)
                    ic_ids.append(ic.id)
                    # Solo (P4, IC): record the IC's work (out-of-pod work) so
                    # the dashboard can watch any role's solo work, not just
                    # the leader's (Story 21).
                    if solo is not None:
                        solo.record(
                            "p6", "Phase 6: IC work", 0, "work",
                            {"summary": ic_out.get("summary", ""),
                             "work_path": ic_out.get(
                                 "work_path", _work_path(ic, task))},
                            role=ic,
                        )
                    # The IC's bounded summary + artifact pointer (the work
                    # path, or a fallback). The upward report carries the
                    # pointer, not the full work.
                    pointer = ic_out.get("work_path", _work_path(ic, task))
                    ic_reports.append({
                        "from": ic.id,
                        "summary": ic_out.get("summary", ""),
                        "pointer": pointer,
                    })
                    # Self-edit (Story 11): the IC's edit_code / write_file
                    # outputs are applied through the edit gate (the path is
                    # validated against the role's scope + the org's artifact
                    # rules; a refusal is logged, never swallowed).
                    _apply_ic_self_edits(ic, ic_out, history, backend, phase=6)
                # The pods A/B/C multi-trigger (disagreement / cross-team /
                # routing rule). The manager + the ICs involved form the pod;
                # its decision is carried all three ways.
                _check_pod_triggers(
                    backend, org, manager, ic_ids, t_obj, ic_outputs, ic_tasks,
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=True,
                    config=config,
                    phase=6,
                )
                # The manager's upward report: a bounded summary of the IC work
                # below it.
                team_reports.append(_upward_report(manager, ic_reports))
            else:
                # Head-directed branch (no manager — the head directs an IC
                # directly): the single IC does the team objective.
                ic = org.get(ic_tasks[0].get("ic_id", "")) if ic_tasks else None
                if ic is None:
                    continue
                ic_out, ic_err = _invoke_ic(
                    backend, ic,
                    _ic_ctx(
                        ic, ic_tasks[0].get("task", ""),
                        policy_summary=head_policies.get(
                            head.id, {}).get("policy_summary", ""),
                        digest=digest),
                    reasoning=classify_complexity(6, ic, {}),
                    timeout=ic_timeout_seconds, phase=6)
                if ic_err is not None:
                    # The IC's work step FAILED. A FAILED report propagates up
                    # the line (visible, never silent); no pod trigger (the
                    # work did not succeed to disagree on).
                    team_reports.append(_upward_report(ic, [
                        {"from": ic.id,
                         "summary": f"FAILED: {ic_err}",
                         "pointer": ""},
                    ]))
                    continue
                # Solo (P4, IC): record the IC's work (out-of-pod work) so the
                # dashboard can watch any role's solo work, not just the
                # leader's (Story 21).
                if solo is not None:
                    solo.record(
                        "p6", "Phase 6: IC work", 0, "work",
                        {"summary": ic_out.get("summary", ""),
                         "work_path": ic_out.get(
                             "work_path", _work_path(ic, ic_tasks[0]))},
                        role=ic,
                    )
                # Self-edit (Story 11): the IC's edit_code / write_file outputs
                # are applied through the edit gate (the path is validated
                # against the role's scope + the org's artifact rules; a
                # refusal is logged, never swallowed).
                _apply_ic_self_edits(ic, ic_out, history, backend, phase=6)
                # The pods A/B/C multi-trigger (the head is the starter, not
                # in the members).
                _check_pod_triggers(
                    backend, org, head, [ic.id], t_obj, [ic_out], [],
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=False,
                    config=config,
                    phase=6,
                )
                # The IC's bounded summary + artifact pointer.
                team_reports.append(_upward_report(ic, [
                    {"from": ic.id,
                     "summary": ic_out.get("summary", ""),
                     "pointer": ic_out.get(
                         "work_path", _work_path(ic, ic_tasks[0]))},
                ]))
        results.append({"head": head.id,
                        "report": _upward_report(head, team_reports)})
    return ExecuteResult(reports=results)
