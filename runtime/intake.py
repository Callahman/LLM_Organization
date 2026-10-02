"""Phase 1 — Intake (clarifying Q&A loop).

The Leader reads an initial prompt, emits structured clarifying questions
(what/why for each), the user answers, and the Leader re-evaluates its
confidence (0-1). The loop runs until confidence >= threshold **or** the
question budget is exhausted; at budget exhaustion the Leader proceeds with
its best understanding, **explicitly marking assumptions**.

The trail of how the mission was understood is written to
`history/intake.jsonl`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.coerce import as_float, as_str_list


@dataclass
class IntakeResult:
    confident: bool
    converged: bool
    rounds: int
    confidence: float
    assumptions: List[str] = field(default_factory=list)
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    audit_path: Optional[str] = None


def _assemble_context(
    initial_prompt: str = "",
    transcript: Optional[List[Dict[str, Any]]] = None,
    current_mission: str = "",
) -> str:
    """Assemble the Leader's intake context.

    The **initial prompt** section is included only when a non-blank prompt is
    supplied (a fresh run starts from the Leader's role info + the intake
    rules — no ETL seed). The **current mission** section is included on a
    revisit (the goal may have changed — re-clarify). The running Q&A
    transcript is always appended (prior speakers' outputs in the new
    speaker's prompt).
    """
    parts: List[str] = []
    if initial_prompt and initial_prompt.strip():
        parts.append(f"INITIAL PROMPT:\n{initial_prompt}")
    if current_mission and current_mission.strip():
        parts.append(
            "CURRENT MISSION (the goal may have changed — re-clarify it):\n"
            + current_mission
        )
    parts.append(
        "INTAKE RULES:\n"
        "- Your FIRST question to the user must be \"What is the organization's "
        "goal?\" — establish the goal before any other clarifying question "
        "(scope, size, ownership, success criteria). Do not jump into scope or "
        "org-size clarifications until you understand the goal.\n"
        "- Only ask clarifying questions you genuinely need; when confident, "
        "stop."
    )
    if transcript:
        parts.append("Q&A SO FAR:")
        for entry in transcript:
            if entry.get("role") == "leader":
                qs = "; ".join(entry.get("questions", [])) or "(no questions)"
                parts.append(
                    f"  [leader, round {entry.get('round')}] confidence="
                    f"{entry.get('confidence'):.2f} questions: {qs}"
                )
            elif entry.get("role") == "user":
                parts.append(
                    f"  [user, round {entry.get('round')}] {entry.get('answer', '')}"
                )
    return "\n".join(parts)


def _write_audit(
    history_dir: str,
    initial_prompt: str,
    rounds: int,
    confidence: float,
    assumptions: List[str],
    transcript: List[Dict[str, Any]],
) -> str:
    os.makedirs(history_dir, exist_ok=True)
    path = os.path.join(history_dir, "intake.jsonl")
    record = {
        "phase": 1,
        "initial_prompt": initial_prompt,
        "rounds": rounds,
        "final_confidence": confidence,
        "assumptions": assumptions,
        "transcript": transcript,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def run_intake(
    backend: LLMBackend,
    leader: Role,
    initial_prompt: str,
    user_answer_fn: Callable[[List[str]], str],
    confidence_threshold: float = 0.8,
    question_budget: int = 5,
    history_dir: str = "history",
    current_mission: str = "",
    mission_path: str = "MISSION.md",
) -> IntakeResult:
    """Run the Phase 1 intake loop.

    `user_answer_fn(questions) -> str` supplies the user's answer to a round's
    clarifying questions (in tests, a scripted function).

    `mission_path` is the existing mission file (if any). When it does not
    exist, no goal has been established yet, so the intake opens with the
    hard-coded goal question and does not converge on the Leader's confidence
    alone (a high-confidence round-1 response must not short-circuit the goal
    question).
    """
    transcript: List[Dict[str, Any]] = []
    assumptions: List[str] = []
    confidence = 0.0
    rounds = 0
    converged = False

    # If no goal is established yet (no MISSION.md), the first question is the
    # hard-coded goal question (don't trust the Leader's confidence).
    goal_established = os.path.exists(mission_path)

    for r in range(1, question_budget + 1):
        rounds = r
        # If no goal is established yet, the first question is the hard-coded
        # goal question (don't invoke the Leader, don't converge).
        if not goal_established:
            questions = ["What is the organization's goal?"]
            goal_established = True
            transcript.append(
                {
                    "role": "leader",
                    "round": r,
                    "confidence": 0.0,
                    "questions": questions,
                }
            )
            answer = user_answer_fn(questions)
            transcript.append({"role": "user", "round": r, "answer": answer})
            continue
        ctx = _assemble_context(initial_prompt, transcript,
                                current_mission=current_mission)
        # Not converging and near the budget -> a deeper pass (thinking on).
        level = classify_complexity(
            1, leader,
            {"converging": confidence >= confidence_threshold,
             "budget_left": question_budget - r + 1},
        )
        out = backend.invoke(leader, ctx, reasoning=level)
        confidence = as_float(out.get("confidence", 0.0))
        questions = as_str_list(out.get("questions", []))
        transcript.append(
            {
                "role": "leader",
                "round": r,
                "confidence": confidence,
                "questions": questions,
            }
        )

        # Converged: confident enough (a clear prompt short-circuits here at
        # round 1 with no questions).
        if confidence >= confidence_threshold:
            converged = True
            break

        # No questions but not confident: the Leader marks assumptions and
        # stops asking.
        if not questions:
            assumptions = as_str_list(out.get("assumptions", []))
            break

        # Ask the user and continue.
        answer = user_answer_fn(questions)
        transcript.append({"role": "user", "round": r, "answer": answer})
    else:
        # Question budget exhausted: proceed with the best understanding,
        # explicitly marking assumptions.
        ctx = _assemble_context(initial_prompt, transcript,
                                current_mission=current_mission)
        # Final pass at budget exhaustion: complex if we never converged.
        level = classify_complexity(
            1, leader,
            {"converging": confidence >= confidence_threshold, "budget_left": 0},
        )
        out = backend.invoke(leader, ctx, reasoning=level)
        confidence = as_float(out.get("confidence", 0.0))
        assumptions = as_str_list(out.get("assumptions", []))
        transcript.append(
            {
                "role": "leader",
                "round": rounds + 1,
                "confidence": confidence,
                "assumptions": assumptions,
                "note": "question budget exhausted",
            }
        )

    audit_path = _write_audit(
        history_dir, initial_prompt, rounds, confidence, assumptions, transcript
    )

    return IntakeResult(
        confident=confidence >= confidence_threshold,
        converged=converged,
        rounds=rounds,
        confidence=confidence,
        assumptions=assumptions,
        transcript=transcript,
        audit_path=audit_path,
    )
