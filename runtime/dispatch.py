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

from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.org import OrgState, hire
from runtime.llm import LLMBackend
from runtime.complexity import detect_disagreement
from runtime.history import HistoryStore
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


def _leader_ctx(digest: str) -> str:
    return (
        "PHASE 4: decompose the mission into department objectives. "
        f"Mission digest: {digest} "
        "Produce decomposition.department_objectives: a list of "
        "{head_id, objective}."
    )


def _head_ctx(head: Role, objective: str, digest: str) -> str:
    return (
        f"PHASE 4 (head {head.id}): decompose the department objective into "
        f"team objectives. Objective: {objective} | Mission digest: {digest} "
        "Produce decomposition.team_objectives: a list of {manager_id, "
        "objective} (or {ic_id, objective} if the head directs ICs directly)."
    )


def _manager_ctx(manager: Role, objective: str) -> str:
    return (
        f"PHASE 4 (manager {manager.id}): decompose the team objective into "
        f"IC tasks. Objective: {objective} "
        "Produce decomposition.ic_tasks: a list of {ic_id, task}."
    )


def _ic_ctx(ic: Role, task: str) -> str:
    return (
        f"PHASE 4 (IC {ic.id}): do the work in your team directory. Task: "
        f"{task} Produce a summary of the work done (and the work path)."
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


def _ensure_role(
    org: OrgState,
    initiator: Role,
    role_id: str,
    architype: str,
    department: str,
    team: str,
    approver_fn,
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
    new_role = Role(
        id=role_id,
        architype=architype,
        department=department,
        team=team,
        reports_to=initiator.id,
    )
    try:
        return hire(org, initiator, new_role, approver_fn)
    except Exception:
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
        )
    except PodMembershipError:
        return
    run_pod(backend, pod)
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
    )
    # Chained-pod escalation: the starter's boss forms a second pod carrying
    # the first pod's decision artifact up the line (the §2.8 worked example).
    boss_id = starter.reports_to
    if boss_id and boss_id in roles:
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
            run_pod(backend, chained)
            write_transcripts(chained, transcripts_dir=transcripts_dir)
            write_decision_artifact(chained, artifacts_dir=artifacts_dir)
    # Seed the members' memory with the cross-team `pod:<id>` entry (what
    # `RoleMemory.cross_team()` filters on). A no-op for a plain stub.
    seed = getattr(backend, "seed_cross_team", None)
    if callable(seed):
        for member in pod.members:
            seed(member.id, pod.id, pod.decision, member.team)


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
) -> List[Dict[str, Any]]:
    """Run the Phase 4 top-down dispatch. Returns the leader's view: a list of
    department reports (each carrying the chain of team/IC reports up).

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
    out = backend.invoke(leader, _leader_ctx(digest))
    dept_objectives = out.get("decomposition", {}).get("department_objectives", [])

    results: List[Dict[str, Any]] = []
    for obj in dept_objectives:
        head = org.get(obj.get("head_id", ""))
        if head is None:
            continue
        head_out = backend.invoke(head, _head_ctx(head, obj.get("objective", ""), digest))
        team_objectives = head_out.get("decomposition", {}).get("team_objectives", [])

        team_reports: List[Dict[str, Any]] = []
        for t_obj in team_objectives:
            manager = org.get(t_obj.get("manager_id", ""))
            if manager is None and t_obj.get("manager_id"):
                manager = _ensure_role(
                    org, head, t_obj.get("manager_id"), "manager",
                    head.department, t_obj.get("team", ""), approver_fn,
                )
            if manager is not None:
                mgr_out = backend.invoke(manager, _manager_ctx(manager, t_obj.get("objective", "")))
                ic_tasks = mgr_out.get("decomposition", {}).get("ic_tasks", [])
                ic_reports: List[Dict[str, Any]] = []
                ic_outputs: List[Dict[str, Any]] = []  # full IC outputs (trigger A)
                ic_ids: List[str] = []
                for task in ic_tasks:
                    ic = org.get(task.get("ic_id", ""))
                    if ic is None and task.get("ic_id"):
                        ic = _ensure_role(
                            org, manager, task.get("ic_id"), "ic",
                            manager.department, manager.team, approver_fn,
                        )
                    if ic is None:
                        continue
                    ic_out = backend.invoke(ic, _ic_ctx(ic, task.get("task", "")))
                    ic_outputs.append(ic_out)
                    ic_ids.append(ic.id)
                    pointer = ic_out.get("work_path", _work_path(ic, task))
                    ic_reports.append(
                        {"from": ic.id, "summary": ic_out.get("summary", ""),
                         "pointer": pointer}
                    )
                # Pods A/B/C (an add-on): disagreement / cross-team / routing.
                _check_pod_triggers(
                    backend, org, manager, ic_ids, t_obj, ic_outputs, ic_tasks,
                    routing_rules, pods_out, history, artifacts_dir,
                    starter_in_members=True,
                )
                team_reports.append(_upward_report(manager, ic_reports))
            else:
                # The head directs ICs directly (a department without managers).
                ic = org.get(t_obj.get("ic_id", ""))
                if ic is None and t_obj.get("ic_id"):
                    ic = _ensure_role(
                        org, head, t_obj.get("ic_id"), "ic",
                        head.department, t_obj.get("team", ""), approver_fn,
                    )
                if ic is None:
                    continue
                ic_out = backend.invoke(ic, _ic_ctx(ic, t_obj.get("objective", "")))
                # Pods A/B/C (an add-on): the head is the starter; the ICs are
                # the members (an IC podding with a department head would be a
                # 2-tier spread — a membership failure skips the pod).
                _check_pod_triggers(
                    backend, org, head, [ic.id], t_obj, [ic_out], [],
                    routing_rules, pods_out, history, artifacts_dir,
                    starter_in_members=False,
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
