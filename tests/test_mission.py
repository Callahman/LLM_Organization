"""Unit tests for `runtime/mission.py` — mission codification + permission flow
(Epic 2 Definition of Done).

A draft is presented, a rejection is honored (no write), an approval writes v1
with the change log — and the runtime refuses any out-of-flow write to
`MISSION.md`.
"""

import os

from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.intake import IntakeResult
from runtime.mission import run_mission


def _intake():
    return IntakeResult(confident=True, converged=True, rounds=1, confidence=0.9)


def _draft():
    return {
        "purpose": "build a weekly report",
        "success_criteria": "accurate",
        "scope": "data pipeline",
        "non_goals": [],
        "constraints": [],
        "org_recommendation": [],
        "resource_envelope": "",
    }


def test_rejection_honored_no_write(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "draft", "mission_draft": _draft()},
        {"summary": "draft2", "mission_draft": _draft()},
    ])
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    # Rejected twice, then the budget is exhausted (no approval).
    decisions = iter([
        {"decision": "reject", "feedback": "scope too broad"},
        {"decision": "reject", "feedback": "missing success criteria"},
    ])
    result = run_mission(
        backend,
        leader,
        _intake(),
        user_permission_fn=lambda draft: next(decisions),
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=2,
    )
    assert not result.approved
    # No write happened (the file does not exist).
    assert not os.path.exists(mission_path)
    # The change log recorded the rejections.
    assert os.path.exists(os.path.join(str(tmp_path), "mission_edits.jsonl"))


def test_approval_writes_v1_with_change_log(tmp_path):
    leader = make_leader()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "draft", "mission_draft": _draft()},
        {"summary": "draft v2", "mission_draft": _draft()},
    ])
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    decisions = iter([
        {"decision": "reject", "feedback": "tighten scope"},
        {"decision": "approve", "feedback": ""},
    ])
    result = run_mission(
        backend,
        leader,
        _intake(),
        user_permission_fn=lambda draft: next(decisions),
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=3,
    )
    assert result.approved
    assert result.version == 2
    # The write happened with the version in the content.
    assert os.path.exists(mission_path)
    content = open(mission_path, encoding="utf-8").read()
    assert "v2" in content
    assert "build a weekly report" in content
    # The change log records both the rejection and the approval.
    log = open(os.path.join(str(tmp_path), "mission_edits.jsonl"), encoding="utf-8").read()
    assert "reject" in log
    assert "approve" in log


def test_mission_draft_string_tolerated(tmp_path):
    """The real LLM leader free-forms `mission_draft` as a **string** (not a
    dict) — the mission must degrade to rendering the string as the `purpose`
    (visible, never an AttributeError crash) — the Phase-2 'did nothing'
    regression."""
    leader = make_leader()
    backend = StubBackend()
    # The leader's mission_draft is a string (the model ignored the forced
    # schema).
    backend.set_script("leader", [
        {"summary": "draft",
         "mission_draft": "Develop a recurring-income business on the 4090."},
    ])
    mission_path = os.path.join(str(tmp_path), "MISSION.md")
    # The user approves the (string) draft — it must render as the purpose.
    result = run_mission(
        backend,
        leader,
        _intake(),
        user_permission_fn=lambda draft: {"decision": "approve", "feedback": ""},
        mission_path=mission_path,
        history_dir=str(tmp_path),
        reask_budget=1,
    )
    assert result.approved
    # The write happened; the string renders as the mission's purpose.
    assert os.path.exists(mission_path)
    content = open(mission_path, encoding="utf-8").read()
    assert "Develop a recurring-income business on the 4090." in content


def test_mission_draft_helper_tolerates_shapes():
    """_mission_draft() handles the shapes the real LLM free-forms: a dict
    (canonical), a string (collapsed to prose), and None/number (ignored)."""
    from runtime.mission import _mission_draft
    # Canonical: a dict.
    assert _mission_draft({"mission_draft": {"purpose": "x"}}) == {"purpose": "x"}
    # String: the model collapsed the draft to prose.
    assert _mission_draft({"mission_draft": "build the pipeline"}) == {"purpose": "build the pipeline"}
    # Whitespace-only string: degrades to an empty dict.
    assert _mission_draft({"mission_draft": "   "}) == {}
    # Missing: no mission_draft key.
    assert _mission_draft({}) == {}
    # Number: degrades to an empty dict.
    assert _mission_draft({"mission_draft": 5}) == {}


def test_no_out_of_flow_write_path(tmp_path):
    """The module exposes no public write function — the only write is inside
    `run_mission` on approval (enforced by construction)."""
    import runtime.mission as m
    public_writes = [
        name for name in dir(m)
        if name.startswith("write") and not name.startswith("_")
    ]
    assert public_writes == []
    # The write helper is private and only called inside run_mission.
    assert hasattr(m, "_write_mission")
