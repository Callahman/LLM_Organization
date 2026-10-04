"""Operator-owned real-time observability dashboard for the Organization.

Zero new dependencies (stdlib only) and fully self-contained (no CDN): a
watcher thread tails the organization's append-only JSONL logs (and the pod
transcript files) and maintains in-memory state; a small HTTP server renders
a localhost dashboard with live charts —

- **agents over time** (segmented by department),
- **code edits over time** (applied vs refused),
- **tool calls over time** (by outcome: tool_call / content_fallback / error),
- **cycle duration per iteration** (phase 4/5/6 durations),

plus a real-time **conversation monitor** (the active pod's transcript live,
last-N historical pods expandable). Historical pods only populate as pods are
spun up (transcript files created or rewritten after the dashboard starts);
prior runs' transcript files are seeded (suppressed) at startup.

The dashboard only READS the organization's state; agents can never write
here (``observability/`` is locked in ``runtime/permissions.py``).

Run:
    python observability/dashboard.py [--port 8090] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")

# Org-event kinds that change the headcount (org_events.jsonl).
HIRE_KINDS = {
    "hired", "bootstrapped", "required_department_bootstrapped",
    "leader_replaced",
}
FIRE_KINDS = {"fired"}

POLL_INTERVAL = 1.0
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
        self.pods: Dict[str, Dict[str, Any]] = {}
        # Live "model stream" window: a 2-slot ring (current + previous
        # segment). Each segment = one model call (one stream_id), with its
        # streamed content accumulated per kind (thinking/content/tool_call).
        self.stream_segments: List[Dict[str, Any]] = []

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
        kind = e.get("kind", "")
        text = e.get("text", "")
        # A new stream_id = a new segment (a new model call): shift the ring.
        if not self.stream_segments or \
                self.stream_segments[0]["stream_id"] != stream_id:
            self.stream_segments.insert(0, {
                "stream_id": stream_id,
                "role": e.get("role", ""),
                "model": e.get("model", ""),
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
        """Record the size of every **existing** pod transcript file without
        ingesting its content.

        Called once when the dashboard starts: 'Historical pods' must only
        populate as pods are spun up (files created or rewritten *after* the
        dashboard starts), not from prior runs' transcript files. ``poll()``
        skips a transcript file whose size equals the recorded offset, so the
        seeded offsets suppress the existing files until they change.
        """
        if not os.path.isdir(self.transcripts_dir):
            return
        for name in os.listdir(self.transcripts_dir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(self.transcripts_dir, name)
            try:
                self._offsets[path] = os.path.getsize(path)
            except OSError:
                pass

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
            stream = [
                {
                    "stream_id": s["stream_id"],
                    "role": s["role"],
                    "model": s["model"],
                    "kinds": {k: v[-4000:] for k, v in s["kinds"].items()},
                    "updated": s["updated"],
                }
                for s in reversed(self.stream_segments)
            ]
            return {
                "ts": time.time(),
                "agents": {
                    "by_department": dict(self.agents_by_dept),
                    "total": sum(self.agents_by_dept.values()),
                    "events": self.agent_events[-SNAPSHOT_CAP:],
                },
                "code_edits": self.code_edits[-SNAPSHOT_CAP:],
                "tool_calls": self.tool_calls[-SNAPSHOT_CAP:],
                "cycles": self.cycles[-SNAPSHOT_CAP:],
                "pods": pods,
                "stream": stream,
            }


# --- HTTP server -------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    watcher: Optional[Watcher] = None  # bound by make_server()

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: str, ctype: str) -> None:
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, b"not found", "text/plain")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                data = json.dumps(self.watcher.snapshot())
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                time.sleep(POLL_INTERVAL)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the client went away

    def do_GET(self):  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._serve_file(
                os.path.join(WEB_DIR, "index.html"),
                "text/html; charset=utf-8")
        elif path.startswith("/web/"):
            name = os.path.basename(path)
            ctype = ("application/javascript"
                     if name.endswith(".js") else "text/css")
            self._serve_file(os.path.join(WEB_DIR, name), ctype)
        elif path == "/api/state":
            self._send(200, json.dumps(self.watcher.snapshot()).encode(),
                       "application/json")
        elif path == "/api/stream":
            self._stream()
        else:
            self._send(404, b"not found", "text/plain")


def make_server(watcher: Watcher, host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"watcher": watcher})
    return ThreadingHTTPServer((host, port), handler)


# --- entry point -------------------------------------------------------------

def _watch_loop(watcher: Watcher) -> None:
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            watcher.poll()
        except Exception:
            pass  # the dashboard must never break; keep polling


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Real-time observability dashboard (read-only).")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", default=os.path.dirname(HERE),
                    help="the Organization root (default: the repo root)")
    args = ap.parse_args()

    watcher = Watcher(args.root)
    # 'Historical pods' only populates as pods are spun up: seed the existing
    # transcript files' sizes (suppressing their prior content) BEFORE the
    # initial load, so only files created/changed after startup are ingested.
    watcher.seed_transcripts()
    watcher.poll()  # initial load (existing history)
    threading.Thread(target=_watch_loop, args=(watcher,), daemon=True).start()
    server = make_server(watcher, args.host, args.port)
    print(f"Observability dashboard: http://{args.host}:{args.port}"
          f"  (root: {args.root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
