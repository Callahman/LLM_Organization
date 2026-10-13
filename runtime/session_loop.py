"""The session runtime — the Phases 4-6 self-improving loop.

``run_phases_4_6`` is the ``for _ in range(max_iterations)`` loop body of
``Session.run``: each iteration runs Phase 4 (dispatch, which hires the
managers/ICs it decomposes onto and forms pods), checks for a
Safety/Morality halt (the only BAU halt — a global halt stops work, a
scoped halt continues non-blocked work), Phase 5 (synthesis), and Phase 6
(evaluation — the continue/complete decision). It checkpoints after each
iteration and finishes the S22 efficiency iteration. The stop is **bounded**
(the iteration cap) **and goal-based** (the leader can stop early on
'complete'); the original goal is still abided by on every pass.

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there).
"""

from __future__ import annotations

import sys

from runtime import dispatch


def run_phases_4_6(
    session,
    intake,
    mission,
    mission_draft,
    approver_fn,
    phase4_halt_fn,
    max_iterations: int,
    p3_started: float,
    p3_ended: float,
):
    """Run the Phases 4-6 loop. Returns
    ``(dispatch_results, verdict, evaluation, status, escalated)`` where
    ``escalated`` is a ``SessionResult`` if a global Safety/Morality halt
    stopped work (an early return), else ``None``."""
    dispatch_results = []
    verdict = ""
    evaluation = {}
    status = "complete"
    for _ in range(max_iterations):
        session.cycles += 1
        # S22: begin the loop iteration (reset the per-iteration
        # accumulators) and capture the active role ids (for N_created).
        session.efficiency.start_iteration()
        iter_start_ids = {r.id for r in session.org.active_roles()}
        if session.cycles == 1 and p3_ended > 0:
            # Phase 3 ran once before the loop — include its time +
            # headcount in the first iteration (S22: the Phase 3-6 loop
            # scope). The _phase() record of Phase 3 was wiped by
            # start_iteration, so re-record it.
            session.efficiency.record_phase(3, p3_started, p3_ended)
            session.efficiency.record_headcount(
                len(session.org.active_roles()), p3_ended - p3_started)

        # Phase 4: dispatch (hires the managers/ICs it decomposes onto).
        # Pods A/B/C form as an add-on; the formed pods accumulate in
        # `session.pods` so their decisions carry up to the leader's
        # Phase 5 synthesis.
        dispatch_results = session._phase(4, session.cycles, dispatch.dispatch,
            session.backend, session.org, session.leader, mission_draft,
            approver_fn=approver_fn,
            pods_out=session.pods,
            history=session.history,
            routing_rules=session.config.get("pod_routing_rules", []),
            artifacts_dir=session.config.get("pod_artifacts_dir", "pods/artifacts"),
            transcripts_dir=session.config.get("pod_transcripts_dir", "pods/transcripts"),
            ic_timeout_seconds=session.config.get("ic_timeout_seconds"),
            config=session.config,
            solo=session.solo,
            timing=session.timing,
        )
        session.phases.append(4)
        # Solo (P4): record the dispatch + the thinking-budget remainder so
        # the dashboard can show the budget (Story 2, A6).
        session.solo.record("p4", "Phase 4: dispatch", session.cycles, "dispatch",
                            {"dispatches": len(dispatch_results),
                             "thinking_budget_remaining":
                                 session.thinking_budget.remaining})

        # A Safety/Morality halt during Phase 4 (the only BAU halt).
        if phase4_halt_fn is not None:
            halt = phase4_halt_fn()
            if halt:
                session.halt_bau(halt["department"], halt["scope"], halt["reason"])
                session.queue_user_input({"kind": "safety_morality_halt", **halt})

        # Story 3 (A10/B12): a GLOBAL Safety/Morality halt stops work
        # before Phase 5 — the halt is CONSUMED, not just recorded
        # (`bau_active()` is False only for a global halt).
        if not session.bau_active():
            return (dispatch_results, verdict, evaluation, status,
                    session._escalate("safety/morality halt (global)",
                                      intake, mission))
        if session.bau_halt:
            # A SCOPED halt — do not stop; continue non-blocked work
            # (visible note; full per-department blocking is a follow-up).
            print(
                f"[session] scoped safety/morality halt in "
                f"{session.bau_halt.get('department')} — continuing "
                f"non-blocked work",
                file=sys.stderr,
            )

        # Phase 5: synthesis.
        verdict = session._phase(5, session.cycles, session._synthesis)
        session.phases.append(5)

        # Story 3 (B12): the same check before Phase 6 — a global halt
        # does not run the continue/complete decision.
        if not session.bau_active():
            return (dispatch_results, verdict, evaluation, status,
                    session._escalate("safety/morality halt (global)",
                                      intake, mission))

        # Phase 6: evaluation (decides continue / stop).
        evaluation, status = session._phase(6, session.cycles, session._evaluate,
            intake, mission, dispatch_results, verdict, max_iterations
        )
        session.phases.append(6)

        # Story 1 (B1): checkpoint after each Phase 4 iteration — a crash
        # in the NEXT iteration loses at most that iteration's hires.
        session._checkpoint(4, session.cycles)

        # S22: finish the iteration — compute M_satisfaction + E, append
        # the per-iteration snapshot to the log, and handle the
        # EFFICIENCY_FLOOR trigger (a visible efficiency action when
        # E < floor).
        session._finish_efficiency(
            iter_start_ids, mission_draft, dispatch_results, verdict)

        if status != "continue":
            break

    return dispatch_results, verdict, evaluation, status, None


__all__ = ["run_phases_4_6"]
