# Story 7 — Pod context & lifecycle bounding

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** A2 (`bounded_assembly` dead; `_pod_ctx` unbounded), B13 (chained
pod runs on empty decision), B14 (no per-pod time/cost budget).

**Goal:** the pod context is token-bounded (via `bounded_assembly`), the chained
pod is skipped when the first pod's decision is empty, and (optionally) a pod
has a wall-clock/token budget.

## Context (what exists today)
- `_pod_ctx` (`runtime/pods.py:114-129`) joins **all** transcript `speak`
  entries (up to `max_rounds × POD_MAX_ROLES` = 18) into the context — bounded in
  entry count but **not** in tokens. `bounded_assembly` (the token-bounded
  assembler — grep `def bounded_assembly`) exists but is never used here.
- The chained pod (`runtime/dispatch.py:436-444`) runs even when the first
  pod's decision is empty.
- There is no per-pod wall-clock/token budget (only the per-invoke timeout).
- `run_pod` deliberation loop: `runtime/pods.py:159`.

## Tasks

- [ ] **Refactor `_pod_ctx` to use `bounded_assembly`.** In
  `runtime/pods.py:114`, replace the unbounded `"\n".join(parts)` with
  `bounded_assembly(parts, budget_tokens=...)` (import it from wherever it
  lives). Pass a token budget (e.g. `context_budget_tokens` — but see Story 8
  for making that knob live; for now use a constant default like 4000). Keep
  the "POD <id>: <kind> — <topic>" header **unbounded** (it must survive) and
  bound only the transcript entries.
- [ ] **Skip the chained pod on an empty first decision.** In
  `runtime/dispatch.py:433-446`, guard the `chained_pod` formation with
  `if boss_id and boss_id in roles and pod.decision.strip():` — if the first
  pod's decision is empty, skip the chained pod (log a visible `[pod] skipped
  chained pod (empty first decision)` note).
- [ ] **Add a per-pod wall-clock budget** (B14, optional): wrap the `run_pod`
  deliberation loop (`runtime/pods.py:159`) with a wall-clock check — if the
  elapsed time exceeds a per-pod budget (e.g. a `pod_wall_clock_seconds` param,
  default e.g. 600), close the pod early (`pod.closed_reason = "pod wall-clock
  budget exceeded"`). Reuse `time.monotonic()` for the timing.
- [ ] **Tests** (`tests/test_pods.py`):
  - (a) **Token bounding:** build a pod with many long `speak` entries (total
    well over the budget); assert `_pod_ctx` output is ≤ the budget tokens (or
    truncated) and the header is intact.
  - (b) **Chained pod skipped on empty decision:** a first pod with an empty
    decision → the chained pod is not formed (assert via a stub that the
    chained `run_pod` is not called).
  - (c) **Wall-clock budget** (if implemented): a pod that exceeds the budget
    closes early with the budget-exceeded reason.

## Definition of done
- The pod context is token-bounded via `bounded_assembly` (header survives).
- The chained pod is skipped when the first pod's decision is empty.
- (Optional) a pod has a wall-clock budget.