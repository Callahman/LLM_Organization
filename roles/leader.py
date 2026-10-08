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
        # Phase 2: the MISSION.md draft. Optional at the top level (so it does
        # not leak into the other phases) but, when present, it is a JSON
        # OBJECT with the exact keys `runtime/mission.py::_render_mission`
        # reads — so the forced submit_output tool constrains the model to
        # emit a dict (not a free-form string, the Phase-2 crash).
        "mission_draft": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "success_criteria": {"type": "array"},
                "scope": {"type": "array"},
                "non_goals": {"type": "array"},
                "constraints": {"type": "array"},
                "org_recommendation": {},
                "resource_envelope": {},
            },
        },
        # Phase 3: the org bootstrap head proposal. Optional at the top level
        # (so it does not leak into the other phases) but, when present, the
        # `department_heads` array is REQUIRED — this is the exact shape
        # `runtime/org.py::bootstrap` reads, so the forced submit_output tool
        # constrains the model to emit it (the "did nothing" regression).
        "org_recommendation": {
            "type": "object",
            "properties": {
                "department_heads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "department": {"type": "string"},
                            "sub_architype": {"type": "string"},
                            "required": {"type": "boolean"},
                            "mandate": {"type": "string"},
                        },
                        "required": ["id", "department", "mandate"],
                    },
                },
            },
            "required": ["department_heads"],
        },
        # Phase 4: the top-down dispatch decomposition. Optional at the top
        # level (so it does not leak into the other phases) but, when present,
        # the `department_objectives` array is REQUIRED — the exact shape
        # `runtime/dispatch.py::dispatch` reads, so the forced submit_output
        # tool constrains the model to emit it (not a free-form string).
        "decomposition": {
            "type": "object",
            "properties": {
                "department_objectives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "head_id": {"type": "string"},
                            "objective": {"type": "string"},
                        },
                        "required": ["head_id", "objective"],
                    },
                },
            },
            "required": ["department_objectives"],
        },
        "verdict": {"type": "string"},         # Phase 5/6: complete / continue / escalate
        # Story 5 (A1): a leader-replacement proposal. A single head setting
        # `propose=True` (with reasoning) triggers the per-head unanimous vote
        # (§2.2.1). Optional at the top level (so it does not leak into the
        # other phases).
        "leader_replacement": {
            "type": "object",
            "properties": {
                "propose": {"type": "boolean"},
                "reasoning": {"type": "string"},
            },
        },
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
