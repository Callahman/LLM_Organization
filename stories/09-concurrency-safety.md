# Story 9 — Concurrency safety

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** B5 (`HistoryStore` not safe under concurrent writers), B6
(`TimeoutBackend` and httpx timeouts independent → zombie thread).

**Goal:** `HistoryStore` writes are serialized (no interleaved/corrupted
records); a `TimeoutBackend` timeout actually bounds the underlying HTTP call
(no long-lived zombie thread).

## Context (what exists today)
- `HistoryStore._append` (`runtime/history.py:43-52`) takes no lock, and the
  rotation (check-then-act at history.py:48-49) is racy. Each log type has its
  own file, so the current *sequential* design avoids same-file conflicts, but a
  zombie thread (B6) or a future concurrent-LLM-call refactor would create
  same-file races.
- `TimeoutBackend` (`runtime/llm.py:117-142`) raises `LLMTimeoutError` on
  timeout but cannot stop the daemon thread — the `httpx` call
  (`runtime/llm_api.py:539`, `connect=10s`, `read=idle_timeout` default 180s)
  keeps running until *its* timeout trips. The effective bound is
  `max(TimeoutBackend, httpx)`, not `min`.

## Tasks

- [x] **Add a lock to `HistoryStore._append`.** In `runtime/history.py`, add a
  `threading.Lock` (e.g. `self._lock = threading.Lock()` in `__init__`,
  history.py:25-39) and wrap the size-check + `_rotate` + write in
  `with self._lock:` (history.py:48-51). This serializes all appends (and the
  rotation) so no two writers interleave or double-rotate.
  (Added `import threading` + `self._lock = threading.Lock()` in `__init__`;
  wrapped the size-check + `_rotate` + write in `with self._lock:`.)
- [x] **Coordinate the `TimeoutBackend` and httpx timeouts.** In
  `TimeoutBackend.invoke` (`runtime/llm.py:117-142`), pass the effective
  timeout down to the inner backend (thread it through `RoutingBackend` →
  `OpenAIBackend`) so the `httpx` `read` timeout is ≤ the `TimeoutBackend`
  bound. Concretely: add a `timeout` param to `OpenAIBackend.invoke`
  (`runtime/llm_api.py`) and use it as the `httpx.Timeout(read=...)` value
  (capped at the existing `idle_timeout`). If a per-invoke timeout is not
  provided, keep the existing `idle_timeout`.
  (`TimeoutBackend.worker` now passes `timeout=effective` to the inner invoke;
  `OpenAIBackend.invoke` uses `min(self.idle_timeout, timeout)` as the `read`
  timeout when `timeout` is provided, else `self.idle_timeout`.)
- [x] **Bound the zombie on timeout.** After `TimeoutBackend` raises
  `LLMTimeoutError` (llm.py:137-139), the daemon thread will finish when the
  (now-coordinated) httpx timeout trips. Add a visible `[llm] invoke for
  <role> timed out at <N>s — the underlying call is bounded to <N>s` note so
  the operator knows the bound.
  (Added a visible `[llm]` note to stderr before raising `LLMTimeoutError`.)
- [x] **Tests** (`tests/test_history.py` or a new one):
  - (a) **Concurrent appends:** spawn N threads each appending M records to the
    same `HistoryStore` log; assert the file has exactly N×M records and every
    line is valid JSON (no interleaved/corrupted records).
  - (b) **Coordinated timeout:** assert that a per-invoke timeout passed to
    `OpenAIBackend.invoke` results in an `httpx.Timeout(read=...)` ≤ the bound
    (inspect the constructed `httpx.Timeout` via a stub, or assert the param is
    threaded through).
  (Written by the agent; run by the user per the rule.)

## Definition of done
- `HistoryStore` writes are serialized (concurrent appends produce no
  corruption).
- A `TimeoutBackend` timeout bounds the underlying HTTP call (no long-lived
  zombie).

## Rollout (what was changed)
- **`runtime/history.py`** — added `import threading` + `self._lock =
  threading.Lock()` in `HistoryStore.__init__`; wrapped the size-check +
  `_rotate` + write in `_append` in `with self._lock:` (serializes all appends
  and the rotation so no two writers interleave or double-rotate).
- **`runtime/llm.py`** — `TimeoutBackend.worker` now passes `timeout=effective`
  to the inner invoke (threading the effective timeout down to the inner
  backend); added a visible `[llm] invoke for <role> timed out at <N>s — the
  underlying call is bounded to <N>s` note to stderr before raising
  `LLMTimeoutError`.
- **`runtime/llm_api.py`** — `OpenAIBackend.invoke` now uses
  `min(self.idle_timeout, timeout)` as the `httpx.Timeout(read=...)` value when
  a per-invoke `timeout` is provided (else `self.idle_timeout`), so the
  underlying HTTP call is bounded to the `TimeoutBackend`'s bound (no
  long-lived zombie thread).
- **`tests/test_history.py`** — added two tests: (a) `test_concurrent_appends_no_corruption`
  (spawn 8 threads each appending 25 records to the same log; assert the file
  has exactly 200 records and every line is valid JSON); (b)
  `test_coordinated_timeout_caps_httpx_read` (assert a per-invoke timeout of 5s
  results in an `httpx.Timeout(read=5.0)` — the param is threaded through and
  capped at the `idle_timeout`).