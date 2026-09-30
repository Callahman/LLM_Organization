"""Run the Organization pipeline against the configured LLM backend.

Loads the backend from the environment (``.env``): ``LLM_BACKEND=stub``
(default) runs offline; ``LLM_BACKEND=api`` runs against the configured
OpenAI-compatible endpoint (e.g. KoboldCpp). The user callbacks auto-answer /
auto-approve for an unattended run; swap them for ``input()`` to go interactive.
"""

from __future__ import annotations

try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

from runtime.llm_api import make_backend
from runtime.session import Session
from roles.leader import make_leader


def main() -> None:
    session = Session(
        backend=make_backend(),
        leader=make_leader(),
        config={"timeout_seconds": 300},
    )

    result = session.run(
        initial_prompt="Build a small ETL pipeline for our analytics team.",
        # Unattended: auto-answer / auto-approve (swap for input() to go interactive).
        user_answer_fn=lambda qs: "Proceed with reasonable assumptions.",
        user_permission_fn=lambda d: {"decision": "approve", "feedback": ""},
        approver_fn=lambda a, act, r: {"decision": "approve", "rationale": "auto"},
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
