"""Phase 2 — Mission codification + permission flow.

The Leader drafts `MISSION.md` (purpose, scope, non-goals, success criteria,
constraints, org recommendation, resource envelope) and presents it to the
user. The user approves or rejects (with feedback); rejections are bounded by
a re-ask budget. On approval the draft is written (versioned) with a change
log, and the edit is recorded in `history/mission_edits.jsonl`.

**Enforced by construction**: the *only* code path that writes `MISSION.md`
is `_write_mission`, which is called **only** on user approval inside
`run_mission`. There is no public write function, so an out-of-flow write to
the global mission markdown is impossible from this module.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role
from runtime.intake import IntakeResult
from runtime.llm import LLMBackend


@dataclass
class MissionResult:
    approved: bool
    attempts: int
    version: Optional[int]
    mission_path: Optional[str]
    edits: List[Dict[str, Any]] = field(default_factory=list)


def _mission_context(intake_result: IntakeResult, feedback: str) -> str:
    parts = [
        "PHASE 2: codify the global mission (MISSION.md).",
        f"Intake confidence: {intake_result.confidence:.2f} "
        f"(converged={intake_result.converged})",
    ]
    if intake_result.assumptions:
        parts.append("Assumptions to carry (mark in the mission):")
        parts.extend(f"  - {a}" for a in intake_result.assumptions)
    if feedback:
        parts.append(f"User feedback on the previous draft: {feedback}")
    parts.append(
        "Produce mission_draft: purpose, scope, non_goals, success_criteria, "
        "constraints, org_recommendation, resource_envelope."
    )
    return "\n".join(parts)


def _render_mission(draft: Dict[str, Any], version: int) -> str:
    def block(key, title):
        val = draft.get(key, "")
        if isinstance(val, list):
            body = "\n".join(f"- {v}" for v in val)
        else:
            body = str(val)
        return f"## {title}\n\n{body}\n"

    return (
        f"# MISSION (v{version})\n\n"
        + block("purpose", "Purpose")
        + block("success_criteria", "Success criteria")
        + block("scope", "Scope")
        + block("non_goals", "Non-goals")
        + block("constraints", "Constraints")
        + block("org_recommendation", "Org recommendation")
        + block("resource_envelope", "Resource envelope")
    )


def _write_mission(mission_path: str, draft: Dict[str, Any], version: int) -> str:
    """THE write path to the global mission markdown. Called only on user
    approval inside `run_mission`. This is the only place MISSION.md is
    written (enforced by construction)."""
    content = _render_mission(draft, version)
    with open(mission_path, "w", encoding="utf-8") as f:
        f.write(content)
    return mission_path


def _log_edit(
    history_dir: str,
    version: int,
    draft: Dict[str, Any],
    decision: Dict[str, Any],
    written: bool,
) -> Dict[str, Any]:
    os.makedirs(history_dir, exist_ok=True)
    record = {
        "phase": 2,
        "version": version,
        "decision": decision.get("decision"),
        "feedback": decision.get("feedback", ""),
        "written": written,
        "draft": draft,
    }
    path = os.path.join(history_dir, "mission_edits.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def run_mission(
    backend: LLMBackend,
    leader: Role,
    intake_result: IntakeResult,
    user_permission_fn: Callable[[Dict[str, Any]], Dict[str, str]],
    mission_path: str = "MISSION.md",
    history_dir: str = "history",
    reask_budget: int = 3,
) -> MissionResult:
    """Run the Phase 2 mission codification + permission flow.

    `user_permission_fn(draft) -> {"decision": "approve"|"reject",
    "feedback": str}` supplies the user's decision on a draft.
    """
    edits: List[Dict[str, Any]] = []
    attempts = 0
    approved = False
    version: Optional[int] = None
    feedback = ""

    while attempts < reask_budget:
        attempts += 1
        ctx = _mission_context(intake_result, feedback)
        out = backend.invoke(leader, ctx)
        draft = out.get("mission_draft", {})
        decision = user_permission_fn(draft)

        if decision.get("decision") == "approve":
            approved = True
            version = attempts
            _write_mission(mission_path, draft, version)  # the only write path
            edits.append(_log_edit(history_dir, version, draft, decision, written=True))
            break

        feedback = decision.get("feedback", "")
        edits.append(_log_edit(history_dir, attempts, draft, decision, written=False))

    return MissionResult(
        approved=approved,
        attempts=attempts,
        version=version,
        mission_path=mission_path if approved else None,
        edits=edits,
    )
