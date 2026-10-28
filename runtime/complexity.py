"""Complexity routing — decide whether a task uses the model's "thinking".

Complex tasks should use "thinking"; simple tasks should run the model without
it active. This module implements that routing:

- `classify_complexity(phase, role, signal)` — a **pure** router mapping a task
  to a `Reasoning` level (complex -> thinking on, simple -> off).
- `ThinkingBudget` — bounds the total number of HIGH (thinking) calls per
  session, with a visible fallback to LOW.
- `detect_disagreement(outputs)` — a pod round has conflicting recommendations.
- `parse_phase(context)` — the phase encoded in a context string ("PHASE N").
- `RoutingBackend` — wraps a backend; routes each invoke by phase (or an
  explicit level), bounds it via the budget, and logs it to the audit trail.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from runtime.llm import LLMBackend, Reasoning, TimeoutBackend
from runtime.history import HistoryStore


def parse_phase(context: str) -> int:
    """The phase encoded in a context string. "PHASE N" -> N; "POD ..." -> 6
    (execute — the pods fire in Phase 6); unknown -> -1."""
    if context.startswith("POD"):
        return 6
    head = context[:12]
    idx = head.find("PHASE")
    if idx != -1:
        digits = ""
        for ch in head[idx + 5:]:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if digits:
            return int(digits)
    return -1


def classify_complexity(phase: int, role, signal: Dict[str, Any]) -> Reasoning:
    """A pure router: map (task-signal, phase, role) to a `Reasoning` level.

    Routing is **TASK-FIRST**: the task signal (what the task IS — a decision,
    a disagreement, a decomposition) drives the level; the phase number is a
    fallback for tasks that carry no signal. This keeps routing consistent at
    every call site (the dispatch sites and the Phase 2/3/7/8 / efficiency /
    pod sites all pass the same (task, phase, role) shape).

    `signal` keys: `disagreement`, `deadlock`, `converging`, `confidence`,
    `budget_left`, `is_decision`, `gut_check`. Complex tasks -> thinking on
    (HIGH); simple tasks -> off (LOW). This is a pure function so the routing
    logic is unit-testable offline, like the other invariants.
    """
    # Task signals drive when present (a decision task is always HIGH,
    # regardless of phase).
    if signal.get("is_decision"):               # hire/fire/offload, leader vote
        return Reasoning.HIGH
    if signal.get("gut_check"):                  # the devil's advocate red-team verdict
        return Reasoning.HIGH
    if phase in (4, 5, 6):                      # plan / staff / execute
        if signal.get("disagreement") or signal.get("deadlock"):
            return Reasoning.HIGH
        # Executing / planning work -> MEDIUM: the leader/head/manager
        # structuring AND the IC executing/planning its task. (Reporting /
        # evaluation steps run in Phase 7/8 and are routed separately — not
        # here — so an IC's post-execution report stays at its Phase 7/8 level.)
        return Reasoning.MEDIUM
    if phase == 1:                              # intake
        if (not signal.get("converging")) and signal.get("budget_left", 99) <= 1:
            return Reasoning.HIGH
        return Reasoning.LOW
    # Phase fallback (no task signal): mission / evaluate / decide are heavy
    # leader tasks -> HIGH.
    if phase in (2, 7, 8):                      # mission, evaluate, decide
        return Reasoning.HIGH
    return Reasoning.LOW


def _level_rank(level: Reasoning) -> int:
    """The ordering rank of a reasoning level (LOW < MEDIUM < HIGH)."""
    return {Reasoning.LOW: 0, Reasoning.MEDIUM: 1, Reasoning.HIGH: 2}[level]


def _one_level_higher(level: Reasoning) -> Reasoning:
    """The reasoning level one step higher (LOW->MEDIUM->HIGH; HIGH stays HIGH)."""
    return {Reasoning.LOW: Reasoning.MEDIUM,
            Reasoning.MEDIUM: Reasoning.HIGH,
            Reasoning.HIGH: Reasoning.HIGH}[level]


def pod_levels(phase: int, starter, members) -> tuple:
    """A pod's reasoning levels: the **originator** (the starter — the role that
    ultimately makes the decision) runs **one level higher** than the other
    members (who are there only to justify / share info).

    The members' base level is the max of their phase-based levels **capped at
    MEDIUM** (they don't make the decision, so they never run HIGH just to share
    info); the originator is base + 1 (HIGH if the members are MEDIUM, MEDIUM if
    the members are LOW). Returns ``(originator_level, member_level)``.

    A pure function so the pod routing is unit-testable offline, like the other
    invariants.
    """
    base = Reasoning.LOW
    for m in members:
        lvl = classify_complexity(phase, m, {})
        if _level_rank(lvl) > _level_rank(base):
            base = lvl
    # Cap the members' base at MEDIUM (they share info, they don't decide).
    if base is Reasoning.HIGH:
        base = Reasoning.MEDIUM
    return _one_level_higher(base), base


def detect_disagreement(outputs: List[Dict[str, Any]]) -> bool:
    """A pod round has disagreement: conflicting recommendations on the same
    topic (e.g. an "approve" alongside a "concern"/"reject"/"object")."""
    recs = [
        str(o.get("recommendation", "")).lower()
        for o in outputs if o.get("recommendation")
    ]
    has_negative = any(
        "reject" in r or "concern" in r or "object" in r for r in recs
    )
    has_positive = any("approv" in r or "agree" in r for r in recs)
    return has_negative and has_positive


class ThinkingBudget:
    """Bounds the total number of HIGH (thinking) calls per session. A HIGH
    request beyond the budget falls back to LOW (a visible, logged fallback).
    The last ``reserved_for_decisions`` highs are reserved for the decide phase
    (phase 8) so the final decision always has thinking left (a low-reasoning
    final decision was the observed failure: the pool was exhausted in Phase 7)."""

    def __init__(self, max_high: int = 10, reserved_for_decisions: int = 2):
        self.max_high = max_high
        self.reserved = max(0, min(reserved_for_decisions, max_high))
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_high - self.used)

    def allow(self, level: Reasoning, phase: Optional[int] = None) -> Reasoning:
        """Return the bounded level: a HIGH within budget is granted (and
        counted); a HIGH beyond the budget falls back to LOW; non-HIGH passes
        through unchanged. The decide phase (phase 8) may draw on the full
        budget (including the reserved highs); other phases are capped at
        ``max_high - reserved`` so the final decision always has thinking left."""
        if level is not Reasoning.HIGH:
            return level
        cap = self.max_high if phase == 8 else (self.max_high - self.reserved)
        if self.used < cap:
            self.used += 1
            return Reasoning.HIGH
        return Reasoning.LOW


class RoutingBackend(LLMBackend):
    """Wraps a backend and routes each invoke by complexity.

    - If the caller passes an explicit `reasoning`, it is used (the caller
      already decided — e.g. a pod round with disagreement, an intake round
      that is not converging, a resourcing decision).
    - Otherwise the level is computed from the phase (parsed from the context)
      + the role via `classify_complexity`.
    - The granted level is bounded by a `ThinkingBudget` and logged to the
      audit trail (`invocations.jsonl`).
    """

    def __init__(
        self,
        inner: LLMBackend,
        budget: Optional[ThinkingBudget] = None,
        history: Optional[HistoryStore] = None,
    ):
        self.inner = inner
        self.budget = budget or ThinkingBudget()
        self.history = history

    def invoke(self, role, context: str,
               reasoning: Optional[Reasoning] = None,
               timeout: Optional[float] = None,
               phase: Optional[int] = None) -> Dict[str, Any]:
        # D2: the phase to LOG and to ROUTE (explicit from the call site, or
        # parsed from the context as a fallback). The explicit phase is what
        # matters: MemoryBackend re-wraps the context ("ROLE:...") before this
        # runs, so the "PHASE N" marker is gone from the context — relying on
        # parse_phase(context) routed non-explicit invokes (Phase 2 mission, IC
        # work) to LOW and logged phase: -1.
        log_phase = phase if phase is not None else parse_phase(context)
        level = (
            reasoning
            if reasoning is not None
            else classify_complexity(log_phase, role, {})
        )
        granted = self.budget.allow(level, phase=log_phase)
        if self.history is not None:
            # Log the role's FULL identity (name, level in hierarchy, architype,
            # sub-architype, department, team, personality) — not just the role
            # id — so the dashboard can segment invocations by the role's full
            # identity.
            self.history.log_invocation(
                role.id, log_phase, level.value, granted.value, role=role,
            )
        # A per-invoke timeout override is only honored when the inner is a
        # TimeoutBackend (a raw backend like the StubBackend has no timeout
        # concept).
        if isinstance(self.inner, TimeoutBackend):
            return self.inner.invoke(role, context, granted, timeout=timeout,
                                     phase=log_phase)
        return self.inner.invoke(role, context, granted, phase=log_phase)
