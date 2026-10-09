# Story 11 — Minor robustness

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** B8 (stale role memories accumulate), B9 (memory bound not
reproducible), B10 (intake trusts leader confidence), B11 (user-approval fns
unguarded), B15 (bootstrap retry not corrective), B16 (total org size not
bounded).

**Goal:** a batch of low-priority robustness fixes — role-memory hygiene,
intake/mission robustness, and org-bootstrap bounding.

## Tasks

- [x] **B8 — Prune stale role memories.** In `MemoryBackend.save_state`
  (`runtime/llm.py:224-235`), prune `self.role_memories` to only the role ids
  present in the current org before saving (pass the org's role ids in, or skip
  saving files whose role id is not in the org). This stops the memory dir from
  growing without bound across runs.
  (Added an `active_role_ids` parameter to `save_state`; the session passes
  `self.org.roles.keys()` when saving.)
- [x] **B9 — Deterministic memory bound.** In `MemoryBackend._memory_for`
  (`runtime/llm.py:169-174`), seed the RNG with the role id (e.g.
  `random.Random(role_id).randint(lo, hi)`) so the `max_entries` bound is stable
  per role across runs (instead of re-randomized when a disk file is absent).
  (Changed `random.randint(lo, hi)` to `random.Random(role_id).randint(lo, hi)`.)
- [x] **B10 — Gate intake convergence on a restated goal.** In `run_intake`
  (`runtime/intake.py:179-181`), when `confidence >= confidence_threshold`, also
  require the leader to restate the goal in the same output (add a
  `restated_goal` field to the intake output schema); converge only if
  `restated_goal` is non-empty. This prevents premature convergence on a fuzzy
  goal.
  (Added a `restated_goal` field to the intake output schema; convergence now
  requires `confidence >= threshold AND restated_goal`.)
- [x] **B11 — Guard the user-approval functions.** Wrap the `user_answer_fn`
  calls (`runtime/intake.py:154,190`) and `user_permission_fn` call
  (`runtime/mission.py:182`) in a bounded retry (e.g. 2 attempts) with a visible
  `[session] user-approval call failed: <reason>` note; on final failure,
  escalate (never a silent crash).
  (Created `runtime/guard.py` with `guarded_call` (bounded retry, visible note,
  `UserApprovalError` on final failure); wrapped the `user_answer_fn` and
  `user_permission_fn` calls.)
- [x] **B15 — Corrective bootstrap retry.** In `bootstrap`
  (`runtime/org.py:378-393`), on a retry, append the previous attempt's failure
  reason (the top-level / `org_recommendation` keys it returned) to the
  `_bootstrap_context` so the leader can adjust (instead of re-sending the same
  context).
  (Added a `retry_hint` parameter to `_bootstrap_context`; the bootstrap builds
  the hint from the previous attempt's failure reason on a retry.)
- [x] **B16 — Total org-size cap.** Add a total org-size cap (e.g.
  `MAX_ORG_ROLES`, default e.g. 60) enforced in the bootstrap (head count) and
  Phase 4 (hires); on exceed, refuse with a visible note (never silent).
  (Added `MAX_ORG_ROLES = 60` to `runtime/org.py`; enforced in the bootstrap
  (head count) and Phase 4 (hires via `_ensure_role`).)
- [x] **Tests:**
  - (a) B8: a `save_state` after a run with fired roles does not re-persist the
    fired roles' memory files.
  - (b) B9: the same role id gets the same `max_entries` bound across two fresh
    `MemoryBackend` instances.
  - (c) B10: intake does not converge when the leader reports high confidence
    but an empty `restated_goal`.
  - (d) B11: a `user_answer_fn` that raises is retried then escalated (not a
    crash).
  - (e) B16: a bootstrap that proposes more heads than the cap refuses with a
    visible note.
  (Written by the agent; run by the user per the rule.)

## Definition of done
- Stale role memories are pruned; the memory bound is deterministic per role.
- Intake convergence is gated on a restated goal; user-approval calls are
  guarded.
- The bootstrap retry is corrective; the total org size is capped.

## Rollout (what was changed)
- **`runtime/llm.py`** — B8: added an `active_role_ids` parameter to
  `MemoryBackend.save_state` (prunes stale roles' memories before saving); B9:
  changed `random.randint(lo, hi)` to `random.Random(role_id).randint(lo, hi)`
  (deterministic per role).
- **`runtime/session.py`** — B8: the session passes the active role ids when
  calling `save_state` (both the checkpoint and the final save). **Fix:** the
  active set is `Session._active_role_ids()` = `self.org.roles.keys()` **plus
  the leader** — the leader drives the session but is not a member of
  `org.roles`, so passing the org keys alone pruned (and wiped in place) the
  leader's memory as "stale", leaving the Phase 4 crash checkpoint with zero
  persisted role memories (broke Story 1's
  `test_phase4_crash_leaves_recoverable_checkpoint`).
- **`runtime/intake.py`** — B10: added a `restated_goal` field to the intake
  output schema; convergence now requires `confidence >= threshold AND
  restated_goal`; B11: wrapped the `user_answer_fn` calls in `guarded_call`.
- **`runtime/mission.py`** — B11: wrapped the `user_permission_fn` call in
  `guarded_call`.
- **`runtime/guard.py`** (new) — B11: `guarded_call` (bounded retry, visible
  `[session] user-approval call failed: <reason>` note, `UserApprovalError` on
  final failure).
- **`runtime/org.py`** — B15: added a `retry_hint` parameter to
  `_bootstrap_context`; the bootstrap builds the hint from the previous
  attempt's failure reason on a retry; B16: added `MAX_ORG_ROLES = 60`;
  enforced in the bootstrap (head count).
- **`runtime/dispatch.py`** — B16: enforced `MAX_ORG_ROLES` in Phase 4 (hires
  via `_ensure_role`).
- **`tests/test_memory.py`** — B8: `test_b8_prune_stale_role_memories`; B9:
  `test_b9_deterministic_memory_bound`.
- **`tests/test_intake.py`** — B10: `test_b10_no_convergence_without_restated_goal`;
  B11: `test_b11_user_answer_fn_raises_is_retried_then_escalated`.
- **`tests/test_org.py`** — B16: `test_b16_bootstrap_exceeds_org_size_cap`.