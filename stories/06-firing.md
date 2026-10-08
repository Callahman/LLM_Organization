# Story 6 — Firing

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** A3 (`fire`/`mark_inactive`/`_offload` dead — R7), R7 (firing is
dead).

**Goal:** a role can be fired — marked inactive (kept in the org chart, not
deleted), its work offloaded, and the event journaled. Firing is observable and
testable.

## Context (what exists today)
- `OrgState.fire` (`runtime/org.py`), `Role.mark_inactive`, and `_offload`
  exist but are never called. Today a "fired" role is simply dropped (or never
  removed).
- `OrgState.active_roles()` (`runtime/org.py`) filters to active roles — so
  marking a role inactive (rather than deleting it) keeps it in the org chart
  but out of the active set.
- The HR approver (`approver_fn("hr", "fire", role)`) is the intended gate for
  firing.
- `hire` (`runtime/org.py:442`) is the parallel path (the fire trigger should
  sit next to it in `runtime/dispatch.py`).

## Rollout (what was changed)
- **`fire` path** (`runtime/org.py`): already existed and already does tasks
  1-3 — it calls `approver_fn(approver, "fire", target)`, on approve runs
  `_offload` + `mark_inactive` (the role stays in `org.roles`, out of
  `org.active_roles()`) + logs `fired`, on veto logs `fire_vetoed`, and rejects
  required roles (`is_required`) with a visible `ResourcingError`. No change
  needed there.
- **Pipeline wiring** (`runtime/dispatch.py`): a `_fire_role` helper (parallel
  to the `_ensure_role` hire path) + a Phase 4 trigger that reads the leader's
  `resourcing.fire` output (each entry `[role_id, reason]`) and fires each role
  through the HR approver. A veto / required-role rejection / missing approver
  is logged to `dispatch_skips.jsonl`, never swallowed.
- **Schema** (`roles/leader.py`): an optional `resourcing` field
  (`{"fire": [[role_id, reason], ...]}`) on the leader output schema.
- **Tests** (`tests/test_org.py`): the three cases (fire an IC, veto a fire,
  required role cannot be fired). (Written by the agent; **run by the user**
  per the rule.)

## Tasks

- [x] **Wire `fire` to the HR approver.** Add a `fire_role` path (in
  `runtime/org.py` or `runtime/dispatch.py`): call
  `approver_fn("hr", "fire", role)`; on `decision == "approve"`, call
  `org.fire(role)` (or the existing `fire` method) which calls
  `role.mark_inactive()` and `_offload(role)` (offload its work to the org
  chart / a successor). On a veto, log `org.log_event("fire_vetoed", ...)` and
  do not fire.
- [x] **Journal the fire.** On a successful fire, call
  `org.log_event("fired", initiator, role.id, {"reason": ...})` so the audit
  trail records it. Ensure `fire` uses `mark_inactive` (not deletion) so the
  role stays in the org chart (verifiable via `org.roles`, absent from
  `org.active_roles()`).
- [x] **Guard required roles.** Ensure a required department head (hr, safety,
  morality — `role.is_required`) **cannot** be fired (the `fire` path should
  reject it with a visible note; find the `is_required` flag in `Role`).
- [x] **Make firing reachable from the pipeline.** Expose the fire path where
  resourcing decisions are made (Phase 4 dispatch — find where `hire` is
  triggered in `runtime/dispatch.py` and add a parallel `fire` trigger, e.g. a
  leader `resourcing` output with `{"fire": [role_id, reason]}`).
- [x] **Tests** (`tests/test_org.py`):
  - (a) **Fire an IC:** approve a fire → the role is `mark_inactive` (in
    `org.roles`, not in `org.active_roles()`), `_offload` ran, and a `fired`
    event is logged.
  - (b) **Veto a fire:** the approver vetoes → the role stays active, a
    `fire_vetoed` event is logged.
  - (c) **Required role cannot be fired:** firing a required department head is
    rejected (the role stays active).

## Definition of done
- A role can be fired (marked inactive, offloaded, journaled) via the HR
  approver.
- Required roles cannot be fired.
- The three tests pass.