"""Tests for — the department caps in the Mission phase (Phase 2).

The leader proposes the departments the mission needs (in priority order) in
Phase 2; `MissionResult` carries them; Phase 3 (Org bootstrap) creates them.
If the proposal is absent, bootstrap falls back to the Phase-3
`org_recommendation` head proposal (the behavior)."""

import os

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.intake import IntakeResult
from runtime.mission import run_mission, MissionResult
from runtime.org import OrgState, bootstrap


def _intake():
    return IntakeResult(confident=True, converged=True, rounds=1, confidence=0.9)


def _approve_all(approver_type, action, target):
    return {"decision": "approve", "rationale": "ok"}


def _draft():
    return {
        "purpose": "build a data pipeline",
        "success_criteria": "accurate",
        "scope": "etl",
        "non_goals": [],
        "constraints": [],
        "org_recommendation": [],
        "resource_envelope": "",
    }


def test_mission_carries_department_caps(tmp_path):
    """Phase 2: the leader's department_caps is extracted and carried on
    MissionResult (in priority order, normalized)."""
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "draft", "mission_draft": _draft(),
         "department_caps": {"departments": [
             {"name": "Data Engineering", "priority": 1,
              "rationale": "owns the ETL pipelines"},
             {"name": "Analytics", "priority": 2,
              "rationale": "owns reporting"},
         ]}},
    ])
    result = run_mission(
        backend, leader, _intake(),
        user_permission_fn=lambda draft: {"decision": "approve", "feedback": ""},
        mission_path=os.path.join(str(tmp_path), "MISSION.md"),
        history_dir=str(tmp_path),
        reask_budget=1,
    )
    assert result.approved
    assert [d["name"] for d in result.department_caps] == [
        "Data Engineering", "Analytics"]
    assert [d["priority"] for d in result.department_caps] == [1, 2]


def test_bootstrap_creates_proposed_departments(tmp_path):
    """Phase 3: bootstrap creates the Phase-2 proposed departments (one head
    each, in priority order) WITHOUT invoking the leader for a head proposal —
    the StubBackend has no leader script, so a successful bootstrap proves the
    proposal path (not the org_recommendation fallback) was used."""
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    mission = MissionResult(
        approved=True, attempts=1, version=1, mission_path="MISSION.md",
        department_caps=[
            {"name": "Data Engineering", "priority": 1, "rationale": "owns ETL"},
            {"name": "Analytics", "priority": 2, "rationale": "owns reporting"},
        ],
    )
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    # The proposed departments were created (free-text names -> slugs).
    assert org.get("head_data_engineering") is not None
    assert org.get("head_analytics") is not None
    # The required governance departments are always present.
    for dept in ("hr", "safety", "morality"):
        assert any(r.department == dept and r.architype == "department_head"
                   for r in org.active_roles())


def test_bootstrap_falls_back_to_org_recommendation(tmp_path):
    """Phase 3: when the Phase-2 proposal is absent, bootstrap falls back to
    the Phase-3 org_recommendation head proposal (the behavior)."""
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_finance", "department": "finance",
              "sub_architype": "head_of_finance", "required": False,
              "mandate": "Head of finance."},
         ]}},
    ])
    # No department_caps (the MissionResult).
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    # The org_recommendation head was created (the fallback path).
    assert org.get("head_finance") is not None


def test_department_caps_helper_tolerates_shapes():
    """_department_caps handles the shapes the real LLM free-forms: a
    dict with a `departments` list, a bare list, a `department` key, and
    missing/empty (degrades to [])."""
    from runtime.mission import _department_caps
    # Canonical: a dict with a departments list.
    assert _department_caps({"department_caps": {"departments": [
        {"name": "a"}, {"name": "b", "priority": 2}]}}) == [
        {"name": "a", "priority": 1, "rationale": ""},
        {"name": "b", "priority": 2, "rationale": ""}]
    # Bare list.
    assert _department_caps({"department_caps": ["a", "b"]}) == [
        {"name": "a", "priority": 1, "rationale": ""},
        {"name": "b", "priority": 2, "rationale": ""}]
    # `department` key (the leader's free-text key).
    assert _department_caps({"department_caps": {"departments": [
        {"department": "finance"}]}}) == [
        {"name": "finance", "priority": 1, "rationale": ""}]
    # Missing: no department_caps key.
    assert _department_caps({}) == []
    # Empty list.
    assert _department_caps({"department_caps": {"departments": []}}) == []
    # Number: degrades to [].
    assert _department_caps({"department_caps": 5}) == []
