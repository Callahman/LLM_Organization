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

The `LEADER_MANDATE` + `LEADER_OUTPUT_SCHEMA` live in `roles/leader_schemas.py`;
they are re-exported here for backward compatibility.
"""

from __future__ import annotations

from roles.base import Role
from roles.leader_schemas import (  # re-exported for backward compatibility
    LEADER_MANDATE,
    LEADER_OUTPUT_SCHEMA,
)

LEADER_ID = "leader"


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


__all__ = [
    "LEADER_ID",
    "LEADER_MANDATE",
    "LEADER_OUTPUT_SCHEMA",
    "make_leader",
]
