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
             "runs (their memory is loaded from / saved to disk).")
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
    session = Session(
        backend=make_backend(),
        leader=make_leader(),
        config=config,
    )

    mode = "interactive" if args.interactive else "unattended"
    if args.revisit:
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
        revisit=args.revisit,
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
