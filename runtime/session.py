"""The session runtime — drives Phases 1–6.

`Session` loads roles and drives the pipeline (malformed LLM output is
envelope-validated in the backend chain — `OpenAIBackend` in
`runtime/llm_api.py` — not here), and applies:

- the **BAU rule**: operations continue business-as-usual when user input is
  pending (a mission permission, a tiebreaker, a Safety/Morality halt) — the
  org keeps working on anything **not blocked** by the pending input; the
  **exception** is a **Safety or Morality halt**, which may halt BAU (scoped or
  global). When the user responds, the blocked branch resumes.
- **escalation** on repeated failure / non-convergence (a structured
  diagnosis to the user).
- the **Phase 6 self-improving loop**: a bounded **continue/complete**
  decision — continue re-enters Phase 1 with the evaluation as input, still
  abiding by the original goal.

**Decomposition (Phase 5):** this file keeps the `Session` core
(`__init__`, the BAU rule methods, `_active_role_ids`, `_checkpoint`,
`_phase`) + the slim `run` orchestrator + `SessionResult` + the
`build_backend` factory. The phase methods moved to focused modules:
Phase 5 synthesis + Phase 6 evaluation -> `runtime/session_phases.py`; the
S22 efficiency methods -> `runtime/session_efficiency.py`; escalation ->
`runtime/session_escalation.py`; the run setup + Phases 1-3 ->
`runtime/session_phases123.py`; the Phases 4-6 loop ->
`runtime/session_loop.py`; the run finalization ->
`runtime/session_finalize.py`. `Session` keeps thin delegations to the phase
methods (so `session._synthesis(...)` etc. keep working). This file
re-exports the full public API (backward-compatible facade).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role
from runtime.llm import LLMBackend, MemoryBackend, TimeoutBackend
from runtime.intake import IntakeResult
from runtime.mission import MissionResult
from runtime.org import OrgState
from runtime import dispatch
from runtime.pods import SoloTracker
from runtime.history import HistoryStore
from runtime.timing import TimingTracker, TimingBackend
from runtime.efficiency import EfficiencyMeter, EFFICIENCY_FLOOR
from runtime.complexity import RoutingBackend, ThinkingBudget
from runtime.session_phases import synthesis, evaluate
from runtime.session_efficiency import (
    finish_efficiency,
    efficiency_floor_action,
)
from runtime.session_escalation import escalate
from runtime.session_phases123 import setup_run, run_phases_1_3
from runtime.session_loop import run_phases_4_6
from runtime.session_finalize import finalize_run


@dataclass
class SessionResult:
    status: str  # "complete" / "continue" / "escalated"
    phases: List[int] = field(default_factory=list)
    intake: Optional[IntakeResult] = None
    mission: Optional[MissionResult] = None
    dispatch_results: List[Dict[str, Any]] = field(default_factory=list)
    pods: List[Any] = field(default_factory=list)
    verdict: str = ""
    evaluation: Dict[str, Any] = field(default_factory=dict)
    cycles: int = 1
    escalation: Optional[Dict[str, Any]] = None


def build_backend(
    raw: LLMBackend,
    config: Dict[str, Any],
    history: HistoryStore,
    thinking_budget: ThinkingBudget,
) -> LLMBackend:
    """D5: the backend-wrapping factory — makes the
    ``MemoryBackend(RoutingBackend(TimeoutBackend(raw)))`` chain + the
    ``on_call``/``on_stream`` observability wiring explicit and testable (it
    was previously implicit in ``Session.__init__``).

    - Wires ``on_call``/``on_stream`` on the raw backend (if it supports them,
      e.g. ``OpenAIBackend``) to the history audit trail.
    - Wraps the raw backend in a ``TimeoutBackend`` (a per-invoke timeout).
    - Wraps that in a ``RoutingBackend`` (complexity routing + thinking budget).
    - Wraps that in a ``MemoryBackend`` (per-role isolated memory).
    """
    # Tool-call observability: if the raw backend supports per-call stats
    # (OpenAIBackend), record each call's outcome to history/tool_calls.jsonl.
    if hasattr(raw, "on_call"):
        raw.on_call = history.log_tool_call
    # Live "model stream" observability: if the raw backend supports per-chunk
    # streaming (OpenAIBackend), forward each streamed chunk to
    # history/stream.jsonl (the dashboard's live "model stream" window).
    if hasattr(raw, "on_stream"):
        raw.on_stream = history.log_stream
    # Bound the actual backend call: a per-invoke timeout (a visible
    # LLMTimeoutError, never silent) guards the real LLM call.
    timed = TimeoutBackend(
        raw, timeout_seconds=config.get("timeout_seconds", 60.0)
    )
    # Complexity routing: wrap the backend so every invoke is routed by task
    # complexity (complex -> thinking on, simple -> off) and bounded by the
    # per-session thinking budget.
    routing = RoutingBackend(timed, thinking_budget, history)
    # Wrap with per-role isolated memory: each role's past conversations / work
    # are folded into its OWN prompt (and only its own), so reasoning is
    # emergent rather than self-confirmation. The per-role cap (the hi of the
    # `max_entries_range`) is the ROLE_MEMORY_MAX_ENTRIES .env knob (S20
    # wire-in).
    return MemoryBackend(
        routing,
        max_entries_range=(5, config.get("role_memory_max_entries", 20)),
    )


class Session:
    def __init__(
        self,
        backend: LLMBackend,
        leader: Role,
        config: Optional[Dict[str, Any]] = None,
        history_dir: str = "history",
    ):
        self.leader = leader
        self.config = config or {}
        self.org = OrgState(history_dir=history_dir)
        self.history = HistoryStore(
            history_dir=history_dir,
            window_sessions=self.config.get("history_window_sessions", 50),
            archive_cap_mb=self.config.get("archive_cap_mb", 1024),
        )
        # D5: the backend chain (MemoryBackend(RoutingBackend(TimeoutBackend(
        # raw))) + the on_call/on_stream observability wiring) is built by the
        # build_backend() factory (explicit + testable, not implicit here).
        self.thinking_budget = ThinkingBudget(
            max_high=self.config.get("thinking_budget", 10)
        )
        self.backend = build_backend(
            backend, self.config, self.history, self.thinking_budget
        )
        # Story 22: invoke timing — the TimingTracker accumulates per-role /
        # per-department wall-clock time (appended to history/efficiency.jsonl,
        # the dashboard's efficiency panel); the TimingBackend wraps the chain
        # so every invoke is timed (transparent: it delegates all other
        # attributes, e.g. save_state / load_state / seed_cross_team).
        self.timing = TimingTracker(history_dir=history_dir)
        self.backend = TimingBackend(self.backend, self.timing)
        # Story 22 (S22): the efficiency meter — instruments the Phase 3-6 loop
        # per iteration (T_total, T_p3..T_p6, T_dept, T_role, H_peak, C,
        # N_created), computes the efficiency score E (M_satisfaction /
        # (0.5*(T_total/T_ref) + 0.5*(C/C_ref)), running-average refs over the
        # last 3 iterations) and appends the per-iteration snapshot to
        # history/efficiency_metrics.jsonl (auditable + the dashboard's
        # Efficiency panel). The floor (EFFICIENCY_FLOOR, default ~0.4) is the
        # `efficiency_floor` .env / config knob.
        self.efficiency = EfficiencyMeter(
            history_dir=history_dir,
            floor=self.config.get("efficiency_floor", EFFICIENCY_FLOOR),
        )
        self.pods: List[Any] = []
        # Solo (single-role) leader pods: one per phase (P1/P2/P3/P5/P6), so the
        # observability dashboard can watch the leader's solo work (not just the
        # multi-role pods). Transcripts grow per round in pods/transcripts/.
        self.solo = SoloTracker(
            leader,
            transcripts_dir=self.config.get("pod_transcripts_dir",
                                            "pods/transcripts"),
        )
        self.cycles = 0

        # BAU rule state.
        self.pending_user_input: List[Dict[str, Any]] = []
        self.bau_halt: Optional[Dict[str, Any]] = None

    # --- BAU rule ----------------------------------------------------------

    def queue_user_input(self, item: Dict[str, Any]) -> None:
        """Queue a pending user input. BAU **continues**: the org keeps working
        on anything not blocked by this input; it resumes when the user
        responds."""
        self.pending_user_input.append(item)

    def halt_bau(self, department: str, scope: str, reason: str) -> None:
        """A Safety or Morality halt — the only departments that may halt BAU
        (scoped or global). Logged."""
        self.bau_halt = {"department": department, "scope": scope, "reason": reason}
        self.history.log_halt(department, scope, reason)

    def bau_active(self) -> bool:
        """BAU is active (work continues) unless a global Safety/Morality halt
        is in effect."""
        if self.bau_halt and self.bau_halt.get("scope") == "global":
            return False
        return True

    # --- Phase 5 synthesis (delegation) ------------------------------------

    def _synthesis(self) -> str:
        return synthesis(self)

    # --- Phase 6 evaluation (delegation) -----------------------------------

    def _evaluate(
        self,
        intake: IntakeResult,
        mission: MissionResult,
        dispatch_results: List[Dict[str, Any]],
        verdict: str,
        max_iterations: int,
    ):
        return evaluate(
            self, intake, mission, dispatch_results, verdict, max_iterations)

    # --- S22: efficiency finishing + the floor trigger (delegation) --------

    def _finish_efficiency(
        self,
        iter_start_ids,
        mission_draft,
        dispatch_results,
        verdict,
    ):
        return finish_efficiency(
            self, iter_start_ids, mission_draft, dispatch_results, verdict)

    def _efficiency_floor_action(self, snap):
        return efficiency_floor_action(self, snap)

    # --- Escalation (delegation) -------------------------------------------

    def _escalate(
        self,
        reason: str,
        intake: Optional[IntakeResult],
        mission: Optional[MissionResult],
    ) -> SessionResult:
        return escalate(self, reason, intake, mission)

    # --- Checkpointing (crash recovery, Story 1) ---------------------------

    def _active_role_ids(self):
        """The active role ids for memory persistence (Story 11, B8): the
        current org's role ids **plus the leader**. The leader drives the
        whole session but is NOT a member of `self.org.roles` (only the
        hired heads/managers/ICs are) — without it, the leader's memory
        would be pruned as "stale" (and wiped in place), losing the
        pre-crash state Story 1 (B1) requires to be recoverable."""
        return {self.leader.id, *self.org.roles.keys()}

    def _checkpoint(self, phase: int, cycle: int) -> str:
        """Write a mid-run checkpoint (Story 1, B1/B4): persist the org chart
        + each role's memory + the event log, then record the phase/cycle
        reached in `state/checkpoint.json` (`{"phase", "cycle", "ts"}`). A
        crash after this point loses at most the work done since — the current
        iteration's hires, not the whole run. The checkpoint file itself is
        written atomically (tmp + `os.replace`). Returns the checkpoint path."""
        org_chart_path = self.config.get("org_chart_path", "state/org_chart.json")
        memory_dir = self.config.get("memory_dir", "state/role_memory")
        checkpoint_path = self.config.get("checkpoint_path", "state/checkpoint.json")
        self.org.save(org_chart_path)
        # Story 11 (B8): prune stale (fired) roles' memories before saving —
        # only the active role ids (the current org's role ids + the leader)
        # are persisted.
        self.backend.save_state(memory_dir,
                                active_role_ids=self._active_role_ids())
        self.org.write_events()
        parent = os.path.dirname(checkpoint_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        tmp = checkpoint_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"phase": phase, "cycle": cycle, "ts": time.time()}, f)
        os.replace(tmp, checkpoint_path)
        return checkpoint_path

    # --- The self-improving loop (bounded) ---------------------------------

    def _phase(self, phase: int, cycle: int, fn, *args, **kwargs):
        """Run one phase and record its duration to ``history/cycles.jsonl``
        (the dashboard's "uptime per iteration" metric). The duration is
        logged even if the phase fails (a visible, measurable crash), and the
        original exception still propagates."""
        started = time.time()
        try:
            return fn(*args, **kwargs)
        finally:
            ended = time.time()
            self.history.log_cycle(phase, cycle, started, ended)
            # S22: record the phase time + the headcount in effect (the org's
            # active roles) to the efficiency meter (T_p + H_peak + C).
            self.efficiency.record_phase(phase, started, ended)
            self.efficiency.record_headcount(
                len(self.org.active_roles()), ended - started)

    def run(
        self,
        initial_prompt: str,
        user_answer_fn: Callable[[List[str]], str],
        user_permission_fn: Callable[[Dict[str, Any]], Dict[str, str]],
        approver_fn: Callable[[str, str, Role], Dict[str, str]],
        phase4_halt_fn: Optional[Callable[[], Optional[Dict[str, str]]]] = None,
        max_iterations: int = 3,
        revisit: bool = False,
        resume_from_phase: int = 1,
    ) -> SessionResult:
        """Run the pipeline: Phases 1-3 run **once** (intake, mission, org
        bootstrap), then Phases 4 & 5 **iterate** (dispatch, synthesis) for up
        to `max_iterations` passes — or until the evaluation says the
        deliverable is genuinely polished. The stop is **bounded** (the
        iteration cap) **and goal-based** (the leader can stop early on
        'complete'); the original goal is still abided by on every pass.

        Each role's isolated memory is loaded from / saved to disk around the
        run (so a role remembers prior runs). A `revisit` run additionally
        loads the saved org chart + the current mission, re-clarifies the goal
        in Phase 1, continues the mission version in Phase 2, bootstraps
        additively in Phase 3, and re-saves the org chart at the end.

        ``resume_from_phase`` (S15): the phase to start from. A revisit from a
        checkpoint at phase 3 or 4 skips Phases 1-3 (the org + mission are
        loaded) and resumes from Phase 4 (the dispatch continues); the intake
        + mission are not re-derived (``_escalate`` handles them being
        ``None``)."""
        # S22: the HR approver (for the efficiency-floor firing / automation
        # actions the Leader takes). Stored so the Phase 6 efficiency action
        # can call it.
        self._approver_fn = approver_fn

        # Setup: config paths, checkpoint detection, memory load, revisit load.
        (memory_dir, org_chart_path, mission_path, checkpoint_path,
         start_version, current_mission) = setup_run(self, revisit)

        self.phases = []
        self.cycles = 0

        # Phases 1-3 (once) — or skipped on a resume-from-checkpoint.
        (intake, mission, mission_draft, p3_started, p3_ended, esc) = \
            run_phases_1_3(
                self, initial_prompt, user_answer_fn, user_permission_fn,
                approver_fn, revisit, resume_from_phase, start_version,
                current_mission, mission_path)
        if esc is not None:
            return esc

        # Phases 4-6 (the bounded self-improving loop).
        (dispatch_results, verdict, evaluation, status, esc) = run_phases_4_6(
            self, intake, mission, mission_draft, approver_fn, phase4_halt_fn,
            max_iterations, p3_started, p3_ended)
        if esc is not None:
            return esc

        # Finalize: rolling-window maintenance + memory / org-chart persist.
        return finalize_run(
            self, memory_dir, org_chart_path, status, intake, mission,
            dispatch_results, verdict, evaluation)


__all__ = [
    # core (kept here)
    "SessionResult",
    "build_backend",
    "Session",
    # facade re-exports (moved to focused modules)
    "synthesis",
    "evaluate",
    "finish_efficiency",
    "efficiency_floor_action",
    "escalate",
    "setup_run",
    "run_phases_1_3",
    "run_phases_4_6",
    "finalize_run",
]
