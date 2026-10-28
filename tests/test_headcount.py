"""the headcount cap chain (top to bottom).

The total cap is in the config (``head_count_total``); the **department caps**
and the **team caps** (a cap per team, summing to <= the department cap) are
stored on the org so they are queryable at each hire. A hire that would exceed
a cap is blocked / escalated.

(The leader's Phase-3 department-cap allotment and the head's Phase-4 team-cap
allotment were removed — the headcount is no longer allotted by the leader or
the head; the team caps are an even-split default, finalized by Pod B.)

This file tests the cap chain: the Phase 5 team-cap check, the Pod B error
containment, and the ``HEAD_COUNT_TOTAL`` config knob.
"""

from __future__ import annotations

from roles.base import Role
from runtime.llm import StubBackend
from runtime.org import OrgState
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


# --- Error containment (a headcount hiccup must not kill the run) -----------

def test_allot_team_caps_contains_pod_failure(tmp_path):
    """Error containment: a team-cap pod (Pod B) whose member invoke fails
    (a free-form reply -> OpenAIOutputError) is contained — the allotment does
    NOT raise; the even-split caps stand (the head has final say) and the
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
    # The head is only invoked for Pod B (the LLM allotment was removed) — the
    # even-split caps (10 // 1 = 10) are the final.
    inner.set_script("head1", [
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
    # The even-split caps stand (the head has final say — 1 team, cap 10).
    assert org.team_caps[("analytics", "pipelines")] == 10
    # The failure is recorded (a visible org event).
    assert any(e["kind"] == "headcount_pod_failed" for e in org.events)


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
