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


def test_solo_pod_closes_on_close_entry():
    # A1: a solo pod that emits a terminal `close` step (when its phase
    # completes) is marked closed, so the dashboard moves it to the historical
    # list (not stuck on the active pane).
    w = Watcher(root="/nonexistent")
    w.ingest_pod_transcript("solo_leader_p1", [
        {"kind": "intake", "role": "leader", "summary": "intake converged"}])
    assert w.pods["solo_leader_p1"]["status"] == "active"
    w.ingest_pod_transcript("solo_leader_p1", [
        {"kind": "intake", "role": "leader", "summary": "intake converged"},
        {"kind": "close", "role": "leader",
         "decision": "intake converged=True, 2 rounds"}])
    assert w.pods["solo_leader_p1"]["status"] == "closed"


def test_seed_transcripts_ingests_closed_history(tmp_path):
    # A1: seed_transcripts ingests every **existing** transcript as closed
    # history (from a prior run) so the historical list is populated at
    # startup. The pod is marked closed regardless of its entries.
    tdir = tmp_path / "pods" / "transcripts"
    tdir.mkdir(parents=True)
    (tdir / "solo_leader_p2.jsonl").write_text(
        json.dumps({"kind": "mission", "role": "leader",
                    "summary": "mission approved"}) + "\n",
        encoding="utf-8")
    w = Watcher(root=str(tmp_path))
    w.seed_transcripts()
    assert "solo_leader_p2" in w.pods
    assert w.pods["solo_leader_p2"]["status"] == "closed"
    assert w.pods["solo_leader_p2"]["entries"][0]["kind"] == "mission"


def test_ingest_halt_event_appends_to_state():
    # A6: the halt pane lists Safety/Morality halt events (from
    # halt_events.jsonl). ingest_halt appends the event to the state.
    w = Watcher(root="/nonexistent")
    w.ingest_halt({"kind": "safety_halt", "reason": "policy violation",
                   "ts": 1.0})
    assert len(w.halt_events) == 1
    assert w.halt_events[0]["kind"] == "safety_halt"
    assert w.halt_events[0]["reason"] == "policy violation"


def test_last_stream_ts_exposed_in_snapshot():
    # A6: the staleness gauge reads "last stream chunk ts" from the snapshot
    # (the dashboard computes seconds-since = ts - last_stream_ts).
    w = Watcher(root="/nonexistent")
    w.ingest_stream({"stream_id": "s1", "role": "leader", "model": "qwen",
                     "kind": "content", "text": "hi", "ts": 123.0})
    snap = w.snapshot()
    assert snap["last_stream_ts"] == 123.0


def test_ingest_stream_groups_by_stream_id_and_kind():
    # The Watcher groups streamed chunks by stream_id (one per model call)
    # and accumulates them per kind (thinking/content/tool_call). The window
    # is a 2-slot ring: a new stream_id shifts the ring (current -> previous,
    # new -> current), so only the current + previous model call are retained.
    w = Watcher(root="/nonexistent")
    # Segment 1 (stream_id "s1"): thinking + content.
    w.ingest_stream({"stream_id": "s1", "role": "leader", "model": "qwen",
                     "kind": "thinking", "text": "let me "})
    w.ingest_stream({"stream_id": "s1", "role": "leader", "model": "qwen",
                     "kind": "thinking", "text": "think..."})
    w.ingest_stream({"stream_id": "s1", "role": "leader", "model": "qwen",
                     "kind": "content", "text": "reply"})
    assert len(w.stream_segments) == 1
    seg1 = w.stream_segments[0]
    assert seg1["stream_id"] == "s1"
    assert seg1["kinds"]["thinking"] == "let me think..."
    assert seg1["kinds"]["content"] == "reply"
    # Segment 2 (stream_id "s2"): a new model call -> shift the ring.
    w.ingest_stream({"stream_id": "s2", "role": "ic", "model": "qwen",
                     "kind": "tool_call", "text": '{"summary": "s"}'})
    assert len(w.stream_segments) == 2
    assert w.stream_segments[0]["stream_id"] == "s2"  # current
    assert w.stream_segments[1]["stream_id"] == "s1"  # previous
    # Segment 3 (stream_id "s3"): a new model call -> drop the oldest.
    w.ingest_stream({"stream_id": "s3", "role": "leader", "model": "qwen",
                     "kind": "thinking", "text": "again"})
    assert len(w.stream_segments) == 2
    assert w.stream_segments[0]["stream_id"] == "s3"  # current
    assert w.stream_segments[1]["stream_id"] == "s2"  # previous (s1 dropped)
    # The snapshot exposes the 2-slot ring, oldest first (previous on top,
    # current at the bottom — the most recent output is always at the bottom).
    snap = w.snapshot()
    assert [s["stream_id"] for s in snap["stream"]] == ["s2", "s3"]


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
