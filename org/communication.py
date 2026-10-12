"""Communication rule checks.

Communication is chain-of-command + team-mates + the leader (apex); no reaching
into another sub-agent's direct reports. Re-exported by the `org/tiers.py`
facade.
"""

from __future__ import annotations

from org.tier_math import is_leader


def _same_team(a, b) -> bool:
    return (
        a.department and a.department == b.department
        and a.team and a.team == b.team
    )


def can_communicate(a, b) -> bool:
    """Can `a` directly communicate with `b`?

    - The leader is the apex: any sub-agent may communicate with the leader,
      and vice versa.
    - Otherwise communication is allowed only within your own line: your boss,
      your reports, or team-mates (same team). No reaching into another
      sub-agent's direct reports.
    """
    if is_leader(a) or is_leader(b):
        return True
    if b.id == a.reports_to:  # b is a's boss
        return True
    if a.id == b.reports_to:  # a is b's boss
        return True
    if _same_team(a, b):
        return True
    return False
