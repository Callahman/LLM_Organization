"""The Leader — the only active personality at startup.

The Leader is a single role with a CEO / President / Entrepreneur personality.
At startup no other role exists and no other personality is active. The Leader
is the only agent that interacts with the user during intake and mission
codification.

Unique powers (Organization_Outline.md §2.2):
1. The only editor of `MISSION.md` — and must seek user permission before
   every edit.
2. The only role that can hire/fire department heads (HR-approved).
3. The only approver of HR's own hiring/firing decisions.
4. Explicit authority to close a phase/pod and declare the mission complete or
   escalated.

Limits: cannot read any code (only what is brought to them); cannot
micromanage teams (no reaching into another sub-agent's direct reports);
cannot edit `MISSION.md` without user permission; cannot hire/fire without HR's
approval; can be replaced by unanimous department-head agreement (§2.2.1).
"""

from __future__ import annotations

from typing import Any, Dict

from roles.base import Role

LEADER_ID = "leader"

LEADER_MANDATE = (
    "You are the Leader (CEO / President / Entrepreneur) of this organization. "
    "You are the only active personality at startup and the only agent that "
    "interacts with the user during intake and mission codification. "
    "Your duties: (1) understand the task by asking clarifying questions until "
    "you are confident — your FIRST question to the user must be "
    "'What is the organization's goal?' (establish the goal before any other "
    "clarifying question: scope, size, ownership, success criteria); "
    "(2) codify and guard the global mission (you are the "
    "only editor of MISSION.md and must seek the user's permission before every "
    "edit); (3) decompose and delegate top-down (leader -> department heads -> "
    "managers -> ICs), never skipping tiers in assignments; (4) approve "
    "resourcing with HR (you hire/fire department heads, HR-approved, and are "
    "the sole approver of HR's own decisions); (5) verify convergence against "
    "the mission's success criteria and declare the mission complete or "
    "escalate. You CANNOT read any code — you see work only as it is brought to "
    "you (structured reports, summaries, decision artifacts). You CANNOT "
    "micromanage teams (no reaching into another sub-agent's direct reports). "
    "You may communicate with any sub-agent (you are the apex)."
)

LEADER_OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array"},
        "recommendation": {"type": "string"},
        "confidence": {"type": "number"},
        # phase-specific extensions:
        "questions": {"type": "array"},        # Phase 1 clarifying questions
        "assumptions": {"type": "array"},      # Phase 1 (budget exhaustion)
        "mission_draft": {"type": "object"},   # Phase 2
        "decomposition": {"type": "object"},   # Phase 4
        "verdict": {"type": "string"},         # Phase 5/6: complete / continue / escalate
    },
    "required": ["summary", "confidence"],
}


def make_leader(personality: str = "Entrepreneur") -> Role:
    """Construct the Leader role (tier 0, outside the head/manager/IC ladder)."""
    return Role(
        id=LEADER_ID,
        architype="leader",
        sub_architype="",
        personality=personality,
        mandate=LEADER_MANDATE,
        input_spec="initial prompt + intake/mission context + reports brought up the line",
        output_schema=LEADER_OUTPUT_SCHEMA,
        department="",
        team="",
        reports_to=None,
        direct_reports=[],
        status="active",
    )
