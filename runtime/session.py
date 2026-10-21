"""The session runtime — drives Phases 1–8.

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
- the **Phase 8 self-improving loop**: a bounded **continue/complete**
  decision — continue re-enters Phase 1 with the evaluation as input, still
  abiding by the original goal.

The 8 phases:

1. **Intake** — the leader clarifies the request (a permission gate /
   tiebreaker may pause for the user).
2. **Mission** — the leader drafts the mission (a permission gate pauses for
   the user's approval).
3. **Org bootstrap** — the leader recommends the org; it is created (a
   leader-replacement vote may run).
4. **Plan** — the leader decomposes the mission into department objectives;
   the heads author their policies and decompose into team objectives; the
   managers are hired.
5. **Staff** — the managers decompose their team objectives into IC tasks;
   the ICs are hired.
6. **Execute** — the ICs do the work (with self-edits through the edit gate);
   the A/B/C pod triggers fire; the work propagates up in bounded reports.
7. **Evaluate** — the leader checks progress against the mission (a BAU
   safety/morality halt may pause here).
8. **Decide** — the leader decides **continue** (re-enter Phase 1) or
   **complete** (exit).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from prompts import (
    DECIDE_INSTRUCTION,
    DEVILS_ADVOCATE_INSTRUCTION,
    EVALUATE_INSTRUCTION,
)
from roles.base import Role
from runtime.llm import LLMBackend, MemoryBackend, TimeoutBackend
from runtime.intake import run_intake, IntakeResult
from runtime.mission import run_mission, MissionResult, load_mission
from runtime.org import OrgState, bootstrap, allot_department_caps
from runtime import dispatch
from runtime import plan, staff, execute
from runtime.pods import (
    SoloTracker,
    form_pod,
    run_pod,
    log_devils_advocate_listening,
)
from runtime.history import HistoryStore
from runtime.timing import TimingTracker, TimingBackend
from runtime.efficiency import (
    EfficiencyMeter,
    compute_m_satisfaction,
    EFFICIENCY_FLOOR,
)
from runtime.complexity import (
    RoutingBackend, ThinkingBudget, classify_complexity,
)


@dataclass
class SessionResult:
    status: str  # "complete" / "continue" / "escalated"
    # The phases reached (1..8) — a map of phase number -> how many times it
    # ran (the cycle phases 4-8 run once per iteration; 1-3 run once).
    phases: Dict[int, int] = field(default_factory=dict)
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
        # Story 22 (S22): the efficiency meter — instruments the Phase 3-8 loop
        # per iteration (T_total, T_p3..T_p8, T_dept, T_role, H_peak, C,
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

        # Story 12: the devil's advocate role's Phase-7 verdict (clean /
        # flag: <findings>) — consumed in Phase 8 (a flag forces a re-check /
        # blocks a stop). Reset per cycle in _devils_advocate_verdict.
        self.da_verdict: Optional[str] = None

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

    # --- Phase 7 evaluate -------------------------------------------------

    def _run_reporting_pods(self) -> None:
        """Story 4: the **reporting pods** (Phase 7) — the child reports to the
        parent (after work): ic→manager, manager→head, head→leader. Each is a
        2-member parent+child pod (kind="reporting"), capped at the reporting
        pod round count. The decisions the pods close on are carried up to the
        leader's synthesis (the existing ``self.pods`` carry-over path)."""
        from org import tiers
        config = self.config
        max_rounds = config.get("reporting_pod_rounds")
        # The leader is not a member of `self.org.roles` — add it so the
        # head→leader reporting pod can be formed (starter = the leader).
        roles = {**self.org.roles, self.leader.id: self.leader}
        # ic→manager + manager→head: each role reports to its `reports_to` boss.
        for role in self.org.active_roles():
            if role.architype not in ("ic", "manager"):
                continue
            # Story 12: the devil's advocate role is a special role (a red-team
            # auditor reporting to the leader) — it is NOT a normal ic/manager
            # direct report, so it does not get a reporting pod (it is invoked
            # directly in Phase 7 via _devils_advocate_verdict). A reporting
            # pod for it would span 3 tiers (ic→leader) and violate the <=1
            # tier-spread bound.
            if tiers.is_devils_advocate(role):
                continue
            parent_id = getattr(role, "reports_to", None)
            if not parent_id:
                continue
            parent = roles.get(parent_id)
            if parent is None:
                continue
            pod = form_pod(
                roles, parent.id, [parent.id, role.id],
                f"{role.id} reports to {parent.id} (status / results / "
                f"fire-replace-keep decisions + headcount changes)",
                kind="reporting",
            )
            # Story 12: the devil's advocate "listens" to a reporting pod when
            # the parent is a head (visible, never silent).
            log_devils_advocate_listening(self.org, pod, roles)
            run_pod(self.backend, pod, max_rounds=max_rounds, phase=7)
        # head→leader: each (operational) department head reports to the
        # leader. The required governance heads (hr / safety / morality) are
        # skipped — like the Phase 4 clarification pod, the leader+head working
        # pods exclude the governance departments (they have no work teams to
        # report status / results / headcount changes on).
        for head in self.org.department_heads():
            if head.is_required:
                continue
            pod = form_pod(
                roles, self.leader.id, [self.leader.id, head.id],
                f"{head.id} reports to {self.leader.id} (status / results / "
                f"fire-replace-keep decisions + headcount changes)",
                kind="reporting",
            )
            # Story 12: the devil's advocate "listens" to the head→leader pod
            # (the leader is a member — visible, never silent).
            log_devils_advocate_listening(self.org, pod, roles)
            run_pod(self.backend, pod, max_rounds=max_rounds, phase=7)

    def _evaluate_progress(self) -> str:
        # Story 4: the **reporting pods** (ic→manager, manager→head,
        # head→leader) run BEFORE the leader's synthesis — the child reports
        # to the parent (after work), and the decisions the pods close on are
        # carried up to the leader (the existing `self.pods` carry-over path).
        self._run_reporting_pods()
        ctx = EVALUATE_INSTRUCTION
        # S22: include the efficiency breakdown + E + the mandate to keep E
        # high (the most recent finished iteration's metrics).
        eff_panel = self.efficiency.panel_text()
        if eff_panel:
            ctx += " " + eff_panel
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
                                  reasoning=classify_complexity(7, self.leader, {}),
                                  phase=7)
        # Solo (P5): record the leader's synthesis step so the dashboard can
        # watch it (one transcript file, growing per round). Story 2 (A6): the
        # thinking-budget remainder is included so the dashboard can show it.
        self.solo.record("p7", "Phase 7: evaluate", self.cycles,
                         "synthesis",
                         {**out, "thinking_budget_remaining":
                              self.thinking_budget.remaining,
                           # Story 3 (A4): the BAU halt state is observable —
                           # the dashboard can show an active halt.
                           "bau_active": self.bau_active(),
                           "bau_halt": self.bau_halt})
        # Story 12 (Phase 7): the devil's advocate role's gut check — it
        # doubts the org's outcomes (the leader's synthesis + the pods'
        # deliberations it "listens" to) against what the pipeline has
        # actually produced. The verdict is stored on `self.da_verdict` and
        # consumed in Phase 8.
        self._devils_advocate_verdict(out, decisions)
        # A1: close the solo pod when the synthesis phase completes.
        self.solo.close("p7", f"evaluate verdict={out.get('verdict', 'complete')}")
        return out.get("verdict", "complete")

    # --- Story 12 (Phase 7): the devil's advocate role's gut check ----------

    def _devils_advocate_verdict(self, leader_out: Dict[str, Any],
                                 decisions: List[str]) -> Optional[str]:
        """Story 12 (Phase 7, Evaluate): the devil's advocate role's formal
        "gut check". It is **primed to doubt** — it checks the claims (the
        leader's synthesis + the pods' deliberations it "listens" to) against
        what the pipeline has **actually produced** (the department work),
        **flags** immoral/improper actions (heavy on moral decision-making),
        and returns a verdict: `clean` (no concerns) or `flag: <findings>`
        (concerns raised — fabrication, hallucination, low-quality outcomes,
        immoral/improper actions).

        The verdict is stored on `self.da_verdict` (consumed in Phase 8) and
        logged to the audit (visible, never silent). **Contained**: a missing
        role or an invoke failure is logged and never takes down Phase 7.
        """
        from org import tiers
        da = self.org.get(tiers.DEVILS_ADVOCATE_ROLE)
        if da is None or da.status != "active":
            # The role is always created in bootstrap — if it is missing here,
            # log it visibly (never silent) and skip the gut check.
            self.org.log_event("devils_advocate_missing", None, None,
                               {"phase": 7, "cycle": self.cycles})
            self.da_verdict = None
            return None
        ctx = DEVILS_ADVOCATE_INSTRUCTION
        ctx += " LEADER'S SYNTHESIS (the claims to doubt): " + str(leader_out)
        if decisions:
            ctx += " PODS' DELIBERATIONS (observed): " + "; ".join(decisions)
        dept_work = self._department_work_summary(da)
        if dept_work:
            ctx += " DEPARTMENT WORK (what the pipeline has produced): " \
                   + dept_work
        # The DA's own policy (in place) — the governance record of the DA's
        # mandate (mirroring the working departments' policies).
        try:
            from runtime import permissions
            da_policy = permissions.read_file(
                da, tiers.policy_path(tiers.DEVILS_ADVOCATE_ROLE))
        except Exception:
            da_policy = ""
        if (da_policy or "").strip():
            ctx += " YOUR OWN POLICY (in place): " + da_policy.strip()
        try:
            out = self.backend.invoke(
                da, ctx,
                reasoning=classify_complexity(7, da, {"gut_check": True}),
                phase=7,
            )
        except Exception as e:
            # Contained: an invoke failure is logged, never takes down Phase 7.
            self.org.log_event("devils_advocate_failed", da.id, None,
                               {"phase": 7, "cycle": self.cycles,
                                "error": str(e)})
            self.da_verdict = None
            return None
        verdict = out.get("verdict", "clean")
        self.da_verdict = verdict
        # Visible: the verdict is logged to the audit (the operator can see the
        # gut check; its Phase-8 consequence is logged separately).
        self.org.log_event("devils_advocate_verdict", da.id, None,
                           {"phase": 7, "cycle": self.cycles,
                            "verdict": verdict})
        return verdict

    def _department_work_summary(self, da) -> str:
        """Story 12 (Phase 7): a bounded summary of the department work (what
        the pipeline has **actually produced**) — each department's policy
        markdown (the governance record of its work). Read through the read
        gate on behalf of the devil's advocate role (its cross-department read
        access). Bounded: each policy is truncated; a missing / unreadable file
        contributes nothing (a read of a new file is not an error)."""
        from runtime import permissions
        from org import tiers
        lines: List[str] = []
        seen_depts: set = set()
        for head in self.org.department_heads():
            dept = head.department
            if not dept or dept in seen_depts:
                continue
            seen_depts.add(dept)
            try:
                content = permissions.read_file(da, tiers.policy_path(dept))
            except Exception as e:
                # Visible: a department's policy could not be read (a
                # permission refusal or a missing file) — the DA's gut check
                # notes it (never silent).
                self.org.log_event(
                    "devils_advocate_policy_read_failed", da.id, None,
                    {"department": dept, "error": str(e)})
                content = ""
            content = (content or "").strip()
            if content:
                lines.append(f"[{dept}] {content[:1500]}")
        return "\n".join(lines)

    # --- Phase 8 decide + continue/complete --------------------------------

    def _decide(
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
                {"phase": 8, "reason": evaluation["escalation_reason"],
                 "cycle": self.cycles},
            )
            return evaluation, "escalated"
        self.history.write_evaluation_report(evaluation)
        # S22: include the efficiency breakdown + E + the mandate to keep E
        # high (the most recent finished iteration's metrics).
        p8_ctx = DECIDE_INSTRUCTION + str(evaluation)
        eff_panel = self.efficiency.panel_text()
        if eff_panel:
            p8_ctx += " " + eff_panel
        out = self.backend.invoke(
            self.leader,
            p8_ctx,
            reasoning=classify_complexity(8, self.leader, {}),
            phase=8,
        )
        decision = out.get("verdict", "complete")
        # Solo (P6): record the leader's continue/complete decision so the
        # dashboard can watch it (one transcript file, growing per round).
        self.solo.record("p8", "Phase 8: decide", self.cycles,
                         "decision", out)
        # Story 12 (Phase 8, Decide): consume the devil's advocate verdict — a
        # `flag` forces a re-check (re-evaluate the flagged outcomes) or blocks
        # a stop (does not complete / ship the low-quality or immoral
        # outcomes). The flag is surfaced to the leader (the decision) + the
        # operator (the audit).
        da_verdict = getattr(self, "da_verdict", None)
        flag_active = bool(da_verdict and da_verdict.startswith("flag"))
        if flag_active:
            evaluation["devils_advocate_flag"] = da_verdict
            self.history._append(
                "escalations.jsonl",
                {"phase": 8, "reason": f"devil's advocate flag: {da_verdict}",
                 "cycle": self.cycles},
            )
            # Visible: the Phase-8 consequence is logged to the audit (the
            # operator can see the gut check + its consequence).
            self.org.log_event("devils_advocate_flag_consumed", None, None,
                               {"phase": 8, "cycle": self.cycles,
                                "verdict": da_verdict, "action": "re-check"})
        # A1: close the solo pod when the evaluation phase completes.
        self.solo.close("p8", f"decide decision={decision}")
        if decision == "continue" and self.cycles < max_iterations:
            return evaluation, "continue"
        # Story 12: a flag BLOCKS A STOP — do not complete / ship the
        # low-quality or immoral outcomes (the status is forced to `continue`
        # = re-check the flagged outcomes).
        if flag_active:
            return evaluation, "continue"
        return evaluation, "complete"

    # --- S22: efficiency finishing + the floor trigger --------------------

    def _finish_efficiency(
        self,
        iter_start_ids,
        mission_draft,
        dispatch_results,
        verdict,
    ):
        """S22: finish the loop iteration — compute ``N_created`` (the roles
        that became active this iteration) + ``M_satisfaction`` (0-1, terminal
        + recurring), then finish the efficiency meter (compute ``E`` with the
        running-average refs, append the per-iteration snapshot to the log).
        When ``E < EFFICIENCY_FLOOR``, trigger a visible efficiency action."""
        # S22: N_created = the roles that became active this iteration.
        iter_end_ids = {r.id for r in self.org.active_roles()}
        n_created = len(iter_end_ids - iter_start_ids)
        self.efficiency.record_created(n_created)
        # S22: M_satisfaction (0-1, terminal + recurring).
        m_sat = compute_m_satisfaction(mission_draft, dispatch_results, verdict)
        # S22: finish the iteration (compute E, append to the log).
        snap = self.efficiency.finish_iteration(m_sat)
        # S22: when E < EFFICIENCY_FLOOR, the Leader must take a visible
        # efficiency action.
        if snap.get("below_floor"):
            self._efficiency_floor_action(snap)
        return snap

    def _efficiency_floor_action(self, snap):
        """S22: when ``E < EFFICIENCY_FLOOR``, the Leader must take a visible
        efficiency action. Invoke the Leader with the efficiency breakdown +
        the mandate, and process its ``efficiency`` action (fire / reassign /
        report / automate) via ``dispatch._process_efficiency`` (the automation
        action runs the IC-writes-script -> fired -> script-executed flow)."""
        ctx = (
            "PHASE 8 (efficiency floor): the efficiency score E is BELOW the "
            f"floor ({snap['E']:.3f} < {snap['EFFICIENCY_FLOOR']}). You MUST "
            "take a visible efficiency action to reduce headcount / compute "
            "time. "
            + self.efficiency.panel_text()
            + " Set `efficiency` to a JSON OBJECT with an `action` (\"fire\" "
            "to fire an inefficient role through HR — the firing cascades to "
            "its report subtree; \"reassign\" to move it to a different team, "
            "named in `new_team`; \"report\" to report the inefficiency to the "
            "user; \"automate\" to automate a recurring task, named in `task`) "
            "and a `target` (the role id or department slug) and a `reasoning`."
        )
        out = self.backend.invoke(
            self.leader, ctx,
            reasoning=classify_complexity(8, self.leader, {}),
            phase=8,
        )
        eff = out.get("efficiency")
        if isinstance(eff, dict):
            dispatch._process_efficiency(
                self.org, self.leader, eff, self._approver_fn, self.history)
            # S22: the automation action (IC writes a script -> fired ->
            # script executed).
            if eff.get("action") == "automate":
                dispatch.run_automation(
                    self.org, self.leader, eff, self.backend,
                    self._approver_fn, self.history)
        else:
            # No efficiency action set — log it visibly (never silent).
            self.org.log_event(
                "efficiency_floor_no_action", self.leader.id, None,
                {"E": snap["E"], "floor": snap["EFFICIENCY_FLOOR"]})

    # --- Escalation --------------------------------------------------------

    def _escalate(
        self,
        reason: str,
        intake: Optional[IntakeResult],
        mission: Optional[MissionResult],
    ) -> SessionResult:
        diagnosis = {
            "phase": max(self.phases) if self.phases else None,
            "reason": reason,
            "intake_confidence": intake.confidence if intake else None,
            "mission_approved": mission.approved if mission else None,
        }
        self.history._append("escalations.jsonl", diagnosis)
        # Rolling window + archive cap (Epic 7) — the session is ending.
        self.history.maintain()
        return SessionResult(
            status="escalated",
            phases=dict(self.phases),
            intake=intake,
            mission=mission,
            verdict="escalate",
            cycles=self.cycles,
            escalation=diagnosis,
        )

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
        bootstrap), then Phases 4-8 **iterate** (plan, staff, execute,
        evaluate, decide) for up to `max_iterations` passes — or until the
        decide phase says the deliverable is genuinely polished. The stop is
        **bounded** (the iteration cap) **and goal-based** (the leader can stop
        early on 'complete'); the original goal is still abided by on every
        pass.

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

        self.phases = {}
        self.cycles = 0
        # S22: the Phase 3 (bootstrap) wall-clock time, captured so it can be
        # included in the first loop iteration (the Phase 3-8 loop scope). 0.0
        # when Phase 3 is skipped (a resume from Phase 4).
        p3_started = p3_ended = 0.0

        # S15: a resume-from-checkpoint skips Phases 1-3 (the org + mission
        # are loaded in the revisit branch above) and resumes from Phase 4 —
        # the dispatch continues without re-deriving the intake / mission.
        if resume_from_phase >= 4 and revisit:
            print(
                f"[session] resuming from Phase 4 (skipping Phases 1-3; the "
                f"org + mission are loaded, the dispatch continues)",
                file=sys.stderr,
            )
            intake = None
            mission = None
            mission_draft = current_mission
        else:
            # --- Phase 1: intake (once) ---
            intake = self._phase(1, 0, run_intake,
                self.backend, self.leader, initial_prompt, user_answer_fn,
                confidence_threshold=self.config.get("confidence_threshold", 0.8),
                question_budget=self.config.get("question_budget", 5),
                history_dir=self.org.history_dir,
                current_mission=current_mission,
                mission_path=mission_path,
                state_dir=self.config.get("state_dir", "state"),
            )
            self.phases[1] = self.phases.get(1, 0) + 1
            # Solo (P1): record the leader's intake so the dashboard can
            # watch it.
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
                informal_draft=intake.informal_draft,
            )
            self.phases[2] = self.phases.get(2, 0) + 1
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
                return self._escalate("mission not approved by the user",
                                      intake, mission)
            mission_draft = mission.edits[-1]["draft"]

            # --- Phase 3: org bootstrap (once) ---
            p3_started = time.time()
            self._phase(3, 0, bootstrap,
                self.org, self.backend, self.leader, mission, approver_fn,
                additive=revisit,
                bootstrap_timeout_seconds=self.config.get(
                    "bootstrap_timeout_seconds",
                    self.config.get("ic_timeout_seconds")))
            p3_ended = time.time()
            self.org.write_events()
            # Story 3: the leader allots the **department caps** + **Pod A**
            # (all heads + the leader, the leader has final say) — the
            # department headcount is finalized + recorded in the mission
            # addendum (before the Phase 4 plan allots the team caps).
            allot_department_caps(
                self.org, self.backend, self.leader, mission_path,
                config=self.config)
            # Story 1 (B1): checkpoint after Phase 3 — a crash in Phase 4
            # loses at most the current iteration's hires, not the
            # bootstrapped org.
            self._checkpoint(3, 0)
            self.phases[3] = self.phases.get(3, 0) + 1
            # Solo (P3): record the leader's org-bootstrap.
            self.solo.record("p3", "Phase 3: org bootstrap", 0, "bootstrap",
                             {"summary": "org bootstrapped",
                              "departments": len(self.org.department_heads()),
                              "roles": len(self.org.roles)})
            # A1: close the solo pod when the bootstrap phase completes.
            self.solo.close("p3", "org bootstrapped")

        # --- Phases 4-8: iterate (bounded + goal-based stop) ---
        dispatch_results: List[Dict[str, Any]] = []
        verdict = ""
        evaluation: Dict[str, Any] = {}
        status = "complete"
        for _ in range(max_iterations):
            self.cycles += 1
            # S22: begin the loop iteration (reset the per-iteration
            # accumulators) and capture the active role ids (for N_created).
            self.efficiency.start_iteration()
            iter_start_ids = {r.id for r in self.org.active_roles()}
            if self.cycles == 1 and p3_ended > 0:
                # Phase 3 ran once before the loop — include its time +
                # headcount in the first iteration (S22: the Phase 3-8 loop
                # scope). The _phase() record of Phase 3 was wiped by
                # start_iteration, so re-record it.
                self.efficiency.record_phase(3, p3_started, p3_ended)
                self.efficiency.record_headcount(
                    len(self.org.active_roles()), p3_ended - p3_started)

            # Phase 4: Plan (the leader decomposition + the per-department
            # head workflow — policies, team decomposition, manager hiring).
            plan_result = self._phase(4, self.cycles, plan.run_plan,
                self.backend, self.org, self.leader, mission_draft,
                approver_fn=approver_fn,
                history=self.history,
                config=self.config,
                solo=self.solo,
                timing=self.timing,
            )
            self.phases[4] = self.phases.get(4, 0) + 1

            # Phase 5: Staff (the per-team manager workflow — IC
            # decomposition + IC hiring).
            staff_result = self._phase(5, self.cycles, staff.run_staff,
                self.backend, self.org, self.leader, plan_result,
                approver_fn=approver_fn,
                config=self.config,
                solo=self.solo,
            )
            self.phases[5] = self.phases.get(5, 0) + 1

            # Phase 6: Execute (the per-IC work + self-edits + the A/B/C pod
            # triggers + the upward report). The formed pods accumulate in
            # `self.pods` so their decisions carry up to the leader's
            # Phase 7 evaluation.
            exec_result = self._phase(6, self.cycles, execute.run_execute,
                self.backend, self.org, self.leader, staff_result,
                approver_fn=approver_fn,
                pods_out=self.pods,
                history=self.history,
                routing_rules=self.config.get("pod_routing_rules", []),
                artifacts_dir=self.config.get("pod_artifacts_dir", "pods/artifacts"),
                transcripts_dir=self.config.get("pod_transcripts_dir", "pods/transcripts"),
                ic_timeout_seconds=self.config.get("ic_timeout_seconds"),
                config=self.config,
                solo=self.solo,
            )
            dispatch_results = exec_result.reports
            self.phases[6] = self.phases.get(6, 0) + 1
            # Solo (P6): record the execute + the thinking-budget remainder so
            # the dashboard can show the budget (Story 2, A6).
            self.solo.record("p6", "Phase 6: execute", self.cycles, "dispatch",
                             {"dispatches": len(dispatch_results),
                              "thinking_budget_remaining":
                                  self.thinking_budget.remaining})

            # A Safety/Morality halt during the work (Phases 4-6) (the only
            # BAU halt).
            if phase4_halt_fn is not None:
                halt = phase4_halt_fn()
                if halt:
                    self.halt_bau(halt["department"], halt["scope"], halt["reason"])
                    self.queue_user_input({"kind": "safety_morality_halt", **halt})

            # Story 3 (A10/B12): a GLOBAL Safety/Morality halt stops work
            # before Phase 7 (evaluate) — the halt is CONSUMED, not just
            # recorded (`bau_active()` is False only for a global halt).
            if not self.bau_active():
                return self._escalate("safety/morality halt (global)",
                                      intake, mission)
            if self.bau_halt:
                # A SCOPED halt — do not stop; continue non-blocked work
                # (visible note; full per-department blocking is a follow-up).
                print(
                    f"[session] scoped safety/morality halt in "
                    f"{self.bau_halt.get('department')} — continuing "
                    f"non-blocked work",
                    file=sys.stderr,
                )

            # Phase 7: evaluate (the leader checks progress against the
            # mission).
            verdict = self._phase(7, self.cycles, self._evaluate_progress)
            self.phases[7] = self.phases.get(7, 0) + 1

            # Story 3 (B12): the same check before Phase 8 (decide) — a
            # global halt does not run the continue/complete decision.
            if not self.bau_active():
                return self._escalate("safety/morality halt (global)",
                                      intake, mission)

            # Phase 8: decide (decides continue / stop).
            evaluation, status = self._phase(8, self.cycles, self._decide,
                intake, mission, dispatch_results, verdict, max_iterations
            )
            self.phases[8] = self.phases.get(8, 0) + 1

            # Story 1 (B1): checkpoint after each iteration (Phase 6,
            # execute) — a crash in the NEXT iteration loses at most that
            # iteration's hires.
            self._checkpoint(6, self.cycles)

            # S22: finish the iteration — compute M_satisfaction + E, append
            # the per-iteration snapshot to the log, and handle the
            # EFFICIENCY_FLOOR trigger (a visible efficiency action when
            # E < floor).
            self._finish_efficiency(
                iter_start_ids, mission_draft, dispatch_results, verdict)

            if status != "continue":
                break

        # Rolling window + archive cap (Epic 7): old sessions move to the
        # archives; the audit path stays resolvable.
        self.history.maintain()

        # Persist each role's memory (so it carries into the next run) and the
        # org chart (so a --revisit run loads it).
        # Story 11 (B8): prune stale (fired) roles' memories before saving —
        # only the active role ids (the current org's role ids + the leader)
        # are persisted.
        self.backend.save_state(memory_dir,
                                active_role_ids=self._active_role_ids())
        self.org.save(org_chart_path)

        return SessionResult(
            status=status,
            phases=dict(self.phases),
            intake=intake,
            mission=mission,
            dispatch_results=dispatch_results,
            pods=list(self.pods),
            verdict=verdict,
            evaluation=evaluation,
            cycles=self.cycles,
        )
