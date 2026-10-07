# Story 1 — Persistence & crash recovery

**Findings:** B1 (no mid-run checkpoint), B2 (Phase 4 hire events never
flushed), B3 (`OrgState.save` not atomic), B4 (no crash recovery/resume), B7
(`MemoryBackend.save_state` not atomic), R1 (incremental flush).

**Goal:** a crash during Phase 4 loses at most the current iteration's hires —
not the whole run; all saves are atomic; a checkpoint is written after Phase 3
and each Phase 4 iteration.

## Context (what exists today)
- `OrgState.save` (`runtime/org.py:102-115`) writes the org chart JSON
  non-atomically (direct `open(path, "w")`).
- `MemoryBackend.save_state` (`runtime/llm.py:224-235`) writes per-role memory
  files non-atomically.
- The pipeline saves the org chart + role memory **only at the very end**
  (`runtime/session.py:459-460`); there is no mid-run checkpoint.
- `OrgState.write_events()` (`runtime/org.py`) flushes the accumulated
  `log_event` entries to `state/org_events.jsonl`.

## Tasks

- [ ] **Add a checkpoint helper** in `runtime/session.py`: a method
  `_checkpoint(self, phase: int, cycle: int)` that (1) calls
  `self.org.save(self.config.get("org_chart_path", "state/org_chart.json"))`,
  (2) calls `self.backend.save_state(self.config.get("memory_dir",
  "state/role_memory"))`, (3) calls `self.org.write_events()`, and (4) writes
  `state/checkpoint.json` = `{"phase": phase, "cycle": cycle, "ts":
  time.time()}`.
- [ ] **Call the checkpoint after Phase 3** — immediately after
  `self.org.write_events()` at `runtime/session.py:530`, call
  `self._checkpoint(3, 0)`.
- [ ] **Call the checkpoint after each Phase 4 iteration** — at the end of the
  `for _ in range(max_iterations):` loop body (just before the `if status !=
  "continue": break` check, ~`runtime/session.py:580`), call
  `self._checkpoint(4, self.cycles)`.
- [ ] **Make `OrgState.save` atomic** (`runtime/org.py:102-115`): write the JSON
  to `path + ".tmp"` first, then `os.replace(path + ".tmp", path)`.
- [ ] **Make `MemoryBackend.save_state` atomic** (`runtime/llm.py:224-235`): for
  each role, write to `os.path.join(directory, f"{role_id}.json.tmp")` then
  `os.replace(..., os.path.join(directory, f"{role_id}.json"))`.
- [ ] **Add a resume note** (minimal B4): at the top of `run()`, if
  `state/checkpoint.json` exists and `revisit` is False, log a visible
  `[session] checkpoint found (phase N, cycle M) — re-run to resume` note to
  stderr. (Full resume-from-checkpoint is a follow-up; this makes the checkpoint
  discoverable.)
- [ ] **Tests** (`tests/test_session.py`):
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
- The three new tests pass.