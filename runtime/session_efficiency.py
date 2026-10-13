"""The session runtime — S22 efficiency finishing + the floor trigger.

``finish_efficiency`` ends a loop iteration: it computes ``N_created`` (the
roles that became active this iteration) + ``M_satisfaction`` (0-1, terminal
+ recurring), then finishes the efficiency meter (compute ``E`` with the
running-average refs, append the per-iteration snapshot to the log). When
``E < EFFICIENCY_FLOOR``, ``efficiency_floor_action`` makes the Leader take a
visible efficiency action (fire / reassign / report / automate) via
``dispatch._process_efficiency`` / ``dispatch.run_automation``.

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there; ``Session._finish_efficiency`` /
``Session._efficiency_floor_action`` keep thin delegations to these
functions).
"""

from __future__ import annotations

from typing import Any, Dict

from runtime.efficiency import compute_m_satisfaction
from runtime.complexity import classify_complexity
from runtime import dispatch


def finish_efficiency(
    session,
    iter_start_ids,
    mission_draft,
    dispatch_results,
    verdict,
):
    """S22: finish the loop iteration — compute ``N_created`` (the roles
    that became active this iteration) + ``M_satisfaction`` (0-1, terminal
    + recurring), then finish the efficiency meter (compute ``E`` with the
    running-average refs, append the per-iteration snapshot to the log).
    When ``E < EFFICIENCY_FLOOR``, trigger a visible efficiency action."""
    # S22: N_created = the roles that became active this iteration.
    iter_end_ids = {r.id for r in session.org.active_roles()}
    n_created = len(iter_end_ids - iter_start_ids)
    session.efficiency.record_created(n_created)
    # S22: M_satisfaction (0-1, terminal + recurring).
    m_sat = compute_m_satisfaction(mission_draft, dispatch_results, verdict)
    # S22: finish the iteration (compute E, append to the log).
    snap = session.efficiency.finish_iteration(m_sat)
    # S22: when E < EFFICIENCY_FLOOR, the Leader must take a visible
    # efficiency action.
    if snap.get("below_floor"):
        efficiency_floor_action(session, snap)
    return snap


def efficiency_floor_action(session, snap):
    """S22: when ``E < EFFICIENCY_FLOOR``, the Leader must take a visible
    efficiency action. Invoke the Leader with the efficiency breakdown +
    the mandate, and process its ``efficiency`` action (fire / reassign /
    report / automate) via ``dispatch._process_efficiency`` (the automation
    action runs the IC-writes-script -> fired -> script-executed flow)."""
    ctx = (
        "PHASE 6 (efficiency floor): the efficiency score E is BELOW the "
        f"floor ({snap['E']:.3f} < {snap['EFFICIENCY_FLOOR']}). You MUST "
        "take a visible efficiency action to reduce headcount / compute "
        "time. "
        + session.efficiency.panel_text()
        + " Set `efficiency` to a JSON OBJECT with an `action` (\"fire\" "
        "to fire an inefficient role through HR — the firing cascades to "
        "its report subtree; \"reassign\" to move it to a different team, "
        "named in `new_team`; \"report\" to report the inefficiency to the "
        "user; \"automate\" to automate a recurring task, named in `task`) "
        "and a `target` (the role id or department slug) and a `reasoning`."
    )
    out = session.backend.invoke(
        session.leader, ctx,
        reasoning=classify_complexity(6, session.leader, {}),
        phase=6,
    )
    eff = out.get("efficiency")
    if isinstance(eff, dict):
        dispatch._process_efficiency(
            session.org, session.leader, eff, session._approver_fn, session.history)
        # S22: the automation action (IC writes a script -> fired ->
        # script executed).
        if eff.get("action") == "automate":
            dispatch.run_automation(
                session.org, session.leader, eff, session.backend,
                session._approver_fn, session.history)
    else:
        # No efficiency action set — log it visibly (never silent).
        session.org.log_event(
            "efficiency_floor_no_action", session.leader.id, None,
            {"E": snap["E"], "floor": snap["EFFICIENCY_FLOOR"]})


__all__ = ["finish_efficiency", "efficiency_floor_action"]
