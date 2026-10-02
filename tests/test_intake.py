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

    # Round 1 is the hard-coded goal question (no MISSION.md exists); the
    # Leader then runs rounds 2-4 (converging at round 4). Use an isolated
    # mission path in tmp_path so the test does not depend on a leftover
    # MISSION.md in the repo root.
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    answers = iter(["build a thing", "a weekly report", "it must be accurate"])
    result = run_intake(
        backend,
        leader,
        "build a thing",
        user_answer_fn=lambda qs: next(answers),
        confidence_threshold=0.8,
        question_budget=5,
        history_dir=str(tmp_path),
        mission_path=mission_path,
    )
    assert result.converged
    assert result.confident
    assert result.rounds == 4
    # The audit trail was written.
    assert os.path.exists(os.path.join(str(tmp_path), "intake.jsonl"))


def test_clear_prompt_short_circuits(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    # Round 1: confident immediately (no questions).
    backend.set_script("leader", [
        {"summary": "clear", "questions": [], "confidence": 0.9},
    ])
    # Isolated mission path in tmp_path (does not exist -> hard-coded goal
    # question at round 1), so the test does not depend on the repo root.
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    result = run_intake(
        backend,
        leader,
        "build a data pipeline that produces a weekly report",
        user_answer_fn=lambda qs: "",
        confidence_threshold=0.8,
        question_budget=5,
        history_dir=str(tmp_path),
        mission_path=mission_path,
    )
    assert result.converged
    # Round 1 is the hard-coded goal question (no MISSION.md); the Leader
    # converges at round 2.
    assert result.rounds == 2


def test_budget_exhaustion_marks_assumptions(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    # Never reaches threshold within the budget: keeps asking questions.
    # Round 1 is the hard-coded goal question (no MISSION.md), so the Leader
    # gets rounds 2-3 (budget 3) to ask questions, then the budget-exhausted
    # pass marks assumptions.
    backend.set_script("leader", [
        {"summary": "?", "questions": ["q1?"], "confidence": 0.3},
        {"summary": "?", "questions": ["q2?"], "confidence": 0.4},
        # After the budget, the Leader marks assumptions.
        {"summary": "best guess", "questions": [], "confidence": 0.55,
         "assumptions": ["assume weekly cadence", "assume accuracy = 95%"]},
    ])
    # Isolated mission path in tmp_path (does not exist -> hard-coded goal
    # question at round 1), so the test does not depend on the repo root.
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    result = run_intake(
        backend,
        leader,
        "build a thing",
        user_answer_fn=lambda qs: "a",
        confidence_threshold=0.8,
        question_budget=3,
        history_dir=str(tmp_path),
        mission_path=mission_path,
    )
    assert not result.converged
    assert not result.confident
    assert result.rounds == 3
    assert "assume weekly cadence" in result.assumptions
    assert os.path.exists(os.path.join(str(tmp_path), "intake.jsonl"))
