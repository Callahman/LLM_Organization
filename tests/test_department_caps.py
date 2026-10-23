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


def test_mission_carries_mission_departments(tmp_path):
    """Phase 2: the leader's mission_departments (the department LIST) is
    extracted and carried on MissionResult (in priority order, normalized)."""
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "draft", "mission_draft": _draft(),
         "mission_departments": {"departments": [
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
    assert [d["name"] for d in result.mission_departments] == [
        "Data Engineering", "Analytics"]
    assert [d["priority"] for d in result.mission_departments] == [1, 2]


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
        mission_departments=[
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
    # No mission_departments (the MissionResult).
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    # The org_recommendation head was created (the fallback path).
    assert org.get("head_finance") is not None


def test_mission_departments_helper_tolerates_shapes():
    """_mission_departments handles the shapes the real LLM free-forms: a
    dict with a `departments` list, a bare list, a `department` key, and
    missing/empty (degrades to []). It reads the `mission_departments` key
    (the Phase-2 key) with a fallback to the legacy `department_caps` key."""
    from runtime.mission import _mission_departments
    # Canonical: a dict with a departments list (the new key).
    assert _mission_departments({"mission_departments": {"departments": [
        {"name": "a"}, {"name": "b", "priority": 2}]}}) == [
        {"name": "a", "priority": 1, "rationale": ""},
        {"name": "b", "priority": 2, "rationale": ""}]
    # Bare list.
    assert _mission_departments({"mission_departments": ["a", "b"]}) == [
        {"name": "a", "priority": 1, "rationale": ""},
        {"name": "b", "priority": 2, "rationale": ""}]
    # `department` key (the leader's free-text key).
    assert _mission_departments({"mission_departments": {"departments": [
        {"department": "finance"}]}}) == [
        {"name": "finance", "priority": 1, "rationale": ""}]
    # Missing: no key at all.
    assert _mission_departments({}) == []
    # Empty list.
    assert _mission_departments({"mission_departments": {"departments": []}}) == []
    # Number: degrades to [].
    assert _mission_departments({"mission_departments": 5}) == []
    # Legacy key fallback: a model that still emits the old `department_caps`
    # key is not lost.
    assert _mission_departments({"department_caps": {"departments": [
        {"name": "a"}]}}) == [
        {"name": "a", "priority": 1, "rationale": ""}]
    # The new key wins over the legacy key when both are present.
    assert _mission_departments({"mission_departments": {"departments": [
        {"name": "new"}]}, "department_caps": {"departments": [
        {"name": "old"}]}}) == [
        {"name": "new", "priority": 1, "rationale": ""}]
