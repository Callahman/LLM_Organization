"""Unit tests for Story 22 (invoke timing + efficiency panel).

- **``TimingTracker``**: accumulates per-role / per-department invoke time and
  appends the running snapshot to ``history/efficiency.jsonl``.
- **``TimingBackend``**: a transparent wrapper that times each invoke (wall
  clock) and records it; delegates all other attributes to the inner backend.
- **Firing cascade** (``org.fire``): firing a role that has its own reports
  fires the **entire report subtree**, and the **cascade size** is included in
  the **single** HR approval request (a 4th ``detail`` argument — not raised
  separately per cascaded role).
- **Leader efficiency actions**: the leader's output schema carries the
  ``efficiency`` action (fire / reassign / report) and the leader is invoked
  with the efficiency panel in Phase 4.
"""

import json
import os

import pytest

from roles.base import Role
from roles.leader import make_leader, LEADER_OUTPUT_SCHEMA
from runtime.org import OrgState, fire, ResourcingVetoed
from runtime.timing import TimingTracker, TimingBackend


# --- TimingTracker -----------------------------------------------------------

def test_tracker_accumulates_per_role_and_department(tmp_path):
    tracker = TimingTracker(history_dir=str(tmp_path))
    tracker.record_invoke("r1", "analytics", 1.0)
    tracker.record_invoke("r1", "analytics", 2.0)
    tracker.record_invoke("r2", "hr", 0.5)
    snap = tracker.snapshot()
    assert snap["per_role"]["r1"] == pytest.approx(3.0)
    assert snap["per_role"]["r2"] == pytest.approx(0.5)
    assert snap["per_department"]["analytics"] == pytest.approx(3.0)
    assert snap["per_department"]["hr"] == pytest.approx(0.5)
    assert snap["total_time"] == pytest.approx(3.5)
    assert snap["total_calls"] == 3


def test_tracker_appends_efficiency_log(tmp_path):
    tracker = TimingTracker(history_dir=str(tmp_path))
    tracker.record_invoke("r1", "analytics", 1.0)
    tracker.record_invoke("r2", "hr", 2.0)
    path = os.path.join(str(tmp_path), "efficiency.jsonl")
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    # One line per invoke (the running cumulative snapshot).
    assert len(lines) == 2
    # The latest line is the full cumulative state.
    assert lines[-1]["per_role"]["r1"] == pytest.approx(1.0)
    assert lines[-1]["per_role"]["r2"] == pytest.approx(2.0)
    assert lines[-1]["per_department"]["analytics"] == pytest.approx(1.0)
    assert lines[-1]["per_department"]["hr"] == pytest.approx(2.0)


def test_tracker_snapshot_is_a_copy(tmp_path):
    tracker = TimingTracker(history_dir=str(tmp_path))
    tracker.record_invoke("r1", "analytics", 1.0)
    snap = tracker.snapshot()
    snap["per_role"]["r1"] = 999.0  # mutating the snapshot...
    assert tracker.snapshot()["per_role"]["r1"] == pytest.approx(1.0)  # ...doesn't leak


# --- TimingBackend -----------------------------------------------------------

class _FakeInner:
    """A minimal inner backend: records the context it was invoked with and
    returns a fixed dict. Also exposes a non-invoke attribute (``save_state``)
    to verify delegation."""

    def __init__(self):
        self.invoked_with = []
        self.saved = False

    def invoke(self, role, context, *args, **kwargs):
        self.invoked_with.append(context)
        return {"summary": "ok", "confidence": 1.0}

    def save_state(self, *args, **kwargs):
        self.saved = True


def _role(rid, dept="analytics"):
    return Role(id=rid, architype="ic", department=dept, team="t1",
                reports_to=None)


def test_timing_backend_times_and_records(tmp_path):
    inner = _FakeInner()
    tracker = TimingTracker(history_dir=str(tmp_path))
    backend = TimingBackend(inner, tracker)
    role = _role("r1", "analytics")
    out = backend.invoke(role, "ctx", reasoning="low", phase=4)
    assert out == {"summary": "ok", "confidence": 1.0}
    assert inner.invoked_with == ["ctx"]
    snap = tracker.snapshot()
    assert snap["per_role"]["r1"] >= 0.0
    assert snap["per_department"]["analytics"] >= 0.0
    assert snap["total_calls"] == 1


def test_timing_backend_delegates_other_attributes(tmp_path):
    inner = _FakeInner()
    tracker = TimingTracker(history_dir=str(tmp_path))
    backend = TimingBackend(inner, tracker)
    backend.save_state("somewhere")  # delegated to the inner backend
    assert inner.saved is True


# --- Firing cascade ----------------------------------------------------------

def _ic(rid, dept, team, reports_to):
    return Role(id=rid, architype="ic", department=dept, team=team,
                sub_architype=team, reports_to=reports_to)


def _mgr(rid, dept, team, reports_to):
    return Role(id=rid, architype="manager", department=dept, team=team,
                sub_architype=team, reports_to=reports_to)


def _head(rid, dept):
    return Role(id=rid, architype="department_head", department=dept,
                sub_architype=f"head_of_{dept}")


def _leader():
    return make_leader()


def test_firing_cascades_to_report_subtree(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = _leader()
    # A head -> a manager -> two ICs (the manager has its own reports).
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "analytics", "team1", reports_to="head_analytics")
    ic1 = _ic("ic1", "analytics", "team1", reports_to="mgr1")
    ic2 = _ic("ic2", "analytics", "team1", reports_to="mgr1")
    for r in (head, mgr, ic1, ic2):
        org.add_role(r)
    # A 3-arg approver (backward compatible) that approves.
    approver_fn = lambda approver_type, action, target: {
        "decision": "approve", "rationale": "ok"}
    fire(org, leader, "mgr1", approver_fn,
         departments_dir=str(tmp_path))
    # The whole subtree (mgr1 + ic1 + ic2) is fired, not just mgr1.
    assert org.get("mgr1").status == "inactive"
    assert org.get("ic1").status == "inactive"
    assert org.get("ic2").status == "inactive"
    # The head (not in the subtree) is untouched.
    assert org.get("head_analytics").status == "active"
    # A single "fired" event with the cascade size in the detail.
    fired = [e for e in org.events if e["kind"] == "fired"]
    assert len(fired) == 1
    assert fired[0]["detail"]["cascade_size"] == 3
    assert fired[0]["detail"]["cascade_role_ids"] == ["mgr1", "ic1", "ic2"]


def test_cascade_size_included_in_hr_approval_request(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = _leader()
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "analytics", "team1", reports_to="head_analytics")
    ic1 = _ic("ic1", "analytics", "team1", reports_to="mgr1")
    for r in (head, mgr, ic1):
        org.add_role(r)
    # A 4-arg approver that CAPTURES the detail (the cascade size) and
    # approves.
    captured = {}
    def approver_fn(approver_type, action, target, detail=None):
        captured["detail"] = detail
        return {"decision": "approve", "rationale": "ok"}
    fire(org, leader, "mgr1", approver_fn, departments_dir=str(tmp_path))
    # The cascade size is included in the (single) HR approval request.
    assert captured["detail"] is not None
    assert captured["detail"]["cascade_size"] == 2
    assert captured["detail"]["cascade_role_ids"] == ["mgr1", "ic1"]


def test_firing_vetoed_logs_cascade_size(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = _leader()
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "analytics", "team1", reports_to="head_analytics")
    ic1 = _ic("ic1", "analytics", "team1", reports_to="mgr1")
    for r in (head, mgr, ic1):
        org.add_role(r)
    approver_fn = lambda approver_type, action, target: {
        "decision": "reject", "rationale": "not needed"}
    with pytest.raises(ResourcingVetoed):
        fire(org, leader, "mgr1", approver_fn, departments_dir=str(tmp_path))
    # Nothing is fired on a veto.
    assert org.get("mgr1").status == "active"
    assert org.get("ic1").status == "active"
    # The veto event carries the cascade size.
    vetoed = [e for e in org.events if e["kind"] == "fire_vetoed"]
    assert len(vetoed) == 1
    assert vetoed[0]["detail"]["cascade_size"] == 2


def test_firing_without_cascade_is_legacy(tmp_path):
    org = OrgState(history_dir=str(tmp_path))
    leader = _leader()
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "analytics", "team1", reports_to="head_analytics")
    ic1 = _ic("ic1", "analytics", "team1", reports_to="mgr1")
    for r in (head, mgr, ic1):
        org.add_role(r)
    approver_fn = lambda approver_type, action, target: {
        "decision": "approve", "rationale": "ok"}
    fire(org, leader, "mgr1", approver_fn, departments_dir=str(tmp_path),
         cascade=False)
    # Only the target is fired (the legacy behavior).
    assert org.get("mgr1").status == "inactive"
    assert org.get("ic1").status == "active"


# --- Leader efficiency actions ------------------------------------------------

def test_leader_schema_has_efficiency_action():
    props = LEADER_OUTPUT_SCHEMA["properties"]
    assert "efficiency" in props
    eff = props["efficiency"]
    assert eff["type"] == "object"
    assert eff["required"] == ["action", "target"]
    action_enum = eff["properties"]["action"]["enum"]
    assert set(action_enum) == {"fire", "reassign", "report"}
    assert "new_team" in eff["properties"]


def test_leader_output_schema_is_valid_json_schema_shape():
    # The efficiency action must be a well-formed object schema (the forced
    # submit_output tool constrains the model to emit it correctly).
    eff = LEADER_OUTPUT_SCHEMA["properties"]["efficiency"]
    assert eff["properties"]["target"]["type"] == "string"
    assert eff["properties"]["reasoning"]["type"] == "string"
