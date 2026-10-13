"""The session runtime — escalation on repeated failure / non-convergence.

``escalate`` builds a structured diagnosis (the phase reached, the reason,
the intake confidence, the mission approval), appends it to
``history/escalations.jsonl``, runs the rolling-window maintenance (the
session is ending), and returns an ``escalated`` ``SessionResult``.

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there; ``Session._escalate`` keeps a thin
delegation to this function).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def escalate(
    session,
    reason: str,
    intake,
    mission,
) -> "Any":
    """Escalate to the user with a structured diagnosis. Returns an
    ``escalated`` ``SessionResult`` (the session ends)."""
    from runtime.session import SessionResult  # lazy (avoids a cycle)
    diagnosis = {
        "phase": session.phases[-1] if session.phases else None,
        "reason": reason,
        "intake_confidence": intake.confidence if intake else None,
        "mission_approved": mission.approved if mission else None,
    }
    session.history._append("escalations.jsonl", diagnosis)
    # Rolling window + archive cap (Epic 7) — the session is ending.
    session.history.maintain()
    return SessionResult(
        status="escalated",
        phases=list(session.phases),
        intake=intake,
        mission=mission,
        verdict="escalate",
        cycles=session.cycles,
        escalation=diagnosis,
    )


__all__ = ["escalate"]
