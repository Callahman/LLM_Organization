"""Unit tests for `runtime/intake.py` — the Phase 1 clarifying Q&A loop
(Epic 1 Definition of Done).

A hand-run intake on a deliberately vague prompt asks sensible questions,
converges (or marks assumptions), and writes the audit trail; a clear prompt
short-circuits to Phase 2 with few/no questions.
"""

import os

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.intake import run_intake


def _approve_script():
    return {"summary": "ok", "findings": [], "recommendation": "", "confidence": 0.9}


def test_vague_prompt_converges(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    # Round 1: not confident, asks a question.
    # Round 2: not confident, asks a question.
    # Round 3: confident (converged).
    backend.set_script("leader", [
        {"summary": "need more info", "questions": ["What is the output?"], "confidence": 0.4},
        {"summary": "narrowing", "questions": ["What is the success criterion?"], "confidence": 0.6},
        {"summary": "understood", "questions": [], "confidence": 0.9},
    ])

    answers = iter(["a weekly report", "it must be accurate"])
    result = run_intake(
        backend,
        leader,
        "build a thing",
        user_answer_fn=lambda qs: next(answers),
        confidence_threshold=0.8,
        question_budget=5,
        history_dir=str(tmp_path),
    )
    assert result.converged
    assert result.confident
    assert result.rounds == 3
    # The audit trail was written.
    assert os.path.exists(os.path.join(str(tmp_path), "intake.jsonl"))


def test_clear_prompt_short_circuits(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    # Round 1: confident immediately (no questions).
    backend.set_script("leader", [
        {"summary": "clear", "questions": [], "confidence": 0.9},
    ])
    result = run_intake(
        backend,
        leader,
        "build a data pipeline that produces a weekly report",
        user_answer_fn=lambda qs: "",
        confidence_threshold=0.8,
        question_budget=5,
        history_dir=str(tmp_path),
    )
    assert result.converged
    assert result.rounds == 1


def test_budget_exhaustion_marks_assumptions(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    # Never reaches threshold within the budget: keeps asking questions.
    backend.set_script("leader", [
        {"summary": "?", "questions": ["q1?"], "confidence": 0.3},
        {"summary": "?", "questions": ["q2?"], "confidence": 0.4},
        {"summary": "?", "questions": ["q3?"], "confidence": 0.5},
        # After the budget, the Leader marks assumptions.
        {"summary": "best guess", "questions": [], "confidence": 0.55,
         "assumptions": ["assume weekly cadence", "assume accuracy = 95%"]},
    ])
    result = run_intake(
        backend,
        leader,
        "build a thing",
        user_answer_fn=lambda qs: "a",
        confidence_threshold=0.8,
        question_budget=3,
        history_dir=str(tmp_path),
    )
    assert not result.converged
    assert not result.confident
    assert result.rounds == 3
    assert "assume weekly cadence" in result.assumptions
    assert os.path.exists(os.path.join(str(tmp_path), "intake.jsonl"))
