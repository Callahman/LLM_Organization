"""Unit tests for `runtime/checkpoint.py` — the work-item checkpointing
feature (the WorkItemTracker + the CheckpointBackend's N-action cadence).

The feature:
- A `WorkItemTracker` records per-phase work-item progress (which departments /
  teams / ICs are completed, which is in progress). This is the checkpoint's
  recovery state, persisted to `state/checkpoint.json` and used on resume to
  skip completed work items (exact next-role resumption).
- A `CheckpointBackend` is a transparent `LLMBackend` wrapper that counts every
  `invoke` and fires the session's N-action checkpoint callback every N
  invokes. It also injects the (scoped) "verify your work" preamble when
  resuming from a checkpoint.
"""

import json

import pytest

from runtime.checkpoint import (
    VERIFY_WORK_PREAMBLE,
    CheckpointBackend,
    WorkItemTracker,
)


# ---------------------------------------------------------------------------
# WorkItemTracker
# ---------------------------------------------------------------------------

def test_tracker_mark_and_complete():
    t = WorkItemTracker()
    t.mark_started(4, "head_analytics", "department")
    assert not t.is_completed(4, "head_analytics")
    t.mark_completed(4, "head_analytics")
    assert t.is_completed(4, "head_analytics")


def test_tracker_is_completed_unknown():
    t = WorkItemTracker()
    assert not t.is_completed(4, "head_analytics")
    assert not t.is_completed(5, "team_x")
    assert not t.is_completed(6, "ic_y")


def test_tracker_seed_one_arg():
    """seed() takes one arg (the completed dict) and coerces string keys."""
    t = WorkItemTracker()
    # string keys (from JSON) are coerced to ints.
    t.seed({"4": ["head_a"], "5": ["team_b"], "6": ["ic_c"]})
    assert t.is_completed(4, "head_a")
    assert t.is_completed(5, "team_b")
    assert t.is_completed(6, "ic_c")


def test_tracker_seed_dedupes():
    """seed() de-duplicates ids against the existing buckets."""
    t = WorkItemTracker()
    t.mark_completed(4, "head_a")
    # seeding the same id again does not duplicate it.
    t.seed({4: ["head_a", "head_b"]})
    assert t.completed[4] == ["head_a", "head_b"]


def test_tracker_current_work_item():
    t = WorkItemTracker()
    t.mark_started(4, "head_analytics", "department")
    assert t.current is not None
    assert t.current["phase"] == 4
    assert t.current["id"] == "head_analytics"
    assert t.current["kind"] == "department"
    # mark_completed clears the current work item.
    t.mark_completed(4, "head_analytics")
    assert t.current is None


def test_tracker_snapshot_roundtrip():
    """snapshot() is JSON-serializable and round-trips through seed()."""
    t = WorkItemTracker()
    t.mark_completed(4, "head_a")
    t.mark_completed(5, "team_b")
    t.mark_started(6, "ic_c", "ic")
    # the snapshot is JSON-serializable.
    s = json.dumps(t.snapshot())
    # a new tracker seeded from the snapshot has the same completed items.
    t2 = WorkItemTracker()
    t2.seed(json.loads(s)["completed_work_items"])
    assert t2.is_completed(4, "head_a")
    assert t2.is_completed(5, "team_b")
    assert not t2.is_completed(6, "ic_c")  # ic_c was started, not completed


# ---------------------------------------------------------------------------
# CheckpointBackend
# ---------------------------------------------------------------------------

class _FakeInner:
    """A fake inner backend that records invokes (for the delegation tests)."""

    def __init__(self):
        self.invokes = []
        self.save_state_called = False

    def invoke(self, role, context, *args, **kwargs):
        self.invokes.append((role, context))
        return "ok"

    def save_state(self, path):
        self.save_state_called = True


def test_checkpoint_backend_n_action_cadence():
    """The CheckpointBackend fires on_checkpoint every N invokes."""
    inner = _FakeInner()
    checkpoints = []
    cb = CheckpointBackend(inner, every_n=3)
    cb.on_checkpoint = lambda: checkpoints.append(len(checkpoints))
    # 3 invokes -> 1 checkpoint.
    for i in range(3):
        cb.invoke("role", f"ctx{i}")
    assert len(checkpoints) == 1
    # 3 more invokes -> 1 more checkpoint.
    for i in range(3):
        cb.invoke("role", f"ctx{i}")
    assert len(checkpoints) == 2
    # 2 invokes (not enough) -> no checkpoint.
    cb.invoke("role", "ctx")
    cb.invoke("role", "ctx")
    assert len(checkpoints) == 2
    # 1 more invoke -> 1 more checkpoint.
    cb.invoke("role", "ctx")
    assert len(checkpoints) == 3


def test_checkpoint_backend_no_callback():
    """A CheckpointBackend with no on_checkpoint callback is a no-op."""
    inner = _FakeInner()
    cb = CheckpointBackend(inner, every_n=1)
    cb.on_checkpoint = None
    # no crash, no checkpoint.
    cb.invoke("role", "ctx")
    cb.invoke("role", "ctx")


def test_checkpoint_backend_resuming_preamble():
    """When resuming, the verify-work preamble is prepended to the context."""
    inner = _FakeInner()
    cb = CheckpointBackend(inner, every_n=5)
    # not resuming: the context is passed through unchanged.
    cb.resuming = False
    cb.invoke("role", "original context")
    assert inner.invokes[-1][1] == "original context"
    # resuming: the preamble is prepended.
    cb.resuming = True
    cb.invoke("role", "original context")
    assert inner.invokes[-1][1].startswith(VERIFY_WORK_PREAMBLE)
    assert "original context" in inner.invokes[-1][1]


def test_checkpoint_backend_delegates_attributes():
    """The CheckpointBackend delegates missing attributes to the inner."""
    inner = _FakeInner()
    cb = CheckpointBackend(inner)
    # save_state is delegated to the inner.
    cb.save_state("/tmp/state.json")
    assert inner.save_state_called


def test_checkpoint_backend_action_count():
    """The CheckpointBackend counts every invoke."""
    inner = _FakeInner()
    cb = CheckpointBackend(inner, every_n=5)
    assert cb.action_count == 0
    cb.invoke("role", "ctx")
    cb.invoke("role", "ctx")
    cb.invoke("role", "ctx")
    assert cb.action_count == 3
