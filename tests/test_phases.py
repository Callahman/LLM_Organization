"""the **8-phase structure** + the **bounded self-improving loop**.

The pipeline is 8 phases: 1 (intake) + 2 (mission) + 3 (org bootstrap) run
**once**, then 4 (plan) + 5 (staff) + 6 (execute) + 7 (evaluate) + 8 (decide)
**iterate** for up to ``max_iterations`` passes. The stop is **bounded** (the
iteration cap) **and goal-based** (the leader can stop early on a "complete"
verdict in Phase 8). This file tests:

- the 8-phase structure (every phase runs, in order);
- the cycle loop **repeating on "continue"** (Phase 8's "continue" re-enters
  Phase 4; the leader can stop early on "complete" — the goal-based stop);
- the cycle loop being **bounded by ``max_iterations``** (a leader that keeps
  saying "continue" still stops at the cap).

Driven with a ``StubBackend`` (offline).
"""

from __future__ import annotations

import os

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.session import Session


def _approve_fns():
    user_answer_fn = lambda qs: "a weekly report"
    user_permission_fn = lambda draft: {"decision": "approve", "feedback": ""}
    approver_fn = lambda approver, action, role: {"decision": "approve",
                                                  "rationale": "ok"}
    return user_answer_fn, user_permission_fn, approver_fn


def _leader_head_script():
    """The head's Phase 4 output (no managers/ICs — an empty team
    decomposition). The StubBackend reuses the last entry once the script is
    exhausted, so one entry covers every Phase 4 the head is invoked in."""
    return [{"decomposition": {"team_objectives": []}}]


def _phase123():
    """The leader's Phases 1-3 outputs (run once): intake (converge in one
    round), the mission draft (approved), the org recommendation (one
    department head)."""
    return [
        {"confidence": 0.9, "questions": []},  # Phase 1: converge in one round
        {"mission_draft": {"purpose": "a data pipeline",
                           "success_criteria": ["works"]}},  # Phase 2
        {"org_recommendation": {"department_heads": [
            {"id": "head_analytics", "department": "analytics"}]}},  # Phase 3
    ]


def _plan_verdict(verdict):
    """One iteration's leader outputs, in invoke order: Phase 4 (plan
    decomposition), the Phase 4 leader+head clarification pod (the leader is
    the starter: agenda + close), the Phase 7 head->leader reporting pod (the
    leader is the starter: agenda + close), Phase 7 (evaluate synthesis),
    Phase 8 (decide). The pod round counts are 0 (see the config), so each pod
    contributes exactly 2 leader invokes (agenda + close) and the flat
    per-role script stays aligned with the phase invokes."""
    return [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
        {},  # Phase 4: leader+head clarification pod — agenda (leader is the starter)
        {},  # Phase 4: leader+head clarification pod — close (leader is the starter)
        {},  # Phase 7: head->leader reporting pod — agenda (leader is the starter)
        {},  # Phase 7: head->leader reporting pod — close (leader is the starter)
        {"verdict": "complete"},  # Phase 7: evaluate (the leader's synthesis)
        {"verdict": verdict},  # Phase 8: decide
    ]


def _run(leader_script, max_iterations, tmp_path):
    backend = StubBackend()
    backend.set_script("leader", leader_script)
    backend.set_script("head_analytics", _leader_head_script())
    user_answer_fn, user_permission_fn, approver_fn = _approve_fns()
    # Every path the session writes (the mission, the state/, the org chart,
    # the checkpoint, the memory, the pod transcripts) is rooted in a fresh
    # temp dir — a run must never resume from a checkpoint left by a previous
    # test (the loop's iteration count is what this file asserts).
    state_dir = str(tmp_path / "state")
    config = {
        "mission_path": str(tmp_path / "MISSION.md"),
        "state_dir": state_dir,
        "org_chart_path": os.path.join(state_dir, "org_chart.json"),
        "memory_dir": os.path.join(state_dir, "role_memory"),
        "checkpoint_path": os.path.join(state_dir, "checkpoint.json"),
        "pod_transcripts_dir": str(tmp_path / "pods" / "transcripts"),
        # This file tests the cycle loop (Phases 4-8 repeating on "continue",
        # bounded by max_iterations), not the pods. The leader is the STARTER
        # of the Phase 4 leader+head clarification pod and the Phase 7
        # head->leader reporting pod, so each pod invokes the leader (agenda +
        # close). Capping the pod round counts at 0 makes each pod contribute
        # exactly 2 leader invokes, so the leader's flat per-role script stays
        # aligned with the phase invokes.
        "clarification_pod_rounds": 0,
        "reporting_pod_rounds": 0,
    }
    session = Session(backend, make_leader(), config=config,
                      history_dir=str(tmp_path))
    return session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        max_iterations=max_iterations,
    )


# --- The 8-phase structure ---------------------------------------------------

def test_all_eight_phases_run_in_order(tmp_path):
    # Every phase (1-8) runs, in order. Phases 1-3 run once; Phases 4-8 run
    # once per iteration (a one-iteration run: Phase 8 says "complete").
    leader_script = _phase123() + _plan_verdict("complete")
    result = _run(leader_script, max_iterations=3, tmp_path=tmp_path)
    assert result.status == "complete"
    # All eight phases ran.
    assert set(result.phases) == {1, 2, 3, 4, 5, 6, 7, 8}
    # Phases 1-3 ran once; Phases 4-8 ran once (a single iteration).
    assert result.phases[1] == 1
    assert result.phases[2] == 1
    assert result.phases[3] == 1
    assert result.phases[4] == 1
    assert result.phases[5] == 1
    assert result.phases[6] == 1
    assert result.phases[7] == 1
    assert result.phases[8] == 1


# --- The cycle loop: repeats on "continue" (the goal-based stop) -------------

def test_cycle_repeats_on_continue(tmp_path):
    # Phase 8's "continue" re-enters Phase 4 (the loop repeats). The leader
    # says "continue" on iteration 1 and "complete" on iteration 2 (it can stop
    # early on "complete" — the goal-based stop), so Phases 4-8 run twice (not
    # the full max_iterations=3 cap).
    leader_script = (_phase123()
                     + _plan_verdict("continue")  # iteration 1
                     + _plan_verdict("complete"))  # iteration 2 (stops early)
    result = _run(leader_script, max_iterations=3, tmp_path=tmp_path)
    assert result.status == "complete"
    # The loop repeated: Phases 4-8 ran twice (2 > 1).
    assert result.phases[4] == 2
    assert result.phases[5] == 2
    assert result.phases[6] == 2
    assert result.phases[7] == 2
    assert result.phases[8] == 2
    # Phases 1-3 ran once (they do not repeat).
    assert result.phases[1] == 1
    assert result.phases[2] == 1
    assert result.phases[3] == 1
    # It stopped early (2 iterations, not the 3-iteration cap).
    assert result.cycles == 2


# --- The cycle loop: bounded by max_iterations -------------------------------

def test_cycle_bounded_by_max_iterations(tmp_path):
    # A leader that keeps saying "continue" still stops at the cap — the loop
    # is bounded by max_iterations (Phases 4-8 run exactly max_iterations
    # times, never more). On the last iteration the bounded check forces a
    # "complete" regardless of the verdict.
    leader_script = (_phase123()
                     + _plan_verdict("continue")  # iteration 1
                     + _plan_verdict("continue")  # iteration 2
                     + _plan_verdict("continue"))  # iteration 3 (bounded stop)
    result = _run(leader_script, max_iterations=3, tmp_path=tmp_path)
    # The loop ran to the cap: Phases 4-8 ran exactly 3 times.
    assert result.phases[4] == 3
    assert result.phases[5] == 3
    assert result.phases[6] == 3
    assert result.phases[7] == 3
    assert result.phases[8] == 3
    assert result.cycles == 3
    # Phases 1-3 ran once.
    assert result.phases[1] == 1
    assert result.phases[2] == 1
    assert result.phases[3] == 1


def test_cycle_bounded_by_smaller_cap(tmp_path):
    # A smaller cap (max_iterations=2) bounds the loop at 2 iterations — even
    # with a leader that keeps saying "continue", Phases 4-8 run exactly twice.
    leader_script = (_phase123()
                     + _plan_verdict("continue")  # iteration 1
                     + _plan_verdict("continue"))  # iteration 2 (bounded stop)
    result = _run(leader_script, max_iterations=2, tmp_path=tmp_path)
    assert result.phases[4] == 2
    assert result.phases[5] == 2
    assert result.phases[6] == 2
    assert result.phases[7] == 2
    assert result.phases[8] == 2
    assert result.cycles == 2
