"""Unit tests for `runtime/org.py` — org bootstrap + resourcing
(Epic 3 Definition of Done).

Bootstrapping a 3-department org (HR + Safety + Morality required) creates the
right directories/policies; a redundant hire is vetoed by HR; a firing of a
team produces an offloading plan that names the automations preserved and the
team continuing their validation; a hire adopts an existing role definition or
creates one (logged); a 4th IC under a non-manager triggers a manager hire; an
IC cannot initiate a hire/fire.
"""

import os

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import (
    OrgState,
    bootstrap,
    hire,
    fire,
    ResourcingError,
    ResourcingVetoed,
)
from runtime.mission import MissionResult


def _head(rid, dept, required=False):
    return Role(id=rid, architype="department_head", department=dept,
                sub_architype=f"head_of_{dept}", is_required=required)


def _mgr(rid, dept, team, reports_to):
    return Role(id=rid, architype="manager", department=dept, team=team,
                sub_architype=team, reports_to=reports_to)


def _ic(rid, dept, team, reports_to):
    return Role(id=rid, architype="ic", department=dept, team=team,
                reports_to=reports_to)


def _approve_all(approver_type, action, target):
    return {"decision": "approve", "rationale": "ok"}


def test_bootstrap_creates_required_departments(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head (HR approves).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    created = bootstrap(org, backend, leader, mission, _approve_all,
                        departments_dir=str(tmp_path))
    # The proposed head + the three required departments are present.
    assert org.get("head_analytics") is not None
    for dept in ("hr", "safety", "morality"):
        assert any(r.department == dept and r.architype == "department_head"
                   for r in org.active_roles())
    # The required departments are marked non-fireable.
    for dept in ("hr", "safety", "morality"):
        head = [r for r in org.active_roles()
                if r.department == dept and r.architype == "department_head"][0]
        assert head.is_required
    # Directories + policy markdowns were created.
    assert os.path.isdir(os.path.join(str(tmp_path), "analytics"))
    assert os.path.isfile(
        os.path.join(str(tmp_path), "analytics", "ANALYTICS_POLICY.md"))
    assert os.path.isdir(os.path.join(str(tmp_path), "hr"))


def test_bootstrap_accepts_leader_departments_shape(tmp_path):
    """The real LLM leader emits ``org_recommendation.departments`` (a list of
    ``{name, head, mandate}``), not the canonical ``department_heads`` — the
    bootstrap must normalize that shape (the Phase-3 'did nothing' regression)."""
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"departments": [
             {"name": "Business Development / Revenue",
              "head": "Business Development Director",
              "mandate": "Owns product lines and the contract pipeline."},
             {"name": "Engineering / Data & ML",
              "head": "Engineering Director (CTO)",
              "mandate": "Owns model development and data pipelines."},
             {"name": "Finance & Compliance",
              "head": "Finance Director (CFO)",
              "mandate": "Owns P&L and the governance log."},
             {"name": "HR", "head": "HR Director",
              "mandate": "Owns resourcing."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    # The operational heads were created (free-text names normalized to slugs).
    for slug in ("business_development_revenue", "engineering_data_ml",
                 "finance_compliance"):
        assert org.get(f"head_{slug}") is not None
    # The required departments are present (the leader's 'HR' is folded into
    # the required hr department and marked non-fireable).
    for dept in ("hr", "safety", "morality"):
        head = [r for r in org.active_roles()
                if r.department == dept and r.architype == "department_head"][0]
        assert head.is_required


def test_redundant_hire_vetoed_by_hr(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    # HR vetoes the hire.
    def hr_veto(approver_type, action, target):
        return {"decision": "veto", "rationale": "redundant with existing head"}
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_dup", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    created = bootstrap(org, backend, leader, mission, hr_veto,
                        departments_dir=str(tmp_path))
    # The redundant head was NOT created (only required departments).
    assert org.get("head_dup") is None
    assert not any(r.id == "head_dup" for r in org.active_roles())


def test_firing_produces_offloading_plan(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head so the bootstrap has an
    # operational head (an unscripted stub would raise BootstrapError).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    # Add a non-required department head to fire.
    head = _head("head_engineering", "engineering")
    org.add_role(head)
    os.makedirs(os.path.join(str(tmp_path), "engineering"), exist_ok=True)
    # The Leader fires the head (HR approves).
    plan = fire(org, leader, "head_engineering", _approve_all,
                departments_dir=str(tmp_path))
    assert plan["automations_preserved"] is True
    assert plan["continuing_team"] is not None
    # The plan file was written.
    assert os.path.isfile(plan["plan_path"])
    # The head is now inactive.
    assert org.get("head_engineering").status == "inactive"


def test_required_department_cannot_be_fired(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head so the bootstrap has an
    # operational head (an unscripted stub would raise BootstrapError).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    try:
        fire(org, leader, "head_hr", _approve_all, departments_dir=str(tmp_path))
        raise AssertionError("expected ResourcingError")
    except ResourcingError as e:
        assert "required" in str(e)


def test_hire_adopts_or_creates_role_definition(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head (HR approves).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    head = org.get("head_analytics")
    # First hire: creates a role definition (logged).
    mgr1 = _mgr("mgr1", "analytics", "pipelines", "head_analytics")
    hire(org, head, mgr1, _approve_all, departments_dir=str(tmp_path))
    assert "manager:pipelines" in org.role_definitions
    # Second hire of the same sub-architype: adopts the existing definition
    # (no new one created).
    mgr2 = _mgr("mgr2", "analytics", "pipelines", "head_analytics")
    hire(org, head, mgr2, _approve_all, departments_dir=str(tmp_path))
    assert "manager:pipelines" in org.role_definitions
    # The role_definition_created event was logged once.
    created_events = [e for e in org.events if e["kind"] == "role_definition_created"]
    assert len(created_events) == 1


def test_fourth_ic_triggers_manager_hire(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head (HR approves).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    head = org.get("head_analytics")  # a non-manager (department head)
    # Three ICs under the head is allowed (the cap is 3).
    for i in range(3):
        hire(org, head, _ic(f"ic{i}", "analytics", "pipelines", "head_analytics"),
             _approve_all, departments_dir=str(tmp_path))
    # The 4th IC under a non-manager triggers a manager hire.
    try:
        hire(org, head, _ic("ic3", "analytics", "pipelines", "head_analytics"),
             _approve_all, departments_dir=str(tmp_path))
        raise AssertionError("expected ResourcingError")
    except ResourcingError as e:
        assert "cap" in str(e)


def test_ic_cannot_initiate_hire_or_fire(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes an analytics head (HR approves).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    mission = MissionResult(approved=True, attempts=1, version=1,
                            mission_path="MISSION.md")
    bootstrap(org, backend, leader, mission, _approve_all,
              departments_dir=str(tmp_path))
    head = org.get("head_analytics")
    mgr = _mgr("mgr1", "analytics", "pipelines", "head_analytics")
    hire(org, head, mgr, _approve_all, departments_dir=str(tmp_path))
    ic = _ic("ic1", "analytics", "pipelines", "mgr1")
    hire(org, mgr, ic, _approve_all, departments_dir=str(tmp_path))
    # An IC cannot initiate a hire.
    try:
        hire(org, ic, _ic("ic2", "analytics", "pipelines", "mgr1"),
             _approve_all, departments_dir=str(tmp_path))
        raise AssertionError("expected ResourcingError")
    except ResourcingError as e:
        assert "ICs cannot initiate" in str(e)
    # An IC cannot initiate a fire.
    try:
        fire(org, ic, "ic1", _approve_all, departments_dir=str(tmp_path))
        raise AssertionError("expected ResourcingError")
    except ResourcingError as e:
        assert "ICs cannot initiate" in str(e)
