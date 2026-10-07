# Story 3 — Safety halt enforcement

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** A4 (`bau_active` dead), A10 (BAU halt set but never consumed),
B12 (Phase 4 halt recorded but not enforced), C1 (BAU rule inert).

**Goal:** a Phase 4 Safety/Morality halt actually changes pipeline behavior —
a **global** halt stops work before Phase 5/6; a **scoped** halt continues only
non-blocked work. The halt is observable and testable.

## Context (what exists today)
- `runtime/session.py:389-396`: after Phase 4, `phase4_halt_fn()` is checked;
  on a halt, `self.halt_bau(...)` (sets `self.bau_halt`) and
  `self.queue_user_input(...)` are called — then the pipeline proceeds to Phase
  5 (synthesis, session.py:399) and Phase 6 (evaluation, session.py:403)
  **without** checking `bau_active()`.
- `OrgState.bau_active()` (`runtime/org.py`) is never called in the pipeline.
- `_escalate` (`runtime/session.py:259`) is the existing "stop and report" path
  (returns a `SessionResult` with `status="escalated"`).

## Tasks

- [ ] **Add a scoped-vs-global distinction to the halt.** In `halt_bau` (find it
  in `runtime/session.py` — the method that sets `self.bau_halt`), store the
  halt's `scope` (the `halt["scope"]` from the caller) so the pipeline can tell
  a global halt from a scoped one.
- [ ] **Enforce the halt before Phase 5.** After the Phase 4 halt block
  (`runtime/session.py:389-396`), add: if `self.bau_active()` is True **and** the
  halt is **global**, stop — `return self._escalate("safety/morality halt
  (global)", intake, mission)` (reuse the existing `_escalate`, session.py:259).
- [ ] **Enforce the halt before Phase 6.** Apply the same check before the
  Phase 6 evaluation (session.py:403) so a global halt does not run the
  continue/complete decision.
- [ ] **Scoped halt: continue non-blocked work.** For a **scoped** halt, do not
  stop, but log a visible `[session] scoped safety/morality halt in <dept> —
  continuing non-blocked work` note (so the behavior is observable). (Full
  per-department blocking is a follow-up.)
- [ ] **Make `bau_active` observable.** Ensure `self.bau_active()` (or
  `self.bau_halt`) is included in a solo record for Phase 5 so the dashboard can
  show the active halt.
- [ ] **Tests** (`tests/test_session.py`):
  - (a) A **global** Phase 4 halt (via a `phase4_halt_fn` returning
    `{"department": "...", "scope": "global", "reason": "..."}`) stops the run
    before Phase 5 (assert `5 not in result.phases` or `result.status ==
    "escalated"`).
  - (b) A **scoped** halt does not stop the run (assert Phase 5 runs) but the
    halt is recorded (assert `result` reflects the halt).

## Definition of done
- A global Phase 4 halt stops work before Phase 5/6.
- A scoped halt continues non-blocked work and is observable.
- `bau_active()` is consumed in the pipeline (no longer dead).