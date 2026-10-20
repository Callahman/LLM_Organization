"""Story 9 — **Intake (Phase 1) + Mission (Phase 2) largely unchanged**.

The Phase 1 (intake clarifying Q&A) + Phase 2 (mission codification +
permission) flow is preserved. The key invariant this file checks:

- Phase 1 (Intake) writes the **INFORMAL** mission draft to ``state/``
  (``state/mission_draft.md``) — NOT the top-level ``MISSION.md``;
- Phase 2 (Mission) writes the **FORMAL**, version-controlled ``MISSION.md``
  (on user approval).

So the informal draft and the formal mission are **distinct** files (the
intake never touches ``MISSION.md``; the mission is what the org abides by).

Driven with a ``StubBackend`` (offline).
"""

from __future__ import annotations

import os

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.intake import IntakeResult, run_intake
from runtime.mission import run_mission


def _clear_intake_script():
    """A leader that converges on a clear prompt in one round (no questions)."""
    return [{"summary": "clear", "questions": [], "confidence": 0.9,
             "restated_goal": "build a data pipeline that produces a weekly report"}]


def _run_intake(tmp, initial_prompt="build a data pipeline that produces a weekly report"):
    backend = StubBackend()
    backend.set_script("leader", _clear_intake_script())
    state_dir = os.path.join(str(tmp), "state")
    mission_path = os.path.join(str(tmp), "MISSION.md")
    return run_intake(
        backend,
        make_leader(),
        initial_prompt,
        user_answer_fn=lambda qs: "",
        confidence_threshold=0.8,
        question_budget=5,
        history_dir=str(tmp),
        mission_path=mission_path,
        state_dir=state_dir,
    ), state_dir, mission_path


# --- Phase 1: the INFORMAL draft goes to state/ (NOT MISSION.md) -------------

def test_intake_saves_informal_draft_to_state(tmp_path):
    # Phase 1 writes the informal draft to state/mission_draft.md (the
    # IntakeResult carries its text + path).
    result, state_dir, _ = _run_intake(tmp_path)
    assert result.informal_draft_path is not None
    assert os.path.exists(result.informal_draft_path)
    # It lives under state/ (not the repo root / not MISSION.md).
    assert os.path.dirname(result.informal_draft_path) == state_dir
    assert os.path.basename(result.informal_draft_path) == "mission_draft.md"
    # The draft content is the informal Phase 1 understanding.
    content = open(result.informal_draft_path, encoding="utf-8").read()
    assert "informal" in content
    assert "build a data pipeline that produces a weekly report" in content


def test_intake_does_not_write_formal_mission_md(tmp_path):
    # Phase 1 does NOT create the top-level MISSION.md (that is Phase 2's
    # formal, version-controlled write).
    result, _, mission_path = _run_intake(tmp_path)
    # The informal draft was written (to state/).
    assert os.path.exists(result.informal_draft_path)
    # But the formal MISSION.md was NOT created by intake.
    assert not os.path.exists(mission_path)


# --- Phase 2: the FORMAL MISSION.md is written on approval -------------------

def _intake_result():
    return IntakeResult(confident=True, converged=True, rounds=1, confidence=0.9)


def _draft():
    return {"purpose": "build a weekly report",
            "success_criteria": "accurate",
            "scope": "data pipeline"}


def test_mission_writes_formal_mission_md(tmp_path):
    # Phase 2 writes the formal, version-controlled MISSION.md on user
    # approval (the version is in the content).
    backend = StubBackend()
    backend.set_script("leader", [{"summary": "draft", "mission_draft": _draft()}])
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    result = run_mission(
        backend,
        make_leader(),
        _intake_result(),
        user_permission_fn=lambda draft: {"decision": "approve", "feedback": ""},
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=1,
    )
    assert result.approved
    assert os.path.exists(mission_path)
    content = open(mission_path, encoding="utf-8").read()
    assert "v1" in content
    assert "build a weekly report" in content


def test_mission_rejection_writes_no_mission_md(tmp_path):
    # A rejected draft writes NO MISSION.md (the formal mission is only written
    # on approval — the permission flow is honored).
    backend = StubBackend()
    backend.set_script("leader", [{"summary": "draft", "mission_draft": _draft()}])
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    result = run_mission(
        backend,
        make_leader(),
        _intake_result(),
        user_permission_fn=lambda draft: {"decision": "reject", "feedback": "wrong"},
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=1,
    )
    assert not result.approved
    assert not os.path.exists(mission_path)


# --- The informal draft and the formal mission are DISTINCT ------------------

def test_informal_draft_and_formal_mission_are_distinct(tmp_path):
    # The informal draft (state/mission_draft.md, Phase 1) and the formal
    # MISSION.md (Phase 2) are distinct files with distinct content.
    result, state_dir, mission_path = _run_intake(tmp_path)
    # Phase 2 then writes the formal MISSION.md.
    backend = StubBackend()
    backend.set_script("leader", [{"summary": "draft", "mission_draft": _draft()}])
    run_mission(
        backend,
        make_leader(),
        _intake_result(),
        user_permission_fn=lambda draft: {"decision": "approve", "feedback": ""},
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=1,
    )
    # Both files exist and are at distinct paths.
    assert os.path.exists(result.informal_draft_path)
    assert os.path.exists(mission_path)
    assert os.path.abspath(result.informal_draft_path) != os.path.abspath(mission_path)
    # The informal draft is marked informal; the formal mission carries a
    # version (they are different artifacts).
    informal = open(result.informal_draft_path, encoding="utf-8").read()
    formal = open(mission_path, encoding="utf-8").read()
    assert "informal" in informal
    assert "v1" in formal


# --- The Phase 1 + Phase 2 flow is intact (largely unchanged) ----------------

def test_intake_and_mission_entry_points_intact():
    # The public entry points + result types of Phase 1 + Phase 2 are intact
    # (the flow is preserved, not restructured away).
    assert callable(run_intake)
    assert callable(run_mission)
    assert hasattr(IntakeResult, "informal_draft")
    assert hasattr(IntakeResult, "informal_draft_path")
