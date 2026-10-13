"""Phase 3 — Leader replacement (unanimous department-head vote, §2.2.1).

A single head's proposal (with reasoning) triggers the per-head vote; the
replacement proceeds only on UNANIMOUS approval (every active department
head votes yes — multiple, not one). The original prompt/goal is still
abided by. Every event is logged to `history/org_events.jsonl`.

**Decomposition (Phase 1):** extracted from `runtime/org.py` (the core
registry, constants, and errors stay there).
"""

from __future__ import annotations

import sys
from typing import List, Optional

from roles.base import Role
from runtime.org import OrgState, ResourcingError


def replace_leader(
    org: OrgState,
    new_leader: Role,
    agreeing_head_ids: List[str],
) -> Role:
    """Unanimous department-head vote replaces the Leader (§2.2.1). The
    original prompt/goal is still abided by. Logged."""
    heads = org.department_heads()
    if not heads:
        raise ResourcingError("no department heads to vote")
    if set(agreeing_head_ids) != {h.id for h in heads}:
        raise ResourcingError("leader replacement requires UNANIMOUS heads")
    # The old leader is marked inactive (a firing by this special rule).
    old = org.get("leader")
    if old is not None:
        old.status = "inactive"
    org.add_role(new_leader)
    org.log_event("leader_replaced", None, new_leader.id,
                  {"agreeing_heads": agreeing_head_ids})
    return new_leader


def run_leader_replacement_vote(
    org: OrgState,
    backend,
    new_leader: Role,
    proposer_id: str,
    reasoning: str,
    phase: Optional[int] = None,
) -> Optional[Role]:
    """Run the per-head leader-replacement vote (§2.2.1). A single head's
    proposal (with reasoning) triggers the vote; the replacement proceeds only
    on UNANIMOUS approval (every active department head votes yes — multiple,
    not one). The unanimity + no-heads guards live in `replace_leader` (which
    this calls only on a unanimous yes).

    Each active department head is sent a vote prompt that includes the
    current leader's id, the proposer's id, and the proposer's reasoning
    (verbatim); the head votes ``{"vote": "yes"|"no"}``.

    Returns the new leader on a unanimous replacement, or None when the vote
    was not unanimous (the leader is NOT replaced).
    """
    heads = org.department_heads()
    current = org.get("leader")
    current_id = current.id if current is not None else "(no leader)"
    # A single head triggered the vote (with reasoning) — log the proposal.
    org.log_event("leader_replacement_proposed", proposer_id, current_id,
                  {"reasoning": reasoning})
    yes = 0
    for h in heads:
        prompt = (
            f"LEADER-REPLACEMENT VOTE (head {h.id}): the current leader is "
            f"{current_id}. {proposer_id} proposes replacing the leader with "
            f"{new_leader.id}, reasoning (verbatim): {reasoning} "
            "Vote {\"vote\": \"yes\"} to approve the replacement, or "
            "{\"vote\": \"no\"} to reject it."
        )
        out = backend.invoke(h, prompt, phase=phase)
        vote = str((out or {}).get("vote", "no")).lower()
        if vote == "yes":
            yes += 1
    # Log the collected votes (the outcome is decided below).
    org.log_event("leader_replacement_voted", proposer_id, current_id,
                  {"yes": yes, "total": len(heads)})
    if heads and yes == len(heads):
        # Unanimous (and there are heads to vote) — replace.
        replaced = replace_leader(org, new_leader,
                                  agreeing_head_ids=[h.id for h in heads])
        print(f"[org] leader-replacement vote unanimous ({yes} of "
              f"{len(heads)} yes) - leader replaced", file=sys.stderr)
        return replaced
    # Partial (or no heads) — do NOT replace.
    print(f"[org] leader-replacement vote not unanimous ({yes} of "
          f"{len(heads)} yes)", file=sys.stderr)
    return None


__all__ = ["replace_leader", "run_leader_replacement_vote"]
