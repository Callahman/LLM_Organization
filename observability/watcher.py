"""The observability dashboard — the log watcher.

The ``Watcher`` tails the organization's append-only JSONL logs (and the pod
transcript files) and maintains in-memory state: ``poll()`` runs on the
watcher thread; ``snapshot()`` is read by the HTTP server. All state access
is guarded by a lock. The ingestion methods (``ingest_*``) are pure state
mutations so the core logic is unit-testable without any files.

**Decomposition (Phase 6):** extracted from ``observability/dashboard.py``
(the thin ``main()`` entry point + facade stay there; the HTTP server moved
to ``observability/server.py``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

# Org-event kinds that change the headcount (org_events.jsonl).
HIRE_KINDS = {
    "hired", "bootstrapped", "required_department_bootstrapped",
    "leader_replaced",
}
FIRE_KINDS = {"fired"}

SNAPSHOT_CAP = 500  # max records per series in a snapshot


class Watcher:
    """Tails the org's JSONL logs + pod transcripts and maintains in-memory
    state. ``poll()`` runs on the watcher thread; ``snapshot()`` is read by
    the HTTP server. All state access is guarded by a lock.

    The ingestion methods (``ingest_*``) are pure state mutations so the
    core logic is unit-testable without any files.
    """

    def __init__(self, root: str):
        self.root = root
        h = os.path.join(root, "history")
        self.paths = {
            "org_events": os.path.join(h, "org_events.jsonl"),
            "code_edits": os.path.join(h, "code_edits.jsonl"),
            "tool_calls": os.path.join(h, "tool_calls.jsonl"),
            "cycles": os.path.join(h, "cycles.jsonl"),
            "stream": os.path.join(h, "stream.jsonl"),
            "halt_events": os.path.join(h, "halt_events.jsonl"),
            "efficiency": os.path.join(h, "efficiency.jsonl"),
            # S22: the per-iteration efficiency metrics (the Phase 3-6 loop
            # metrics: T_total, T_p, T_dept, T_role, H_peak, C, N_created,
            # M_satisfaction, E, EFFICIENCY_FLOOR).
            "efficiency_metrics": os.path.join(h, "efficiency_metrics.jsonl"),
        }
        self.transcripts_dir = os.path.join(root, "pods", "transcripts")
        self._offsets: Dict[str, int] = {}
        self._lock = threading.Lock()
        # state
        self.agents_by_dept: Dict[str, int] = {}
        self.agent_events: List[Dict[str, Any]] = []
        self.code_edits: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self.cycles: List[Dict[str, Any]] = []
        self.halt_events: List[Dict[str, Any]] = []
        self.pods: Dict[str, Dict[str, Any]] = {}
        # Story 22: the efficiency panel (per-role / per-department invoke
        # time). The efficiency log appends a *cumulative* snapshot after each
        # invoke, so the dashboard renders the LATEST line as the current
        # panel (not an accumulation).
        self.efficiency: Optional[Dict[str, Any]] = None
        # S22: the per-iteration efficiency metrics (the Phase 3-6 loop
        # metrics). The log appends one snapshot per iteration, so the
        # dashboard keeps the LATEST line as the current S22 panel.
        self.efficiency_metrics: Optional[Dict[str, Any]] = None
        # Live "model stream" window: a 2-slot ring (current + previous
        # segment). Each segment = one model call (one stream_id), with its
        # streamed content accumulated per kind (thinking/content/tool_call).
        self.stream_segments: List[Dict[str, Any]] = []
        # A6: the ts of the last streamed chunk (for the staleness gauge —
        # seconds since the model last produced output).
        self.last_stream_ts: float = 0.0

    # --- ingestion (pure state mutations) -----------------------------------

    def ingest_org_event(self, e: Dict[str, Any]) -> None:
        kind = e.get("kind", "")
        if kind not in HIRE_KINDS and kind not in FIRE_KINDS:
            return
        dept = (e.get("detail") or {}).get("department") or "leadership"
        delta = 1 if kind in HIRE_KINDS else -1
        self.agents_by_dept[dept] = max(
            0, self.agents_by_dept.get(dept, 0) + delta)
        self.agent_events.append({
            "ts": e.get("ts", time.time()), "kind": kind,
            "target": e.get("target", ""), "department": dept,
            "delta": delta,
        })

    def ingest_code_edit(self, e: Dict[str, Any]) -> None:
        self.code_edits.append(e)

    def ingest_tool_call(self, e: Dict[str, Any]) -> None:
        self.tool_calls.append(e)

    def ingest_cycle(self, e: Dict[str, Any]) -> None:
        self.cycles.append(e)

    def ingest_halt(self, e: Dict[str, Any]) -> None:
        self.halt_events.append(e)

    def ingest_efficiency(self, e: Dict[str, Any]) -> None:
        """Ingest one efficiency snapshot (from history/efficiency.jsonl). The
        log appends a *cumulative* snapshot after each invoke, so each line is
        the full current state — the dashboard keeps the LATEST line as the
        current efficiency panel (per-role / per-department invoke time)."""
        self.efficiency = e

    def ingest_s22_efficiency(self, e: Dict[str, Any]) -> None:
        """Ingest one S22 per-iteration efficiency snapshot (from
        history/efficiency_metrics.jsonl). The log appends one snapshot per
        loop iteration, so the dashboard keeps the LATEST line as the current
        S22 panel (the Phase 3-6 loop metrics: T_total, T_p, T_dept, T_role,
        H_peak, C, N_created, M_satisfaction, E, EFFICIENCY_FLOOR)."""
        self.efficiency_metrics = e

    def ingest_pod_transcript(
        self, pod_id: str, entries: List[Dict[str, Any]]
    ) -> None:
        closed = any(en.get("kind") == "close" for en in entries)
        self.pods[pod_id] = {
            "id": pod_id,
            "status": "closed" if closed else "active",
            "entries": entries,
            "updated": time.time(),
        }

    def ingest_stream(self, e: Dict[str, Any]) -> None:
        """Ingest one streamed chunk (from history/stream.jsonl). Chunks are
        grouped by stream_id (one per model call) and accumulated per kind
        (thinking/content/tool_call). The window is a 2-slot ring: a new
        stream_id shifts the ring (current -> previous, new -> current), so
        only the current + previous model call are retained (short-term)."""
        stream_id = e.get("stream_id", "")
        if not stream_id:
            return
        # A6: record the ts of the last streamed chunk (for the staleness
        # gauge). The record may carry an explicit ts; otherwise use now.
        self.last_stream_ts = float(e.get("ts") or time.time())
        kind = e.get("kind", "")
        text = e.get("text", "")
        # A new stream_id = a new segment (a new model call): shift the ring.
        if not self.stream_segments or \
                self.stream_segments[0]["stream_id"] != stream_id:
            self.stream_segments.insert(0, {
                "stream_id": stream_id,
                "role": e.get("role", ""),
                "model": e.get("model", ""),
                "label": e.get("label", ""),
                "reasoning": e.get("reasoning", ""),
                "kinds": {"thinking": "", "content": "", "tool_call": ""},
                "updated": time.time(),
            })
            del self.stream_segments[2:]  # keep only current + previous
        # Accumulate the chunk into the current segment's kind.
        seg = self.stream_segments[0]
        if kind in seg["kinds"]:
            seg["kinds"][kind] += text
        seg["updated"] = time.time()

    # --- file polling --------------------------------------------------------

    def seed_transcripts(self) -> None:
        """Ingest every **existing** pod transcript as **closed history** (from
        a prior run) so the historical list is populated at startup (A1). The
        offsets are set to the file sizes so the content isn't re-ingested until
        the file changes; the current run's pods are created *after* startup, so
        they aren't pre-existing and still appear live in the active pane.
        Pre-existing pods are marked closed regardless of their entries (the
        prior run is over), so a stale *active* pod isn't re-shown as active."""
        if not os.path.isdir(self.transcripts_dir):
            return
        for name in os.listdir(self.transcripts_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.transcripts_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entries = [json.loads(ln) for ln in f if ln.strip()]
            except (OSError, json.JSONDecodeError):
                continue
            try:
                self._offsets[path] = os.path.getsize(path)
            except OSError:
                continue
            self.seed_pod_transcript(name[:-len(".jsonl")], entries)

    def seed_pod_transcript(
        self, pod_id: str, entries: List[Dict[str, Any]]
    ) -> None:
        """Ingest a **pre-existing** transcript as closed history (A1). The pod
        is marked closed regardless of its entries (the prior run is over), so
        it appears in the historical list, not the active pane."""
        self.pods[pod_id] = {
            "id": pod_id,
            "status": "closed",
            "entries": entries,
            "updated": time.time(),
        }

    def _read_new_lines(self, path: str) -> List[str]:
        if not os.path.exists(path):
            return []
        size = os.path.getsize(path)
        offset = self._offsets.get(path, 0)
        if size < offset:  # rotated / truncated: re-read from the start
            offset = 0
        if size == offset:
            return []
        with open(path, "r", encoding="utf-8") as f:
            f.seek(offset)
            data = f.read()
        self._offsets[path] = size
        return [ln for ln in data.splitlines() if ln.strip()]

    def _poll_transcripts(self) -> None:
        if not os.path.isdir(self.transcripts_dir):
            return
        for name in os.listdir(self.transcripts_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.transcripts_dir, name)
            # write_transcripts rewrites the whole file: re-read on any change.
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if self._offsets.get(path) == size:
                continue
            self._offsets[path] = size
            try:
                with open(path, "r", encoding="utf-8") as f:
                    entries = [json.loads(ln) for ln in f if ln.strip()]
            except (json.JSONDecodeError, OSError):
                continue
            self.ingest_pod_transcript(name[:-6], entries)

    def poll(self) -> None:
        with self._lock:
            for key, path in self.paths.items():
                for line in self._read_new_lines(path):
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if key == "org_events":
                        self.ingest_org_event(e)
                    elif key == "code_edits":
                        self.ingest_code_edit(e)
                    elif key == "tool_calls":
                        self.ingest_tool_call(e)
                    elif key == "stream":
                        self.ingest_stream(e)
                    elif key == "halt_events":
                        self.ingest_halt(e)
                    elif key == "efficiency":
                        self.ingest_efficiency(e)
                    elif key == "efficiency_metrics":
                        self.ingest_s22_efficiency(e)
                    else:
                        self.ingest_cycle(e)
            self._poll_transcripts()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            pods = [
                {
                    "id": p["id"],
                    "status": p["status"],
                    "updated": p["updated"],
                    "entries": p["entries"][-200:],
                }
                for p in (self.pods[k] for k in sorted(self.pods))
            ]
            # Oldest first, newest last: the ring is [current, previous], so
            # emit it reversed -> [previous, current]. The dashboard renders
            # in array order, so the previous call sits on top and the current
            # (growing) call at the bottom — the most recent output is always
            # at the bottom, like a terminal.
            # The current segment (self.stream_segments[0]) is still streaming —
            # keep it capped so the per-second SSE payload stays small while a
            # call is actively growing. The previous segment(s) are complete —
            # emit them in full (the user should see the whole finished call,
            # not a 4000-char cut).
            stream = [
                {
                    "stream_id": s["stream_id"],
                    "role": s["role"],
                    "model": s["model"],
                    "label": s.get("label", ""),
                    "reasoning": s.get("reasoning", ""),
                    "kinds": (
                        {k: v for k, v in s["kinds"].items()}
                        if s is not self.stream_segments[0]
                        else {k: v[-4000:] for k, v in s["kinds"].items()}
                    ),
                    "updated": s["updated"],
                }
                for s in reversed(self.stream_segments)
            ]
            return {
                "ts": time.time(),
                # A6: the ts of the last streamed chunk (for the staleness
                # gauge — the dashboard computes seconds-since = ts -
                # last_stream_ts).
                "last_stream_ts": self.last_stream_ts,
                "agents": {
                    "by_department": dict(self.agents_by_dept),
                    "total": sum(self.agents_by_dept.values()),
                    "events": self.agent_events[-SNAPSHOT_CAP:],
                },
                "code_edits": self.code_edits[-SNAPSHOT_CAP:],
                "tool_calls": self.tool_calls[-SNAPSHOT_CAP:],
                "cycles": self.cycles[-SNAPSHOT_CAP:],
                "halt_events": self.halt_events[-SNAPSHOT_CAP:],
                # Story 22: the efficiency panel (per-role / per-department
                # invoke time) — the latest cumulative snapshot.
                "efficiency": self.efficiency,
                # S22: the per-iteration efficiency metrics (the Phase 3-6
                # loop metrics) — the latest per-iteration snapshot.
                "efficiency_metrics": self.efficiency_metrics,
                "pods": pods,
                "stream": stream,
            }


__all__ = ["HIRE_KINDS", "FIRE_KINDS", "SNAPSHOT_CAP", "Watcher"]
