"""Shared dispatch helpers (a pure move out of the old monolithic
``runtime/dispatch.py``).

The old Phase 4 (Dispatch) was a single ``dispatch()`` that did the leader
decomposition -> per-department head workflow -> per-team manager workflow ->
per-IC work -> pod triggers -> upward report. It is now split into three
phase modules that import the shared helpers from here:

- ``runtime/plan.py`` (Phase 4, Plan) -- the leader decomposition + the
  per-department head workflow (policies, team decomposition, manager hiring).
- ``runtime/staff.py`` (Phase 5, Staff) -- the per-team manager workflow
  (IC decomposition, IC hiring).
- ``runtime/execute.py`` (Phase 6, Execute) -- the per-IC work + self-edits +
  the A/B/C pod triggers + the upward report.

This module contains **only** helpers (no phase sequence). The three phase
modules import from it.
"""


from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from prompts import (
    AUTOMATION_CTX_MID,
    AUTOMATION_CTX_PREFIX,
    AUTOMATION_CTX_SUFFIX,
    HEAD_CTX_DIGEST,
    HEAD_CTX_INSTRUCTION,
    HEAD_CTX_OBJ,
    HEAD_CTX_PREFIX,
    IC_CTX_CLAR_PREFIX,
    IC_CTX_DIGEST,
    IC_CTX_INSTRUCTION_MID,
    IC_CTX_INSTRUCTION_PREFIX,
    IC_CTX_INSTRUCTION_SUFFIX,
    IC_CTX_PATH_RULES_BARE,
    IC_CTX_PATH_RULES_CONCRETE_END,
    IC_CTX_PATH_RULES_CONCRETE_MID,
    IC_CTX_PATH_RULES_CONCRETE_PREFIX,
    IC_CTX_PATH_RULES_CONCRETE_SUFFIX,
    IC_CTX_PATH_RULES_CONCRETE_TAIL,
    IC_CTX_POLICY,
    IC_CTX_PREFIX,
    IC_CTX_TASK,
    IC_CTX_WORK_DIR,
    IC_CTX_WRITE_ALL,
    IC_RETRY_NUDGE,
    LEADER_CTX_DIGEST,
    LEADER_CTX_INSTRUCTION,
    LEADER_CTX_NO_INVENT,
    MANAGER_CTX_CLAR_PREFIX,
    MANAGER_CTX_DIGEST,
    MANAGER_CTX_INSTRUCTION,
    MANAGER_CTX_OBJ,
    MANAGER_CTX_POLICY,
    MANAGER_CTX_PREFIX,
    POLICY_CTX_CLAR_PREFIX,
    POLICY_CTX_DIRECTIVE,
    POLICY_CTX_EXISTING,
    POLICY_CTX_INSTRUCTION,
    POLICY_CTX_OBJ,
    POLICY_CTX_PREFIX,
    POD_UPWARD_REPORT_MID,
    POD_UPWARD_REPORT_PREFIX,
    POD_UPWARD_REPORT_SUFFIX,
    SELF_EDIT_CORRECTION_MID,
    SELF_EDIT_CORRECTION_PREFIX,
    SELF_EDIT_CORRECTION_SUFFIX,
)
from roles.base import Role, spin_personality, spin_sub_architype
from roles.worker import worker_output_schema
from org import tiers
from runtime.org import (
    OrgState,
    hire,
    fire,
    run_leader_replacement_vote,
    ResourcingError,
    ResourcingVetoed,
    MAX_ORG_ROLES,
)
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity, detect_disagreement
from runtime.history import HistoryStore
from runtime.timing import TimingTracker
from runtime.permissions import apply_code_edits, read_file
from runtime.coerce import as_dict_list
from runtime.pods import (
    Pod,
    PodMembershipError,
    form_pod,
    run_pod,
    write_decision_artifact,
    write_transcripts,
    senior_member,
    chained_pod,
    SoloTracker,
)


def mission_digest(mission: Dict[str, Any]) -> str:
    """A bounded digest of the mission (purpose + success criteria + scope) —
    what leaders/heads see, not the full MISSION.md."""
    parts = []
    for key in ("purpose", "success_criteria", "scope"):
        val = mission.get(key, "")
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val)
        if val:
            parts.append(f"{key}: {val}")
    return " | ".join(parts) if parts else "(no mission digest)"


def _run_contained_pod(backend: LLMBackend, org: OrgState, pod: Pod,
                       max_rounds: Optional[int] = None,
                       phase: int = 4) -> None:
    """Run a clarification pod with **containment** (Story 4): a backend
    failure inside the pod is logged (visible, never silent) and the phase
    continues (the pod's decision stays empty). A clarification pod must not
    take down the phase it clarifies. The pod's kind drives the default capped
    round count (an explicit ``max_rounds`` overrides it).

    The pod is always **formed** by the caller (so its membership is validated
    + recorded); only its **run** is contained here.
    """
    try:
        run_pod(backend, pod, max_rounds=max_rounds, phase=phase)
    except Exception as e:
        org.log_event(
            "pod_failed", pod.starter.id, None,
            {"pod": pod.id, "kind": pod.kind, "error": str(e)},
        )


def _leader_ctx(digest: str, head_ids: List[str],
                efficiency_panel: str = "") -> str:
    base = (
        LEADER_CTX_DIGEST + digest +
        LEADER_CTX_INSTRUCTION + str(head_ids) +
        LEADER_CTX_NO_INVENT
    )
    # Story 22: the Leader is invoked with the efficiency panel (per-role /
    # per-department invoke time) so it can act on an inefficient role or
    # department.
    if efficiency_panel:
        base += " " + efficiency_panel
    return base


def _efficiency_panel_text(snap: Dict[str, Any]) -> str:
    """Render the efficiency panel (per-role + per-department invoke time,
    cumulative) as text for the Leader's Phase 4 context (Story 22)."""
    per_role = snap.get("per_role", {})
    per_dept = snap.get("per_department", {})
    lines = [
        "EFFICIENCY PANEL (per-role / per-department invoke time, cumulative):"
    ]
    if per_role:
        lines.append("  per-role:")
        for rid, t in sorted(per_role.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {rid}: {t:.1f}s")
    if per_dept:
        lines.append("  per-department:")
        for dept, t in sorted(per_dept.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {dept}: {t:.1f}s")
    if not per_role and not per_dept:
        lines.append("  (no invoke time recorded yet)")
    lines.append(
        "If a role or department is inefficient, set `efficiency` with an "
        "`action` (\"fire\" to fire it through HR resourcing — the firing "
        "cascades to its report subtree; \"reassign\" to move it to a "
        "different team, named in `new_team`; \"report\" to report the "
        "inefficiency to the user without acting) and `target` (the role id or "
        "department slug)."
    )
    return "\n".join(lines)


def _reassign_role(org, leader, target_id, new_team, reasoning, history) -> None:
    """Reassign a role to a different team (Story 22). The role's `team` (its
    work-directory slug) is changed; the move is logged visibly (never
    silent)."""
    role = org.get(target_id)
    if role is None:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "reassign",
                             "target": target_id, "reasoning": reasoning,
                             "error": "unknown role"})
        return
    if not new_team:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "reassign",
                             "target": target_id, "reasoning": reasoning,
                             "error": "no new_team specified"})
        return
    old_team = role.team
    role.team = new_team
    org.log_event("role_reassigned", leader.id, target_id,
                  {"old_team": old_team, "new_team": new_team,
                   "reasoning": reasoning})
    if history is not None:
        history._append("efficiency_reports.jsonl",
                        {"ts": time.time(), "action": "reassign",
                         "target": target_id, "old_team": old_team,
                         "new_team": new_team, "reasoning": reasoning})


def _process_efficiency(org, leader, eff: Dict[str, Any], approver_fn,
                        history) -> None:
    """Process the Leader's efficiency action (Story 22): fire / reassign /
    report an inefficient role or department. All actions are logged visibly
    (never silent)."""
    action = eff.get("action")
    target = eff.get("target")
    reasoning = eff.get("reasoning", "")
    if not action or not target:
        return
    if action == "fire":
        # Fire the inefficient role through HR resourcing (cascades to its
        # report subtree).
        _fire_role(org, leader, target, f"efficiency: {reasoning}",
                   approver_fn, history)
    elif action == "reassign":
        # Reassign the named role to a different team.
        _reassign_role(org, leader, target, eff.get("new_team"), reasoning,
                       history)
    elif action == "report":
        # Report the inefficiency to the user (no action).
        org.log_event("efficiency_reported", leader.id, target,
                      {"reasoning": reasoning})
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "report",
                             "target": target, "reasoning": reasoning})
    elif action == "automate":
        # A recurring task is being automated (an IC writes a Python script, is
        # fired, and the task is then done by executing the script). The actual
        # IC-writes-script -> fired -> script-executed flow is run by
        # ``run_automation`` (the caller, which has the backend); here we just
        # log the action visibly (never silent) so it is not mistaken for an
        # unknown action.
        org.log_event("efficiency_automate_requested", leader.id, target,
                      {"task": eff.get("task", target), "reasoning": reasoning})
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "automate",
                             "target": target,
                             "task": eff.get("task", target),
                             "reasoning": reasoning})
    else:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": action,
                             "target": target, "reasoning": reasoning,
                             "error": "unknown efficiency action"})


def _head_ctx(head: Role, objective: str, digest: str) -> str:
    return (
        HEAD_CTX_PREFIX + head.id +
        HEAD_CTX_OBJ + objective +
        HEAD_CTX_DIGEST + digest +
        HEAD_CTX_INSTRUCTION
    )


def _manager_ctx(manager: Role, objective: str, policy: str = "",
                 digest: str = "", clarification: str = "") -> str:
    # The prompt contract: {mission} + {department policy} + {short-term
    # memory} + {current objective}. The mission digest (the org's goal) is
    # the manager's north star; the department policy (the head's POLICY.md)
    # is its operating constraint (managers get the FULL policy). The role's
    # memory (its past [content] outputs) is auto-folded by the
    # MemoryBackend.
    # **Story 5:** the context also includes the **head+manager clarification
    # pod's outcome** (``clarification``) — the manager decomposes **after**
    # the pod, so its IC tasks reflect the clarified team mission (the pod →
    # decomposition sequencing is strict).
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the manager id, the objective, the policy, the digest, the
    # clarification) is composed in here.
    clarification_line = (
        MANAGER_CTX_CLAR_PREFIX + clarification
        if clarification else ""
    )
    return (
        MANAGER_CTX_PREFIX + manager.id +
        MANAGER_CTX_OBJ + objective +
        clarification_line +
        MANAGER_CTX_DIGEST + (digest or "(none)") +
        MANAGER_CTX_POLICY + (policy or "(none)") +
        MANAGER_CTX_INSTRUCTION
    )


def _ic_ctx(ic: Role, task: str, policy_summary: str = "",
            digest: str = "", clarification: str = "") -> str:
    # The prompt contract: {mission} + {department policy summary} +
    # {short-term memory} + {current task}. The mission digest (the org's
    # goal) is the IC's north star; the department policy summary (NOT the
    # full policy) is its operating constraint. The role's memory (its past
    # [content] outputs) is auto-folded by the MemoryBackend.
    # **Story 5:** the context also includes the **manager+ic clarification
    # pod's outcome** (``clarification``) — the IC does its work **after** the
    # pod, so the work reflects the clarified task (the pod → work sequencing
    # is strict).
    # The exact team work root (departments/<dept>/<team>/). The IC must write
    # there — a bare top-level dir is refused by the permission layer as
    # out_of_scope, so the prompt names the real root, shows a correct/wrong
    # pair, and forbids the role's own id as a directory (the default the
    # model falls into when no concrete root is given).
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the ic id, the team root, the path rules, the task, the
    # policy summary, the clarification) is composed in here.
    if ic.department and ic.team:
        team_root = f"departments/{ic.department}/{ic.team}"
        path_rules = (
            IC_CTX_PATH_RULES_CONCRETE_PREFIX + team_root +
            IC_CTX_PATH_RULES_CONCRETE_MID + team_root +
            IC_CTX_PATH_RULES_CONCRETE_SUFFIX + ic.team +
            IC_CTX_PATH_RULES_CONCRETE_TAIL + ic.id +
            IC_CTX_PATH_RULES_CONCRETE_END
        )
    else:
        team_root = "your team directory"
        path_rules = IC_CTX_PATH_RULES_BARE
    clarification_line = (
        IC_CTX_CLAR_PREFIX + clarification
        if clarification else ""
    )
    return (
        IC_CTX_PREFIX + ic.id +
        IC_CTX_WORK_DIR + team_root +
        IC_CTX_WRITE_ALL + path_rules +
        IC_CTX_DIGEST + (digest or "(none)") +
        IC_CTX_POLICY + (policy_summary or "(none)") +
        IC_CTX_TASK + task +
        clarification_line +
        IC_CTX_INSTRUCTION_PREFIX + team_root +
        IC_CTX_INSTRUCTION_MID + team_root +
        IC_CTX_INSTRUCTION_SUFFIX
    )


def _policy_ctx(head: Role, mission_digest: str, existing_policy: str,
                directive: str, clarification: str = "") -> str:
    """The head's Phase 4 policy-generation context. The head is invoked
    BEFORE it decomposes into managers to produce (a) the full department
    POLICY markdown and (b) a POLICY_SUMMARY that distils the key policy points
    for ICs. Context = Mission + the head's existing policy (Department
    Instructions) + the boss's directive (the leader's department objective, or
    the head's mandate for a required dept) + the role's memory (auto-folded by
    the MemoryBackend).

    **Story 5:** the context also includes the **leader+head clarification
    pod's outcome** (``clarification``) — the policy is authored **after** the
    pod, so it reflects the clarified mission (the pod → policy sequencing is
    strict)."""
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the head id, the mission digest, the directive, the
    # existing policy, the clarification) is composed in here.
    clarification_line = (
        POLICY_CTX_CLAR_PREFIX + clarification
        if clarification else ""
    )
    return (
        POLICY_CTX_PREFIX + head.id +
        POLICY_CTX_OBJ + mission_digest +
        POLICY_CTX_DIRECTIVE + directive +
        clarification_line +
        POLICY_CTX_EXISTING + (existing_policy or "(none yet)") +
        POLICY_CTX_INSTRUCTION
    )


def _read_policy(dept: str, departments_dir: str) -> str:
    """The existing content of a department's policy markdown ("" if missing)."""
    if not dept:
        return ""
    path = os.path.join(departments_dir, dept, f"{dept.upper()}_POLICY.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_policy(dept: str, policy_text: str, departments_dir: str) -> None:
    """Write a department's policy markdown (creating the dir if needed)."""
    if not dept or not policy_text:
        return
    dept_dir = os.path.join(departments_dir, dept)
    os.makedirs(dept_dir, exist_ok=True)
    with open(os.path.join(dept_dir, f"{dept.upper()}_POLICY.md"), "w",
              encoding="utf-8") as f:
        f.write(policy_text)


def _work_path(ic: Role, task: Dict[str, Any]) -> str:
    """The team-directory path where the IC's work lives (the leader never
    reads it — it is brought up as a bounded summary + pointer)."""
    return f"departments/{ic.department}/{ic.team}/{task.get('id', 'work')}.md"


def _upward_report(role: Role, children: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A structured upward report: a bounded summary + artifact pointers (not
    the full work). This is how work propagates up the line of command."""
    return {
        "from": role.id,
        "summary": f"{len(children)} unit(s) reported up",
        "pointers": [c.get("pointer") for c in children if c.get("pointer")],
        "children": [
            {"from": c.get("from"), "summary": c.get("summary")}
            for c in children
        ],
    }


def _invoke_ic(backend: LLMBackend, ic: Role, ctx: str, reasoning,
               timeout: Optional[float], phase: int) -> Tuple[
                   Optional[Dict[str, Any]], Optional[str]]:
    """Invoke an IC with **one corrective retry** on a failure (error
    containment). Returns ``(output, error)``: on success ``error`` is None;
    if the corrective retry also fails, ``output`` is None and ``error`` is a
    visible description (the caller records the IC's failure in its upward
    report and continues — one IC hiccup must not kill the run).

    The corrective retry re-asks the SAME task with a nudge appended (the
    model's malformed / missing reply is called out; it must produce one
    complete submit_output call) — the same one-retry-on-refusal pattern the
    self-edit path already uses.
    """
    # The nudge text lives in prompts/ (Story 11 — a pure move).
    nudge = IC_RETRY_NUDGE
    try:
        return backend.invoke(
            ic, ctx, reasoning=reasoning, timeout=timeout, phase=phase,
        ), None
    except Exception as e:
        # Containment boundary: a model quirk (a malformed tool call), a
        # timeout, a transport blip — recorded visibly below, never a
        # run-killer.
        try:
            return backend.invoke(
                ic, ctx + nudge, reasoning=reasoning, timeout=timeout,
                phase=phase,
            ), None
        except Exception as e2:
            return None, (f"{type(e).__name__}: {e} "
                          f"(corrective retry failed: {type(e2).__name__}: "
                          f"{e2})")


def _self_edit_log(history: Optional[HistoryStore], role_id: str):
    """A log callable for self-edit results (appends to the HistoryStore's
    ``self_edits.jsonl`` audit, so a refusal is visible, not swallowed).
    Returns None when no history is available (the results are still returned
    by ``apply_code_edits``)."""
    if history is None:
        return None
    def log(msg: str) -> None:
        history._append("self_edits.jsonl", {"role": role_id, "msg": msg})
    return log


def _repair_edit_paths(
    ic: Role,
    edits: List[Dict[str, Any]],
    history: Optional[HistoryStore],
) -> List[Dict[str, Any]]:
    """Repair bare top-level paths the model emitted for its own team dir.

    When a path's top-level component is the role's own id or team (the model
    dropped the ``departments/<dept>/`` prefix), rewrite it into the
    department scope the permission layer already grants in-dept roles. Only
    such paths are repaired — any other out-of-scope path (another dept,
    ``runtime/``, ``MISSION.md``) is left for the gate to refuse, so the
    repair can never become a channel around the sandbox. Each repair is
    logged visibly (``history/path_repairs.jsonl``) so the audit shows the
    harness corrected the model.
    """
    own = {name for name in (ic.id, ic.team) if name}
    repaired: List[Dict[str, Any]] = []
    for edit in edits:
        if not isinstance(edit, dict) or not ic.department:
            repaired.append(edit)
            continue
        norm = str(edit.get("path", "")).replace("\\", "/")
        parts = norm.split("/", 1)
        top = parts[0]
        if (
            top in own
            and len(parts) > 1            # a subpath (a file), not a bare dir
            and not norm.startswith("departments/")
        ):
            fixed = "departments/%s/%s" % (ic.department, norm)
            note = dict(edit)
            note["path"] = fixed
            note["_repaired_from"] = str(edit.get("path", ""))
            if history is not None:
                history._append(
                    "path_repairs.jsonl",
                    {"ts": time.time(), "role": ic.id,
                     "from": str(edit.get("path", "")), "to": fixed},
                )
            repaired.append(note)
        else:
            repaired.append(edit)
    return repaired


def _ic_pre_read(
    ic: Role,
    edits: List[Dict[str, Any]],
    history: Optional[HistoryStore],
) -> None:
    """The IC reads the code it is about to change (gated by the **read gate**
    — the read invariants: the sandbox, the mission lock, the meta-rule lock,
    the department scope, the code-read invariants). This is the concrete
    "a role reads a file" in the dispatch that the read gate wires into.

    A **cross-team read** (a sibling team dir in the same department) is
    **logged** (visible, not silent); a **refused read** is **logged**
    (visible, never silent). The write gate remains authoritative — this is
    the read observability step (the read of a new file is not an error)."""
    def log(msg: str) -> None:
        if history is not None:
            history._append("self_edits.jsonl", {"role": ic.id, "msg": msg})
    for edit in edits:
        if not isinstance(edit, dict):
            continue
        path = edit.get("path", "")
        if not path:
            continue
        try:
            read_file(ic, path, log=log)
        except PermissionError as e:
            log(f"REFUSED read: {ic.id!r} -> {path!r}: {e}")


def _run_self_edits(
    ic: Role,
    edits: List[Dict[str, Any]],
    history: Optional[HistoryStore],
) -> List[Dict[str, Any]]:
    """Repair + apply + log one batch of self-edits for an IC (gated by the
    permission layer). Returns the per-edit results (the gate's decisions)."""
    edits = _repair_edit_paths(ic, edits, history)
    # The IC reads the code it is about to change (gated by the read gate —
    # the read invariants; a cross-team read is logged, a refused read is
    # logged, both visible, never silent).
    _ic_pre_read(ic, edits, history)
    results = apply_code_edits(ic, edits, log=_self_edit_log(history, ic.id))
    if history is not None:
        for r in results:
            history.log_code_edit(
                ic.id, r["path"], r["ok"],
                error=r.get("error", ""),
                department=ic.department,
            )
    return results


def _retry_refused_edits(
    ic: Role,
    refused: List[Dict[str, Any]],
    history: Optional[HistoryStore],
    backend: LLMBackend,
    phase: int = 4,
) -> None:
    """One corrective retry for refused self-edits: the model is shown the
    specific refusal reasons (which name the role's team work dir) and asked
    to re-propose the edits with corrected paths. Bounded to a single pass —
    a second refusal stands (visible, never looped). Best-effort: a backend
    failure just means no retry (the original refusals are already logged)."""
    reasons = "\n".join(
        "- %s — %s" % (r.get("path", ""), r.get("error", "")) for r in refused
    )
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the ic id, the refusal reasons) is composed in here.
    ctx = (
        SELF_EDIT_CORRECTION_PREFIX + ic.id +
        SELF_EDIT_CORRECTION_MID +
        reasons +
        SELF_EDIT_CORRECTION_SUFFIX
    )
    try:
        out = backend.invoke(ic, ctx,
                             reasoning=classify_complexity(phase, ic, {}),
                             phase=phase)
    except Exception as e:
        # Visible: the corrective re-invoke failed (a backend failure). The
        # original refusals are already logged; this records that no retry
        # happened (never silent).
        if history is not None:
            history._append("dispatch_skips.jsonl",
                            {"role_id": ic.id, "reason": "self_edit_retry",
                             "why": f"corrective re-invoke failed: {e}"})
        return
    edits = as_dict_list((out or {}).get("code_edits", []))
    if not edits:
        return
    # One bounded corrective pass — the results are logged; no further retry.
    _run_self_edits(ic, edits, history)


def _apply_ic_self_edits(
    ic: Role,
    ic_out: Dict[str, Any],
    history: Optional[HistoryStore],
    backend: Optional[LLMBackend] = None,
    phase: int = 4,
) -> None:
    """Collect, repair, and apply an IC's self-edit requests (gated by the
    permission layer), with one corrective retry on refusal. Refusals,
    repairs, and the retry are all recorded visibly (never silent)."""
    edits = as_dict_list((ic_out or {}).get("code_edits", []))
    if not edits:
        return
    results = _run_self_edits(ic, edits, history)
    refused = [r for r in results if not r.get("ok")]
    if refused and backend is not None:
        _retry_refused_edits(ic, refused, history, backend, phase)


def _ensure_role(
    org: OrgState,
    initiator: Role,
    role_id: str,
    architype: str,
    department: str,
    team: str,
    approver_fn,
    direct_ic_cap: int = 3,
    backend: Optional[LLMBackend] = None,
    phase: int = 4,
) -> Optional[Role]:
    """Get a role by ID, or create + hire it (through the approval matrix) if
    it doesn't exist yet. This is how the dispatch spins up the managers/ICs it
    decomposes onto, so the full heads->managers->ICs chain is exercised.
    Returns None if it can't be hired (no approver supplied, or the hire is
    vetoed / the 3-IC cap is hit).

    On a hire failure the failure is **sent back to the initiator** (the
    manager/head that requested the hire) so it can update its next steps
    (re-decompose its IC tasks / note the failure in its upward report) —
    visible, never silent (``backend`` is required for the re-invoke; without
    it the failure is still logged as an org event)."""
    role = org.get(role_id)
    if role is not None:
        return role
    if approver_fn is None:
        return None
    # Story 11 (B16): total org-size cap — refuse a hire that would exceed the
    # cap (visible note, never silent).
    if len(org.roles) >= MAX_ORG_ROLES:
        print(
            f"[dispatch] org-size cap reached ({MAX_ORG_ROLES}) — refusing to "
            f"hire {role_id} (visible note, never silent).",
            file=sys.stderr,
        )
        _send_hire_failure_to_initiator(
            org, initiator, role_id, architype, department, team,
            f"org-size cap reached ({MAX_ORG_ROLES})", backend, phase)
        return None
    # Spin a functional specialty + a stable behavioral bias so a spun
    # manager/IC is never left with an empty identity (the prompt rendered
    # "(architype=ic, sub-architype=, personality=)" before this).
    new_role = Role(
        id=role_id,
        architype=architype,
        sub_architype=spin_sub_architype(architype, role_id),
        personality=spin_personality(role_id),
        department=department,
        team=team,
        reports_to=initiator.id,
        output_schema=worker_output_schema(architype),
    )
    try:
        return hire(org, initiator, new_role, approver_fn,
                    direct_ic_cap=direct_ic_cap)
    except Exception as e:
        # Visible: the hire failed (vetoed / cap / approver rejection). The
        # failure is sent back to the initiator so it can update its next
        # steps (never silent).
        _send_hire_failure_to_initiator(
            org, initiator, role_id, architype, department, team,
            f"{type(e).__name__}: {e}", backend, phase)
        return None


def _send_hire_failure_to_initiator(
    org: OrgState,
    initiator: Role,
    role_id: str,
    architype: str,
    department: str,
    team: str,
    error: str,
    backend: Optional[LLMBackend],
    phase: int,
) -> None:
    """Send a hire failure back to the initiator (the manager/head that
    requested the hire) so it can update its next steps (re-decompose its IC
    tasks / note the failure in its upward report). The failure is logged
    visibly (an org event) and the initiator is re-invoked with a correction
    context (it must not assign work to a role that does not exist).

    Best-effort: a failure in the corrective re-invoke is not fatal (the hire
    already failed; the org event records it)."""
    # Visible: the hire failure is logged (the operator + the dashboard can see
    # it; the initiator's report will reference it).
    org.log_event("hire_failed", initiator.id, role_id,
                  {"architype": architype, "department": department,
                   "team": team, "error": error})
    if backend is None:
        return
    ctx = (
        f"YOUR HIRE FAILED: your request to hire {role_id} "
        f"(architype={architype}, department={department}, team={team}) "
        f"FAILED ({error}). You CANNOT assign work to a role that does not "
        f"exist. Update your next steps: (1) do NOT reference {role_id} in "
        f"your task assignments; (2) re-decompose your IC tasks / adjust your "
        f"plan to account for this failure (reassign the work to an existing "
        f"role or drop it); (3) note the failed hire in your upward report so "
        f"the line of command knows the work is unassigned."
    )
    try:
        backend.invoke(initiator, ctx,
                       reasoning=classify_complexity(phase, initiator, {}),
                       phase=phase)
    except Exception:
        # The corrective re-invoke failing is not fatal (the hire already
        # failed; the org event records it).
        pass


def _fire_role(org, leader, role_id, reason, approver_fn, history=None):
    """Fire a role (through the HR approver) — the dispatch's parallel to
    `_ensure_role` (the hire path). The `fire` path marks the role inactive
    (kept in the org chart, not deleted), offloads its work, and journals the
    event. A veto / required-role rejection / missing approver is logged
    visibly, never swallowed."""
    if approver_fn is None:
        if history is not None:
            history._append("dispatch_skips.jsonl",
                            {"role_id": role_id, "reason": reason,
                             "why": "fire requested but no approver supplied"})
        return None
    try:
        return fire(org, leader, role_id, approver_fn)
    except ResourcingVetoed as e:
        if history is not None:
            history._append("dispatch_skips.jsonl",
                            {"role_id": role_id, "reason": reason,
                             "why": f"fire vetoed: {e}"})
        return None
    except ResourcingError as e:
        if history is not None:
            history._append("dispatch_skips.jsonl",
                            {"role_id": role_id, "reason": reason,
                             "why": f"fire rejected: {e}"})
        return None


# --- S22: automation over headcount ----------------------------------------

def _automation_slug(task: str) -> str:
    """A short directory slug for an automation task (the script filename)."""
    out = []
    for ch in (task or "task").lower():
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:40] or "task"


def run_automation(org, leader, eff, backend, approver_fn, history=None,
                   script_dir="automations"):
    """S22: the **automation over headcount** flow — for a recurring task, spin
    up an IC to **write a Python script**, the script is **created** (written to
    ``<script_dir>/<slug>.py``), the IC is **fired** (if not needed for other
    work), and the recurring task is then done by **executing the script**
    (subprocess / tool call) instead of an IC each time.

    ``eff`` is the Leader's efficiency action dict (``action="automate"``,
    ``task`` the recurring task, ``target`` the role/department, ``reasoning``).
    All steps are logged visibly (never silent).
    """
    task = eff.get("task") or eff.get("target") or "(unspecified recurring task)"
    reasoning = eff.get("reasoning", "")
    # The script path (where the automation script lives).
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, _automation_slug(task) + ".py")
    # Step 1: spin up an IC to write the script (hired through the approval
    # matrix, like any other dispatch role).
    ic_id = "auto-" + _automation_slug(task)
    ic = _ensure_role(org, leader, ic_id, "ic", "automations", "automations",
                      approver_fn, backend=backend, phase=4)
    if ic is None:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "automate",
                             "task": task,
                             "error": "could not hire the automation IC"})
        return {"task": task, "script_path": script_path, "ic_fired": None,
                "error": "could not hire the automation IC"}
    # Step 2: the IC writes the Python script for the recurring task.
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the ic id, the task) is composed in here.
    ctx = (
        AUTOMATION_CTX_PREFIX + ic.id +
        AUTOMATION_CTX_MID + task +
        AUTOMATION_CTX_SUFFIX
    )
    out = backend.invoke(ic, ctx,
                         reasoning=classify_complexity(4, ic, {}), phase=4)
    script = out.get("script", "") if isinstance(out, dict) else ""
    # Step 3: the script is created (written to a file).
    if script:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
    org.log_event("automation_script_created", leader.id, ic.id,
                  {"task": task, "script_path": script_path,
                   "reasoning": reasoning})
    if history is not None:
        history._append("efficiency_reports.jsonl",
                        {"ts": time.time(), "action": "automate",
                         "task": task, "script_path": script_path,
                         "reasoning": reasoning})
    # Step 4: the IC is fired (if not needed for other work) — the recurring
    # task is now done by executing the script instead of an IC each time.
    _fire_role(org, leader, ic.id, f"automation: {reasoning}", approver_fn,
               history)
    # Step 5: the automation is active (a visible log — the script is executed
    # via subprocess when the recurring task is due).
    org.log_event("automation_active", leader.id, ic.id,
                  {"task": task, "script_path": script_path})
    return {"task": task, "script_path": script_path, "ic_fired": ic.id}


# --- Pods A/B/C multi-trigger (an add-on to the dispatch) ------------------

def _task_types(team_obj: Dict[str, Any], ic_tasks: List[Dict[str, Any]]) -> List[str]:
    """The task types in scope for a team objective (trigger C): the
    objective's own `task_type` + each IC task's `task_type`."""
    types = [team_obj.get("task_type")]
    types.extend(t.get("task_type") for t in ic_tasks)
    return [t for t in types if t]


def _pod_topic(objective: str, triggers: List[str]) -> str:
    return (
        f"Phase 6 pod (triggers: {', '.join(triggers)}) — "
        f"{objective or 'the team objective'}"
    )


def _check_pod_triggers(
    backend: LLMBackend,
    org: OrgState,
    starter: Role,
    ic_ids: List[str],
    team_obj: Dict[str, Any],
    ic_outputs: List[Dict[str, Any]],
    ic_tasks: List[Dict[str, Any]],
    routing_rules: Optional[List[str]],
    pods_out: Optional[List[Pod]],
    history: Optional[HistoryStore],
    artifacts_dir: str,
    transcripts_dir: str = "pods/transcripts",
    starter_in_members: bool = True,
    config: Optional[Dict[str, Any]] = None,
    phase: int = 4,
) -> None:
    """The pods A/B/C multi-trigger — form a pod when any trigger fires:

    - **A (disagreement)**: `detect_disagreement(ic_outputs)` — conflicting
      recommendations across the IC work outputs (the dispatch keeps the full
      IC outputs for this; the upward reports alone would not suffice).
    - **B (cross-team)**: the team objective is marked `cross_team`
      (optionally naming the other teams' roles in `cross_team_with`).
    - **C (routing rule)**: a task type matches the routing-rule config
      (a list of task types that always go to a pod, e.g. "evaluation"/
      "incident").

    When one fires, the pod is formed (the **starter** + the ICs involved —
    manager + ICs is a valid 1-tier spread), run, and its decision is carried
    **all three ways**: written to `pods/artifacts/` (+ the `history`
    decision journal), collected for the leader's Phase 7 evaluate
    (`pods_out`), and seeded into the members' memory as a cross-team
    `pod:<id>` entry (via `MemoryBackend.seed_cross_team` — a no-op for a
    plain `StubBackend`).

    A membership failure (e.g. a 2-tier spread — an IC podding with a
    department head) **skips the pod**; the dispatch continues.
    """
    triggers: List[str] = []
    if detect_disagreement(ic_outputs):
        triggers.append("A")
    if team_obj.get("cross_team"):
        triggers.append("B")
    rules = routing_rules or []
    if any(t in rules for t in _task_types(team_obj, ic_tasks)):
        triggers.append("C")
    if not triggers:
        return

    # The starter + the ICs involved. For a cross-team objective, the other
    # teams' roles named in `cross_team_with` join the pod (validated — a
    # 2-tier spread is rejected and the pod is skipped).
    member_ids = [starter.id] if starter_in_members else []
    member_ids.extend(dict.fromkeys(ic_ids))
    if team_obj.get("cross_team"):
        member_ids.extend(
            rid for rid in team_obj.get("cross_team_with", []) if org.get(rid)
        )
    roles = {r.id: r for r in org.roles.values()}
    try:
        pod = form_pod(
            roles, starter.id, member_ids,
            _pod_topic(team_obj.get("objective", ""), triggers),
            cross_team=bool(team_obj.get("cross_team")),
            min_roles=(config or {}).get("pod_min_roles", tiers.POD_MIN_ROLES),
            max_roles=(config or {}).get("pod_max_roles", tiers.POD_MAX_ROLES),
        )
    except PodMembershipError:
        return
    run_pod(backend, pod, max_rounds=(config or {}).get("pod_max_rounds", 3),
            transcripts_dir=transcripts_dir,
            budget_tokens=(config or {}).get("context_budget_tokens", 4000),
            phase=phase)
    # Write the pod's transcript (pods/transcripts/) + its decision artifact
    # (pods/artifacts/).
    write_transcripts(pod, transcripts_dir=transcripts_dir)
    base = write_decision_artifact(pod, artifacts_dir=artifacts_dir)
    if history is not None:
        history.log_decision(
            decision=pod.decision,
            artifacts=[base + ".json", base + ".md"],
            outcome=f"triggers: {', '.join(triggers)}",
        )
    if pods_out is not None:
        pods_out.append(pod)
    # The most senior member shares the outcome up the line.
    senior = senior_member(pod)
    # The static prompt parts live in prompts/ (Story 11 — a pure move); the
    # dynamic data (the pod id, the decision) is composed in here.
    backend.invoke(
        senior,
        POD_UPWARD_REPORT_PREFIX + pod.id +
        POD_UPWARD_REPORT_MID + pod.decision +
        POD_UPWARD_REPORT_SUFFIX,
        reasoning=classify_complexity(phase, senior, {}),
        phase=phase,
    )
    # Chained-pod escalation: the starter's boss forms a second pod carrying
    # the first pod's decision artifact up the line (the §2.8 worked example).
    # A **chained pod on an empty first decision** is skipped (a visible note,
    # never silent) — there is nothing to carry up the line.
    boss_id = starter.reports_to
    if boss_id and boss_id in roles:
        if pod.decision.strip():
            boss = roles[boss_id]
            try:
                chained = chained_pod(
                    pod, roles, boss.id, [boss.id, starter.id],
                    f"escalation of {pod.topic}",
                    first_artifact_path=base + ".md",
                    min_roles=(config or {}).get("pod_min_roles", tiers.POD_MIN_ROLES),
                    max_roles=(config or {}).get("pod_max_roles", tiers.POD_MAX_ROLES),
                )
            except PodMembershipError:
                chained = None
            if chained is not None:
                run_pod(backend, chained,
                        max_rounds=(config or {}).get("pod_max_rounds", 3),
                        transcripts_dir=transcripts_dir,
                        budget_tokens=(config or {}).get("context_budget_tokens", 4000),
                        phase=phase)
                write_transcripts(chained, transcripts_dir=transcripts_dir)
                write_decision_artifact(chained, artifacts_dir=artifacts_dir)
        else:
            print("[pod] skipped chained pod (empty first decision)",
                  file=sys.stderr)
    # Seed the members' memory with the cross-team `pod:<id>` entry (what
    # `RoleMemory.cross_team()` filters on). A no-op for a plain stub.
    seed = getattr(backend, "seed_cross_team", None)
    if callable(seed):
        for member in pod.members:
            seed(member.id, pod.id, pod.decision, member.team)


def _decomposition_list(out: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Safely read a list from a role's ``decomposition`` object, tolerating the
    shapes the real LLM free-forms: a dict (canonical), a bare list (the model
    collapsed the object into the list itself), or a string/number/None (the
    model ignored the forced schema). Returns a list of dicts (empty if none).

    This is the defensive half of the Phase-4 fix: even if the model ignores
    the forced ``submit_output`` schema, a string ``decomposition`` degrades to
    "no work to dispatch" (visible + logged) instead of an ``AttributeError``
    crash on ``.get(...)``."""
    rec = (out or {}).get("decomposition")
    if isinstance(rec, dict):
        val = rec.get(key)
    elif isinstance(rec, list):
        val = rec
    else:
        return []
    if not isinstance(val, list):
        return []
    return [v for v in val if isinstance(v, dict)]


def generate_head_policies(
    backend: LLMBackend,
    org: OrgState,
    dept_objectives: List[Dict[str, Any]],
    mission_digest: str,
    departments_dir: str = "departments",
    clarifications: Optional[Dict[str, str]] = None,
) -> Dict[str, Dict[str, str]]:
    """Phase 4 (pre-decomposition): every department head — operational AND
    required (HR/Safety/Morality) — is invoked to author its department POLICY
    (full markdown, written to ``departments/<dept>/<DEPT>_POLICY.md``) and a
    POLICY_SUMMARY (the key points ICs are given directly). This runs BEFORE
    any head decomposes into managers, so managers/ICs have a clear instruction
    on how their work fulfils the org's goal.

    **Story 5:** ``clarifications`` is an optional ``{head_id: clarified_mission}``
    mapping (the **leader+head clarification pod's** outcome). The policy is
    authored **after** the pod, so the policy context includes the clarification
    (the pod → policy sequencing is strict). Required governance depts get no
    clarification (no leader+head clarification pod).

    The head's context = Mission + its existing policy (Department
    Instructions) + its directive (the leader's department objective if the
    leader assigned one, else the head's mandate) + the clarification (Story 5)
    + its memory (auto-folded by the MemoryBackend).

    Returns ``{head_id: {"policy": <full text>, "policy_summary": <summary>}}``.
    """
    clarifications = clarifications or {}
    # A head's directive: the leader's department objective if assigned, else
    # the head's own mandate (a required dept gets no operational objective).
    objective_by_head = {
        obj.get("head_id", ""): obj.get("objective", "")
        for obj in dept_objectives
        if isinstance(obj, dict)
    }
    policies: Dict[str, Dict[str, str]] = {}
    for head in org.department_heads():
        directive = (
            objective_by_head.get(head.id, "")
            or head.mandate
            or "your department's governance responsibilities"
        )
        existing = _read_policy(head.department, departments_dir)
        out = backend.invoke(
            head, _policy_ctx(head, mission_digest, existing, directive,
                              clarification=clarifications.get(head.id, "")),
            reasoning=classify_complexity(4, head, {}),
            phase=4,
        )
        policy = out.get("policy", "") if isinstance(out, dict) else ""
        policy_summary = (
            out.get("policy_summary", "") if isinstance(out, dict) else ""
        )
        if policy:
            _write_policy(head.department, policy, departments_dir)
        else:
            # A visible failure state (never silent): the head was invoked for
            # the department policy but returned none (the policy file stays a
            # stub and managers/ICs get no policy context). The org event is
            # surfaced in the dashboard's org-event stream.
            org.log_event("policy_missing", head.id, None,
                          {"department": head.department})
        policies[head.id] = {
            "policy": policy,
            "policy_summary": policy_summary,
        }
    return policies
