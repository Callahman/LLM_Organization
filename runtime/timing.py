"""Invoke timing (Story 22) — per-role and per-department wall-clock time.

Two pieces:

- **``TimingTracker``**: accumulates the wall-clock time of every backend
  invoke, segmented by role and by department, and appends the running
  snapshot to ``history/efficiency.jsonl`` (an append-only log the dashboard
  tails for the **efficiency panel**). Thread-safe (a lock guards the
  accumulation; the file append is a single line).
- **``TimingBackend``**: a transparent ``LLMBackend`` wrapper that times each
  ``invoke`` (wall clock, start -> end) and records it to the tracker. All
  other attributes (``save_state`` / ``load_state`` / ``seed_cross_team`` / ...)
  are delegated to the inner backend via ``__getattr__``, so the wrapper is
  drop-in at the outermost position of the backend chain.

The efficiency panel is what the Leader is invoked with in Phase 4 (it decides
whether a role or department is inefficient and sets an ``efficiency`` action —
fire / reassign / report).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional


class TimingTracker:
    """Accumulates per-role and per-department invoke time and appends the
    running snapshot to ``history/efficiency.jsonl``.

    The snapshot is a **cumulative** state (the total time each role /
    department has spent in invokes so far), so the dashboard renders the
    latest line as the current efficiency panel.
    """

    def __init__(self, history_dir: str = "history"):
        self.history_dir = history_dir
        self._efficiency_path = os.path.join(history_dir, "efficiency.jsonl")
        self._lock = threading.Lock()
        self._per_role: Dict[str, float] = {}
        self._per_department: Dict[str, float] = {}
        self._total_time: float = 0.0
        self._total_calls: int = 0

    def record_invoke(self, role_id: str, department: str, elapsed: float) -> None:
        """Record one invoke's wall-clock time (segmented by role +
        department) and append the running snapshot to the efficiency log."""
        with self._lock:
            self._per_role[role_id] = self._per_role.get(role_id, 0.0) + elapsed
            if department:
                self._per_department[department] = \
                    self._per_department.get(department, 0.0) + elapsed
            self._total_time += elapsed
            self._total_calls += 1
            snap = {
                "ts": time.time(),
                "per_role": dict(self._per_role),
                "per_department": dict(self._per_department),
                "total_time": self._total_time,
                "total_calls": self._total_calls,
            }
        # File I/O outside the lock (a single-line append).
        self._append_efficiency(snap)

    def _append_efficiency(self, snap: Dict[str, Any]) -> None:
        os.makedirs(self.history_dir, exist_ok=True)
        with open(self._efficiency_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")

    def snapshot(self) -> Dict[str, Any]:
        """The current cumulative efficiency state (a copy — safe to read)."""
        with self._lock:
            return {
                "ts": time.time(),
                "per_role": dict(self._per_role),
                "per_department": dict(self._per_department),
                "total_time": self._total_time,
                "total_calls": self._total_calls,
            }


class TimingBackend:
    """A transparent ``LLMBackend`` wrapper that times each ``invoke`` (wall
    clock) and records it to a :class:`TimingTracker`.

    ``invoke`` forwards ``*args`` / ``**kwargs`` to the inner backend, so it is
    compatible with every backend's invoke signature (``reasoning`` /
    ``timeout`` / ``phase`` passed positionally or by keyword). All other
    attributes are delegated to the inner backend (``__getattr__``), so the
    wrapper is drop-in at the outermost position of the chain.
    """

    def __init__(self, inner, tracker: TimingTracker):
        # Note: ``inner`` is set via ``object.__setattr__``-free plain
        # assignment; ``__getattr__`` only fires for *missing* attributes, so
        # ``self.inner`` / ``self.tracker`` resolve normally.
        self.inner = inner
        self.tracker = tracker

    def invoke(self, role, context, *args, **kwargs):
        t0 = time.time()
        try:
            return self.inner.invoke(role, context, *args, **kwargs)
        finally:
            dept = getattr(role, "department", "") or ""
            self.tracker.record_invoke(role.id, dept, time.time() - t0)

    def __getattr__(self, name):
        # Delegate any attribute the wrapper does not define (save_state,
        # load_state, seed_cross_team, ...). ``__getattr__`` is only called
        # when normal lookup fails, so ``self.inner`` / ``self.tracker`` are
        # never re-routed here.
        return getattr(self.inner, name)
