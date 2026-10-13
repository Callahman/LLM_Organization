"""The session runtime — run setup + Phases 1-3 (intake, mission, bootstrap).

``setup_run`` is the setup portion of ``Session.run``: it reads the config
paths, surfaces a checkpoint left by a crashed run (Story 1, B4), loads each
role's persisted memory, and (for a ``revisit`` run) loads the saved org
chart + the current mission. ``run_phases_1_3`` runs Phases 1-3 **once**
(intake, mission, org bootstrap) — or, for a resume-from-checkpoint, skips
them (the org + mission are loaded) and resumes from Phase 4.

**Decomposition (Phase 5):** extracted from ``runtime/session.py`` (the
``Session`` class + facade stay there).
"""

from __future__ import annotations

import json
import os
import sys
import time

from runtime.intake import run_intake
from runtime.mission import run_mission, load_mission
from runtime.org import OrgState, bootstrap


def setup_run(session, revisit: bool):
    """The setup portion of ``Session.run``. Returns
    ``(memory_dir, org_chart_path, mission_path, checkpoint_path,
    start_version, current_mission)``."""
    memory_dir = session.config.get("memory_dir", "state/role_memory")
    org_chart_path = session.config.get("org_chart_path", "state/org_chart.json")
    mission_path = session.config.get("mission_path", "MISSION.md")
    checkpoint_path = session.config.get("checkpoint_path", "state/checkpoint.json")

    # Story 1 (B4, minimal): a checkpoint left by a crashed run is
    # discoverable — if one exists and this is not a revisit, surface it
    # (full resume-from-checkpoint is a follow-up). A corrupted checkpoint
    # is still surfaced (the phase/cycle read as "?").
    if not revisit and os.path.exists(checkpoint_path):
        cp_phase, cp_cycle = "?", "?"
        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                cp = json.load(f)
            cp_phase, cp_cycle = cp.get("phase", "?"), cp.get("cycle", "?")
        except (OSError, ValueError):
            pass
        print(
            f"[session] checkpoint found (phase {cp_phase}, cycle {cp_cycle}) "
            f"— re-run to resume",
            file=sys.stderr,
        )

    # Load each role's persisted memory (so roles remember prior runs).
    session.backend.load_state(memory_dir)

    # A revisit: load the saved org chart + the current mission.
    start_version = None
    current_mission = ""
    if revisit:
        loaded_org = OrgState.load(org_chart_path,
                                   history_dir=session.org.history_dir)
        for rid, role in loaded_org.roles.items():
            session.org.roles.setdefault(rid, role)
        session.org.role_definitions.update(loaded_org.role_definitions)
        start_version, current_mission = load_mission(mission_path)

    return (memory_dir, org_chart_path, mission_path, checkpoint_path,
            start_version, current_mission)


def run_phases_1_3(
    session,
    initial_prompt,
    user_answer_fn,
    user_permission_fn,
    approver_fn,
    revisit: bool,
    resume_from_phase: int,
    start_version,
    current_mission: str,
    mission_path: str,
):
    """Run Phases 1-3 **once** (intake, mission, org bootstrap). Returns
    ``(intake, mission, mission_draft, p3_started, p3_ended, escalated)``
    where ``escalated`` is a ``SessionResult`` if the mission was not
    approved (an early return), else ``None``. A resume-from-checkpoint
    (``resume_from_phase >= 4`` on a revisit) skips Phases 1-3."""
    # S15: a resume-from-checkpoint skips Phases 1-3 (the org + mission
    # are loaded in the revisit branch above) and resumes from Phase 4 —
    # the dispatch continues without re-deriving the intake / mission.
    if resume_from_phase >= 4 and revisit:
        print(
            f"[session] resuming from Phase 4 (skipping Phases 1-3; the "
            f"org + mission are loaded, the dispatch continues)",
            file=sys.stderr,
        )
        return None, None, current_mission, 0.0, 0.0, None

    # --- Phase 1: intake (once) ---
    intake = session._phase(1, 0, run_intake,
        session.backend, session.leader, initial_prompt, user_answer_fn,
        confidence_threshold=session.config.get("confidence_threshold", 0.8),
        question_budget=session.config.get("question_budget", 5),
        history_dir=session.org.history_dir,
        current_mission=current_mission,
        mission_path=mission_path,
    )
    session.phases.append(1)
    # Solo (P1): record the leader's intake so the dashboard can
    # watch it.
    session.solo.record("p1", "Phase 1: intake", 0, "intake",
                        {"summary": f"intake converged={intake.converged} "
                                    f"rounds={intake.rounds}",
                         "confidence": intake.confidence,
                         "converged": intake.converged,
                         "rounds": intake.rounds,
                         "assumptions": intake.assumptions})

    # --- Phase 2: mission (once) ---
    mission = session._phase(2, 0, run_mission,
        session.backend, session.leader, intake, user_permission_fn,
        history_dir=session.org.history_dir,
        reask_budget=session.config.get("mission_reask_budget", 3),
        start_version=start_version,
        current_mission=current_mission,
    )
    session.phases.append(2)
    # Solo (P2): record the leader's mission draft + approval.
    session.solo.record("p2", "Phase 2: mission", 0, "mission",
                        {"summary": f"mission approved={mission.approved} "
                                    f"version={mission.version} "
                                    f"attempts={mission.attempts}",
                         "approved": mission.approved,
                         "version": mission.version,
                         "attempts": mission.attempts,
                         "edits": len(mission.edits)})
    # A1: close the solo pod when the mission phase completes.
    session.solo.close("p2", f"mission approved={mission.approved}, "
                             f"v{mission.version}")
    if not mission.approved:
        return intake, mission, None, 0.0, 0.0, session._escalate(
            "mission not approved by the user", intake, mission)
    mission_draft = mission.edits[-1]["draft"]

    # --- Phase 3: org bootstrap (once) ---
    p3_started = time.time()
    session._phase(3, 0, bootstrap,
        session.org, session.backend, session.leader, mission, approver_fn,
        additive=revisit,
        bootstrap_timeout_seconds=session.config.get(
            "bootstrap_timeout_seconds",
            session.config.get("ic_timeout_seconds")))
    p3_ended = time.time()
    session.org.write_events()
    # Story 1 (B1): checkpoint after Phase 3 — a crash in Phase 4
    # loses at most the current iteration's hires, not the
    # bootstrapped org.
    session._checkpoint(3, 0)
    session.phases.append(3)
    # Solo (P3): record the leader's org-bootstrap.
    session.solo.record("p3", "Phase 3: org bootstrap", 0, "bootstrap",
                        {"summary": "org bootstrapped",
                         "departments": len(session.org.department_heads()),
                         "roles": len(session.org.roles)})
    # A1: close the solo pod when the bootstrap phase completes.
    session.solo.close("p3", "org bootstrapped")

    return intake, mission, mission_draft, p3_started, p3_ended, None


__all__ = ["setup_run", "run_phases_1_3"]
