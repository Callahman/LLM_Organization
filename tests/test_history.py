"""Unit tests for `runtime/history.py` — audit trail + archives (Epic 7
Definition of Done).

From any recorded decision, the audit path to its transcripts, mission
section, and outcome is resolvable; old sessions move to the archives within
the rolling window; beyond the archive cap, the oldest are deleted first.
"""

import json
import os

from runtime.history import HistoryStore


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_audit_path_resolvable_from_decision(tmp_path):
    store = HistoryStore(
        history_dir=str(tmp_path), archives_dir=str(tmp_path / "archives")
    )
    store.log_decision(
        "pod closed on option B",
        transcripts=["pods/transcripts/pod1.jsonl"],
        artifacts=["pods/artifacts/pod1_decision.md"],
        mission_section="## Success criteria",
        outcome="shipped",
    )
    records = _read_jsonl(os.path.join(str(tmp_path), "decision_journal.jsonl"))
    assert len(records) == 1
    rec = records[0]
    # decision -> transcripts + artifacts -> mission section -> outcome.
    assert rec["decision"] == "pod closed on option B"
    assert rec["transcripts"] == ["pods/transcripts/pod1.jsonl"]
    assert rec["artifacts"] == ["pods/artifacts/pod1_decision.md"]
    assert rec["mission_section"] == "## Success criteria"
    assert rec["outcome"] == "shipped"


def test_window_moves_old_sessions_to_archives(tmp_path):
    hist = str(tmp_path)
    arch = str(tmp_path / "archives")
    store = HistoryStore(history_dir=hist, archives_dir=arch, window_sessions=3)
    # Six session files (oldest first by name).
    for i in range(6):
        store._append(f"session_{i:02d}.jsonl", {"n": i})
    moved = store.apply_window()
    # Only the last 3 stay; the oldest 3 moved to the archives.
    assert moved == 3
    remaining = sorted(f for f in os.listdir(hist) if f.endswith(".jsonl"))
    assert remaining == ["session_03.jsonl", "session_04.jsonl", "session_05.jsonl"]
    archived = sorted(os.listdir(arch))
    assert archived == ["session_00.jsonl", "session_01.jsonl", "session_02.jsonl"]


def test_archive_cap_deletes_oldest_beyond_cap(tmp_path):
    hist = str(tmp_path)
    arch = str(tmp_path / "archives")
    store = HistoryStore(
        history_dir=hist, archives_dir=arch,
        window_sessions=1, archive_cap_mb=1,
    )
    # Three archived files of 1 MiB each — 3 MiB total, over the 1 MiB cap.
    for i in range(3):
        with open(os.path.join(arch, f"old_{i:02d}.jsonl"), "w", encoding="utf-8") as f:
            f.write("x" * (1024 * 1024))
    deleted = store.enforce_archive_cap()
    # Oldest deleted first until under the cap.
    assert deleted == 2
    assert sorted(os.listdir(arch)) == ["old_02.jsonl"]


def test_maintain_applies_window_and_cap(tmp_path):
    hist = str(tmp_path)
    arch = str(tmp_path / "archives")
    store = HistoryStore(history_dir=hist, archives_dir=arch, window_sessions=2)
    for i in range(5):
        store._append(f"session_{i:02d}.jsonl", {"n": i})
    result = store.maintain()
    assert result["moved_to_archive"] == 3
    assert result["deleted_from_archive"] == 0  # far under the 1 GiB cap


def test_concurrent_appends_no_corruption(tmp_path):
    """Story 9 (B5): concurrent appends produce no interleaved/corrupted
    records (the lock serializes the size-check + rotation + write)."""
    import threading
    store = HistoryStore(history_dir=str(tmp_path))
    n_threads = 8
    m_records = 25
    def worker(tid):
        for i in range(m_records):
            store._append("concurrent.jsonl", {"tid": tid, "i": i})
    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # The file has exactly N*M records and every line is valid JSON.
    records = _read_jsonl(os.path.join(str(tmp_path), "concurrent.jsonl"))
    assert len(records) == n_threads * m_records
    # Every record is valid (the JSON parsed without error).
    for rec in records:
        assert "tid" in rec and "i" in rec


def test_coordinated_timeout_caps_httpx_read(tmp_path, monkeypatch):
    """Story 9 (B6): a per-invoke timeout passed to OpenAIBackend.invoke
    results in an httpx.Timeout(read=...) <= the bound (the param is threaded
    through and capped at the idle_timeout)."""
    import httpx
    from runtime.llm_api import OpenAIBackend
    from roles.base import Role
    # Capture the httpx.Timeout constructed by the invoke.
    captured = {}
    real_timeout = httpx.Timeout
    def fake_timeout(connect=None, read=None, write=None, pool=None, **kw):
        captured['connect'] = connect
        captured['read'] = read
        captured['write'] = write
        captured['pool'] = pool
        return real_timeout(connect=connect, read=read, write=write, pool=pool, **kw)
    monkeypatch.setattr(httpx, 'Timeout', fake_timeout)
    # A stub that raises before the httpx call (so the invoke doesn't actually
    # hit the network).
    def fake_client(*args, **kwargs):
        raise httpx.ConnectError("no network")
    monkeypatch.setattr(httpx, 'Client', fake_client)
    # An OpenAIBackend with idle_timeout=180s.
    backend = OpenAIBackend(model="m", base_url="http://localhost:1", idle_timeout=180.0)
    role = Role(id="r1", architype="ic", department="analytics", team="pipelines", reports_to="mgr")
    # Call the invoke with a per-invoke timeout of 5s.
    try:
        backend.invoke(role, "ctx", timeout=5.0)
    except Exception:
        pass
    # The httpx.Timeout(read=...) is <= the bound (5s).
    assert captured['read'] <= 5.0
    assert captured['read'] == 5.0
