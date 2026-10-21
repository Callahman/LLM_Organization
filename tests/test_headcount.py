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


class _FlakyBackend:
    """A backend that fails the first ``fail_times`` invokes of the roles in
    ``fail_roles`` (raising ``OpenAIOutputError``) and then delegates to
    ``inner``. Records every ``(role_id, context)`` it sees (for
    corrective-retry checks)."""

    def __init__(self, inner, fail_roles=(), fail_times=1):
        from runtime.llm_api import OpenAIOutputError
        self._err = OpenAIOutputError
        self.inner = inner
        self.fail_roles = set(fail_roles)
        self.fail_times = fail_times
        self._fails = {}
        self.contexts = []

    def invoke(self, role, context, reasoning=None, timeout=None, phase=None):
        self.contexts.append((role.id, context))
        if role.id in self.fail_roles:
            n = self._fails.get(role.id, 0)
            if n < self.fail_times:
                self._fails[role.id] = n + 1
                raise self._err("malformed reply (simulated)")
        return self.inner.invoke(
            role, context, reasoning=reasoning, timeout=timeout, phase=phase)


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


# --- Error containment (a headcount hiccup must not kill the run) -----------

def test_allot_department_caps_contains_pod_failure(tmp_path):
    """Error containment: a headcount pod (Pod A) whose member invoke fails
    (a free-form reply -> OpenAIOutputError) is contained — the allotment does
    NOT raise; the leader's allotment stands (the leader has final say) and the
    failure is recorded (a visible org event)."""
    leader = make_leader()
    org = OrgState(history_dir=str(tmp_path))
    org.add_role(_head("head1", "analytics"))
    org.add_role(_head("head2", "data"))
    inner = StubBackend()
    inner.set_script("leader", [
        {"department_caps": {"analytics": 5, "data": 3}},  # allotment
        {"summary": "agenda", "agenda": "finalize the caps"},  # pod agenda
        {"summary": "close", "decision": "caps finalized",
         "rationale": "ok", "open_items": []},  # pod close
    ])
    inner.set_script("head1", [{"summary": "ok with 5"}])
    # head2's speak fails (a free-form reply -> OpenAIOutputError).
    backend = _FlakyBackend(inner, fail_roles={"head2"}, fail_times=99)
    mission_path = str(tmp_path / "MISSION.md")
    with open(mission_path, "w", encoding="utf-8") as f:
        f.write("# MISSION\n")
    # Must NOT raise — the pod failure is contained.
    caps = allot_department_caps(org, backend, leader, mission_path,
                                 config={"head_count_total": 10})
    # The leader's allotment stands (the leader has final say).
    assert caps == {"analytics": 5, "data": 3}
    assert org.department_caps == {"analytics": 5, "data": 3}
    # The failure is recorded (a visible org event).
    assert any(e["kind"] == "headcount_pod_failed" for e in org.events)


def test_allot_department_caps_contains_allotment_failure(tmp_path):
    """Error containment: the leader's department-cap allotment that fails
    (even after its one corrective retry) is contained — the allotment does
    NOT raise; the org falls back to the per-manager IC cap (no department
    caps) and the failure is recorded (a visible org event)."""
    leader = make_leader()
    org = OrgState(history_dir=str(tmp_path))
    org.add_role(_head("head1", "analytics"))
    inner = StubBackend()
    # The leader's allotment fails (the corrective retry fails too); the pod
    # then runs fine (the leader recovers).
    backend = _FlakyBackend(inner, fail_roles={"leader"}, fail_times=2)
    mission_path = str(tmp_path / "MISSION.md")
    with open(mission_path, "w", encoding="utf-8") as f:
        f.write("# MISSION\n")
    # Must NOT raise — the allotment failure is contained.
    caps = allot_department_caps(org, backend, leader, mission_path,
                                 config={"head_count_total": 10})
    # No department caps (the org falls back to the per-manager IC cap).
    assert caps == {}
    assert org.department_caps == {}
    # The corrective retry was attempted (the nudge context was sent).
    assert any(rid == "leader" and "[RETRY]" in c
               for (rid, c) in backend.contexts)
    # The failure is recorded (a visible org event).
    assert any(e["kind"] == "headcount_allotment_failed" for e in org.events)


def test_allot_team_caps_contains_pod_failure(tmp_path):
    """Error containment: a team-cap pod (Pod B) whose member invoke fails
    (a free-form reply -> OpenAIOutputError) is contained — the allotment does
    NOT raise; the head's allotment stands (the head has final say) and the
    failure is recorded (a visible org event). A single-manager department also
    forms a valid pod (the head is a member, so the 2-member minimum holds)."""
    from runtime.plan import _allot_team_caps
    org = OrgState(history_dir=str(tmp_path))
    head = _head("head1", "analytics")
    org.add_role(head)
    # The department has a cap allotted (otherwise _allot_team_caps is a no-op).
    org.department_caps["analytics"] = 10
    mgr = Role(id="mgr1", architype="manager", department="analytics",
               team="pipelines", reports_to="head1")
    org.add_role(mgr)
    inner = StubBackend()
    inner.set_script("head1", [
        {"team_caps": {"pipelines": 3}},  # allotment
        {"summary": "agenda", "agenda": "finalize the team caps"},  # pod agenda
        {"summary": "speak", "findings": []},  # pod speak (the head is a member)
        {"summary": "close", "decision": "done", "rationale": "ok",
         "open_items": []},  # pod close
    ])
    # mgr1's speak fails (a free-form reply -> OpenAIOutputError).
    backend = _FlakyBackend(inner, fail_roles={"mgr1"}, fail_times=99)
    team_objectives = [{"manager_id": "mgr1", "team": "pipelines",
                        "objective": "build the pipelines"}]
    # Must NOT raise — the pod failure is contained.
    _allot_team_caps(org, backend, head, team_objectives,
                     config={"head_count_total": 10})
    # The head's caps stand (the head has final say).
    assert org.team_caps[("analytics", "pipelines")] == 3
    # The failure is recorded (a visible org event).
    assert any(e["kind"] == "headcount_pod_failed" for e in org.events)


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
