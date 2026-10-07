# Story 2 — Complexity routing & thinking budget

**Findings:** A7 (`MemoryBackend` reasoning default bypasses routing), B17
(`thinking_budget` consumed but not `.env`-loadable), A6 (`ThinkingBudget.
remaining` dead).

**Goal:** restore the "complex → thinking on" feature end-to-end (routing is
used in the live path), make the thinking budget operator-settable from `.env`,
and surface the budget in observability.

## Context (what exists today)
- Backend chain: `MemoryBackend → RoutingBackend → TimeoutBackend →
  OpenAIBackend` (`runtime/llm.py`).
- `MemoryBackend.invoke` (`runtime/llm.py:189-220`) calls
  `self.inner.invoke(role, full_prompt, reasoning, timeout=..., phase=...)`,
  but the **default** `reasoning=Reasoning.LOW` at most call-sites means
  `RoutingBackend` (which maps `reasoning` → the model's "thinking" flag) is
  effectively bypassed for most invokes.
- `RoutingBackend` exists and is tested; the fix is to make the live path
  actually route `reasoning`.
- `ThinkingBudget` (`runtime/` — created at `runtime/session.py:106` with
  `max_high=self.config.get("thinking_budget", 10)`) — but `thinking_budget` is
  **not** in the `ENV_TO_CONFIG` map (`runtime/config.py:25-43`), so it is not
  `.env`-loadable.

## Tasks

- [ ] **Fix the `MemoryBackend` reasoning pass-through**
  (`runtime/llm.py:199-204`): ensure the `reasoning` argument is forwarded to
  `self.inner.invoke` (the `RoutingBackend`) for **every** invoke — do not
  substitute a hardcoded `Reasoning.LOW`. Verify the `except TypeError`
  fallback (raw backends with no `timeout`/`phase` params) still forwards
  `reasoning`.
- [ ] **Audit the call-sites** that invoke the backend: confirm each passes an
  explicit `reasoning` (from `classify_complexity`) rather than relying on the
  default. Grep `backend.invoke(` in `runtime/` and check the `reasoning=`
  argument is present (or a deliberate `Reasoning.LOW` for a known-simple step).
- [ ] **Add `THINKING_BUDGET` to the config map** (`runtime/config.py:25-43`):
  add `"THINKING_BUDGET": ("thinking_budget", int)` to `ENV_TO_CONFIG`.
- [ ] **Document the knob** in `SETUP.md` (the org-tuning table, ~line 176):
  add a row for `THINKING_BUDGET` (default `10`) — "max HIGH-reasoning invokes
  per session before the budget forces a lower level."
- [ ] **Surface the budget in observability** (A6, optional): in the solo record
  for Phase 4/5 (`runtime/session.py`), include the `ThinkingBudget.remaining`
  value so the dashboard can show the budget (find where `ThinkingBudget` is
  created — session.py:106 — and expose `.remaining` in a solo record).
- [ ] **Integration test** (`tests/test_complexity.py` or a new
  `tests/test_routing_live.py`): use a `RoutingBackend` wrapped in a
  `MemoryBackend`; assert that a `classify_complexity(...)` call returning
  `Reasoning.HIGH` results in the `RoutingBackend` receiving `Reasoning.HIGH`
  (via a stub inner that records the `reasoning` it was called with). Assert
  the budget, once exhausted, downgrades to a lower level.

## Definition of done
- The live path routes `reasoning` through `RoutingBackend` (no bypass).
- `THINKING_BUDGET` is settable from `.env` and documented.
- The integration test proves a HIGH classification reaches the router and the
  budget downgrades when exhausted.