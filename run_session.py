"""Run the Organization pipeline against the configured LLM backend.

Loads the backend from the environment (``.env``): ``LLM_BACKEND=stub``
runs offline; ``LLM_BACKEND=api`` (the shipped default) runs against the
configured OpenAI-compatible endpoint (e.g. KoboldCpp).

By default the run is **unattended**: the user callbacks auto-answer the
Leader's clarifying questions and auto-approve the mission (a bounded smoke
run). Pass ``--interactive`` to instead prompt you at the two user-facing
gates — the intake clarifying Q&A and the mission approval — so you can
watch and steer the Leader.
"""

from __future__ import annotations

import argparse
import json
import os

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

from runtime.config import load_config
from runtime.llm_api import make_backend
from runtime.session import Session
from roles.leader import make_leader


def _unattended_callbacks():
    """Auto-answer / auto-approve (a bounded, unattended smoke run)."""
    return (
        lambda qs: "Proceed with reasonable assumptions.",
        lambda d: {"decision": "approve", "feedback": ""},
        lambda a, act, r: {"decision": "approve", "rationale": "auto"},
    )


def _interactive_callbacks():
    """Prompt the user at the two user-facing gates: the intake clarifying
    Q&A and the mission approval. HR resourcing (hire/fire) is internal and
    auto-approved (watch it on the dashboard's org events)."""
    from runtime.mission import _render_mission

    def user_answer_fn(questions):
        print("\n" + "=" * 64)
        print("LEADER'S CLARIFYING QUESTIONS (intake)")
        for i, q in enumerate(questions, 1):
            print(f"  {i}. {q}")
        print("=" * 64)
        answer = input("Your answer (Enter = proceed with assumptions): ").strip()
        return answer or "Proceed with reasonable assumptions."

    def user_permission_fn(draft):
        print("\n" + "=" * 64)
        print("PROPOSED MISSION.md DRAFT")
        print("-" * 64)
        print(_render_mission(draft, version=0))
        print("=" * 64)
        while True:
            choice = input("Approve this mission? [y]es / [n]o: ").strip().lower()
            if choice in ("y", "yes"):
                return {"decision": "approve", "feedback": ""}
            if choice in ("n", "no"):
                fb = input("Feedback for the Leader (Enter = none): ").strip()
                return {"decision": "reject", "feedback": fb}
            print("Please answer y or n.")

    def approver_fn(approver_type, action, role):
        return {"decision": "approve", "rationale": "auto-approved (interactive)"}

    return user_answer_fn, user_permission_fn, approver_fn


def _decide_run_mode(args, mission_path, checkpoint_path):
    """S15/S16: decide the run mode (fresh vs revisit) + the resume point.

    The default mode is **revisit** (S15: ``run_session.py`` defaults to
    ``--revisit`` when no mode flag is given). Returns
    ``(mode, resume_point, resume_from_phase)`` where:

    - ``mode`` is ``"fresh"`` or ``"revisit"``.
    - ``resume_point`` is a string describing where the run starts (for the
      visible log).
    - ``resume_from_phase`` is the phase to start from (1 for a fresh run or a
      revisit with no checkpoint; 4 for a revisit from a checkpoint at phase 3
      or 4, which skips Phases 1-3).

    Precedence:
    1. ``--fresh`` (explicit) -> fresh.
    2. ``MISSION.md`` absent -> fresh (S16: clear the environment).
    3. ``checkpoint.json`` present -> revisit from the checkpointed phase/cycle.
    4. no checkpoint -> revisit from the last phase (re-clarify from Phase 1).
    """
    if getattr(args, "fresh", False):
        return "fresh", "Phase 1 (fresh, --forced)", 1
    if not os.path.exists(mission_path):
        return "fresh", "Phase 1 (fresh, no MISSION.md)", 1
    if os.path.exists(checkpoint_path):
        cp_phase, cp_cycle = 3, 0
        try:
            with open(checkpoint_path, encoding="utf-8") as f:
                cp = json.load(f)
            cp_phase, cp_cycle = cp.get("phase", 3), cp.get("cycle", 0)
        except (OSError, ValueError):
            pass
        # A checkpoint at phase 3 or 4 -> resume from Phase 4 (skip Phases
        # 1-3; the org + mission are loaded, the dispatch continues).
        resume_from_phase = 4 if cp_phase >= 3 else cp_phase + 1
        return ("revisit",
                f"checkpoint phase {cp_phase}, cycle {cp_cycle}",
                resume_from_phase)
    return ("revisit",
            "last phase (no checkpoint, re-clarify from Phase 1)", 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Organization pipeline.")
    parser.add_argument(
        "--interactive", action="store_true",
        help="prompt for the Leader's clarifying answers and the mission "
             "approval (default: unattended auto-answer / auto-approve).")
    parser.add_argument(
        "--revisit", action="store_true",
        help="revisit the current mission: re-clarify the goal (Phase 1), "
             "continue the mission version (Phase 2), bootstrap additively "
             "(Phase 3), and re-save the org chart. Roles remember prior "
             "runs (their memory is loaded from / saved to disk). This is the "
             "DEFAULT mode (S15) — it resumes the current mission from the "
             "last checkpoint / last phase.")
    parser.add_argument(
        "--fresh", action="store_true",
        help="S15: force a FRESH run (clear the generated state first, then "
             "start from Phase 1) — overrides the default --revisit mode. Use "
             "this to start a brand-new mission.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="D7: preview what a run would do without mutating the org's "
              "state — the run's audit trail (history/, departments/, state/, "
              "MISSION.md, pods/) is written to a throwaway temp dir instead, "
              "so the real org is left untouched. The pipeline still runs "
              "end-to-end (you see the hires / mission draft / phases).")
    args = parser.parse_args()

    user_answer_fn, user_permission_fn, approver_fn = (
        _interactive_callbacks() if args.interactive
        else _unattended_callbacks()
    )

    # Timeouts are config-driven (not hardcoded). The PRIMARY bound is the
    # backend's progress-based idle timeout (LLM_IDLE_TIMEOUT_SECONDS, default
    # 180s in runtime/llm_api.py): it fails only when the model STOPS emitting
    # chunks (a hang), so a long-but-active think never trips it. The wall-
    # clock here (`timeout_seconds` / `ic_timeout_seconds`) is now just a large
    # safety-net BACKSTOP (default 3600s) — it only catches what the idle bound
    # misses (e.g. a connection stuck before any chunk, or the offline stub,
    # which has no idle bound at all). All can be overridden via the
    # environment (LLM_TIMEOUT_SECONDS / LLM_IC_TIMEOUT_SECONDS) without
    # touching this file.
    # D1: the config is loaded centrally (runtime/config.py) — every .env
    # org-tuning knob is mapped to its Session config key (with the right
    # cast), so a knob like CONFIDENCE_THRESHOLD actually changes behavior
    # (before, only the two timeout backstops were passed and the rest used
    # hardcoded defaults). Unknown/unused .env keys produce a visible warning.
    config = load_config()
    # D7: --dry-run previews a run without mutating the real org — the pipeline
    # runs end-to-end, but its state (history/, departments/, state/,
    # MISSION.md, pods/) is written to a throwaway temp dir instead. The
    # pipeline's paths are relative to the CWD, so chdir'ing to a temp dir
    # redirects every write.
    dry_run_dir = None
    if args.dry_run:
        import tempfile
        dry_run_dir = tempfile.mkdtemp(prefix="org_dry_run_")
        os.chdir(dry_run_dir)
        print(f"[dry-run] previewing in a throwaway dir: {dry_run_dir} "
              f"(the real org is left untouched)")

    # S15/S16: decide the run mode (fresh vs revisit) + the resume point. The
    # default mode is revisit (S15: run_session.py defaults to --revisit when
    # no mode flag is given).
    mission_path = config.get("mission_path", "MISSION.md")
    checkpoint_path = config.get("checkpoint_path", "state/checkpoint.json")
    run_mode, resume_point, resume_from_phase = _decide_run_mode(
        args, mission_path, checkpoint_path)
    print(f"[run-mode] mode={run_mode}, resume from: {resume_point}, "
          f"resume_from_phase={resume_from_phase}")

    # S16: a fresh run clears the generated state first (visible, never
    # silent) — the same wipe logic as `reset_org --yes`, so a run with no
    # MISSION.md starts from a clean slate.
    if run_mode == "fresh":
        import reset_org
        print("[run-mode] fresh run — clearing the generated state first...")
        reset_org.wipe_state(verbose=True)

    session = Session(
        backend=make_backend(),
        leader=make_leader(),
        config=config,
    )

    mode = "interactive" if args.interactive else "unattended"
    if run_mode == "revisit":
        print("Revisiting the current mission (roles remember prior runs)...")
    else:
        print(f"Running the Organization pipeline ({mode})...")
    result = session.run(
        initial_prompt="",  # blank: Phase 1 starts from the Leader's role info
        user_answer_fn=user_answer_fn,
        user_permission_fn=user_permission_fn,
        approver_fn=approver_fn,
        # D6: the Phase 4/5 iteration cap is config-driven (MAX_ITERATIONS in
        # .env, default 2) — not hardcoded.
        max_iterations=config.get("max_iterations", 2),
        revisit=(run_mode == "revisit"),
        # S15: the resume-from phase (a revisit from a checkpoint at phase 3
        # or 4 skips Phases 1-3 and resumes from Phase 4).
        resume_from_phase=resume_from_phase,
    )

    print("=== Session complete ===")
    print(f"status:     {result.status}")
    print(f"phases:     {result.phases}")
    print(f"cycles:     {result.cycles}")
    print(f"verdict:    {result.verdict}")
    print(f"evaluation: {result.evaluation}")
    if result.escalation:
        print(f"escalation: {result.escalation}")


if __name__ == "__main__":
    main()
