"""Unit tests for `runtime/complexity.py` — the "thinking" routing.

Complex tasks use the model's "thinking" (HIGH); simple tasks run without it
(LOW); structuring work uses MEDIUM. A per-session thinking budget bounds the
total number of HIGH calls, and every invoke is logged to the audit trail.
"""

import os

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import MemoryBackend, StubBackend, Reasoning
from runtime.complexity import (
    classify_complexity, detect_disagreement, parse_phase, pod_levels,
    ThinkingBudget, RoutingBackend,
)
from runtime.history import HistoryStore


def _role(architype, department="", team=""):
    return Role(id=architype, architype=architype, department=department, team=team)


def test_complex_phases_route_high():
    leader = make_leader()
    assert classify_complexity(2, leader, {}) is Reasoning.HIGH   # mission
    assert classify_complexity(7, leader, {}) is Reasoning.HIGH   # evaluate
    assert classify_complexity(8, leader, {}) is Reasoning.HIGH   # decide


def test_decisions_route_high():
    leader = make_leader()
    assert classify_complexity(3, leader, {"is_decision": True}) is Reasoning.HIGH


def test_ic_executing_planning_routes_medium():
    ic = _role("ic", "analytics", "pipelines")
    # IC executing / planning its task (Phase 6) -> MEDIUM (raised from LOW).
    assert classify_complexity(6, ic, {}) is Reasoning.MEDIUM


def test_gut_check_routes_high():
    da = _role("department_head", "devils_advocate")
    # The devil's advocate red-team verdict (gut check) -> HIGH.
    assert classify_complexity(7, da, {"gut_check": True}) is Reasoning.HIGH


def test_pod_levels_originator_one_higher():
    # The originator (the decision-maker) runs one level higher than the
    # members (who share info); the members are capped at MEDIUM. In Phase 6
    # the members' base is MEDIUM (executing/planning), so the originator is
    # HIGH.
    starter = _role("department_head", "analytics")
    members = [_role("ic", "analytics", "pipelines"),
               _role("manager", "analytics", "pipelines")]
    originator, member = pod_levels(6, starter, members)
    assert member is Reasoning.MEDIUM
    assert originator is Reasoning.HIGH


def test_structuring_routes_medium():
    leader = make_leader()
    mgr = _role("manager", "analytics", "pipelines")
    head = _role("department_head", "analytics")
    assert classify_complexity(4, leader, {}) is Reasoning.MEDIUM
    assert classify_complexity(4, mgr, {}) is Reasoning.MEDIUM
    assert classify_complexity(4, head, {}) is Reasoning.MEDIUM


def test_disagreement_or_deadlock_routes_high():
    ic = _role("ic", "analytics", "pipelines")
    assert classify_complexity(6, ic, {"disagreement": True}) is Reasoning.HIGH
    assert classify_complexity(6, ic, {"deadlock": True}) is Reasoning.HIGH


def test_intake_nonconvergence_routes_high():
    leader = make_leader()
    # not converging and at the last round -> HIGH
    assert classify_complexity(1, leader, {"converging": False, "budget_left": 1}) is Reasoning.HIGH
    # converging, or budget remaining -> LOW
    assert classify_complexity(1, leader, {"converging": True, "budget_left": 1}) is Reasoning.LOW
    assert classify_complexity(1, leader, {"converging": False, "budget_left": 3}) is Reasoning.LOW


def test_detect_disagreement():
    assert detect_disagreement([
        {"recommendation": "approve the schema change"},
        {"recommendation": "concern about migration cost"},
    ]) is True
    # no conflict -> no disagreement
    assert detect_disagreement([
        {"recommendation": "approve"}, {"recommendation": "agree"},
    ]) is False
    # no recommendations -> no disagreement
    assert detect_disagreement([{"summary": "ok"}]) is False


def test_parse_phase():
    assert parse_phase("PHASE 1: intake") == 1
    assert parse_phase("PHASE 4 (head h1): decompose") == 4
    assert parse_phase("POD pod_x: speak — topic") == 6
    assert parse_phase("no phase here") == -1


def test_thinking_budget_bounds_high():
    budget = ThinkingBudget(max_high=2)
    assert budget.allow(Reasoning.HIGH) is Reasoning.HIGH   # 1
    assert budget.allow(Reasoning.HIGH) is Reasoning.HIGH   # 2
    assert budget.allow(Reasoning.HIGH) is Reasoning.LOW    # 3 -> fallback
    assert budget.allow(Reasoning.LOW) is Reasoning.LOW     # non-HIGH passes
    assert budget.remaining == 0


def test_routing_backend_routes_and_logs(tmp_path):
    history = HistoryStore(history_dir=str(tmp_path))
    inner = StubBackend()
    backend = RoutingBackend(inner, ThinkingBudget(max_high=1), history)
    leader = make_leader()
    ic = _role("ic", "analytics", "pipelines")

    backend.invoke(leader, "PHASE 2: draft the mission")     # HIGH (in budget)
    backend.invoke(ic, "PHASE 6 (IC ic): do the work")       # MEDIUM (IC executing)
    backend.invoke(leader, "PHASE 8: decide")                # HIGH -> LOW (budget)

    assert inner.reasoning_log == [Reasoning.HIGH, Reasoning.MEDIUM, Reasoning.LOW]
    assert os.path.exists(os.path.join(str(tmp_path), "invocations.jsonl"))


def test_routing_backend_uses_explicit_level():
    inner = StubBackend()
    backend = RoutingBackend(inner, ThinkingBudget(max_high=10))
    ic = _role("ic", "analytics", "pipelines")
    # An explicit HIGH (e.g. a pod round with disagreement) overrides phase routing.
    backend.invoke(ic, "POD pod_x: speak — topic", reasoning=Reasoning.HIGH)
    assert inner.reasoning_log == [Reasoning.HIGH]


def test_live_path_high_reaches_router(tmp_path):
    # the live path (MemoryBackend -> RoutingBackend) routes
    # `reasoning` — a `classify_complexity` HIGH reaches the router, and the
    # default (`reasoning=None`) is CLASSIFIED by the router (no hardcoded LOW
    # bypass).
    inner = StubBackend()
    routing = RoutingBackend(inner, ThinkingBudget(max_high=10))
    memory = MemoryBackend(routing)
    leader = make_leader()

    # An explicit HIGH (a classify_complexity result) reaches the router.
    level = classify_complexity(2, leader, {})
    assert level is Reasoning.HIGH
    memory.invoke(leader, "PHASE 2: draft the mission", reasoning=level, phase=2)
    assert inner.reasoning_log[-1] is Reasoning.HIGH

    # The default (`reasoning=None`) is classified by the router, not forced
    # LOW: Phase 7 (evaluate) classifies HIGH and the router grants it.
    memory.invoke(leader, "PHASE 7: evaluate", phase=7)
    assert inner.reasoning_log[-1] is Reasoning.HIGH


def test_live_path_budget_exhaustion_downgrades(tmp_path):
    # once the thinking budget is exhausted, a HIGH is downgraded to a
    # lower level (the visible fallback).
    inner = StubBackend()
    routing = RoutingBackend(inner, ThinkingBudget(max_high=1))
    memory = MemoryBackend(routing)
    leader = make_leader()

    memory.invoke(leader, "PHASE 2: draft the mission",
                  reasoning=Reasoning.HIGH, phase=2)
    assert inner.reasoning_log[-1] is Reasoning.HIGH   # within budget
    memory.invoke(leader, "PHASE 2: draft the mission",
                  reasoning=Reasoning.HIGH, phase=2)
    assert inner.reasoning_log[-1] is Reasoning.LOW    # budget exhausted
