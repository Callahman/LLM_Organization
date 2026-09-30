"""Tests for the observability dashboard (observability/dashboard.py).

The Watcher's ingestion is pure state mutation, so the core tests need no
files. One test exercises file polling against a temp dir, and the HTTP
tests boot the real server on an ephemeral port.
"""

import json
import os
import sys
import threading
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "observability"))

from dashboard import Watcher, make_server  # noqa: E402


# --- Watcher ingestion (pure, no files) --------------------------------------

def test_ingest_org_events_builds_department_counts():
    w = Watcher(root="/nonexistent")
    w.ingest_org_event({"kind": "bootstrapped", "target": "hr-head",
                        "detail": {"department": "hr"}, "ts": 1.0})
    w.ingest_org_event({"kind": "hired", "target": "sales-ops",
                        "detail": {"department": "sales"}, "ts": 2.0})
    w.ingest_org_event({"kind": "hired", "target": "sales-ops2",
                        "detail": {"department": "sales"}, "ts": 3.0})
    w.ingest_org_event({"kind": "fired", "target": "sales-ops2",
                        "detail": {"department": "sales"}, "ts": 4.0})
    w.ingest_org_event({"kind": "hire_vetoed", "target": "x",
                        "detail": {"department": "sales"}, "ts": 5.0})
    assert w.agents_by_dept == {"hr": 1, "sales": 1}
    assert len(w.agent_events) == 4  # a veto is not a headcount change
    ev = w.agent_events[-1]
    assert ev["kind"] == "fired" and ev["delta"] == -1


def test_snapshot_shape():
    w = Watcher(root="/nonexistent")
    w.ingest_org_event({"kind": "hired", "target": "a",
                        "detail": {"department": "sales"}, "ts": 1.0})
    w.ingest_code_edit(
        {"ts": 1.0, "role": "r", "path": "p", "ok": True, "error": ""})
    w.ingest_tool_call(
        {"ts": 1.0, "role": "r", "mode": "tools",
         "outcome": "tool_call", "error": "", "latency": 0.1})
    w.ingest_cycle(
        {"ts": 1.0, "phase": 4, "cycle": 1, "started": 0.0, "duration": 0.5})
    w.ingest_pod_transcript(
        "pod1", [{"kind": "speak", "role": "a", "summary": "s"}])
    snap = w.snapshot()
    assert snap["agents"]["total"] == 1
    assert snap["agents"]["by_department"] == {"sales": 1}
    assert len(snap["code_edits"]) == 1
    assert len(snap["tool_calls"]) == 1
    assert snap["cycles"][0]["phase"] == 4
    assert snap["pods"][0]["id"] == "pod1"
    assert snap["pods"][0]["status"] == "active"


def test_pod_transcript_active_vs_closed():
    w = Watcher(root="/nonexistent")
    w.ingest_pod_transcript("p1", [{"kind": "agenda", "role": "a"}])
    assert w.pods["p1"]["status"] == "active"
    w.ingest_pod_transcript("p1", [
        {"kind": "agenda", "role": "a"},
        {"kind": "close", "role": "a", "decision": "d"}])
    assert w.pods["p1"]["status"] == "closed"


# --- file polling (temp dir) ---------------------------------------------------

def test_poll_reads_new_lines_incrementally(tmp_path):
    h = tmp_path / "history"
    h.mkdir()
    f = h / "org_events.jsonl"
    f.write_text(
        json.dumps({"kind": "hired", "target": "a",
                    "detail": {"department": "sales"}, "ts": 1.0}) + "\n",
        encoding="utf-8")
    w = Watcher(root=str(tmp_path))
    w.poll()
    assert w.agents_by_dept == {"sales": 1}
    with open(str(f), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "hired", "target": "b",
                             "detail": {"department": "hr"}, "ts": 2.0}) + "\n")
    w.poll()
    assert w.agents_by_dept == {"sales": 1, "hr": 1}
    w.poll()  # no new lines: nothing changes
    assert len(w.agent_events) == 2


# --- HTTP server (ephemeral port) ----------------------------------------------

def _boot_server(watcher):
    server = make_server(watcher, "127.0.0.1", 0)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def test_http_state_and_index():
    w = Watcher(root="/nonexistent")
    w.ingest_org_event({"kind": "hired", "target": "a",
                        "detail": {"department": "sales"}, "ts": 1.0})
    server, port = _boot_server(w)
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/state", timeout=5) as resp:
            assert resp.status == 200
            snap = json.loads(resp.read())
        assert snap["agents"]["total"] == 1
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=5) as resp:
            body = resp.read().decode("utf-8")
        assert "Observability" in body
    finally:
        server.shutdown()


def test_http_stream_sends_sse():
    w = Watcher(root="/nonexistent")
    server, port = _boot_server(w)
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/stream", timeout=10) as resp:
            line = resp.readline().decode("utf-8").strip()
        assert line.startswith("data: ")
        snap = json.loads(line[len("data: "):])
        assert "agents" in snap
    finally:
        server.shutdown()
