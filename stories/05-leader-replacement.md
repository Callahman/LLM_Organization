# Story 5 — Leader replacement

**Finding:** A1 (`replace_leader` dead — never called, never tested).

**Design (from the outline §2.2.1 + the refinement):** a **single head can
trigger** the vote (propose a leader replacement, *with reasoning*); the system
sends a per-head vote prompt **including the proposer's reasoning**; the
replacement proceeds only on **unanimous** approval (all active department
heads vote yes — multiple, not one). `OrgState.replace_leader` (org.py:531)
already enforces unanimity correctly (`set(agreeing_head_ids) == {h.id for h in
heads}`, and raises if there are no heads) — the wiring must preserve that.

## Context (what exists today)
- `OrgState.replace_leader` (`runtime/org.py:531`) exists but is never called.
- No resourcing path parses a leader-replacement proposal/vote.
- The department heads are available via `org.department_heads()`
  (`runtime/org.py`).
- The leader's output schema is in `roles/leader.py` (the `output_schema`
  dataclass).

## Tasks

- [ ] **Add a `leader_replacement` proposal the leader can emit.** Extend the
  leader's Phase 4/5 output schema (find the leader `output_schema` in
  `roles/leader.py`) with an optional `leader_replacement` field:
  `{"propose": bool, "reasoning": str}`. A single head setting `propose=True`
  triggers the vote.
- [ ] **Build the per-head vote prompt.** When a `leader_replacement` proposal
  with `propose=True` is detected, for **each** active department head, build a
  vote prompt that includes: the current leader's id, the proposer's id, and the
  **proposer's reasoning** (verbatim). The prompt asks the head to vote
  `{"vote": "yes"|"no"}`.
- [ ] **Collect the votes and call `replace_leader` on unanimity.** Invoke each
  head with the vote prompt; collect the `vote` values. If **all** active heads
  vote "yes" (unanimous), call
  `org.replace_leader(leader, new_leader, agreeing_head_ids=[h.id for h in
  heads])`. If any head votes "no" (partial), do **not** replace — log a visible
  `[org] leader-replacement vote not unanimous (N of M yes)` note.
- [ ] **Wire the trigger into the pipeline.** Detect the `leader_replacement`
  proposal in the Phase 4 dispatch (or Phase 5 synthesis) — find where the
  leader's output is consumed in `runtime/dispatch.py` / `runtime/session.py` —
  and run the vote flow there. Log the proposal, the votes, and the outcome via
  `org.log_event("leader_replacement_proposed"/"leader_replacement_voted"/
  "leader_replaced", ...)`.
- [ ] **Tests** (`tests/test_org.py`):
  - (a) **Unanimous (multi-head) case:** two department heads both vote "yes" →
    `replace_leader` is called and the leader is replaced.
  - (b) **Partial-vote (rejected) case:** one of two heads votes "no" → the
    leader is NOT replaced.
  - (c) **Single-head-trigger + reasoning-in-prompt case:** assert the vote
    prompt sent to each head contains the proposer's reasoning (capture the
    prompt via a stub backend and assert the reasoning substring is present).
  - (d) **No-heads case:** `replace_leader` raises when there are no department
    heads (the existing guard).

## Definition of done
- A single head can trigger a leader-replacement vote (with reasoning).
- The vote prompt to each head includes the proposer's reasoning.
- The replacement proceeds only on unanimous (multi-head) approval.
- The four tests pass.