# Story 8 — CLI (`run_session.py`, `reset_org.py`)

## Goal

Update the **CLI** to the 8-phase process: the run-mode / phase logging
reflects the 8 phases, and a **checkpoint at Phase 3+ resumes from Phase 4**
(skipping Phases 1–3). `reset_org.py` is **unchanged** (it wipes the generated
state).

## Files

- `run_session.py` — **modify** (the run-mode / phase logging + the
  `resume_from_phase` logic).
- `reset_org.py` — **no change** (the wipe logic is unchanged).

## Detailed changes

### 8.1 `run_session.py` — the run-mode / phase logging

The current `run_session.py` decides the run mode (`_decide_run_mode`: fresh vs
revisit) + the resume point, and runs the session. Update the **phase logging**
to the 8 phases:

1. **The run-mode logging** — the visible log (the "starting from Phase N"
   message) reflects the 8 phases (Intake=1, Mission=2, Org bootstrap=3,
   Plan=4, Staff=5, Execute=6, Evaluate=7, Decide=8).
2. **The `resume_from_phase` logic** — a **checkpoint at Phase 3+ resumes from
   Phase 4** (skipping Phases 1–3). The current logic (a revisit from a
   checkpoint at phase 3 or 4 skips Phases 1–3 and resumes from Phase 4) is
   **largely unchanged** — the phase numbers are the same (Phases 1–3 are
   Intake / Mission / Org bootstrap, and a checkpoint at Phase 3+ means the org
   structure exists, so the run resumes from Phase 4 (Plan)).
3. **The result logging** — the "Session complete" log (the status / phases /
   cycles / verdict) reflects the 8 phases (the `phases` dict is `{1..8: count}`,
   from Story 1).

> **Note:** the `--fresh` / `--revisit` / `--dry-run` flags are unchanged. The
> `--interactive` flag (the user-facing gates — the intake Q&A + the mission
> approval) is unchanged (Phases 1–2 are largely unchanged, from Story 1).

### 8.2 `reset_org.py` — unchanged

`reset_org.py` is **unchanged**. It wipes the generated state (the same logic
as a `reset_org --yes` run):
- `departments/` — every department / team directory.
- `state/` — the saved org chart + each role's memory.
- `MISSION.md` — the current mission.
- `history/*.jsonl` — the audit trails.
- `pods/` — pod artifacts + transcripts.
- `reports/` — the evaluation reports.
- `archives/` — the archived sessions.

The wipe logic (`_collect_targets` / `wipe_state`) is **not** modified. The
new phase modules (Plan / Staff / Execute) do not add new generated artifacts
that need wiping (they write to the existing `departments/` / `state/` /
`pods/` / `reports/` / `history/` directories).

> **Ordering:** this story **depends on Story 1** (the 8-phase Session) — the
> CLI's phase logging reflects the 8 phases. Do this after Story 1.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the existing `tests/test_session.py` (the
> run-mode / resume logic) — the `resume_from_phase` logic must still work
> (a checkpoint at Phase 3+ resumes from Phase 4).
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
