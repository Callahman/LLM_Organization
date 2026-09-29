"""org — the org chart, tier math, and the visibility/communication/pod rule
checks.

`org/tiers.py` is the single source of truth for the invariants in
Organization_Outline.md §2.3–§2.4 and §2.8:

- A role can only read its team's department directory.
- Department heads and the leader cannot read any code — they see work only as
  it is brought to them (reports, summaries, decision artifacts).
- Communication is chain-of-command + team-mates + the leader (apex); no
  reaching into another sub-agent's direct reports.
- Pod membership requires max 1-tier spread across all members (2–6 size).
"""
