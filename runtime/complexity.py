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

from runtime.llm import LLMBackend, Reasoning
from runtime.history import HistoryStore


def parse_phase(context: str) -> int:
    """The phase encoded in a context string. "PHASE N" -> N; "POD ..." -> 4
    (execution); unknown -> -1."""
    if context.startswith("POD"):
        return 4
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
    """A pure router: map (phase, role, task-signal) to a `Reasoning` level.

    `signal` keys: `disagreement`, `deadlock`, `converging`, `confidence`,
    `budget_left`, `is_decision`. Complex tasks -> thinking on (HIGH); simple
    tasks -> off (LOW). This is a pure function so the routing logic is
    unit-testable offline, like the other invariants.
    """
    if phase in (2, 5, 6):                      # mission, synthesis, evaluation
        return Reasoning.HIGH
    if signal.get("is_decision"):               # hire/fire/offload, leader vote
        return Reasoning.HIGH
    if phase == 4:                              # execution
        if signal.get("disagreement") or signal.get("deadlock"):
            return Reasoning.HIGH
        # Structuring work (leader/head/manager decomposition) -> MEDIUM;
        # routine IC work -> LOW.
        if role.architype in ("leader", "department_head", "manager"):
            return Reasoning.MEDIUM
        return Reasoning.LOW
    if phase == 1:                              # intake
        if (not signal.get("converging")) and signal.get("budget_left", 99) <= 1:
            return Reasoning.HIGH
        return Reasoning.LOW
    return Reasoning.LOW


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
    request beyond the budget falls back to LOW (a visible, logged fallback)."""

    def __init__(self, max_high: int = 10):
        self.max_high = max_high
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.max_high - self.used)

    def allow(self, level: Reasoning) -> Reasoning:
        """Return the bounded level: a HIGH within budget is granted (and
        counted); a HIGH beyond the budget falls back to LOW; non-HIGH passes
        through unchanged."""
        if level is Reasoning.HIGH:
            if self.used < self.max_high:
                self.used += 1
                return Reasoning.HIGH
            return Reasoning.LOW
        return level


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
               reasoning: Optional[Reasoning] = None) -> Dict[str, Any]:
        phase = parse_phase(context)
        level = (
            reasoning
            if reasoning is not None
            else classify_complexity(phase, role, {})
        )
        granted = self.budget.allow(level)
        if self.history is not None:
            self.history.log_invocation(
                role.id, phase, level.value, granted.value
            )
        return self.inner.invoke(role, context, granted)
