"""the headcount cap chain (top to bottom).

The total cap is in the config (``head_count_total``); the **department caps**
(allotted by the leader in Phase 3, summing to <= the total) and the **team
caps** (allotted by the head in Phase 4, summing to <= the department cap) are
stored on the org so they are queryable at each hire. A hire that would exceed
a cap is blocked / escalated.

This file tests the cap chain: the parse + clamp helpers, the Phase 3
allotment (department caps + Pod A), the Phase 5 team-cap check, and the
``HEAD_COUNT_TOTAL`` config knob.
"""

from __future__ import annotations

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import (
    OrgState,
    allot_department_caps,
    _parse_and_clamp_caps,
)
from runtime.plan import _parse_team_caps
from runtime.staff import _team_cap_ok


def _head(rid, department):
    return Role(id=rid, architype="department_head", department=department)


# --- The cap chain structure -------------------------------------------------

def test_org_state_has_cap_chain():
    # The org carries the cap chain (top to bottom): the department caps and the
    # team caps (a cap per team, keyed by (department, team)).
    org = OrgState(history_dir="history")
    assert org.department_caps == {}
    assert org.team_caps == {}


# --- Phase 3: the leader allots the department caps --------------------------

def test_parse_and_clamp_caps_parses():
    # Parses the leader's `department_caps` output into a {department: cap}.
    out = {"department_caps": {"analytics": 10, "data": 5}}
    caps = _parse_and_clamp_caps(out, ["analytics", "data"], total=20)
    assert caps == {"analytics": 10, "data": 5}


def test_parse_and_clamp_caps_clamps():
    # Clamps so the sum of the caps is <= the total cap.
    out = {"department_caps": {"analytics": 10, "data": 5}}
    caps = _parse_and_clamp_caps(out, ["analytics", "data"], total=10)
    assert sum(caps.values()) <= 10


def test_parse_and_clamp_caps_ignores_non_dict():
    # A non-dict `department_caps` is ignored (no caps).
    out = {"department_caps": "nonsense"}
    caps = _parse_and_clamp_caps(out, ["analytics"], total=10)
    assert caps == {}


def test_parse_and_clamp_caps_ignores_non_positive():
    # Non-positive caps are ignored.
    out = {"department_caps": {"analytics": -1, "data": 0}}
    caps = _parse_and_clamp_caps(out, ["analytics", "data"], total=10)
    assert caps == {}


def test_allot_department_caps_no_total():
    # No total cap -> returns {} without invoking the leader or forming a pod.
    leader = make_leader()
    org = OrgState(history_dir="history")
    org.add_role(_head("head1", "analytics"))
    backend = StubBackend()
    caps = allot_department_caps(org, backend, leader, "", config={})
    assert caps == {}
    assert org.department_caps == {}
    # The leader was NOT invoked (no caps allotment).
    assert len(backend.calls) == 0


def test_allot_department_caps_stores_and_records(tmp_path, monkeypatch):
    # With a total cap: the leader allots the department caps, Pod A (all heads
    # + the leader) finalizes them, the caps are stored on the org, and the
    # mission addendum is recorded.
    leader = make_leader()
    org = OrgState(history_dir=str(tmp_path))
    org.add_role(_head("head1", "analytics"))
    org.add_role(_head("head2", "data"))
    backend = StubBackend()
    backend.set_script("leader", [
        {"department_caps": {"analytics": 5, "data": 3}},
    ])
    # Capture Pod A (without running it).
    captured = []

    def fake_run_pod(backend, pod, max_rounds=None, **kw):
        captured.append(pod)
        return pod

    monkeypatch.setattr("runtime.org.run_pod", fake_run_pod)
    mission_path = str(tmp_path / "MISSION.md")
    with open(mission_path, "w", encoding="utf-8") as f:
        f.write("# MISSION\n")
    caps = allot_department_caps(org, backend, leader, mission_path,
                                 config={"head_count_total": 10})
    assert caps == {"analytics": 5, "data": 3}
    # The caps are stored on the org (queryable at each hire).
    assert org.department_caps == {"analytics": 5, "data": 3}
    # The mission addendum is recorded.
    content = open(mission_path, encoding="utf-8").read()
    assert "Headcount Addendum" in content
    assert "analytics: 5" in content
    assert "data: 3" in content
    # Pod A was formed as a headcount pod (all heads + the leader, the leader
    # is the starter).
    assert len(captured) == 1
    assert captured[0].kind == "headcount"
    assert captured[0].starter.id == leader.id


# --- Phase 4: the head allots the team caps ---------------------------------

def test_parse_team_caps_parses():
    # Parses the head's `team_caps` output into a {team: cap}.
    out = {"team_caps": {"pipelines": 4, "reporting": 2}}
    caps = _parse_team_caps(out, ["pipelines", "reporting"], dept_cap=10)
    assert caps == {"pipelines": 4, "reporting": 2}


def test_parse_team_caps_clamps():
    # Clamps so the sum of the team caps is <= the department cap.
    out = {"team_caps": {"pipelines": 4, "reporting": 2}}
    caps = _parse_team_caps(out, ["pipelines", "reporting"], dept_cap=4)
    assert sum(caps.values()) <= 4


# --- Phase 5: enforce the team/IC cap ----------------------------------------

def test_team_cap_ok_no_cap():
    # No cap allotted -> the hire is allowed (falls back to the per-manager IC cap).
    org = OrgState(history_dir="history")
    assert _team_cap_ok(org, "analytics", "pipelines") is True


def test_team_cap_ok_within_cap():
    # current + 1 <= cap -> allowed.
    org = OrgState(history_dir="history")
    for i in range(2):
        org.add_role(Role(id=f"ic{i}", architype="ic",
                          department="analytics", team="pipelines"))
    org.team_caps[("analytics", "pipelines")] = 3
    assert _team_cap_ok(org, "analytics", "pipelines") is True


def test_team_cap_ok_over_cap():
    # current + 1 > cap -> blocked.
    org = OrgState(history_dir="history")
    for i in range(3):
        org.add_role(Role(id=f"ic{i}", architype="ic",
                          department="analytics", team="pipelines"))
    org.team_caps[("analytics", "pipelines")] = 3
    assert _team_cap_ok(org, "analytics", "pipelines") is False


# --- Config -------------------------------------------------------------------

def test_head_count_total_config(monkeypatch):
    # The HEAD_COUNT_TOTAL .env knob is consumed (the total org-size cap).
    monkeypatch.setenv("HEAD_COUNT_TOTAL", "50")
    from runtime.config import load_config
    config = load_config()
    assert config["head_count_total"] == 50
