# Story 1 — Persistence & crash recovery

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** B1 (no mid-run checkpoint), B2 (Phase 4 hire events never
flushed), B3 (`OrgState.save` not atomic), B4 (no crash recovery/resume), B7
(`MemoryBackend.save_state` not atomic), R1 (incremental flush).

**Goal:** a crash during Phase 4 loses at most the current iteration's hires —
not the whole run; all saves are atomic; a checkpoint is written after Phase 3
and each Phase 4 iteration.

## Context (before)
- `OrgState.save` (`runtime/org.py:102-115`) writes the org chart JSON
  non-atomically (direct `open(path, "w")`).
- `MemoryBackend.save_state` (`runtime/llm.py:224-235`) writes per-role memory
  files non-atomically.
- The pipeline saves the org chart + role memory **only at the very end**
  (`runtime/session.py:459-460`); there is no mid-run checkpoint.
- `OrgState.write_events()` (`runtime/org.py`) flushes the accumulated
  `log_event` entries to `state/org_events.jsonl`.

## Rollout (what was changed)
- `OrgState.save` (`runtime/org.py:102`) is now **atomic**: the JSON goes to
  `path + ".tmp"` first, then `os.replace` swaps it in (B3).
- `MemoryBackend.save_state` (`runtime/llm.py:224`) is now **atomic** per role
  file: `<role_id>.json.tmp` then `os.replace` (B7).
- `Session._checkpoint(phase, cycle)` (`runtime/session.py:429`) persists the
  org chart + role memory + event log, then writes `state/checkpoint.json`
  (`{"phase", "cycle", "ts"}`, itself written atomically) (B1).
- The checkpoint is called after Phase 3 (`runtime/session.py:579`,
  `_checkpoint(3, 0)`) and after each Phase 4 iteration
  (`runtime/session.py:632`, `_checkpoint(4, self.cycles)`) (B1, R1).
- A resume note is printed to stderr at the top of `run()`
  (`runtime/session.py:504`) when `state/checkpoint.json` exists and the run
  is not a revisit (B4, minimal — full resume-from-checkpoint is a follow-up).
- The end-of-run save (`runtime/session.py:643-644`) is unchanged; the
  checkpoints make the mid-run state recoverable in addition.
- New tests in `tests/test_session.py`:
  `test_phase4_crash_leaves_recoverable_checkpoint`,
  `test_org_state_save_is_atomic`,
  `test_memory_backend_save_state_is_atomic` (written by the agent; **run by
  the user** per the rule).

## Tasks

- [x] **Add a checkpoint helper** in `runtime/session.py`: a method
  `_checkpoint(self, phase: int, cycle: int)` that (1) calls
  `self.org.save(self.config.get("org_chart_path", "state/org_chart.json"))`,
  (2) calls `self.backend.save_state(self.config.get("memory_dir",
  "state/role_memory"))`, (3) calls `self.org.write_events()`, and (4) writes
  `state/checkpoint.json` = `{"phase": phase, "cycle": cycle, "ts":
  time.time()}`.
- [x] **Call the checkpoint after Phase 3** — immediately after
  `self.org.write_events()` at `runtime/session.py:530`, call
  `self._checkpoint(3, 0)`.
- [x] **Call the checkpoint after each Phase 4 iteration** — at the end of the
  `for _ in range(max_iterations):` loop body (just before the `if status !=
  "continue": break` check, ~`runtime/session.py:580`), call
  `self._checkpoint(4, self.cycles)`.
- [x] **Make `OrgState.save` atomic** (`runtime/org.py:102-115`): write the JSON
  to `path + ".tmp"` first, then `os.replace(path + ".tmp", path)`.
- [x] **Make `MemoryBackend.save_state` atomic** (`runtime/llm.py:224-235`): for
  each role, write to `os.path.join(directory, f"{role_id}.json.tmp")` then
  `os.replace(..., os.path.join(directory, f"{role_id}.json"))`.
- [x] **Add a resume note** (minimal B4): at the top of `run()`, if
  `state/checkpoint.json` exists and `revisit` is False, log a visible
  `[session] checkpoint found (phase N, cycle M) — re-run to resume` note to
  stderr. (Full resume-from-checkpoint is a follow-up; this makes the checkpoint
  discoverable.)
- [x] **Tests** (`tests/test_session.py`):
  - (a) Monkeypatch a Phase 4 step to raise; assert `state/checkpoint.json`
    exists with `phase <= 4` and the org chart + a role-memory file were saved
    (the pre-crash state is recoverable).
  - (b) `OrgState.save` atomicity: save to a path, then simulate a mid-write
    crash by writing garbage to `path + ".tmp"`; assert the previous good
    `path` is intact (the temp is not the live file).
  - (c) `MemoryBackend.save_state` atomicity: same pattern for a role file.

## Definition of done
- A Phase 4 crash loses at most the current iteration's hires.
- All saves are atomic (no partial JSON on crash).
- A checkpoint is written after Phase 3 and each Phase 4 iteration.
- The three new tests pass (**run by the user** per the rule — the agent
  wrote them but did not execute them).