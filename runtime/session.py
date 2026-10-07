"""The session runtime — drives Phases 1–6.

`Session` loads roles, enforces schemas (bounded retries on malformed output),
drives the pipeline, and applies:

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
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role, validate_envelope
from runtime.llm import LLMBackend, MemoryBackend, TimeoutBackend
from runtime.intake import run_intake, IntakeResult
from runtime.mission import run_mission, MissionResult, load_mission
from runtime.org import OrgState, bootstrap
from runtime import dispatch
from runtime.pods import SoloTracker
from runtime.history import HistoryStore
from runtime.complexity import (
    RoutingBackend, ThinkingBudget, classify_complexity,
)


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
    # emergent rather than self-confirmation.
    return MemoryBackend(routing)


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
        self.history = HistoryStore(history_dir=history_dir)
        # D5: the backend chain (MemoryBackend(RoutingBackend(TimeoutBackend(
        # raw))) + the on_call/on_stream observability wiring) is built by the
        # build_backend() factory (explicit + testable, not implicit here).
        self.thinking_budget = ThinkingBudget(
            max_high=self.config.get("thinking_budget", 10)
        )
        self.backend = build_backend(
            backend, self.config, self.history, self.thinking_budget
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

    # --- schema enforcement (bounded retries) ------------------------------

    def invoke_checked(self, role, context: str, max_retries: int = 2,
                   phase: Optional[int] = None) -> Dict[str, Any]:
        """Invoke the backend, retrying (bounded) on a malformed output. If
        still malformed after the retries, returns the last output with a
        visible `__malformed__` flag (never silent). The `phase` is passed
        explicitly (D2) so the routing doesn't rely on parsing it from a
        re-wrapped context."""
        output = self.backend.invoke(role, context, phase=phase)
        attempts = 0
        while validate_envelope(output) and attempts < max_retries:
            attempts += 1
            output = self.backend.invoke(role, context, phase=phase)
        if validate_envelope(output):
            output = dict(output)
            output["__malformed__"] = True
        return output

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

    # --- Phase 5 synthesis -------------------------------------------------

    def _synthesis(self) -> str:
        ctx = (
            "PHASE 5: check progress against the mission's success criteria AND "
            "assess whether the deliverable can be IMPROVED (more polished, "
            "more fun, more features, better quality). Do NOT stop at the first "
            "working version — the goal is a polished deliverable, not just a "
            "working one. Produce a verdict: complete (genuinely polished, "
            "stop) / continue (can improve, keep iterating) / escalate."
        )
        # Carry the pods' decisions up to the leader's synthesis (the second
        # carry-over path: the cross-team decisions the pods closed on).
        decisions = [
            f"[{p.id}] {p.decision}"
            for p in self.pods
            if getattr(p, "decision", "")
        ]
        if decisions:
            ctx += " POD DECISIONS: " + "; ".join(decisions)
        out = self.backend.invoke(self.leader, ctx,
                                  reasoning=classify_complexity(5, self.leader, {}),
                                  phase=5)
        # Solo (P5): record the leader's synthesis step so the dashboard can
        # watch it (one transcript file, growing per round). Story 2 (A6): the
        # thinking-budget remainder is included so the dashboard can show it.
        self.solo.record("p5", "Phase 5: synthesis", self.cycles,
                         "synthesis",
                         {**out, "thinking_budget_remaining":
                              self.thinking_budget.remaining})
        # A1: close the solo pod when the synthesis phase completes.
        self.solo.close("p5", f"synthesis verdict={out.get('verdict', 'complete')}")
        return out.get("verdict", "complete")

    # --- Phase 6 evaluation + continue/complete ----------------------------

    def _evaluate(
        self,
        intake: IntakeResult,
        mission: MissionResult,
        dispatch_results: List[Dict[str, Any]],
        verdict: str,
        max_iterations: int,
    ):
        dispatch_units = len(dispatch_results)
        evaluation = {
            "ts": f"cycle{self.cycles}",
            "outcome": verdict,
            "process": {
                "pods": len(self.pods),
                "dispatch_units": dispatch_units,
                "resourcing_events": len(self.org.events),
            },
            "improvement_actions": [
                "department heads update their policy markdowns",
                "role-catalog improvements proposed through HR",
                "leader updates the mission's working section (user permission)",
            ],
        }
        # A no-op cycle (zero work dispatched) must not masquerade as a clean
        # "complete" — surface it as an escalation so it is visible, never
        # silent.
        if dispatch_units == 0:
            evaluation["no_work"] = True
            evaluation["escalation_reason"] = (
                "Phase 4 dispatched zero work (no department objectives could "
                "be resolved to heads in the org) — the cycle did nothing."
            )
            self.history.write_evaluation_report(evaluation)
            self.history._append(
                "escalations.jsonl",
                {"phase": 6, "reason": evaluation["escalation_reason"],
                 "cycle": self.cycles},
            )
            return evaluation, "escalated"
        self.history.write_evaluation_report(evaluation)
        out = self.backend.invoke(
            self.leader,
            "PHASE 6: decide whether to keep iterating. Bias toward 'continue' "
            "(keep improving the deliverable) unless it is genuinely polished. "
            "The goal is a high-quality deliverable, not just a working one. "
            "Choose 'complete' (stop) or 'continue' (another iteration, still "
            f"abiding by the original goal). Evaluation: {evaluation}",
            reasoning=classify_complexity(6, self.leader, {}),
            phase=6,
        )
        decision = out.get("verdict", "complete")
        # Solo (P6): record the leader's continue/complete decision so the
        # dashboard can watch it (one transcript file, growing per round).
        self.solo.record("p6", "Phase 6: evaluation", self.cycles,
                         "decision", out)
        # A1: close the solo pod when the evaluation phase completes.
        self.solo.close("p6", f"eval decision={decision}")
        if decision == "continue" and self.cycles < max_iterations:
            return evaluation, "continue"
        return evaluation, "complete"

    # --- Escalation --------------------------------------------------------

    def _escalate(
        self,
        reason: str,
        intake: Optional[IntakeResult],
        mission: Optional[MissionResult],
    ) -> SessionResult:
        diagnosis = {
            "phase": self.phases[-1] if self.phases else None,
            "reason": reason,
            "intake_confidence": intake.confidence if intake else None,
            "mission_approved": mission.approved if mission else None,
        }
        self.history._append("escalations.jsonl", diagnosis)
        # Rolling window + archive cap (Epic 7) — the session is ending.
        self.history.maintain()
        return SessionResult(
            status="escalated",
            phases=list(self.phases),
            intake=intake,
            mission=mission,
            verdict="escalate",
            cycles=self.cycles,
            escalation=diagnosis,
        )

    # --- Single cycle (Phases 1–6) -----------------------------------------

    def run_cycle(
        self,
        initial_prompt: str,
        user_answer_fn: Callable[[List[str]], str],
        user_permission_fn: Callable[[Dict[str, Any]], Dict[str, str]],
        approver_fn: Callable[[str, str, Role], Dict[str, str]],
        phase4_halt_fn: Optional[Callable[[], Optional[Dict[str, str]]]] = None,
        max_iterations: int = 3,
    ) -> SessionResult:
        """Run one full pass (Phases 1–6) — the single-iteration form. The
        main `run` method instead runs Phases 1-3 once and iterates Phases 4-5.
        `phase4_halt_fn` may return a Safety/Morality halt
        `{"department", "scope", "reason"}` during Phase 4 (the only
        departments that may halt BAU)."""
        self.cycles += 1
        self.phases = []

        # --- Phase 1: intake ---
        intake = self._phase(1, self.cycles, run_intake,
            self.backend,
            self.leader,
            initial_prompt,
            user_answer_fn,
            confidence_threshold=self.config.get("confidence_threshold", 0.8),
            question_budget=self.config.get("question_budget", 5),
            history_dir=self.org.history_dir,
        )
        self.phases.append(1)
        # Solo (P1): record the leader's intake (clarifying Q&A convergence) so
        # the dashboard can watch it (one transcript file, growing per round).
        self.solo.record("p1", "Phase 1: intake", self.cycles, "intake",
                         {"summary": f"intake converged={intake.converged} "
                                     f"rounds={intake.rounds}",
                          "confidence": intake.confidence,
                          "converged": intake.converged,
                          "rounds": intake.rounds,
                          "assumptions": intake.assumptions})
        # A1: close the solo pod when the phase completes so the dashboard
        # moves it to the historical list (not stuck on the active pane).
        self.solo.close("p1", f"intake converged={intake.converged}, "
                              f"{intake.rounds} rounds")

        # --- Phase 2: mission (permission flow) ---
        mission = self._phase(2, self.cycles, run_mission,
            self.backend,
            self.leader,
            intake,
            user_permission_fn,
            history_dir=self.org.history_dir,
            reask_budget=self.config.get("mission_reask_budget", 3),
        )
        self.phases.append(2)
        # Solo (P2): record the leader's mission draft + approval so the
        # dashboard can watch it (one transcript file, growing per round).
        self.solo.record("p2", "Phase 2: mission", self.cycles, "mission",
                         {"summary": f"mission approved={mission.approved} "
                                     f"version={mission.version} "
                                     f"attempts={mission.attempts}",
                          "approved": mission.approved,
                          "version": mission.version,
                          "attempts": mission.attempts,
                          "edits": len(mission.edits)})
        # A1: close the solo pod when the mission phase completes.
        self.solo.close("p2", f"mission approved={mission.approved}, "
                              f"v{mission.version}")
        if not mission.approved:
            return self._escalate("mission not approved by the user", intake, mission)
        mission_draft = mission.edits[-1]["draft"]

        # --- Phase 3: org bootstrap + resourcing ---
        self._phase(3, self.cycles, bootstrap,
            self.org, self.backend, self.leader, mission, approver_fn,
            bootstrap_timeout_seconds=self.config.get(
                "bootstrap_timeout_seconds", self.config.get("ic_timeout_seconds")))
        self.org.write_events()
        self.phases.append(3)
        # Solo (P3): record the leader's org-bootstrap (department-head
        # proposals + hires) so the dashboard can watch it (one transcript
        # file, growing per round).
        self.solo.record("p3", "Phase 3: org bootstrap", self.cycles, "bootstrap",
                         {"summary": "org bootstrapped",
                          "departments": len(self.org.department_heads()),
                          "roles": len(self.org.roles)})
        # A1: close the solo pod when the bootstrap phase completes.
        self.solo.close("p3", "org bootstrapped")

        # --- Phase 4: top-down dispatch (+ pods / resourcing / BAU) ---
        # The approver_fn lets the dispatch hire the managers/ICs it decomposes
        # onto (the full heads->managers->ICs chain). Pods A/B/C form as an
        # add-on; the formed pods accumulate in `self.pods` so their decisions
        # carry up to the leader's Phase 5 synthesis.
        dispatch_results = self._phase(4, self.cycles, dispatch.dispatch,
            self.backend, self.org, self.leader, mission_draft,
            approver_fn=approver_fn,
            pods_out=self.pods,
            history=self.history,
            routing_rules=self.config.get("pod_routing_rules", []),
            artifacts_dir=self.config.get("pod_artifacts_dir", "pods/artifacts"),
            transcripts_dir=self.config.get("pod_transcripts_dir", "pods/transcripts"),
            ic_timeout_seconds=self.config.get("ic_timeout_seconds"),
        )
        self.phases.append(4)

        # A Safety/Morality halt during Phase 4 (the only BAU halt).
        if phase4_halt_fn is not None:
            halt = phase4_halt_fn()
            if halt:
                self.halt_bau(halt["department"], halt["scope"], halt["reason"])
                # Even on a scoped halt, the needed user input is queued; BAU
                # continues for non-blocked work unless the halt is global.
                self.queue_user_input({"kind": "safety_morality_halt", **halt})

        # --- Phase 5: synthesis ---
        verdict = self._phase(5, self.cycles, self._synthesis)
        self.phases.append(5)

        # --- Phase 6: evaluation + continue/complete ---
        evaluation, status = self._phase(6, self.cycles, self._evaluate,
            intake, mission, dispatch_results, verdict, max_iterations
        )
        self.phases.append(6)

        # Rolling window + archive cap (Epic 7): old sessions move to the
        # archives; the audit path stays resolvable.
        self.history.maintain()

        return SessionResult(
            status=status,
            phases=list(self.phases),
            intake=intake,
            mission=mission,
            dispatch_results=dispatch_results,
            pods=list(self.pods),
            verdict=verdict,
            evaluation=evaluation,
            cycles=self.cycles,
        )

    # --- Checkpointing (crash recovery, Story 1) ---------------------------

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
        self.backend.save_state(memory_dir)
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
            self.history.log_cycle(phase, cycle, started, time.time())

    def run(
        self,
        initial_prompt: str,
        user_answer_fn: Callable[[List[str]], str],
        user_permission_fn: Callable[[Dict[str, Any]], Dict[str, str]],
        approver_fn: Callable[[str, str, Role], Dict[str, str]],
        phase4_halt_fn: Optional[Callable[[], Optional[Dict[str, str]]]] = None,
        max_iterations: int = 3,
        revisit: bool = False,
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
        additively in Phase 3, and re-saves the org chart at the end."""
        memory_dir = self.config.get("memory_dir", "state/role_memory")
        org_chart_path = self.config.get("org_chart_path", "state/org_chart.json")
        mission_path = self.config.get("mission_path", "MISSION.md")
        checkpoint_path = self.config.get("checkpoint_path", "state/checkpoint.json")

        # Story 1 (B4, minimal): a checkpoint left by a crashed run is
        # discoverable — if one exists and this is not a revisit, surface it
        # (full resume-from-checkpoint is a follow-up). A corrupted checkpoint
        # is still surfaced (the phase/cycle read as "?").
        if not revisit and os.path.exists(checkpoint_path):
            cp_phase, cp_cycle = "?", "?"
            try:
                with open(checkpoint_path, encoding="utf-8") as f:
                    cp = json.load(f)
                cp_phase, cp_cycle = cp.get("phase", "?"), cp.get("cycle", "?")
            except (OSError, ValueError):
                pass
            print(
                f"[session] checkpoint found (phase {cp_phase}, cycle {cp_cycle}) "
                f"— re-run to resume",
                file=sys.stderr,
            )

        # Load each role's persisted memory (so roles remember prior runs).
        self.backend.load_state(memory_dir)

        # A revisit: load the saved org chart + the current mission.
        start_version = None
        current_mission = ""
        if revisit:
            loaded_org = OrgState.load(org_chart_path,
                                       history_dir=self.org.history_dir)
            for rid, role in loaded_org.roles.items():
                self.org.roles.setdefault(rid, role)
            self.org.role_definitions.update(loaded_org.role_definitions)
            start_version, current_mission = load_mission(mission_path)

        self.phases = []
        self.cycles = 0

        # --- Phase 1: intake (once) ---
        intake = self._phase(1, 0, run_intake,
            self.backend, self.leader, initial_prompt, user_answer_fn,
            confidence_threshold=self.config.get("confidence_threshold", 0.8),
            question_budget=self.config.get("question_budget", 5),
            history_dir=self.org.history_dir,
            current_mission=current_mission,
            mission_path=mission_path,
        )
        self.phases.append(1)
        # Solo (P1): record the leader's intake so the dashboard can watch it.
        self.solo.record("p1", "Phase 1: intake", 0, "intake",
                         {"summary": f"intake converged={intake.converged} "
                                     f"rounds={intake.rounds}",
                          "confidence": intake.confidence,
                          "converged": intake.converged,
                          "rounds": intake.rounds,
                          "assumptions": intake.assumptions})

        # --- Phase 2: mission (once) ---
        mission = self._phase(2, 0, run_mission,
            self.backend, self.leader, intake, user_permission_fn,
            history_dir=self.org.history_dir,
            reask_budget=self.config.get("mission_reask_budget", 3),
            start_version=start_version,
            current_mission=current_mission,
        )
        self.phases.append(2)
        # Solo (P2): record the leader's mission draft + approval.
        self.solo.record("p2", "Phase 2: mission", 0, "mission",
                         {"summary": f"mission approved={mission.approved} "
                                     f"version={mission.version} "
                                     f"attempts={mission.attempts}",
                          "approved": mission.approved,
                          "version": mission.version,
                          "attempts": mission.attempts,
                          "edits": len(mission.edits)})
        # A1: close the solo pod when the mission phase completes.
        self.solo.close("p2", f"mission approved={mission.approved}, "
                              f"v{mission.version}")
        if not mission.approved:
            return self._escalate("mission not approved by the user", intake, mission)
        mission_draft = mission.edits[-1]["draft"]

        # --- Phase 3: org bootstrap (once) ---
        self._phase(3, 0, bootstrap,
            self.org, self.backend, self.leader, mission, approver_fn,
            additive=revisit,
            bootstrap_timeout_seconds=self.config.get(
                "bootstrap_timeout_seconds", self.config.get("ic_timeout_seconds")))
        self.org.write_events()
        # Story 1 (B1): checkpoint after Phase 3 — a crash in Phase 4 loses at
        # most the current iteration's hires, not the bootstrapped org.
        self._checkpoint(3, 0)
        self.phases.append(3)
        # Solo (P3): record the leader's org-bootstrap.
        self.solo.record("p3", "Phase 3: org bootstrap", 0, "bootstrap",
                         {"summary": "org bootstrapped",
                          "departments": len(self.org.department_heads()),
                          "roles": len(self.org.roles)})
        # A1: close the solo pod when the bootstrap phase completes.
        self.solo.close("p3", "org bootstrapped")

        # --- Phases 4 & 5: iterate (bounded + goal-based stop) ---
        dispatch_results: List[Dict[str, Any]] = []
        verdict = ""
        evaluation: Dict[str, Any] = {}
        status = "complete"
        for _ in range(max_iterations):
            self.cycles += 1

            # Phase 4: dispatch (hires the managers/ICs it decomposes onto). Pods
            # A/B/C form as an add-on; the formed pods accumulate in
            # `self.pods` so their decisions carry up to the leader's
            # Phase 5 synthesis.
            dispatch_results = self._phase(4, self.cycles, dispatch.dispatch,
                self.backend, self.org, self.leader, mission_draft,
                approver_fn=approver_fn,
                pods_out=self.pods,
                history=self.history,
                routing_rules=self.config.get("pod_routing_rules", []),
                artifacts_dir=self.config.get("pod_artifacts_dir", "pods/artifacts"),
                transcripts_dir=self.config.get("pod_transcripts_dir", "pods/transcripts"),
                ic_timeout_seconds=self.config.get("ic_timeout_seconds"),
            )
            self.phases.append(4)
            # Solo (P4): record the dispatch + the thinking-budget remainder so
            # the dashboard can show the budget (Story 2, A6).
            self.solo.record("p4", "Phase 4: dispatch", self.cycles, "dispatch",
                             {"dispatches": len(dispatch_results),
                              "thinking_budget_remaining":
                                  self.thinking_budget.remaining})

            # A Safety/Morality halt during Phase 4 (the only BAU halt).
            if phase4_halt_fn is not None:
                halt = phase4_halt_fn()
                if halt:
                    self.halt_bau(halt["department"], halt["scope"], halt["reason"])
                    self.queue_user_input({"kind": "safety_morality_halt", **halt})

            # Phase 5: synthesis.
            verdict = self._phase(5, self.cycles, self._synthesis)
            self.phases.append(5)

            # Phase 6: evaluation (decides continue / stop).
            evaluation, status = self._phase(6, self.cycles, self._evaluate,
                intake, mission, dispatch_results, verdict, max_iterations
            )
            self.phases.append(6)

            # Story 1 (B1): checkpoint after each Phase 4 iteration — a crash
            # in the NEXT iteration loses at most that iteration's hires.
            self._checkpoint(4, self.cycles)

            if status != "continue":
                break

        # Rolling window + archive cap (Epic 7): old sessions move to the
        # archives; the audit path stays resolvable.
        self.history.maintain()

        # Persist each role's memory (so it carries into the next run) and the
        # org chart (so a --revisit run loads it).
        self.backend.save_state(memory_dir)
        self.org.save(org_chart_path)

        return SessionResult(
            status=status,
            phases=list(self.phases),
            intake=intake,
            mission=mission,
            dispatch_results=dispatch_results,
            pods=list(self.pods),
            verdict=verdict,
            evaluation=evaluation,
            cycles=self.cycles,
        )
