"""Unit tests for `MemoryBackend` (per-role isolated memory, Step 3).

Each role's `RoleMemory` is folded into **its own** prompt before the invoke
(and only its own — the other roles in the same conversation are blind to
what it knows, so reasoning is emergent, not self-confirmation), bounded
(decay — oldest entries dropped first), with a slightly different bound per
role (within `max_entries_range`), and accumulates both conversations
(summaries) and work artifacts (`work_path`/`artifact`).
`seed_cross_team` seeds a pod's decision as a cross-team `pod:<id>` entry
(the third carry-over path).
"""

from roles.base import Role
from runtime.llm import StubBackend, MemoryBackend


def _role(rid, architype="ic", department="analytics", team="pipelines"):
    return Role(id=rid, architype=architype, department=department, team=team)


def _prompt_for(stub: StubBackend, role_id: str) -> str:
    """The most recent prompt the stub saw for `role_id`."""
    return [ctx for rid, ctx in stub.calls if rid == role_id][-1]


def test_memory_isolation_between_roles():
    stub = StubBackend()
    role_a = _role("role_a")
    role_b = _role("role_b")
    stub.set_script("role_a", [{"summary": "A built the extractor"}])
    stub.set_script("role_b", [{"summary": "B built the loader"}])
    mem = MemoryBackend(stub, max_entries_range=(5, 20))

    mem.invoke(role_a, "objective A")
    # B's prompt must NOT contain A's memory (isolation).
    mem.invoke(role_b, "objective B")
    assert "A built the extractor" not in _prompt_for(stub, "role_b")
    # B's own memory IS folded into B's own prompt (on the next invoke).
    mem.invoke(role_b, "objective B2")
    assert "B built the loader" in _prompt_for(stub, "role_b")
    # A's memory still does not leak into B.
    assert "A built the extractor" not in _prompt_for(stub, "role_b")


def test_memory_decay_bounded_oldest_dropped():
    stub = StubBackend()
    role = _role("role_x")
    stub.set_script("role_x", [{"summary": f"entry {i}"} for i in range(30)])
    lo, hi = 5, 20
    mem = MemoryBackend(stub, max_entries_range=(lo, hi))
    for i in range(30):
        mem.invoke(role, f"objective {i}")
    memory = mem.role_memories["role_x"]
    # Bounded: the memory holds exactly its (random, per-role) bound.
    assert len(memory) <= hi
    assert len(memory) == memory.max_entries
    # Oldest dropped first: the newest is present, the oldest is gone.
    summaries = [e.summary for e in memory.entries]
    assert "entry 29" in summaries
    assert "entry 0" not in summaries


def test_per_role_bound_within_range():
    stub = StubBackend()
    mem = MemoryBackend(stub, max_entries_range=(5, 20))
    for rid in ("r1", "r2", "r3", "r4", "r5"):
        stub.set_script(rid, [{"summary": "s"}])
        mem.invoke(_role(rid), "obj")
        assert 5 <= mem.role_memories[rid].max_entries <= 20


def test_work_artifact_appended_to_memory():
    stub = StubBackend()
    ic = _role("ic1")
    stub.set_script("ic1", [
        {"summary": "extractor done",
         "work_path": "departments/analytics/pipelines/extractor.md"},
    ])
    mem = MemoryBackend(stub)
    mem.invoke(ic, "do the work")
    entries = mem.role_memories["ic1"].entries
    assert any(
        e.summary == "work: departments/analytics/pipelines/extractor.md"
        and e.source == "report"
        for e in entries
    )


def test_seed_cross_team_entry():
    stub = StubBackend()
    mem = MemoryBackend(stub)
    ic = _role("ic1")
    stub.set_script("ic1", [{"summary": "s"}])
    mem.invoke(ic, "obj")
    mem.seed_cross_team("ic1", "pod_mgr1_1", "approve schema v2", team="pipelines")
    memory = mem.role_memories["ic1"]
    # The entry carries the `pod:<id>` source (what cross_team() filters on).
    assert any(
        e.source == "pod:pod_mgr1_1" and e.summary == "approve schema v2"
        for e in memory.entries
    )
    assert memory.cross_team()
    # An empty decision is a no-op (never a visible silent entry).
    before = len(memory.entries)
    mem.seed_cross_team("ic1", "pod_mgr1_2", "", team="pipelines")
    assert len(memory.entries) == before