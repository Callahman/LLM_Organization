"""Unit tests for `runtime/context.py` — memory + bounded prompt construction
(Epic 6 Definition of Done).

A 10-round fixture exchange stays within the context budget; truncation drops
the oldest summaries first and never the agenda; a manager's cross-team pod
memory carries into its next intra-team meeting; every prompt is assembled
from the four-part outline.
"""

from roles.leader import make_leader
from runtime.context import (
    RoleMemory,
    MemoryEntry,
    assemble_prompt,
    bounded_assembly,
    estimate_tokens,
)


def test_four_part_prompt():
    leader = make_leader()
    mem = RoleMemory()
    mem.add_summary("did the pipeline", source="intra-team", team="pipelines")
    prompt = assemble_prompt(leader, "build a report", mem, prior_conversation="earlier talk")
    # All four parts are present.
    assert "ROLE:" in prompt
    assert "OBJECTIVE:" in prompt
    assert "SHORT-TERM MEMORY:" in prompt
    assert "PRIOR CONVERSATION:" in prompt
    assert "build a report" in prompt
    assert "(intra-team) did the pipeline" in prompt
    assert "earlier talk" in prompt


def test_truncation_never_drops_agenda_and_drops_oldest_first():
    agenda = "AGENDA"
    # 10 summaries, each ~5 tokens. Budget just fits the agenda + the newest
    # few.
    summaries = [(f"round{i}", f"summary number {i} with five tokens") for i in range(10)]
    out = bounded_assembly(agenda, summaries, budget_tokens=30)
    # The agenda is always kept.
    assert "AGENDA" in out
    # The newest summary is kept; the oldest is dropped.
    assert "round9" in out
    assert "round0" not in out
    # Deterministic: running again gives the same output.
    assert out == bounded_assembly(agenda, summaries, budget_tokens=30)


def test_ten_round_exchange_stays_within_budget():
    agenda = "AGENDA"
    summaries = [(f"r{i}", f"round {i} summary text") for i in range(10)]
    budget = 4000
    out = bounded_assembly(agenda, summaries, budget_tokens=budget)
    assert estimate_tokens(out) <= budget
    # With a generous budget, all 10 rounds are present.
    for i in range(10):
        assert f"r{i}" in out


def test_cross_team_pod_memory_carries_over():
    mem = RoleMemory(max_entries=20)
    # An intra-team entry.
    mem.add_summary("did the etl", source="intra-team", team="etl")
    # A cross-team (pod) carry-over entry.
    mem.add_summary("pod decided the schema", source="pod:42", team="etl")
    assert len(mem.cross_team()) == 1
    assert mem.cross_team()[0].summary == "pod decided the schema"
    # Both are in the seed (so the pod memory carries into the next meeting).
    assert "pod decided the schema" in mem.seed()
    assert "did the etl" in mem.seed()


def test_memory_is_bounded():
    mem = RoleMemory(max_entries=3)
    for i in range(10):
        mem.add_summary(f"s{i}", source="intra-team")
    assert len(mem) == 3
    # Only the most recent three remain.
    assert "s7" in mem.seed()
    assert "s0" not in mem.seed()
