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
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from prompts import MISSION_DEPARTMENTS, MISSION_INSTRUCTION
from roles.base import Role
from runtime.intake import IntakeResult
from runtime.llm import LLMBackend
from runtime.guard import guarded_call
from runtime.complexity import classify_complexity


@dataclass
class MissionResult:
    approved: bool
    attempts: int
    version: Optional[int]
    mission_path: Optional[str]
    edits: List[Dict[str, Any]] = field(default_factory=list)
    # the Phase-2 department LIST (the departments + priority order, as a list
    # of {name, priority, rationale} dicts, in priority order). This is the
    # department LIST (which departments the mission needs) — it is NOT the
    # Phase-3 `department_caps` (a {department: integer cap} mapping). Empty if
    # the leader did not propose departments (bootstrap then falls back to the
    # Phase-3 org_recommendation head proposal).
    mission_departments: List[Dict[str, Any]] = field(default_factory=list)


def _mission_context(intake_result: IntakeResult, feedback: str,
                     current_mission: str = "",
                     informal_draft: str = "") -> str:
    parts = [
        "PHASE 2: codify the global mission (MISSION.md).",
        f"Intake confidence: {intake_result.confidence:.2f} "
        f"(converged={intake_result.converged})",
    ]
    if current_mission:
        parts.append(
            "CURRENT MISSION (revise it — the goal may have changed):\n"
            + current_mission
        )
    if informal_draft:
        parts.append(
            "INFORMAL DRAFT (from Phase 1 intake — refine it into the formal "
            "mission):\n" + informal_draft
        )
    if intake_result.assumptions:
        parts.append("Assumptions to carry (mark in the mission):")
        parts.extend(f"  - {a}" for a in intake_result.assumptions)
    if feedback:
        parts.append(f"User feedback on the previous draft: {feedback}")
    parts.append(MISSION_INSTRUCTION)
    # also propose the departments the mission needs, in priority
    # order (Phase 3 creates them).
    parts.append(MISSION_DEPARTMENTS)
    return "\n".join(parts)


def _mission_draft(out: Dict[str, Any]) -> Dict[str, Any]:
    """Safely extract the Phase-2 ``mission_draft`` from the Leader's output,
    tolerating the shapes the real LLM free-forms. A dict is returned as-is;
    a **string** (the model collapsed the draft to prose — the Phase-2 crash)
    degrades to ``{"purpose": <string>}`` so it still renders (visible, never
    an ``AttributeError``); anything else (None / number / list) degrades to
    an empty dict. This is the defensive half of the Phase-2 fix: even if the
    model ignores the forced ``submit_output`` schema, a string draft renders
    as the mission's purpose instead of crashing ``_render_mission``."""
    rec = (out or {}).get("mission_draft")
    if isinstance(rec, dict):
        return rec
    if isinstance(rec, str) and rec.strip():
        return {"purpose": rec}
    return {}


def _mission_departments(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Safely extract the Phase-2 ``mission_departments`` (the department LIST)
    from the Leader's output. Returns a list of ``{name, priority, rationale}``
    dicts, in priority order. This is the department LIST (which departments
    the mission needs) — it is NOT the Phase-3 ``department_caps`` (a
    {department: integer cap} mapping). Tolerates the shapes the real LLM
    free-forms: a dict with a ``departments`` list, or a bare list; each item a
    dict (``name`` / ``department``) or a bare string. Reads the ``
    mission_departments`` key (the Phase-2 key) with a fallback to the legacy
    ``department_caps`` key (so a model that still emits the old key is not
    lost). Returns ``[]`` if absent/empty — so a missing proposal degrades to
    the Phase-3 ``org_recommendation`` fallback (never a crash)."""
    out = out or {}
    rec = out.get("mission_departments")
    if rec is None:
        rec = out.get("department_caps")  # legacy key fallback
    if isinstance(rec, dict):
        depts = rec.get("departments")
    elif isinstance(rec, list):
        depts = rec
    else:
        return []
    if not (isinstance(depts, list) and depts):
        return []
    norm: List[Dict[str, Any]] = []
    for i, d in enumerate(depts):
        if isinstance(d, str) and d.strip():
            norm.append({"name": d.strip(), "priority": i + 1, "rationale": ""})
        elif isinstance(d, dict):
            name = str(d.get("name", "") or d.get("department", "")).strip()
            if not name:
                continue
            norm.append({
                "name": name,
                "priority": int(d.get("priority", i + 1)),
                "rationale": str(d.get("rationale", "")),
            })
    return norm


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


def load_mission(mission_path: str = "MISSION.md"):
    """Load the current mission from disk. Returns `(version, text)` — the
    version (from the `# MISSION (vN)` header, or None if absent) and the full
    mission text (for seeding a revisit's draft / the intake frame). Returns
    `(None, "")` if the file is missing."""
    if not os.path.exists(mission_path):
        return None, ""
    with open(mission_path, encoding="utf-8") as f:
        text = f.read()
    version = None
    lines = text.splitlines()
    if lines:
        m = re.match(r"# MISSION \(v(\d+)\)", lines[0])
        if m:
            version = int(m.group(1))
    return version, text


def run_mission(
    backend: LLMBackend,
    leader: Role,
    intake_result: IntakeResult,
    user_permission_fn: Callable[[Dict[str, Any]], Dict[str, str]],
    mission_path: str = "MISSION.md",
    history_dir: str = "history",
    reask_budget: int = 3,
    start_version: Optional[int] = None,
    current_mission: str = "",
    informal_draft: str = "",
) -> MissionResult:
    """Run the Phase 2 mission codification + permission flow.

    `user_permission_fn(draft) -> {"decision": "approve"|"reject",
    "feedback": str}` supplies the user's decision on a draft. On a revisit
    (`start_version` set), the version number **continues** from the current
    mission (v1 -> v2 -> ...) and the draft is seeded from the current mission
    (`current_mission`) so the Leader revises it rather than starting fresh.
    """
    edits: List[Dict[str, Any]] = []
    attempts = 0
    approved = False
    version: Optional[int] = None
    feedback = ""
    base_version = start_version or 0
    proposal: List[Dict[str, Any]] = [] 

    while attempts < reask_budget:
        attempts += 1
        ctx = _mission_context(intake_result, feedback, current_mission,
                             informal_draft)
        out = backend.invoke(leader, ctx,
                             reasoning=classify_complexity(2, leader, {}), phase=2)
        draft = _mission_draft(out)
        proposal = _mission_departments(out) 
        # guard the user-approval callback (bounded retry,
        # visible note, escalate on final failure — never a silent crash).
        decision = guarded_call(user_permission_fn, draft)

        if decision.get("decision") == "approve":
            approved = True
            version = base_version + attempts
            _write_mission(mission_path, draft, version)  # the only write path
            edits.append(_log_edit(history_dir, version, draft, decision, written=True))
            break

        feedback = decision.get("feedback", "")
        edits.append(_log_edit(history_dir, base_version + attempts, draft,
                               decision, written=False))

    return MissionResult(
        approved=approved,
        attempts=attempts,
        version=version,
        mission_path=mission_path if approved else None,
        edits=edits,
        mission_departments=proposal if approved else [],
    )
