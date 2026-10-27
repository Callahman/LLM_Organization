"""The Phase 4-6 (Plan/Staff/Execute) sequence — a thin re-export shim.

The old monolithic ``dispatch`` (a single Phase 4 that did the leader
decomposition -> per-department head workflow -> per-team manager workflow ->
per-IC work -> pod triggers -> upward report) is now split into three phase
modules:

- ``runtime/plan.py`` (Phase 4, Plan) -- ``run_plan``.
- ``runtime/staff.py`` (Phase 5, Staff) -- ``run_staff``.
- ``runtime/execute.py`` (Phase 6, Execute) -- ``run_execute``.

The shared helpers live in ``runtime/dispatch_common.py``.

This shim keeps ``from runtime.dispatch import ...`` working for the external
importers (the tests, the dashboard): it re-exports the shared helpers + the
phase modules, and defines ``dispatch`` as the three-phase sequence (the
same return shape as the old monolith).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import OrgState
from runtime.llm import LLMBackend
from runtime.history import HistoryStore
from runtime.timing import TimingTracker
from runtime.pods import SoloTracker

# Re-export the shared helpers (so `from runtime.dispatch import <helper>`
# keeps working for the external importers).
from runtime.dispatch_common import (
    mission_digest,
    _leader_ctx,
    _efficiency_panel_text,
    _reassign_role,
    _process_efficiency,
    _head_ctx,
    _manager_ctx,
    _ic_ctx,
    _policy_ctx,
    _read_policy,
    _write_policy,
    _work_path,
    _upward_report,
    _invoke_ic,
    _self_edit_log,
    _repair_edit_paths,
    _ic_pre_read,
    _run_self_edits,
    _retry_refused_edits,
    _apply_ic_self_edits,
    _ensure_role,
    _fire_role,
    _automation_slug,
    run_automation,
    _task_types,
    _pod_topic,
    _check_pod_triggers,
    _decomposition_list,
    generate_head_policies,
)

# Re-export the phase modules (the split).
from runtime.plan import run_plan, PlanResult
from runtime.staff import run_staff, StaffResult
from runtime.execute import run_execute, ExecuteResult


def dispatch(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    mission: Dict[str, Any],
    approver_fn=None,
    pods_out: Optional[List[Any]] = None,
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
    """Run the Phase 4-6 (Plan/Staff/Execute) sequence top-down.

    A thin wrapper over the three phase modules (the same behavior + return
    shape as the old monolithic ``dispatch``):

    1. **Phase 4 (Plan)** (``run_plan``): the leader decomposes the mission
       into department objectives; the heads author their policies and
       decompose into team objectives; the managers are hired.
    2. **Phase 5 (Staff)** (``run_staff``): the managers decompose their team
       objectives into IC tasks; the ICs are hired.
    3. **Phase 6 (Execute)** (``run_execute``): the ICs do the work (with
       self-edits through the edit gate); the A/B/C pod triggers fire; the
       work propagates up in bounded reports.

    The leader's view is the bounded reports: one per department, carrying the
    head's bounded summary of the team work below it + artifact pointers (the
    leader never sees the full work, only summaries + pointers).

    ``approver_fn`` (optional) lets the sequence hire the roles it decomposes
    onto when they don't exist yet (the full heads->managers->ICs chain);
    without it, the sequence only reaches roles already in the org.
    """
    plan = run_plan(
        backend, org, leader, mission,
        approver_fn=approver_fn, history=history, new_leader=new_leader,
        config=config, solo=solo, timing=timing,
    )
    staff = run_staff(
        backend, org, leader, plan,
        approver_fn=approver_fn, config=config, solo=solo, history=history,
    )
    result = run_execute(
        backend, org, leader, staff,
        approver_fn=approver_fn, pods_out=pods_out, history=history,
        routing_rules=routing_rules, artifacts_dir=artifacts_dir,
        transcripts_dir=transcripts_dir, ic_timeout_seconds=ic_timeout_seconds,
        config=config, solo=solo,
    )
    return result.reports
