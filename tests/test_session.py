"""Unit tests for `runtime/session.py` — the full Phase 1-6 pipeline (Epic 10).

The pipeline: intake -> mission (permission) -> org bootstrap -> dispatch ->
synthesis -> evaluation, with the **bounded** self-improving loop (Phase 6
"continue" re-enters Phase 1, still abiding by the original goal) and the **BAU
rule** (a Safety/Morality halt during Phase 4 is the only BAU halt).
"""

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.session import Session


def _approve_fns():
    user_answer_fn = lambda qs: "a weekly report"
    user_permission_fn = lambda draft: {"decision": "approve", "feedback": ""}
    approver_fn = lambda approver, action, role: {"decision": "approve",
                                                 "rationale": "ok"}
    return user_answer_fn, user_permission_fn, approver_fn


def _leader_script_full():
    """The Leader is invoked once per phase (1-6), in order."""
    return [
        {"confidence": 0.9, "questions": []},  # Phase 1: converge in one round
        {"mission_draft": {"purpose": "a data pipeline",
                           "success_criteria": ["works"]}},  # Phase 2
        {"org_recommendation": {"department_heads": [
            {"id": "head_analytics", "department": "analytics"}]}},  # Phase 3
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},  # Phase 4
        {"verdict": "complete"},  # Phase 5: synthesis
        {"verdict": "complete"},  # Phase 6: evaluation -> complete
    ]


def test_full_pipeline_completes(tmp_path):
    backend = StubBackend()
    backend.set_script("leader", _leader_script_full())
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": []}},  # no managers/ICs hired yet
    ])
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    result = session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        max_iterations=3,
    )
    assert result.status == "complete"
    assert result.phases == [1, 2, 3, 4, 5, 6]
    assert result.verdict == "complete"
    assert result.mission.approved
    # The department head was bootstrapped and is in the org.
    assert session.org.get("head_analytics") is not None


def test_escalates_when_mission_rejected(tmp_path):
    backend = StubBackend()
    # Phase 1 converges; Phase 2's draft is rejected (repeated until the
    # re-ask budget is exhausted) -> the session escalates before Phase 3.
    backend.set_script("leader", [
        {"confidence": 0.9, "questions": []},  # Phase 1
        {"mission_draft": {"purpose": "x"}},  # Phase 2 (rejected each round)
    ])
    user_answer_fn = lambda qs: "a"
    user_permission_fn = lambda draft: {"decision": "reject", "feedback": "wrong scope"}
    approver_fn = lambda approver, action, role: {"decision": "approve"}
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    result = session.run(
        "build a thing",
        user_answer_fn, user_permission_fn, approver_fn,
        max_iterations=3,
    )
    assert result.status == "escalated"
    # It stopped at Phase 2 (no org bootstrap / dispatch).
    assert result.phases == [1, 2]
    assert result.escalation is not None


def test_full_chain_hires_managers_and_ics(tmp_path):
    # Phase 4 now exercises the FULL heads->managers->ICs chain: the dispatch
    # hires the manager and IC it decomposes onto (through the approver).
    backend = StubBackend()
    backend.set_script("leader", _leader_script_full())
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"},
        ]}},
    ])
    backend.set_script("mgr1", [
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"},
        ]}},
    ])
    backend.set_script("ic1", [
        {"summary": "extractor done",
         "work_path": "departments/analytics/pipelines/extractor.md"},
    ])
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    result = session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        max_iterations=3,
    )
    assert result.status == "complete"
    # The manager and IC were hired during Phase 4 (the full chain).
    assert session.org.get("mgr1") is not None
    assert session.org.get("ic1") is not None


def test_bau_halt_during_phase4(tmp_path):
    backend = StubBackend()
    backend.set_script("leader", _leader_script_full())
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": []}},
    ])
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    # A Safety halt during Phase 4 (the only BAU halt).
    phase4_halt_fn = lambda: {
        "department": "safety", "scope": "global", "reason": "unsafe output",
    }
    result = session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        phase4_halt_fn=phase4_halt_fn,
        max_iterations=3,
    )
    # The halt is recorded and BAU is halted (global scope).
    assert session.bau_halt is not None
    assert session.bau_halt["department"] == "safety"
    assert session.bau_active() is False
    # The cycle still completes (the halt queues the needed user input).
    assert result.status == "complete"
