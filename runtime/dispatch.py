"""Phase 4 — Top-down dispatch.

The leader decomposes the mission into **department objectives** → department
heads decompose into **team objectives** → managers decompose into **IC
tasks** → ICs do the work in their team directories. Work propagates **up**
in **structured reports** (bounded summaries + artifact pointers) — the leader
never reads code; its synthesis reflects IC-level work **via the chain of
command**.

No tier is skipped in assignments. The **mission digest** is in scope for
leaders/heads (a bounded summary of the mission, not the full markdown).

**Pods A/B/C multi-trigger** (an add-on to the dispatch, never a
replacement): after each team's IC work, a pod forms when any trigger fires —

- **A (disagreement)**: the IC work outputs carry conflicting
  recommendations (`detect_disagreement` reads the `recommendation` field —
  so the dispatch keeps the **full IC outputs**, not just the upward
  reports);
- **B (cross-team)**: the team objective is marked `cross_team` (optionally
  naming the other teams' roles in `cross_team_with`);
- **C (routing rule)**: a task type matches the routing-rule config.

The pod's decision is then carried **all three ways**: written to
`pods/artifacts/` (+ the `HistoryStore` decision journal), carried up to the
leader's Phase 5 synthesis, and seeded into the members' memory as a
cross-team `pod:<id>` entry (via `MemoryBackend.seed_cross_team` — a no-op
for a plain `StubBackend`).
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional

from roles.base import Role, spin_personality, spin_sub_architype
from roles.worker import worker_output_schema
from runtime.org import (
    OrgState,
    hire,
    fire,
    run_leader_replacement_vote,
    ResourcingError,
    ResourcingVetoed,
)
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity, detect_disagreement
from runtime.history import HistoryStore
from runtime.permissions import apply_code_edits
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


def _leader_ctx(digest: str, head_ids: List[str]) -> str:
    return (
        "PHASE 4: decompose the mission into department objectives. "
        f"Mission digest: {digest} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`department_objectives` key is a NON-EMPTY JSON array of objects, "
        "each exactly {\"head_id\": <str>, \"objective\": <str>}. "
        f"The head_id MUST be one of the existing department heads: {head_ids}. "
        "Do NOT invent new head_ids — only assign objectives to the heads that "
        "already exist in the org."
    )


def _head_ctx(head: Role, objective: str, digest: str) -> str:
    return (
        f"PHASE 4 (head {head.id}): decompose the department objective into "
        f"team objectives. Objective: {objective} | Mission digest: {digest} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`team_objectives` key is a JSON array of objects, each exactly "
        "{\"manager_id\": <str>, \"team\": <str>, \"objective\": <str>} (or "
        "{\"ic_id\": <str>, \"team\": <str>, \"objective\": <str>} if you "
        "direct ICs directly). `team` is the team's directory name (a short "
        "slug, e.g. \"pipelines\") — it becomes the team work dir "
        "(departments/<dept>/<team>/) where the team's ICs write their work."
    )


def _manager_ctx(manager: Role, objective: str) -> str:
    return (
        f"PHASE 4 (manager {manager.id}): decompose the team objective into "
        f"IC tasks. Objective: {objective} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`ic_tasks` key is a JSON array of objects, each exactly "
        "{\"ic_id\": <str>, \"task\": <str>}."
    )


def _ic_ctx(ic: Role, task: str) -> str:
    # The exact team work root (departments/<dept>/<team>/). The IC must write
    # there — a bare top-level dir is refused by the permission layer as
    # out_of_scope, so the prompt names the real root, shows a correct/wrong
    # pair, and forbids the role's own id as a directory (the default the
    # model falls into when no concrete root is given).
    if ic.department and ic.team:
        team_root = f"departments/{ic.department}/{ic.team}"
        path_rules = (
            f"Every path MUST start with {team_root}/ — e.g. correct: "
            f"{team_root}/README.md; wrong: {ic.team}/README.md or "
            f"{ic.id}/README.md (a bare top-level dir, or your own id as a "
            f"directory, is refused as out_of_scope)."
        )
    else:
        team_root = "your team directory"
        path_rules = (
            "Write under your team directory (departments/<dept>/<team>/); a "
            "bare top-level path is refused as out_of_scope."
        )
    return (
        f"PHASE 4 (IC {ic.id}): do the work in your team directory. Your team "
        f"work directory is {team_root}/ — write ALL files there. {path_rules} "
        f"Task: {task} Set `summary` to a one-line summary of the work done "
        f"and `work_path` to the path of the work (under {team_root}/). If "
        "your work requires changing code, set `code_edits` to a JSON array "
        "of objects, each exactly {\"path\": <str>, \"content\": <str>}. Each "
        f"edit is gated by the permission layer: write under {team_root}/ "
        "only; the mission and the rules are read-only."
    )


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


def _run_self_edits(
    ic: Role,
    edits: List[Dict[str, Any]],
    history: Optional[HistoryStore],
) -> List[Dict[str, Any]]:
    """Repair + apply + log one batch of self-edits for an IC (gated by the
    permission layer). Returns the per-edit results (the gate's decisions)."""
    edits = _repair_edit_paths(ic, edits, history)
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
    ctx = (
        f"PHASE 4 (IC {ic.id}) — self-edit correction. Some of your proposed "
        f"code edits were REFUSED by the permission layer:\n{reasons}\n"
        "Re-propose the refused edits with corrected paths (write under your "
        "team work dir; the mission and the rules are read-only). Set "
        "`code_edits` to a JSON array of objects, each exactly "
        "{\"path\": <str>, \"content\": <str>}. If a refused edit cannot be "
        "placed in an allowed scope, omit it."
    )
    try:
        out = backend.invoke(ic, ctx,
                             reasoning=classify_complexity(phase, ic, {}),
                             phase=phase)
    except Exception:
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
) -> Optional[Role]:
    """Get a role by ID, or create + hire it (through the approval matrix) if
    it doesn't exist yet. This is how the dispatch spins up the managers/ICs it
    decomposes onto, so the full heads->managers->ICs chain is exercised.
    Returns None if it can't be hired (no approver supplied, or the hire is
    vetoed / the 3-IC cap is hit)."""
    role = org.get(role_id)
    if role is not None:
        return role
    if approver_fn is None:
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
    except Exception:
        return None


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


# --- Pods A/B/C multi-trigger (an add-on to the dispatch) ------------------

def _task_types(team_obj: Dict[str, Any], ic_tasks: List[Dict[str, Any]]) -> List[str]:
    """The task types in scope for a team objective (trigger C): the
    objective's own `task_type` + each IC task's `task_type`."""
    types = [team_obj.get("task_type")]
    types.extend(t.get("task_type") for t in ic_tasks)
    return [t for t in types if t]


def _pod_topic(objective: str, triggers: List[str]) -> str:
    return (
        f"Phase 4 pod (triggers: {', '.join(triggers)}) — "
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
    decision journal), collected for the leader's Phase 5 synthesis
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
        )
    except PodMembershipError:
        return
    run_pod(backend, pod, max_rounds=(config or {}).get("pod_max_rounds", 3),
            transcripts_dir=transcripts_dir)
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
    backend.invoke(
        senior,
        f"POD {pod.id} outcome to share up the line — decision: {pod.decision}. "
        "Produce an upward report of the pod's decision.",
        reasoning=classify_complexity(4, senior, {}),
        phase=4,
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
                )
            except PodMembershipError:
                chained = None
            if chained is not None:
                run_pod(backend, chained,
                        max_rounds=(config or {}).get("pod_max_rounds", 3),
                        transcripts_dir=transcripts_dir)
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


def dispatch(
    backend: LLMBackend,
    org: OrgState,
    leader: Role,
    mission: Dict[str, Any],
    approver_fn=None,
    pods_out: Optional[List[Pod]] = None,
    history: Optional[HistoryStore] = None,
    routing_rules: Optional[List[str]] = None,
    artifacts_dir: str = "pods/artifacts",
    transcripts_dir: str = "pods/transcripts",
    ic_timeout_seconds: Optional[float] = None,
    new_leader: Optional[Role] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Run the Phase 4 top-down dispatch. Returns the leader's view: a list of
    department reports (each carrying the chain of team/IC reports up).

    `ic_timeout_seconds` (optional) gives the IC work invokes a larger per-
    invoke timeout than the session default — the ICs do the actual work, so
    they are the heaviest invokes and the ones most likely to hit the flat
    budget. `None` uses the session default.

    `approver_fn` (optional) lets the dispatch hire the managers/ICs it
    decomposes onto when they don't exist yet (the full heads->managers->ICs
    chain); without it, the dispatch only reaches roles already in the org.

    **Pods A/B/C multi-trigger** (an add-on, not a replacement): after each
    team's IC work, a pod forms when any trigger fires — A (disagreement
    across the IC work outputs), B (a `cross_team`-marked objective), C (a
    routing-rule task type). The formed pods are appended to `pods_out`
    (when supplied) so the session can carry their decisions up to the
    leader's Phase 5 synthesis; the decision is also written to
    `pods/artifacts/` (+ the `history` decision journal when supplied) and
    seeded into the members' memory as a cross-team `pod:<id>` entry (via
    `MemoryBackend.seed_cross_team` — a no-op for a plain stub)."""
    digest = mission_digest(mission)
    head_ids = [h.id for h in org.department_heads()]
    out = backend.invoke(leader, _leader_ctx(digest, head_ids),
                         reasoning=classify_complexity(4, leader, {}), phase=4)
    # Story 5 (A1): a single head's leader-replacement proposal (with
    # reasoning) triggers the per-head unanimous vote. The new-leader
    # candidate is supplied by the caller (`new_leader`); without one, the
    # proposal is logged but no vote runs (visible, not silent).
    _leader_replacement = out.get("leader_replacement")
    if (isinstance(_leader_replacement, dict)
            and _leader_replacement.get("propose")):
        if new_leader is not None:
            run_leader_replacement_vote(
                org, backend, new_leader, leader.id,
                _leader_replacement.get("reasoning", ""), phase=4)
        elif history is not None:
            history._append(
                "dispatch_skips.jsonl",
                {"reason": "leader_replacement proposal but no new-leader "
                           "candidate supplied — no vote run"},
            )
    # Story 6 (R7): the leader's resourcing output can request firing roles
    # (each `fire` entry is [role_id, reason]). The fire goes through the HR
    # approver (a veto / required-role rejection / missing approver is logged,
    # never swallowed).
    _resourcing = out.get("resourcing")
    if isinstance(_resourcing, dict):
        for _fire_entry in _resourcing.get("fire", []):
            if isinstance(_fire_entry, (list, tuple)) and _fire_entry:
                _fire_role(org, leader, _fire_entry[0],
                           _fire_entry[1] if len(_fire_entry) >= 2 else "",
                           approver_fn, history)
    dept_objectives = _decomposition_list(out, "department_objectives")
    if not dept_objectives:
        # The leader's Phase 4 decomposition came back empty — no work to
        # dispatch. Log it so the no-op is visible, never silent.
        if history is not None:
            history._append(
                "dispatch_skips.jsonl",
                {"reason": "leader produced no department_objectives (empty "
                           "Phase 4 decomposition)"},
            )

    results: List[Dict[str, Any]] = []
    for obj in dept_objectives:
        head = org.get(obj.get("head_id", ""))
        if head is None:
            # A missing head (the leader decomposed onto a department that was
            # never created in Phase 3) — log it so the skip is visible, never
            # silent.
            if history is not None:
                history._append(
                    "dispatch_skips.jsonl",
                    {"head_id": obj.get("head_id", ""),
                     "objective": obj.get("objective", ""),
                     "reason": "head not in the org (never created in Phase 3)"},
                )
            continue
        head_out = backend.invoke(head, _head_ctx(head, obj.get("objective", ""), digest),
                          reasoning=classify_complexity(4, head, {}),
                          phase=4)
        team_objectives = _decomposition_list(head_out, "team_objectives")

        team_reports: List[Dict[str, Any]] = []
        for t_obj in team_objectives:
            manager = org.get(t_obj.get("manager_id", ""))
            if manager is None and t_obj.get("manager_id"):
                # `team` becomes the team work dir (departments/<dept>/<team>/).
                # Fall back to the manager_id so it is NEVER empty — an empty
                # team leaves the ICs with no concrete work root (the exact
                # bug that got every self-edit refused as out_of_scope).
                manager = _ensure_role(
                    org, head, t_obj.get("manager_id"), "manager",
                    head.department,
                    t_obj.get("team") or t_obj.get("manager_id", ""),
                    approver_fn,
                    direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                )
            if manager is not None:
                mgr_out = backend.invoke(manager, _manager_ctx(manager, t_obj.get("objective", "")),
                         reasoning=classify_complexity(4, manager, {}),
                         phase=4)
                ic_tasks = _decomposition_list(mgr_out, "ic_tasks")
                ic_reports: List[Dict[str, Any]] = []
                ic_outputs: List[Dict[str, Any]] = []  # full IC outputs (trigger A)
                ic_ids: List[str] = []
                for task in ic_tasks:
                    ic = org.get(task.get("ic_id", ""))
                    if ic is None and task.get("ic_id"):
                        ic = _ensure_role(
                            org, manager, task.get("ic_id"), "ic",
                            manager.department, manager.team, approver_fn,
                            direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                        )
                    if ic is None:
                        continue
                    ic_out = backend.invoke(
                        ic, _ic_ctx(ic, task.get("task", "")),
                        reasoning=classify_complexity(4, ic, {}),
                        timeout=ic_timeout_seconds,
                        phase=4,
                    )
                    ic_outputs.append(ic_out)
                    ic_ids.append(ic.id)
                    pointer = ic_out.get("work_path", _work_path(ic, task))
                    ic_reports.append(
                        {"from": ic.id, "summary": ic_out.get("summary", ""),
                         "pointer": pointer}
                    )
                    # Self-edit: the IC may propose code edits (repaired,
                    # gated by the permission layer, one corrective retry on
                    # refusal).
                    _apply_ic_self_edits(ic, ic_out, history, backend, phase=4)
                # Pods A/B/C (an add-on): disagreement / cross-team / routing.
                _check_pod_triggers(
                    backend, org, manager, ic_ids, t_obj, ic_outputs, ic_tasks,
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=True,
                    config=config,
                )
                team_reports.append(_upward_report(manager, ic_reports))
            else:
                # The head directs ICs directly (a department without managers).
                ic = org.get(t_obj.get("ic_id", ""))
                if ic is None and t_obj.get("ic_id"):
                    # Fall back to the ic_id so the team (work dir) is never
                    # empty (see the manager branch above).
                    ic = _ensure_role(
                        org, head, t_obj.get("ic_id"), "ic",
                        head.department,
                        t_obj.get("team") or t_obj.get("ic_id", ""),
                        approver_fn,
                        direct_ic_cap=(config or {}).get("direct_ic_cap", 3),
                    )
                if ic is None:
                    continue
                ic_out = backend.invoke(
                    ic, _ic_ctx(ic, t_obj.get("objective", "")),
                    reasoning=classify_complexity(4, ic, {}),
                    timeout=ic_timeout_seconds,
                    phase=4,
                )
                # Self-edit: the IC may propose code edits (repaired, gated by
                # the permission layer, one corrective retry on refusal).
                _apply_ic_self_edits(ic, ic_out, history, backend, phase=4)
                # Pods A/B/C (an add-on): the head is the starter; the ICs are
                # the members (an IC podding with a department head would be a
                # 2-tier spread — a membership failure skips the pod).
                _check_pod_triggers(
                    backend, org, head, [ic.id], t_obj, [ic_out], [],
                    routing_rules, pods_out, history, artifacts_dir,
                    transcripts_dir,
                    starter_in_members=False,
                    config=config,
                )
                team_reports.append(
                    _upward_report(
                        ic,
                        [{"from": ic.id, "summary": ic_out.get("summary", ""),
                          "pointer": ic_out.get("work_path", _work_path(ic, t_obj))}],
                    )
                )
        results.append({"head": head.id, "report": _upward_report(head, team_reports)})
    return results
