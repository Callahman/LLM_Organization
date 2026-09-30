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

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

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
    args = parser.parse_args()

    user_answer_fn, user_permission_fn, approver_fn = (
        _interactive_callbacks() if args.interactive
        else _unattended_callbacks()
    )

    session = Session(
        backend=make_backend(),
        leader=make_leader(),
        config={"timeout_seconds": 300},
    )

    mode = "interactive" if args.interactive else "unattended"
    print(f"Running the Organization pipeline ({mode})...")
    result = session.run(
        initial_prompt="Build a small ETL pipeline for our analytics team.",
        user_answer_fn=user_answer_fn,
        user_permission_fn=user_permission_fn,
        approver_fn=approver_fn,
        max_iterations=2,
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
