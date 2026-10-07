# Story 9 — Concurrency safety

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

- [ ] **Add a lock to `HistoryStore._append`.** In `runtime/history.py`, add a
  `threading.Lock` (e.g. `self._lock = threading.Lock()` in `__init__`,
  history.py:25-39) and wrap the size-check + `_rotate` + write in
  `with self._lock:` (history.py:48-51). This serializes all appends (and the
  rotation) so no two writers interleave or double-rotate.
- [ ] **Coordinate the `TimeoutBackend` and httpx timeouts.** In
  `TimeoutBackend.invoke` (`runtime/llm.py:117-142`), pass the effective
  timeout down to the inner backend (thread it through `RoutingBackend` →
  `OpenAIBackend`) so the `httpx` `read` timeout is ≤ the `TimeoutBackend`
  bound. Concretely: add a `timeout` param to `OpenAIBackend.invoke`
  (`runtime/llm_api.py`) and use it as the `httpx.Timeout(read=...)` value
  (capped at the existing `idle_timeout`). If a per-invoke timeout is not
  provided, keep the existing `idle_timeout`.
- [ ] **Bound the zombie on timeout.** After `TimeoutBackend` raises
  `LLMTimeoutError` (llm.py:137-139), the daemon thread will finish when the
  (now-coordinated) httpx timeout trips. Add a visible `[llm] invoke for
  <role> timed out at <N>s — the underlying call is bounded to <N>s` note so
  the operator knows the bound.
- [ ] **Tests** (`tests/test_history.py` or a new one):
  - (a) **Concurrent appends:** spawn N threads each appending M records to the
    same `HistoryStore` log; assert the file has exactly N×M records and every
    line is valid JSON (no interleaved/corrupted records).
  - (b) **Coordinated timeout:** assert that a per-invoke timeout passed to
    `OpenAIBackend.invoke` results in an `httpx.Timeout(read=...)` ≤ the bound
    (inspect the constructed `httpx.Timeout` via a stub, or assert the param is
    threaded through).

## Definition of done
- `HistoryStore` writes are serialized (concurrent appends produce no
  corruption).
- A `TimeoutBackend` timeout bounds the underlying HTTP call (no long-lived
  zombie).