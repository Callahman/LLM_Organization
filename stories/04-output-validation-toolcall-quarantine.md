# Story 4 — Output validation & tool_call quarantine

**Findings:** A8 (`validate_envelope` never applied), A9 (broken `tool_call`
not quarantined), R10 (malformed `tool_call` not quarantined).

**Goal:** every LLM output is envelope-validated in the live path; a broken
`tool_call` is quarantined (logged, not propagated) rather than crashing the
session or feeding a bad tool call downstream.

## Context (what exists today)
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

## Tasks

- [ ] **Apply `validate_envelope` in the live path.** At the point just after
  the raw output is produced — add it in `TimeoutBackend.invoke`
  (`runtime/llm.py:140-142`, after `box["out"]` is retrieved) or in
  `OpenAIBackend.invoke` (right before returning). Call
  `validate_envelope(output)` (import it from wherever it lives). On an invalid
  envelope, do NOT raise a crash — log a visible `[llm] invalid envelope from
  <role>: <reason>` note and either (a) return a safe fallback output (e.g.
  `{"summary": "", "error": "invalid_envelope"}`) or (b) raise a typed,
  catchable error (e.g. `InvalidEnvelopeError`) that the caller handles.
- [ ] **Quarantine broken `tool_call`s.** In the same location (or in the
  tool-dispatch logic that consumes `tool_call`), check the `tool_call` field:
  if it's present but malformed (not a dict, missing `name`, or `args` not
  parseable), **quarantine** it — log `[llm] quarantined malformed tool_call
  from <role>: <reason>`, drop it (set it to `None`), and continue with the rest
  of the output. Do NOT propagate the bad tool call.
- [ ] **Surface the quarantine in the history log.** When a tool_call is
  quarantined, call `history.log_tool_call(...)` with an `error`/`quarantined`
  marker so the audit trail records it (find the existing `log_tool_call`
  call-site in `OpenAIBackend` and mirror it for the quarantine case).
- [ ] **Tests** (`tests/test_llm.py` or a new `tests/test_envelope.py`):
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