# Story 4 — Output validation & tool_call quarantine

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** A8 (`validate_envelope` never applied), A9 (broken `tool_call`
not quarantined), R10 (malformed `tool_call` not quarantined).

**Goal:** every LLM output is envelope-validated in the live path; a broken
`tool_call` is quarantined (logged, not propagated) rather than crashing the
session or feeding a bad tool call downstream.

## Context (before)
- `validate_envelope` (in `runtime/` — grep `def validate_envelope`) exists and
  is tested, but is never called in the live invoke path. LLM outputs flow
  directly `OpenAIBackend.invoke` → `TimeoutBackend` → `RoutingBackend` →
  `MemoryBackend` → the caller, with no envelope check.
- A malformed `tool_call` (missing `name`, bad args, or a non-dict) is not
  quarantined — it propagates to the tool-dispatch logic and can crash the
  session or feed a bad call downstream.
- The live chain: `TimeoutBackend.invoke` (`runtime/llm.py:117-142`, after
  `box["out"]` is retrieved) or `OpenAIBackend.invoke`
  (`runtime/llm_api.py`, right before returning the parsed output).

## Rollout (what was changed)
- `validate_envelope` lives in `roles/base.py` (imported into `llm_api.py`);
  it was only used by the dead `invoke_checked` (Story 12 removes that).
- **Design note (envelope strictness):** `validate_envelope` originally
  required all four envelope keys, but the role output schemas
  (`roles/worker.py::_schema`) only require `summary` + `confidence` — applying
  it strictly would have replaced well-formed outputs (e.g. `{"summary":...,
  "confidence":..., "decomposition":{...}}`) with the fallback and broken the
  pipeline. So `validate_envelope` (`roles/base.py`) was **aligned with the
  schemas**: it now requires only the always-required keys (`summary` +
  `confidence`, `REQUIRED_ENVELOPE_KEYS`) and type-checks the keys that are
  present; a missing optional key (`findings` / `recommendation`) is not a
  problem. The live path calls `validate_envelope` directly (no filter).
- **Validation + quarantine** (`runtime/llm_api.py`): `validate_and_quarantine`
  (:83) envelope-validates an output (safe fallback `{"summary": "", ...,
  "error": "invalid_envelope"}` on a malformation — never a crash) and
  quarantines a malformed `tool_call` via `_tool_call_problem` (:64) (not a
  dict / missing `name` / `args` not parseable → dropped to `None`, never
  propagated). Returns `(output, events)` (the visible log lines).
- **Wired into the live path** (`runtime/llm_api.py:653`, in
  `OpenAIBackend.invoke` right after `_parse`): the events are printed to
  stderr (`[llm] invalid envelope from <role>: <reason>` / `[llm] quarantined
  malformed tool_call from <role>: <reason>`).
- **Quarantine in the history log** (task 3): an invalid envelope is recorded
  via `_report(role, "error", ...)`; a quarantined tool_call via
  `_report(role, "quarantined", ...)` — mirroring the existing `log_tool_call`
  wiring (`on_call` → `history.log_tool_call`). `_error_type` classifies the
  quarantine as `quarantined` (`runtime/llm_api.py:507`) so the audit trail
  segments it.
- **Tests** (`tests/test_envelope.py`, new): a malformed envelope (a list, or a
  missing required key) → the safe fallback; a well-formed output omitting
  optional keys → passes through unchanged; a malformed `tool_call` (not a
  dict / no `name` / unparseable args) → quarantined (dropped + logged) with
  the rest of the output returned; a well-formed `tool_call` → kept.
  (Written by the agent; **run by the user** per the rule.)

- **Existing-test fixture fix** (`tests/test_observability_hooks.py`): four
  observability tests used a minimal `{"summary": "s"}` envelope that predates
  validation; now that `confidence` is required, those fixtures were updated to
  a valid envelope (`{"summary": "s", "confidence": 0.5}`). No behavior change —
  the tests still assert the same observability outcomes.

## Tasks

- [x] **Apply `validate_envelope` in the live path.** At the point just after
  the raw output is produced — add it in `TimeoutBackend.invoke`
  (`runtime/llm.py:140-142`, after `box["out"]` is retrieved) or in
  `OpenAIBackend.invoke` (right before returning). Call
  `validate_envelope(output)` (import it from wherever it lives). On an invalid
  envelope, do NOT raise a crash — log a visible `[llm] invalid envelope from
  <role>: <reason>` note and either (a) return a safe fallback output (e.g.
  `{"summary": "", "error": "invalid_envelope"}`) or (b) raise a typed,
  catchable error (e.g. `InvalidEnvelopeError`) that the caller handles.
- [x] **Quarantine broken `tool_call`s.** In the same location (or in the
  tool-dispatch logic that consumes `tool_call`), check the `tool_call` field:
  if it's present but malformed (not a dict, missing `name`, or `args` not
  parseable), **quarantine** it — log `[llm] quarantined malformed tool_call
  from <role>: <reason>`, drop it (set it to `None`), and continue with the rest
  of the output. Do NOT propagate the bad tool call.
- [x] **Surface the quarantine in the history log.** When a tool_call is
  quarantined, call `history.log_tool_call(...)` with an `error`/`quarantined`
  marker so the audit trail records it (find the existing `log_tool_call`
  call-site in `OpenAIBackend` and mirror it for the quarantine case).
- [x] **Tests** (`tests/test_llm.py` or a new `tests/test_envelope.py`):
  - (a) Feed a malformed envelope (e.g. a list instead of a dict, or missing
    required keys) to the invoke path; assert it is validated and either
    returns the safe fallback or raises the typed error (not a crash).
  - (b) Feed a malformed `tool_call` (e.g. `tool_call="not-a-dict"` or
    `tool_call={"args": ...}` with no `name`); assert it is quarantined
    (dropped + logged) and the rest of the output is returned.

## Definition of done
- Every LLM output is envelope-validated in the live path.
- A malformed `tool_call` is quarantined (logged + dropped), never propagated.
- The quarantine is recorded in the history log.
- The tests prove both behaviors (**run by the user** per the rule).