"""Unit tests for Epic 9 hardening — timeouts + log rotation.

A backend invoke that exceeds its timeout raises a visible `LLMTimeoutError`
(never silent); a log that grows past its cap rotates to a numbered file and
starts fresh.
"""

import os
import time

from roles.leader import make_leader
from runtime.llm import (
    LLMBackend,
    TimeoutBackend,
    LLMTimeoutError,
    Reasoning,
)
from runtime.history import HistoryStore


class SlowBackend(LLMBackend):
    """A backend that sleeps — to exercise the timeout guard. Conforms to the
    `LLMBackend` interface (accepts the optional `reasoning` level the
    wrappers pass through)."""

    def __init__(self, delay: float):
        self.delay = delay

    def invoke(self, role, context: str, reasoning: Reasoning = Reasoning.LOW):
        time.sleep(self.delay)
        return {"summary": "ok", "findings": [], "recommendation": "", "confidence": 0.9}


def test_timeout_raises_visible_error():
    slow = SlowBackend(delay=2.0)
    guarded = TimeoutBackend(slow, timeout_seconds=0.2)
    leader = make_leader()
    try:
        guarded.invoke(leader, "ctx")
        raise AssertionError("expected LLMTimeoutError")
    except LLMTimeoutError as e:
        assert "exceeded" in str(e)


def test_timeout_passes_when_fast():
    fast = SlowBackend(delay=0.01)
    guarded = TimeoutBackend(fast, timeout_seconds=2.0)
    leader = make_leader()
    out = guarded.invoke(leader, "ctx")
    assert out.get("summary") == "ok"


def _rotated(files):
    """The rotated log files (`<name>.<n>.jsonl`) — the numbered ones, not the
    current (unnumbered) log."""
    return [
        f for f in files
        if f.startswith("decision_journal.") and f != "decision_journal.jsonl"
    ]


def test_log_rotation(tmp_path):
    store = HistoryStore(history_dir=str(tmp_path), max_log_bytes=200)
    for i in range(30):
        store.log_decision(f"decision number {i} with a longer body text", outcome="ok")
    files = os.listdir(str(tmp_path))
    # At least one rotated file (numbered) exists.
    rotated = _rotated(files)
    assert len(rotated) >= 1
    # The main (fresh) file still exists after the last rotation.
    assert "decision_journal.jsonl" in files


def test_rotation_preserves_numbering(tmp_path):
    store = HistoryStore(history_dir=str(tmp_path), max_log_bytes=150)
    for i in range(20):
        store.log_decision(f"decision number {i} with a longer body", outcome="ok")
    files = sorted(
        _rotated(os.listdir(str(tmp_path)))
    )
    # At least one rotated file (non-vacuous).
    assert len(files) >= 1
    # Numbered sequentially from 1 (decision_journal.1.jsonl, .2, ...).
    nums = []
    for f in files:
        assert f.endswith(".jsonl")
        num = int(f.split(".")[1])
        assert num >= 1
        nums.append(num)
    assert nums == list(range(1, len(nums) + 1))
