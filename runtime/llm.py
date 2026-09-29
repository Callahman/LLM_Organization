"""The LLM backend interface + a deterministic offline stub.

The Organization is a company of LLM agents, but the outline does not pin a
model. This module defines a clean `LLMBackend` interface so that all
loop/budget/schema logic is testable **offline** with a deterministic
`StubBackend` (scripted per role), mirroring the prior design's
`--feed-file` offline iteration. A real backend (e.g. an API client) is a
later task and must implement the same interface.
"""

from __future__ import annotations

import random
import threading
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Tuple

from runtime.context import RoleMemory, assemble_prompt


class Reasoning(Enum):
    """The model's "thinking" level for a task. Complex tasks use thinking
    (HIGH); simple tasks run without it (LOW). MEDIUM is an intermediate
    effort for providers that support a gradient."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LLMBackend(ABC):
    """A backend that turns a role + its assembled context into a structured
    output (validated against the role's output schema / envelope)."""

    @abstractmethod
    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        """Given a role and its context/prompt, return the role's structured
        output (a dict containing the shared output envelope). `reasoning`
        selects the model's thinking level (complex -> on, simple -> off)."""
        raise NotImplementedError


class StubBackend(LLMBackend):
    """Deterministic, scripted backend for offline testing.

    Each role id maps to a **script**: a list of structured outputs. Each
    `invoke` for that role pops the next output (repeating the last once the
    script is exhausted). This lets tests drive multi-round loops (intake
    Q&A, pod deliberation, mission re-asks) without a live model.
    """

    def __init__(self, scripts: Dict[str, List[Dict[str, Any]]] | None = None):
        self.scripts: Dict[str, List[Dict[str, Any]]] = scripts or {}
        self._cursor: Dict[str, int] = {}
        # audit of every (role_id, context) the backend saw
        self.calls: List[Tuple[str, str]] = []
        # the reasoning level requested for each invoke (for routing tests)
        self.reasoning_log: List[Reasoning] = []

    def set_script(self, role_id: str, outputs: List[Dict[str, Any]]) -> None:
        """Script a role's sequence of structured outputs."""
        self.scripts[role_id] = outputs
        self._cursor[role_id] = 0

    def _next(self, role_id: str) -> Dict[str, Any]:
        outputs = self.scripts.get(role_id, [])
        if not outputs:
            # No script: return a valid empty envelope (visible, not silent).
            return {
                "summary": "",
                "findings": [],
                "recommendation": "",
                "confidence": 0.0,
            }
        i = self._cursor.get(role_id, 0)
        idx = min(i, len(outputs) - 1)
        self._cursor[role_id] = i + 1
        return outputs[idx]

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        self.calls.append((role.id, context))
        self.reasoning_log.append(reasoning)
        return self._next(role.id)


class LLMTimeoutError(RuntimeError):
    """Raised when a backend invoke exceeds its timeout — a visible failure
    state, never silent."""


class TimeoutBackend(LLMBackend):
    """Wraps any `LLMBackend` and enforces a per-invoke timeout.

    The invoke runs in a daemon worker thread; if it does not finish within
    `timeout_seconds`, a `LLMTimeoutError` is raised (a visible failure state,
    never silent). The daemon thread does not block process exit. This is the
    portable way to bound a real backend call (no signal-based timeouts).
    """

    def __init__(self, inner: LLMBackend, timeout_seconds: float = 60.0):
        self.inner = inner
        self.timeout_seconds = timeout_seconds

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        box: Dict[str, Any] = {}

        def worker() -> None:
            try:
                box["out"] = self.inner.invoke(role, context, reasoning)
            except Exception as e:  # propagate the real error, not a timeout
                box["err"] = e

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(self.timeout_seconds)
        if t.is_alive():
            raise LLMTimeoutError(
                f"backend invoke for {role.id} exceeded {self.timeout_seconds}s"
            )
        if "err" in box:
            raise box["err"]
        return box["out"]


class MemoryBackend(LLMBackend):
    """Wraps any `LLMBackend` and adds **per-role isolated memory**.

    Before the invoke, the role's `RoleMemory` is folded into its prompt (via
    `assemble_prompt`); after the invoke, the role's output is appended to its
    `RoleMemory` (bounded — it decays, oldest entries dropped first). Each
    role's memory is **isolated**: the other roles in the same conversation do
    NOT see it (a manager carries its past; the ICs beside it are blind to
    what it knows — so reasoning is emergent, not self-confirmation). Each
    role gets a slightly different memory bound (within `max_entries_range`)
    so roles don't all perform identically.

    `seed_cross_team(role_id, pod_id, decision, team)` additionally seeds a
    pod's decision into a member's memory as a cross-team `pod:<id>` entry
    (what `RoleMemory.cross_team()` filters on) — a pod's decision carries
    into the members' later intra-team meetings.
    """

    def __init__(self, inner: LLMBackend,
                 max_entries_range: Tuple[int, int] = (5, 20)):
        self.inner = inner
        self.max_entries_range = max_entries_range
        self.role_memories: Dict[str, RoleMemory] = {}

    def _memory_for(self, role_id: str) -> RoleMemory:
        if role_id not in self.role_memories:
            lo, hi = self.max_entries_range
            max_entries = random.randint(lo, hi)
            self.role_memories[role_id] = RoleMemory(max_entries=max_entries)
        return self.role_memories[role_id]

    def seed_cross_team(self, role_id: str, pod_id: str, decision: str,
                        team: str = "") -> None:
        """Seed a pod's decision into a member's memory as a **cross-team
        carry-over entry** — source `pod:<id>`, exactly what
        `RoleMemory.cross_team()` filters on. This is the third carry-over
        path: a pod's decision carries into the members' later intra-team
        meetings. An empty decision is a no-op (never a visible silent
        entry)."""
        if not decision:
            return
        memory = self._memory_for(role_id)
        memory.add_summary(decision, source=f"pod:{pod_id}", team=team)

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        memory = self._memory_for(role.id)
        # Before the invoke: fold the role's isolated memory into its prompt.
        full_prompt = assemble_prompt(role, context, memory=memory)
        # Call the inner backend.
        result = self.inner.invoke(role, full_prompt, reasoning)
        # After the invoke: append the role's output to its memory (bounded).
        # A manager accumulates conversations (summaries); an IC/dev accumulates
        # work artifacts (raw code) — so append both the summary and any work
        # artifact the role produced.
        team = getattr(role, "team", "")
        summary = result.get("summary", "")
        if summary:
            memory.add_summary(summary, source="intra-team", team=team)
        work = result.get("work_path") or result.get("artifact")
        if work:
            memory.add_summary(f"work: {work}", source="report", team=team)
        return result
