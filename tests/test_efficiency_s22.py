"""Unit tests for Story 22 (S22) — the efficiency trade-off in the Phase 3-6
loop.

- **``EfficiencyMeter``**: instruments the Phase 3-6 loop per iteration
  (T_total, T_p3..T_p6, T_dept, T_role, H_peak, C, N_created) and appends the
  per-iteration snapshot to ``history/efficiency_metrics.jsonl`` (auditable +
  the dashboard's Efficiency panel).
- **``efficiency_score``**: the efficiency score
  ``E = M_satisfaction / (0.5·(T_total/T_ref) + 0.5·(C/C_ref))`` with
  running-average refs over the last 3 iterations.
- **``compute_m_satisfaction``**: the mission satisfaction (0-1), generalized
  for BOTH terminal and recurring goals.
- **EFFICIENCY_FLOOR**: when ``E`` is below the floor, ``below_floor`` is True
  (the Leader must take a visible efficiency action).
- **``run_automation``**: the automation flow — an IC writes a Python script,
  the script is created, the IC is fired, and the recurring task is then done
  by executing the script.
"""

import json
import os

import pytest

from runtime.efficiency import (
    EfficiencyMeter,
    compute_m_satisfaction,
    efficiency_score,
    EFFICIENCY_FLOOR,
)


# --- EfficiencyMeter ---------------------------------------------------------

def test_meter_records_phases_and_headcount(tmp_path):
    meter = EfficiencyMeter(history_dir=str(tmp_path))
    meter.start_iteration()
    # Phase 3: 10s, 2 roles; Phase 4: 20s, 5 roles; Phase 5: 5s, 5 roles.
    meter.record_phase(3, 0.0, 10.0)
    meter.record_headcount(2, 10.0)
    meter.record_phase(4, 10.0, 30.0)
    meter.record_headcount(5, 20.0)
    meter.record_phase(5, 30.0, 35.0)
    meter.record_headcount(5, 5.0)
    meter.record_role_time("ic1", "analytics", 12.0)
    meter.record_created(3)
    snap = meter.finish_iteration(1.0)
    # T_total = 10 + 20 + 5 = 35s.
    assert snap["T_total"] == pytest.approx(35.0)
    assert snap["T_p"][3] == pytest.approx(10.0)
    assert snap["T_p"][4] == pytest.approx(20.0)
    assert snap["T_p"][5] == pytest.approx(5.0)
    # H_peak = max(2, 5, 5) = 5.
    assert snap["H_peak"] == 5
    # C = 2*10 + 5*20 + 5*5 = 20 + 100 + 25 = 145 role-min.
    assert snap["C"] == pytest.approx(145.0)
    assert snap["N_created"] == 3
    assert snap["T_role"]["ic1"] == pytest.approx(12.0)
    assert snap["T_dept"]["analytics"] == pytest.approx(12.0)
    # First iteration: no prior refs -> a neutral baseline (denominator 1.0),
    # so E = M_satisfaction = 1.0.
    assert snap["E"] == pytest.approx(1.0)
    assert snap["T_ref"] is None
    assert snap["C_ref"] is None


def test_meter_running_averages_over_last_3(tmp_path):
    meter = EfficiencyMeter(history_dir=str(tmp_path))
    # Four iterations with distinct (T_total, C). The 4th iteration's refs are
    # the running averages over the last 3 PRIOR iterations (1, 2, 3).
    for t, c in [(10.0, 100.0), (20.0, 200.0), (30.0, 300.0), (40.0, 400.0)]:
        meter.start_iteration()
        meter.record_phase(4, 0.0, t)
        meter.record_headcount(c, 1.0)  # C = c * 1.0 = c
        meter.finish_iteration(1.0)
    snap = meter.last()
    # The 4th iteration's T_ref = avg(10, 20, 30) = 20; C_ref = avg(100, 200, 300) = 200.
    assert snap["T_ref"] == pytest.approx(20.0)
    assert snap["C_ref"] == pytest.approx(200.0)


def test_meter_appends_efficiency_metrics_log(tmp_path):
    meter = EfficiencyMeter(history_dir=str(tmp_path))
    meter.start_iteration()
    meter.record_phase(4, 0.0, 10.0)
    meter.record_headcount(3, 10.0)
    meter.finish_iteration(0.5)
    meter.start_iteration()
    meter.record_phase(4, 0.0, 20.0)
    meter.record_headcount(4, 20.0)
    meter.finish_iteration(1.0)
    path = os.path.join(str(tmp_path), "efficiency_metrics.jsonl")
    assert os.path.isfile(path)
    with open(path, "r", encoding="utf-8") as f:
        lines = [json.loads(ln) for ln in f if ln.strip()]
    # One line per iteration.
    assert len(lines) == 2
    assert lines[0]["cycle"] == 1
    assert lines[1]["cycle"] == 2
    assert lines[0]["M_satisfaction"] == pytest.approx(0.5)
    assert lines[1]["M_satisfaction"] == pytest.approx(1.0)


def test_meter_last_is_none_before_any_iteration(tmp_path):
    meter = EfficiencyMeter(history_dir=str(tmp_path))
    assert meter.last() is None
    assert meter.panel_text() == ""


# --- efficiency_score --------------------------------------------------------

def test_efficiency_score_first_iteration_neutral_baseline():
    # No prior refs (None/None) -> a neutral baseline (denominator 1.0), so
    # E = M_satisfaction.
    assert efficiency_score(0.8, 10.0, 100.0, None, None) == pytest.approx(0.8)


def test_efficiency_score_with_refs():
    # E = M / (0.5*(T/T_ref) + 0.5*(C/C_ref)).
    # T/T_ref = 20/10 = 2; C/C_ref = 200/100 = 2; denom = 0.5*2 + 0.5*2 = 2.
    # E = 1.0 / 2 = 0.5.
    assert efficiency_score(1.0, 20.0, 200.0, 10.0, 100.0) == pytest.approx(0.5)


def test_efficiency_score_faster_than_ref_is_higher():
    # An iteration FASTER than the ref (smaller T, smaller C) yields a HIGHER E
    # (the incentive: less headcount / compute time is encouraged).
    slow = efficiency_score(1.0, 20.0, 200.0, 10.0, 100.0)  # E = 0.5
    fast = efficiency_score(1.0, 5.0, 50.0, 10.0, 100.0)
    # T/T_ref = 5/10 = 0.5; C/C_ref = 50/100 = 0.5; denom = 0.5; E = 1.0/0.5 = 2.
    assert fast == pytest.approx(2.0)
    assert fast > slow


def test_efficiency_score_zero_ref_guards():
    # A zero reference yields a ratio of 1.0 (guarded against division by
    # zero).
    # T/T_ref = 10/0 -> 1.0; C/C_ref = 100/0 -> 1.0; denom = 1.0; E = 1.0/1.0 = 1.
    assert efficiency_score(1.0, 10.0, 100.0, 0.0, 0.0) == pytest.approx(1.0)


# --- compute_m_satisfaction --------------------------------------------------

def test_m_satisfaction_terminal_with_criteria():
    # A terminal goal with success criteria: the base (verdict) is blended with
    # the coverage (the fraction of criteria with dispatched work).
    mission = {"success_criteria": ["a", "b", "c", "d"]}
    dispatch_results = [
        {"summary": "done a", "work_path": "w/a"},
        {"summary": "done b", "work_path": "w/b"},
        {"summary": "done c", "work_path": "w/c"},
    ]
    # verdict "complete" -> base 1.0; coverage = 3/4 = 0.75; sat = 0.5*1.0 +
    # 0.5*0.75 = 0.875.
    sat = compute_m_satisfaction(mission, dispatch_results, "complete")
    assert sat == pytest.approx(0.875)


def test_m_satisfaction_recurring_verdict_driven():
    # A recurring goal (no explicit success criteria): the verdict alone drives
    # the satisfaction (the verdict already reflects the cycle-target
    # attainment).
    assert compute_m_satisfaction(None, [], "complete") == pytest.approx(1.0)
    assert compute_m_satisfaction(None, [], "continue") == pytest.approx(0.5)
    assert compute_m_satisfaction(None, [], "escalate") == pytest.approx(0.2)


def test_m_satisfaction_clamped_to_unit_interval():
    # The result is clamped to [0, 1].
    assert 0.0 <= compute_m_satisfaction(None, [], "complete") <= 1.0
    assert 0.0 <= compute_m_satisfaction(None, [], "escalate") <= 1.0
    # A mission that is not a dict is handled (no criteria -> verdict-driven).
    assert compute_m_satisfaction("not a dict", [], "complete") == pytest.approx(1.0)


# --- EFFICIENCY_FLOOR trigger ------------------------------------------------

def test_efficiency_floor_trigger_below_floor(tmp_path):
    # A meter with a HIGH floor: an iteration with a LOW E is below the floor.
    meter = EfficiencyMeter(history_dir=str(tmp_path), floor=0.9)
    meter.start_iteration()
    meter.record_phase(4, 0.0, 10.0)
    meter.record_headcount(3, 10.0)
    # M_satisfaction 0.2, first iteration -> E = 0.2 (neutral baseline).
    snap = meter.finish_iteration(0.2)
    assert snap["E"] == pytest.approx(0.2)
    assert snap["below_floor"] is True
    assert snap["EFFICIENCY_FLOOR"] == pytest.approx(0.9)


def test_efficiency_floor_default_is_about_point_four():
    # The default floor is ~0.4 (the .env / config knob `efficiency_floor`).
    assert EFFICIENCY_FLOOR == pytest.approx(0.4)


def test_panel_text_includes_breakdown_and_mandate(tmp_path):
    meter = EfficiencyMeter(history_dir=str(tmp_path))
    meter.start_iteration()
    meter.record_phase(4, 0.0, 10.0)
    meter.record_headcount(3, 10.0)
    meter.finish_iteration(0.5)
    text = meter.panel_text()
    # The breakdown (T_total, H_peak, C) + E + the mandate are present.
    assert "T_total=" in text
    assert "H_peak=" in text
    assert "E=" in text
    assert "MANDATE" in text


# --- run_automation ----------------------------------------------------------

def _automation_org(tmp_path):
    from roles.leader import make_leader
    from runtime.org import OrgState
    from roles.base import Role
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    org.add_role(leader)
    # A department head (the automation IC reports to the leader, but a head
    # must exist for the org to be coherent).
    head = Role(id="head_analytics", architype="department_head",
                department="analytics", sub_architype="head_of_analytics")
    org.add_role(head)
    return org, leader


class _FakeBackend:
    """A minimal backend: returns a fixed dict with a `script` (the automation
    IC's output)."""

    def __init__(self):
        self.invoked = []

    def invoke(self, role, context, *args, **kwargs):
        self.invoked.append((role.id, context))
        return {"script": "print('recurring task done')\n", "summary": "ok"}


def test_run_automation_writes_script_and_fires_ic(tmp_path):
    from runtime.dispatch import run_automation
    org, leader = _automation_org(tmp_path)
    backend = _FakeBackend()
    # A 3-arg approver that approves the hire + the fire.
    approver_fn = lambda approver_type, action, target: {
        "decision": "approve", "rationale": "ok"}
    eff = {"action": "automate", "task": "send daily report",
           "reasoning": "recurring"}
    result = run_automation(org, leader, eff, backend, approver_fn, None,
                            script_dir=str(tmp_path))
    # The script is created (written to a file).
    assert result["script_path"].endswith(".py")
    assert os.path.isfile(result["script_path"])
    with open(result["script_path"], "r", encoding="utf-8") as f:
        assert "recurring task done" in f.read()
    # The IC was invoked to write the script.
    assert any(ic_id.startswith("auto-") for ic_id, _ in backend.invoked)
    # The IC is fired (the recurring task is now done by executing the script).
    fired_ids = [e["target"] for e in org.events if e["kind"] == "fired"]
    assert any(ic_id.startswith("auto-") for ic_id in fired_ids)
    # The automation is logged visibly (never silent).
    assert any(e["kind"] == "automation_script_created" for e in org.events)
    assert any(e["kind"] == "automation_active" for e in org.events)


def test_run_automation_slug():
    from runtime.dispatch import _automation_slug
    # Non-alphanumeric chars become dashes; consecutive dashes collapse.
    assert _automation_slug("Send Daily Report!") == "send-daily-report"
    assert _automation_slug("  a__b  c  ") == "a-b-c"
    # An empty task yields a fallback slug.
    assert _automation_slug("") == "task"
