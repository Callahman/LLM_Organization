"""The session runtime — run finalization.

``finalize_run`` is the tail of ``Session.run``: it runs the rolling-window
maintenance (Epic 7 — old sessions move to the archives; the audit path
stays resolvable), persists each role's memory (pruning stale fired roles'
memories — Story 11, B8) + the org chart (so a ``--revisit`` run loads it),
and builds the final ``SessionResult``.

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there).
"""

from __future__ import annotations

from typing import Any, Dict, List


def finalize_run(
    session,
    memory_dir: str,
    org_chart_path: str,
    status: str,
    intake,
    mission,
    dispatch_results: List[Dict[str, Any]],
    verdict: str,
    evaluation: Dict[str, Any],
):
    """Finalize the run and return the ``SessionResult``."""
    from runtime.session import SessionResult  # lazy (avoids a cycle)
    # Rolling window + archive cap (Epic 7): old sessions move to the
    # archives; the audit path stays resolvable.
    session.history.maintain()

    # Persist each role's memory (so it carries into the next run) and the
    # org chart (so a --revisit run loads it).
    # Story 11 (B8): prune stale (fired) roles' memories before saving —
    # only the active role ids (the current org's role ids + the leader)
    # are persisted.
    session.backend.save_state(memory_dir,
                               active_role_ids=session._active_role_ids())
    session.org.save(org_chart_path)

    return SessionResult(
        status=status,
        phases=list(session.phases),
        intake=intake,
        mission=mission,
        dispatch_results=dispatch_results,
        pods=list(session.pods),
        verdict=verdict,
        evaluation=evaluation,
        cycles=session.cycles,
    )


__all__ = ["finalize_run"]
