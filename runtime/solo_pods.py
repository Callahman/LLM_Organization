"""Solo (single-role) leader pods (P1/P2/P3/P5/P6) — Story 21.

A solo pod observes a role's single-activity out-of-pod work as a pod (one
transcript file per (role, activity), growing per round). Generalized
(Story 21): any role (the leader, a department head, a manager, an IC) can form
a solo pod — not just the leader. Re-exported by the `runtime/pods.py` facade.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from roles.base import Role
from runtime.pod_artifacts import write_transcripts

if TYPE_CHECKING:  # Pod is only needed for type hints (avoids a runtime cycle).
    from runtime.pods import Pod


def form_solo_pod(role: Role, activity: str, topic: str) -> Pod:
    """Form a **solo** pod: a role working a single activity (its out-of-pod
    work), observed as a pod. Skips the 2–6 / 1-tier-spread membership bounds
    (a lone role is not a working group) — the pod has the role as both starter
    and sole member. The id is stable per (role, activity) so the transcript
    file grows per round (one file per (role, activity), rewritten each round).

    **Generalized (Story 21):** any role (the leader, a department head, a
    manager, an IC) can form a solo pod — not just the leader."""
    # Lazy import: `Pod` lives in `runtime/pods.py`, which re-exports this
    # module — importing it at module top would be a circular import. Deferring
    # it to call time (when `pods.py` is fully loaded) breaks the cycle.
    from runtime.pods import Pod
    pod_id = f"solo_{role.id}_{activity}"
    return Pod(id=pod_id, starter=role, members=[role],
               topic=topic, solo=True)


def record_solo_step(pod: Pod, round_no: int, kind: str,
                     output: Dict[str, Any]) -> None:
    """Append one leader working step to a solo pod's transcript. `kind` is a
    short label for the step (e.g. ``questions``, ``answer``, ``draft``,
    ``verdict``); the full structured output is carried in the entry so the
    dashboard can render the leader's actual work."""
    pod.transcript.append({
        "kind": kind,
        "role": pod.starter.id,
        "round": round_no,
        "summary": str(output.get("summary", "")),
        "output": output,
    })


class SoloTracker:
    """Holds a role's solo pods (one per activity) and rewrites their
    transcripts after each step, so the observability dashboard can watch a
    role's solo work (not just the multi-role pods).

    **Generalized (Story 21):** the tracker is **role-agnostic** — any role
    (the leader, a department head, a manager, an IC) can have solo-pod records
    for its out-of-pod work. The `leader` argument is the **default** role
    (the leader, for backward compatibility); a different role can be named per
    step (the `role` argument to `pod_for`/`record`/`close`).

    Each (role, activity) gets one pod (one transcript file, growing per
    round). The tracker is optional: when no `transcripts_dir` is supplied,
    steps are recorded in memory only (no file I/O) — so a session without
    observability still works.
    """

    def __init__(self, leader: Role,
                 transcripts_dir: Optional[str] = "pods/transcripts"):
        self.leader = leader  # the default role (the leader, for backward compat)
        self.transcripts_dir = transcripts_dir
        self.pods: Dict[str, Pod] = {}  # keyed by (role.id, activity)

    def _key(self, role: Role, activity: str) -> str:
        return f"{role.id}|{activity}"

    def pod_for(self, activity: str, topic: str,
                role: Optional[Role] = None) -> Pod:
        """Get (or create) the solo pod for a (role, activity) (one file each)."""
        role = role or self.leader
        key = self._key(role, activity)
        if key not in self.pods:
            self.pods[key] = form_solo_pod(role, activity, topic)
        return self.pods[key]

    def record(self, activity: str, topic: str, round_no: int, kind: str,
               output: Dict[str, Any], role: Optional[Role] = None) -> None:
        """Record one working step for a (role, activity) and (re)write the
        transcript so the dashboard sees it live."""
        pod = self.pod_for(activity, topic, role)
        record_solo_step(pod, round_no, kind, output)
        if self.transcripts_dir:
            write_transcripts(pod, self.transcripts_dir)

    def close(self, activity: str, reason: str = "",
              role: Optional[Role] = None) -> None:
        """Emit a terminal `close` step for a (role, activity) solo pod when it
        completes, so the dashboard marks the pod **closed** (it moves from the
        active pane to the historical list). `reason` is a short summary line
        (e.g. "intake converged, 2 rounds", "mission approved v1")."""
        role = role or self.leader
        key = self._key(role, activity)
        pod = self.pods.get(key)
        if pod is None:
            return
        pod.closed_reason = reason
        pod.transcript.append({
            "kind": "close",
            "role": pod.starter.id,
            "summary": reason,
            "decision": reason,
        })
        if self.transcripts_dir:
            write_transcripts(pod, self.transcripts_dir)
