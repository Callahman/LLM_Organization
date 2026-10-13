"""The session runtime — Phase 5 synthesis + Phase 6 evaluation.

The two LLM-decision methods that drive the self-improving loop: Phase 5
(``synthesis`` — the leader checks progress against the mission's success
criteria and assesses whether the deliverable can be improved, producing a
complete / continue / escalate verdict) and Phase 6 (``evaluate`` — the
bounded continue/complete decision that re-enters Phase 1 with the
evaluation as input, still abiding by the original goal).

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there; ``Session._synthesis`` /
``Session._evaluate`` keep thin delegations to these functions).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from runtime.complexity import classify_complexity


def synthesis(session) -> str:
    """Phase 5: the leader checks progress against the mission's success
    criteria AND assesses whether the deliverable can be IMPROVED (more
    polished, more fun, more features, better quality). Do NOT stop at the
    first working version — the goal is a polished deliverable, not just a
    working one. Produces a verdict: complete (genuinely polished, stop) /
    continue (can improve, keep iterating) / escalate."""
    ctx = (
        "PHASE 5: check progress against the mission's success criteria AND "
        "assess whether the deliverable can be IMPROVED (more polished, "
        "more fun, more features, better quality). Do NOT stop at the first "
        "working version — the goal is a polished deliverable, not just a "
        "working one. Produce a verdict: complete (genuinely polished, "
        "stop) / continue (can improve, keep iterating) / escalate."
    )
    # S22: include the efficiency breakdown + E + the mandate to keep E
    # high (the most recent finished iteration's metrics).
    eff_panel = session.efficiency.panel_text()
    if eff_panel:
        ctx += " " + eff_panel
    # Carry the pods' decisions up to the leader's synthesis (the second
    # carry-over path: the cross-team decisions the pods closed on).
    decisions = [
        f"[{p.id}] {p.decision}"
        for p in session.pods
        if getattr(p, "decision", "")
    ]
    if decisions:
        ctx += " POD DECISIONS: " + "; ".join(decisions)
    out = session.backend.invoke(session.leader, ctx,
                                 reasoning=classify_complexity(5, session.leader, {}),
                                 phase=5)
    # Solo (P5): record the leader's synthesis step so the dashboard can
    # watch it (one transcript file, growing per round). Story 2 (A6): the
    # thinking-budget remainder is included so the dashboard can show it.
    session.solo.record("p5", "Phase 5: synthesis", session.cycles,
                        "synthesis",
                        {**out, "thinking_budget_remaining":
                             session.thinking_budget.remaining,
                         # Story 3 (A4): the BAU halt state is observable —
                         # the dashboard can show an active halt.
                         "bau_active": session.bau_active(),
                         "bau_halt": session.bau_halt})
    # A1: close the solo pod when the synthesis phase completes.
    session.solo.close("p5", f"synthesis verdict={out.get('verdict', 'complete')}")
    return out.get("verdict", "complete")


def evaluate(
    session,
    intake,
    mission,
    dispatch_results: List[Dict[str, Any]],
    verdict: str,
    max_iterations: int,
) -> Tuple[Dict[str, Any], str]:
    """Phase 6: the bounded continue/complete decision. Returns
    ``(evaluation, status)`` where status is ``"continue"`` (re-enter the
    loop) or ``"complete"`` (stop) or ``"escalated"`` (a no-op cycle — zero
    work dispatched — surfaced as an escalation, never silent)."""
    dispatch_units = len(dispatch_results)
    evaluation = {
        "ts": f"cycle{session.cycles}",
        "outcome": verdict,
        "process": {
            "pods": len(session.pods),
            "dispatch_units": dispatch_units,
            "resourcing_events": len(session.org.events),
        },
        "improvement_actions": [
            "department heads update their policy markdowns",
            "role-catalog improvements proposed through HR",
            "leader updates the mission's working section (user permission)",
        ],
    }
    # A no-op cycle (zero work dispatched) must not masquerade as a clean
    # "complete" — surface it as an escalation so it is visible, never
    # silent.
    if dispatch_units == 0:
        evaluation["no_work"] = True
        evaluation["escalation_reason"] = (
            "Phase 4 dispatched zero work (no department objectives could "
            "be resolved to heads in the org) — the cycle did nothing."
        )
        session.history.write_evaluation_report(evaluation)
        session.history._append(
            "escalations.jsonl",
            {"phase": 6, "reason": evaluation["escalation_reason"],
             "cycle": session.cycles},
        )
        return evaluation, "escalated"
    session.history.write_evaluation_report(evaluation)
    # S22: include the efficiency breakdown + E + the mandate to keep E
    # high (the most recent finished iteration's metrics).
    p6_ctx = (
        "PHASE 6: decide whether to keep iterating. Bias toward 'continue' "
        "(keep improving the deliverable) unless it is genuinely polished. "
        "The goal is a high-quality deliverable, not just a working one. "
        "Choose 'complete' (stop) or 'continue' (another iteration, still "
        f"abiding by the original goal). Evaluation: {evaluation}"
    )
    eff_panel = session.efficiency.panel_text()
    if eff_panel:
        p6_ctx += " " + eff_panel
    out = session.backend.invoke(
        session.leader,
        p6_ctx,
        reasoning=classify_complexity(6, session.leader, {}),
        phase=6,
    )
    decision = out.get("verdict", "complete")
    # Solo (P6): record the leader's continue/complete decision so the
    # dashboard can watch it (one transcript file, growing per round).
    session.solo.record("p6", "Phase 6: evaluation", session.cycles,
                        "decision", out)
    # A1: close the solo pod when the evaluation phase completes.
    session.solo.close("p6", f"eval decision={decision}")
    if decision == "continue" and session.cycles < max_iterations:
        return evaluation, "continue"
    return evaluation, "complete"


__all__ = ["synthesis", "evaluate"]
