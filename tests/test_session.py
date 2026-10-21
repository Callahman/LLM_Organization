"""Unit tests for `runtime/session.py` — the full Phase 1-8 pipeline.

The pipeline: intake -> mission (permission) -> org bootstrap -> plan ->
staff -> execute -> evaluate -> decide, with the **bounded** self-improving
loop (Phase 8 "continue" re-enters Phase 1, still abiding by the original
goal) and the **BAU rule** (a Safety/Morality halt during the work, Phases
4-6, is the only BAU halt).
"""

import json
import os

import pytest

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import MemoryBackend, StubBackend
from runtime.org import OrgState
from runtime.session import Session


def _approve_fns():
    user_answer_fn = lambda qs: "a weekly report"
    user_permission_fn = lambda draft: {"decision": "approve", "feedback": ""}
    approver_fn = lambda approver, action, role: {"decision": "approve",
                                                 "rationale": "ok"}
    return user_answer_fn, user_permission_fn, approver_fn


def _leader_script_full():
    """The Leader is invoked in Phases 1, 2, 3, 4, 7, 8 (the work phases 5-6
    don't invoke the leader), in order."""
    return [
        {"confidence": 0.9, "questions": []},  # Phase 1: converge in one round
        {"mission_draft": {"purpose": "a data pipeline",
                           "success_criteria": ["works"]}},  # Phase 2
        {"org_recommendation": {"department_heads": [
            {"id": "head_analytics", "department": "analytics"}]}},  # Phase 3
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},  # Phase 4: plan
        {"verdict": "complete"},  # Phase 7: evaluate
        {"verdict": "complete"},  # Phase 8: decide -> complete
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
    assert result.phases == {1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1}
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
    # It stopped at Phase 2 (no org bootstrap / plan / staff / execute).
    assert result.phases == {1: 1, 2: 1}
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
    # a GLOBAL Safety/Morality halt during the work
    # (Phases 4-6) stops the run before Phase 7 (evaluate) — the halt is
    # CONSUMED, not just recorded (previously the cycle "still completed":
    # the halt was set but never consumed).
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
    assert session.bau_halt["scope"] == "global"
    assert session.bau_active() is False
    # The run stops before Phase 7 (no evaluate, no decide).
    assert result.status == "escalated"
    assert 7 not in result.phases
    assert 8 not in result.phases


def test_scoped_bau_halt_during_phase4_continues(tmp_path):
    # a SCOPED halt during the work does not stop the run (Phase 7 +
    # 8 run) and the halt is recorded (observable).
    backend = StubBackend()
    backend.set_script("leader", _leader_script_full())
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": []}},
    ])
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    phase4_halt_fn = lambda: {
        "department": "safety", "scope": "scoped", "reason": "unsafe output",
    }
    result = session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        phase4_halt_fn=phase4_halt_fn,
        max_iterations=3,
    )
    # The run continues (non-blocked work) and completes.
    assert result.status == "complete"
    assert 7 in result.phases
    assert 8 in result.phases
    # The halt is recorded (the scoped halt is observable) and BAU stays
    # active under a scoped halt.
    assert session.bau_halt is not None
    assert session.bau_halt["scope"] == "scoped"
    assert session.bau_active() is True


# ---: persistence & crash recovery ---------------------------------


def test_phase4_crash_leaves_recoverable_checkpoint(tmp_path, monkeypatch):
    # a crash during Phase 4 (plan) must leave the pre-crash
    # state recoverable — the checkpoint written after Phase 3 (phase <= 4)
    # plus the persisted org chart + role memory.
    backend = StubBackend()
    backend.set_script("leader", _leader_script_full())
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": []}},
    ])
    state_dir = tmp_path / "state"
    config = {
        "org_chart_path": str(state_dir / "org_chart.json"),
        "memory_dir": str(state_dir / "role_memory"),
        "checkpoint_path": str(state_dir / "checkpoint.json"),
        "pod_transcripts_dir": str(tmp_path / "pods" / "transcripts"),
    }
    session = Session(backend, make_leader(), config=config,
                      history_dir=str(tmp_path / "history"))
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()

    import runtime.session as session_mod

    def boom(*args, **kwargs):
        raise RuntimeError("simulated crash in Phase 4")

    # Monkeypatch a Phase 4 step (the plan) to raise mid-run.
    monkeypatch.setattr(session_mod.plan, "run_plan", boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        session.run(
            "build a data pipeline",
            user_answer_fn, user_permission_fn, approver_fn,
            max_iterations=3,
        )
    # The checkpoint written after Phase 3 survived the crash (phase <= 4).
    cp_path = state_dir / "checkpoint.json"
    assert cp_path.exists()
    cp = json.loads(cp_path.read_text(encoding="utf-8"))
    assert cp["phase"] <= 4
    # The pre-crash state is recoverable: the org chart was saved with the
    # bootstrapped head, and a role-memory file was saved.
    chart = json.loads(
        (state_dir / "org_chart.json").read_text(encoding="utf-8"))
    assert "head_analytics" in chart["roles"]
    mem_files = [p for p in os.listdir(state_dir / "role_memory")
                 if p.endswith(".json")]
    assert mem_files


def test_org_state_save_is_atomic(tmp_path):
    # OrgState.save writes to `path + ".tmp"` then
    # `os.replace`s — a mid-write crash (garbage left in the temp) must not
    # corrupt the live chart, and a subsequent save consumes the temp.
    org = OrgState(history_dir=str(tmp_path))
    org.add_role(Role(id="r1", architype="ic", sub_architype="dev"))
    path = tmp_path / "org_chart.json"
    org.save(str(path))
    good = path.read_text(encoding="utf-8")
    json.loads(good)  # the live chart is valid JSON
    # Simulate a mid-write crash: garbage left in the temp file.
    with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
        f.write("GARBAGE-PARTIAL-WRITE")
    # The live chart is intact (the temp is not the live file).
    assert path.read_text(encoding="utf-8") == good
    # A subsequent save atomically replaces the chart and consumes the temp.
    org.add_role(Role(id="r2", architype="ic", sub_architype="qa"))
    org.save(str(path))
    chart = json.loads(path.read_text(encoding="utf-8"))
    assert set(chart["roles"]) == {"r1", "r2"}
    assert not os.path.exists(str(path) + ".tmp")


def test_memory_backend_save_state_is_atomic(tmp_path):
    # MemoryBackend.save_state writes `<role_id>.json.tmp` then
    # `os.replace`s — a mid-write crash must not corrupt the live memory, and
    # a subsequent save consumes the temp.
    backend = MemoryBackend(StubBackend())
    memory = backend._memory_for("r1")
    memory.add_summary("first interaction", source="intra-team")
    directory = tmp_path / "role_memory"
    backend.save_state(str(directory))
    role_file = directory / "r1.json"
    good = role_file.read_text(encoding="utf-8")
    json.loads(good)  # the live memory is valid JSON
    # Simulate a mid-write crash: garbage left in the temp file.
    with open(str(role_file) + ".tmp", "w", encoding="utf-8") as f:
        f.write("GARBAGE-PARTIAL-WRITE")
    # The live memory is intact (the temp is not the live file).
    assert role_file.read_text(encoding="utf-8") == good
    # A subsequent save atomically replaces the memory and consumes the temp.
    memory.add_summary("second interaction", source="intra-team")
    backend.save_state(str(directory))
    data = json.loads(role_file.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 2
    assert not os.path.exists(str(role_file) + ".tmp")
