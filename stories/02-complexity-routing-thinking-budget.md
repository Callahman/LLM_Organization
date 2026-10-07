# Story 2 — Complexity routing & thinking budget

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** A7 (`MemoryBackend` reasoning default bypasses routing), B17
(`thinking_budget` consumed but not `.env`-loadable), A6 (`ThinkingBudget.
remaining` dead).

**Goal:** restore the "complex → thinking on" feature end-to-end (routing is
used in the live path), make the thinking budget operator-settable from `.env`,
and surface the budget in observability.

## Context (before)
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

## Rollout (what was changed)
- `MemoryBackend.invoke` (`runtime/llm.py:190`) now defaults to
  `reasoning: Optional[Reasoning] = None` (was a hardcoded `Reasoning.LOW`) —
  a `None` is forwarded to the inner, which then CLASSIFIES (A7). The
  `except TypeError` fallback still forwards `reasoning` positionally.
- Every live call-site now passes an explicit
  `reasoning=classify_complexity(phase, role, signal)`:
  - `runtime/dispatch.py`: the IC self-edit invoke, the pod outcome "up the
    line" invoke, the leader/head/manager decomposition invokes, and both IC
    work invokes (7 sites).
  - `runtime/mission.py:182`: the Phase 2 mission invoke.
  - `runtime/pods.py`: the pod agenda + close invokes (2 sites).
  - `runtime/session.py`: the Phase 5 synthesis + Phase 6 evaluation invokes
    (2 sites).
  - The dead `invoke_checked` call-sites (`runtime/session.py`, D1) were left
    untouched — Story 12 removes that function.
- `THINKING_BUDGET` added to `ENV_TO_CONFIG` (`runtime/config.py:45`) —
  `.env`-loadable (B17).
- `THINKING_BUDGET` documented in `SETUP.md` (the Configuration table,
  default `10`).
- The thinking-budget remainder is surfaced in the Phase 4 + Phase 5 solo
  records (`runtime/session.py:624`, `runtime/session.py:199`) as
  `thinking_budget_remaining` (A6).
- New tests in `tests/test_complexity.py`:
  `test_live_path_high_reaches_router`,
  `test_live_path_budget_exhaustion_downgrades` (written by the agent; **run
  by the user** per the rule).

## Tasks

- [x] **Fix the `MemoryBackend` reasoning pass-through**
  (`runtime/llm.py:199-204`): ensure the `reasoning` argument is forwarded to
  `self.inner.invoke` (the `RoutingBackend`) for **every** invoke — do not
  substitute a hardcoded `Reasoning.LOW`. Verify the `except TypeError`
  fallback (raw backends with no `timeout`/`phase` params) still forwards
  `reasoning`.
- [x] **Audit the call-sites** that invoke the backend: confirm each passes an
  explicit `reasoning` (from `classify_complexity`) rather than relying on the
  default. Grep `backend.invoke(` in `runtime/` and check the `reasoning=`
  argument is present (or a deliberate `Reasoning.LOW` for a known-simple step).
- [x] **Add `THINKING_BUDGET` to the config map** (`runtime/config.py:25-43`):
  add `"THINKING_BUDGET": ("thinking_budget", int)` to `ENV_TO_CONFIG`.
- [x] **Document the knob** in `SETUP.md` (the org-tuning table, ~line 176):
  add a row for `THINKING_BUDGET` (default `10`) — "max HIGH-reasoning invokes
  per session before the budget forces a lower level."
- [x] **Surface the budget in observability** (A6, optional): in the solo record
  for Phase 4/5 (`runtime/session.py`), include the `ThinkingBudget.remaining`
  value so the dashboard can show the budget (find where `ThinkingBudget` is
  created — session.py:106 — and expose `.remaining` in a solo record).
- [x] **Integration test** (`tests/test_complexity.py` or a new
  `tests/test_routing_live.py`): use a `RoutingBackend` wrapped in a
  `MemoryBackend`; assert that a `classify_complexity(...)` call returning
  `Reasoning.HIGH` results in the `RoutingBackend` receiving `Reasoning.HIGH`
  (via a stub inner that records the `reasoning` it was called with). Assert
  the budget, once exhausted, downgrades to a lower level.

## Definition of done
- The live path routes `reasoning` through `RoutingBackend` (no bypass).
- `THINKING_BUDGET` is settable from `.env` and documented.
- The integration test proves a HIGH classification reaches the router and the
  budget downgrades when exhausted (**run by the user** per the rule).