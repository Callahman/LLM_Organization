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
