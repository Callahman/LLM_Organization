"""Phase 4 — Pods A/B/C multi-trigger (an add-on to the dispatch, never a
replacement).

After each team's IC work, a pod forms when any trigger fires:

- **A (disagreement)**: the IC work outputs carry conflicting
  recommendations (`detect_disagreement` reads the `recommendation` field —
  so the dispatch keeps the **full IC outputs**, not just the upward
  reports);
- **B (cross-team)**: the team objective is marked `cross_team` (optionally
  naming the other teams' roles in `cross_team_with`);
- **C (routing rule)**: a task type matches the routing-rule config (a list
  of task types that always go to a pod, e.g. "evaluation" / "incident").

When one fires, the pod is formed (the **starter** + the ICs involved —
manager + ICs is a valid 1-tier spread), run, and its decision is carried
**all three ways**: written to `pods/artifacts/` (+ the `history` decision
journal), collected for the leader's Phase 5 synthesis (`pods_out`), and
seeded into the members' memory as a cross-team `pod:<id>` entry (via
`MemoryBackend.seed_cross_team` — a no-op for a plain `StubBackend`).

A membership failure (e.g. a 2-tier spread — an IC podding with a department
head) **skips the pod**; the dispatch continues.

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there).
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from roles.base import Role
from org import tiers
from runtime.org import OrgState
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity, detect_disagreement
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
            min_roles=(config or {}).get("pod_min_roles", tiers.POD_MIN_ROLES),
            max_roles=(config or {}).get("pod_max_roles", tiers.POD_MAX_ROLES),
        )
    except PodMembershipError:
        return
    run_pod(backend, pod, max_rounds=(config or {}).get("pod_max_rounds", 3),
            transcripts_dir=transcripts_dir,
            budget_tokens=(config or {}).get("context_budget_tokens", 4000))
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
                    min_roles=(config or {}).get("pod_min_roles", tiers.POD_MIN_ROLES),
                    max_roles=(config or {}).get("pod_max_roles", tiers.POD_MAX_ROLES),
                )
            except PodMembershipError:
                chained = None
            if chained is not None:
                run_pod(backend, chained,
                        max_rounds=(config or {}).get("pod_max_rounds", 3),
                        transcripts_dir=transcripts_dir,
                        budget_tokens=(config or {}).get("context_budget_tokens", 4000))
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


__all__ = ["_task_types", "_pod_topic", "_check_pod_triggers"]
