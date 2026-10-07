# Story 12 — Dead-code cleanup

**Finding:** A5 (`invoke_checked` / `run_cycle` dead — D1/D2).

**Goal:** remove (or wire) the dead `invoke_checked` / `run_cycle` functions so
the codebase has no silently dead entry points.

## Context (what exists today)
- `invoke_checked` (D1) and `run_cycle` (D2) exist in `runtime/` but are never
  called. They are dead entry points — either they were superseded (by the live
  invoke path in Story 4) or they are intended future work.

## Tasks

- [ ] **Locate `invoke_checked` and `run_cycle`.** Grep `def invoke_checked`
  and `def run_cycle` in `runtime/` to find them and read their docstrings.
- [ ] **Decide remove-vs-wire.** If they are superseded by the live invoke path
  (Story 4 applies `validate_envelope` in the chain), **remove** them (delete
  the functions and their tests, if any). If they are intended future work
  (e.g. a checked-invoke wrapper), **wire** them into the live path or add a
  docstring note that they are not yet used.
- [ ] **Remove the dead references.** If removed, delete any imports of
  `invoke_checked` / `run_cycle` and their tests. Update the docstring of the
  module to reflect the removal.
- [ ] **Test:** run the full test suite (`pytest tests/`) and assert it passes
  with the dead functions removed (no orphaned references).

## Definition of done
- `invoke_checked` / `run_cycle` are removed or wired (no silently dead entry
  point).
- The test suite passes with no orphaned references.