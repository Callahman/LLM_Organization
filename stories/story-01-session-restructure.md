# Story 1 — 8-Phase Session restructure

## Goal

Restructure the `Session.run` pipeline from the current **6 phases** to the
**8 phases**:

`Intake → Mission → Org bootstrap → Plan → Staff → Execute → Evaluate → Decide`

Phases 1 (Intake) and 2 (Mission) are **largely unchanged**. The monolithic
old Phase 4 (`dispatch`) is replaced by three phase modules (Plan / Staff /
Execute) from Story 2. The old Phase 5 (Synthesis) + Phase 6 (Evaluation)
become the new Phase 7 (Evaluate) + Phase 8 (Decide).

## Files

- `runtime/session.py` — **modify** (the main change).
- `runtime/plan.py`, `runtime/staff.py`, `runtime/execute.py` — **import**
  (created in Story 2).
- `runtime/org.py` — **import** (the Org bootstrap, unchanged except the
  department caps from Story 3).
- `runtime/solo.py`, `runtime/timing.py` — **modify** (phase labels / the
  `record_phase` wiring for phases 4–8).

## Detailed changes

### 1.1 `Session.run` — the 8-phase sequence

Replace the current body of `Session.run` (the 6-phase loop) with the 8-phase
sequence. Keep the **setup** (loading `MISSION.md`, the org chart, the
checkpoint) and the **final** (saving the org chart, the checkpoint, the
result) unchanged. The new sequence:

```
Phase 1 (Intake):       run_intake(...)          # unchanged
Phase 2 (Mission):      run_mission(...)         # + department proposal (Story 6)
Phase 3 (Org bootstrap): org.bootstrap(...)       # + department caps + Pod A (Story 3)
                         history.log_cycle(cycle, 3, "bootstrap", ...)
                         self._save_org_state()
                         self._save_checkpoint(phase=3, cycle=cycle)
                         if resume_from_phase > 3: break to the cycle loop

# The cycle loop (repeats while Phase 8 says "continue"):
while cycle < max_iterations:
    cycle += 1
    Phase 4 (Plan):      plan.run_plan(...)       # the head workflow (Story 2)
                         history.log_cycle(cycle, 4, "plan", ...)
    Phase 5 (Staff):     staff.run_staff(...)     # the manager workflow (Story 2)
                         history.log_cycle(cycle, 5, "staff", ...)
    Phase 6 (Execute):   execute.run_execute(...) # IC execution (Story 2)
                         history.log_cycle(cycle, 6, "execute", ...)
                         self._save_org_state()
                         self._save_checkpoint(phase=6, cycle=cycle)
    Phase 7 (Evaluate):  self._evaluate(...)      # status pods + leader evaluation
                         history.log_cycle(cycle, 7, "evaluate", ...)
    Phase 8 (Decide):    verdict = self._decide(...)  # continue / complete / escalate
                         if verdict != "continue": break
```

Notes:
- **Intake (Phase 1) and Mission (Phase 2) are called exactly as today** —
  `run_intake` and `run_mission`. Do not change their call signatures or
  arguments.
- **Org bootstrap (Phase 3)** is the existing `org.bootstrap` call, now
  followed by the department-caps allotment + Pod A (Story 3). Keep the
  existing `resume_from_phase > 3` skip (a revisit from a checkpoint at phase
  3+ skips Phases 1–3).
- The **cycle loop** wraps Phases 4–8. The `cycle` counter is incremented at
  the top of each iteration (matching the current behavior where `cycle` is
  incremented before the dispatch).
- **Bounded by `max_iterations`** (the existing `config["max_iterations"]`).

### 1.2 Phase 7 (Evaluate) — `Session._evaluate`

The current `Session._evaluate` (old Phase 6) does the leader evaluation
(invoking the leader with the department briefs + getting a verdict). The new
Phase 7 (Evaluate) **adds the status pods (the reporting pods) before the
leader evaluation**:

1. **Run the reporting pods** (Story 4): IC→manager, manager→head,
   head→leader. These surface the fire/replace/keep decisions + the headcount
   changes (the child reports to the parent).
2. **Apply the resourcing** (the existing `_apply_resourcing`) — the firing /
   replacement from the reporting pods.
3. **Invoke the leader** for the evaluation (the existing `_evaluate` body) —
   the leader sees the department briefs + the reporting-pod outcomes and
   returns a verdict + findings.

Keep the existing `_evaluate` body (the leader invoke + the resourcing) and
**prepend the reporting pods**.

### 1.3 Phase 8 (Decide) — `Session._decide`

Extract the **decision** from the old Phase 6 into a new `Session._decide`
method. It reads the leader's verdict (from Phase 7) and returns one of
`"continue"`, `"complete"`, `"escalate"`. The cycle loop breaks when the
verdict is not `"continue"`.

- `"continue"` → repeat the cycle (Phase 4 again).
- `"complete"` → the mission is complete (the result's `status` is
  `"complete"`).
- `"escalate"` → the mission is escalated (the result's `status` is
  `"escalated"`, with the escalation note).

A **headcount reassignment** in Phase 8 can trigger a reorg (the org adapts its
structure/headcount on the next cycle).

### 1.4 `SessionResult.phases` — `{1..8: count}`

The current `SessionResult.phases` is a dict of phase → count. Update it to
track **phases 1–8** (the new phase numbers). The `phases` dict is populated
as each phase runs (increment the count for the phase number).

### 1.5 `solo.record` phase labels + `EfficiencyMeter.record_phase`

- **`solo.record`**: the current `solo.record` (in `runtime/solo.py`) records
  the phase for the solo-pod tracker. Update the phase labels to the new
  8-phase numbers (Plan=4, Staff=5, Execute=6, Evaluate=7, Decide=8).
- **`EfficiencyMeter.record_phase`**: the current `EfficiencyMeter` (in
  `runtime/timing.py`) records per-phase invoke time. Update the `record_phase`
  wiring so phases 4–8 are recorded (the new phase numbers).

### 1.6 Keep `Session._synthesis` / `Session._evaluate`

The current `Session._synthesis` (old Phase 5, leader synthesis) and
`Session._evaluate` (old Phase 6, leader evaluation) become part of the new
Phase 7 (Evaluate). **Optionally rename** `_synthesis` → `_evaluate_progress`
and `_evaluate` → `_decide`, or keep them as-is and fold them into the new
Phase 7. The **logic is unchanged** (the leader synthesis + evaluation); only
the phase number + the prepended reporting pods change.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the
> code changes, **try to run the test suite once in the repo's virtual
> environment** (e.g. `python -m pytest tests/ -x` from the project root, using
> the repo's venv — see `SETUP.md` for how the venv is created).
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error, or the environment is not set up) **or the tests fail for
>   reasons outside your changes**, **still complete the code work** (do not
>   leave the story half-done to chase a broken environment), and then
>   **explicitly raise the need for testing to the user** — state clearly that
>   you could not verify the changes by running the tests, why (the specific
>   error / missing venv), and that the user should run the test suite to
>   confirm. Do not silently skip this step.
