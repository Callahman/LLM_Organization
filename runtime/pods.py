"""Pods — bounded, 1-tier-spread working groups (Epic 5).

A pod is a small group (2–6) of roles within a **1-tier spread** that
deliberates a topic. The **starter** (the role that created the pod) manages
the conversation: it sets the agenda and closes it (producing the decision).
Members speak in bounded rounds; a round that makes no progress (identical
output to the previous round) is a **deadlock** and closes the pod.

Chained pods carry the first pod's **decision artifact** up the line (the §2.8
worked example). Transcripts + decision artifacts are written to
`pods/transcripts/` and `pods/artifacts/`.

Complexity routing: a pod round that has **disagreement** (conflicting
recommendations) uses the model's "thinking" (HIGH); a routine round does not.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from org import tiers
from roles.base import Role
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity, detect_disagreement
from runtime.coerce import as_str_list


class PodMembershipError(ValueError):
    """Raised when a pod's membership violates the bounds (size / tier spread)."""


# A module-level counter keeps pod ids unique within a run.
_pod_counter = 0


def _next_pod_id(starter_id: str) -> str:
    global _pod_counter
    _pod_counter += 1
    return f"pod_{starter_id}_{_pod_counter}"


@dataclass
class Pod:
    id: str
    starter: Role
    members: List[Role]
    topic: str
    agenda: str = ""
    decision: str = ""
    rationale: str = ""
    open_items: List[str] = field(default_factory=list)
    rounds: int = 0
    closed_reason: str = ""
    input_artifacts: List[str] = field(default_factory=list)
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    # A **solo** pod is a single-role (leader) working step observed as a pod
    # (P1/P2/P3/P5/P6). It skips the 2–6 / 1-tier-spread membership bounds
    # (a lone leader is not a working group) and its transcript grows per
    # round in `pods/transcripts/` so the dashboard can watch the leader's
    # solo work, not just the multi-role pods.
    solo: bool = False


def form_pod(
    roles: Dict[str, Role],
    starter_id: str,
    member_ids: List[str],
    topic: str,
) -> Pod:
    """Form a pod from `roles`: the starter + members, validated against the
    2–6 size and 1-tier-spread bounds (raises `PodMembershipError` if invalid)."""
    members = [roles[mid] for mid in member_ids]
    starter = roles[starter_id]
    ok, reason = tiers.validate_pod(members)
    if not ok:
        raise PodMembershipError(reason)
    return Pod(id=_next_pod_id(starter_id), starter=starter,
               members=members, topic=topic)


def chained_pod(
    first_pod: Pod,
    roles: Dict[str, Role],
    starter_id: str,
    member_ids: List[str],
    topic: str,
    first_artifact_path: str = "",
) -> Pod:
    """Form a second (chained escalation) pod that carries the first pod's
    **decision artifact** up the line. `first_artifact_path` is the first pod's
    decision-artifact markdown; the first pod's decision is also carried into
    the new pod's context."""
    pod = form_pod(roles, starter_id, member_ids, topic)
    pod.input_artifacts = [first_artifact_path] if first_artifact_path else []
    # Carry the first pod's decision into the context (via the transcript seed).
    pod.transcript.append({
        "kind": "carried_decision",
        "from_pod": first_pod.id,
        "decision": first_pod.decision,
        "artifact": first_artifact_path,
    })
    return pod


def senior_member(pod: Pod) -> Role:
    """The most senior member (lowest tier number). After a pod closes, this
    member shares the outcome up the line."""
    return min(pod.members, key=lambda m: tiers.tier_of(m))


def _pod_ctx(pod: Pod, kind: str, prior: str = "") -> str:
    """Build a pod member's context. Starts with "POD" so the routing backend
    parses it as Phase 4 (execution)."""
    parts = [f"POD {pod.id}: {kind} — {pod.topic}"]
    if pod.agenda:
        parts.append(f"AGENDA: {pod.agenda}")
    if pod.input_artifacts:
        parts.append("INPUT ARTIFACTS: " + ", ".join(pod.input_artifacts))
    for entry in pod.transcript:
        if entry.get("kind") == "speak":
            parts.append(f"  [{entry.get('role')}] {entry.get('summary', '')}")
        elif entry.get("kind") == "carried_decision":
            parts.append(f"  (carried) {entry.get('decision', '')}")
    if prior:
        parts.append(f"PRIOR: {prior}")
    return "\n".join(parts)


def run_pod(backend: LLMBackend, pod: Pod, max_rounds: int = 3,
            transcripts_dir: Optional[str] = None) -> Pod:
    """Run a pod's conversation:

    1. the **starter** sets the agenda (it manages the conversation);
    2. members speak in bounded rounds — a round identical to the previous one
       is a **deadlock** and closes the pod; a round with **disagreement**
       (conflicting recommendations) uses "thinking" (HIGH);
    3. the **starter** always closes, producing the decision.

    When ``transcripts_dir`` is given, the transcript file is (re)written
    after the agenda and after each deliberation round, so the file grows
    **live** (the observability dashboard tails it for the active-pod view).
    """
    # 1. The starter sets the agenda.
    out = backend.invoke(pod.starter, _pod_ctx(pod, "agenda"),
                         reasoning=classify_complexity(4, pod.starter, {}), phase=4)
    pod.agenda = str(out.get("agenda", ""))
    pod.transcript.append({
        "kind": "agenda", "role": pod.starter.id,
        "summary": str(out.get("summary", "")),
    })
    if transcripts_dir:
        write_transcripts(pod, transcripts_dir)

    # 2. Deliberation rounds (deadlock detection + disagreement routing).
    prev: List[tuple] | None = None
    prev_outputs: List[Dict[str, Any]] = []
    for round in range(1, max_rounds + 1):
        this_round: List[tuple] = []
        this_outputs: List[Dict[str, Any]] = []
        disagreement = detect_disagreement(prev_outputs)
        for member in pod.members:
            level = classify_complexity(4, member, {"disagreement": disagreement})
            out = backend.invoke(member, _pod_ctx(pod, "speak"), reasoning=level,
                                 phase=4)
            summary = str(out.get("summary", ""))
            this_round.append((member.id, summary))
            this_outputs.append(out)
            pod.transcript.append({
                "kind": "speak", "role": member.id, "round": round,
                "summary": summary, "output": out,
            })
        pod.rounds = round
        if transcripts_dir:
            write_transcripts(pod, transcripts_dir)
        if prev is not None and this_round == prev:
            pod.closed_reason = "deadlock: no progress between rounds"
            break
        prev = this_round
        prev_outputs = this_outputs

    # 3. The starter always closes, producing the decision.
    out = backend.invoke(pod.starter, _pod_ctx(pod, "close"),
                         reasoning=classify_complexity(4, pod.starter, {}), phase=4)
    pod.decision = str(out.get("decision", ""))
    pod.rationale = str(out.get("rationale", ""))
    pod.open_items = as_str_list(out.get("open_items", []))
    if not pod.closed_reason:
        pod.closed_reason = "closed by starter"
    pod.transcript.append({
        "kind": "close", "role": pod.starter.id, "decision": pod.decision,
        "rationale": pod.rationale, "open_items": pod.open_items,
    })
    return pod


def write_transcripts(pod: Pod, transcripts_dir: str = "pods/transcripts") -> str:
    """Write the pod's transcript to `<base>.jsonl` (machine) and `<base>.md`
    (human). Returns `base` (the path without extension)."""
    os.makedirs(transcripts_dir, exist_ok=True)
    base = os.path.join(transcripts_dir, pod.id)
    with open(base + ".jsonl", "w", encoding="utf-8") as f:
        for entry in pod.transcript:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(f"# Pod {pod.id}: {pod.topic}\n\n")
        f.write(f"- starter: {pod.starter.id}\n")
        f.write(f"- members: {', '.join(m.id for m in pod.members)}\n")
        f.write(f"- agenda: {pod.agenda}\n")
        f.write(f"- decision: {pod.decision}\n")
        f.write(f"- rounds: {pod.rounds}\n")
        f.write(f"- closed: {pod.closed_reason}\n\n")
        f.write("## Transcript\n")
        for entry in pod.transcript:
            if entry.get("kind") == "speak":
                f.write(f"- [speak, r{entry.get('round')}] {entry.get('role')}: "
                        f"{entry.get('summary', '')}\n")
            elif entry.get("kind") == "agenda":
                f.write(f"- [agenda] {entry.get('role')}: {entry.get('summary', '')}\n")
            elif entry.get("kind") == "close":
                f.write(f"- [close] {entry.get('role')}: {entry.get('decision', '')}\n")
            elif entry.get("kind") == "carried_decision":
                f.write(f"- [carried] from {entry.get('from_pod')}: "
                        f"{entry.get('decision', '')}\n")
            else:
                # A solo (single-role) leader step (intake / mission /
                # bootstrap / synthesis / decision) — render its label +
                # summary so the dashboard can show the leader's solo work.
                f.write(f"- [{entry.get('kind')}, r{entry.get('round')}] "
                        f"{entry.get('role')}: {entry.get('summary', '')}\n")
    return base


def write_decision_artifact(pod: Pod, artifacts_dir: str = "pods/artifacts") -> str:
    """Write the pod's **decision artifact** to `<base>.json` (machine) and
    `<base>.md` (human). This is what a chained pod carries up the line.
    Returns `base` (the path without extension)."""
    os.makedirs(artifacts_dir, exist_ok=True)
    base = os.path.join(artifacts_dir, pod.id)
    artifact = {
        "pod": pod.id,
        "topic": pod.topic,
        "decision": pod.decision,
        "rationale": pod.rationale,
        "open_items": pod.open_items,
        "members": [m.id for m in pod.members],
        "starter": pod.starter.id,
    }
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(artifact, f, ensure_ascii=False, indent=2)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(f"# Decision: {pod.topic}\n\n")
        f.write(f"- decision: {pod.decision}\n")
        f.write(f"- rationale: {pod.rationale}\n")
        f.write(f"- open items: {', '.join(pod.open_items) or '(none)'}\n")
        f.write(f"- members: {', '.join(artifact['members'])}\n")
    return base


# --- Solo (single-role) leader pods (P1/P2/P3/P5/P6) ------------------------

def form_solo_pod(leader: Role, phase: str, topic: str) -> Pod:
    """Form a **solo** pod: the leader working a single phase, observed as a
    pod. Skips the 2–6 / 1-tier-spread membership bounds (a lone leader is not
    a working group) — the pod has the leader as both starter and sole member.
    The id is stable per (leader, phase) so the transcript file grows per
    round (one file per phase, rewritten each round)."""
    pod_id = f"solo_{leader.id}_{phase}"
    return Pod(id=pod_id, starter=leader, members=[leader],
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
    """Holds the leader's solo pods (one per phase: P1/P2/P3/P5/P6) and
    rewrites their transcripts after each step, so the observability dashboard
    can watch the leader's solo work (not just the multi-role pods).

    Each phase gets one pod (one transcript file, growing per round). The
    tracker is optional: when no `transcripts_dir` is supplied, steps are
    recorded in memory only (no file I/O) — so a session without observability
    still works.
    """

    def __init__(self, leader: Role,
                 transcripts_dir: Optional[str] = "pods/transcripts"):
        self.leader = leader
        self.transcripts_dir = transcripts_dir
        self.pods: Dict[str, Pod] = {}

    def pod_for(self, phase: str, topic: str) -> Pod:
        """Get (or create) the solo pod for a phase (one file per phase)."""
        if phase not in self.pods:
            self.pods[phase] = form_solo_pod(self.leader, phase, topic)
        return self.pods[phase]

    def record(self, phase: str, topic: str, round_no: int, kind: str,
               output: Dict[str, Any]) -> None:
        """Record one leader working step for a phase and (re)write the
        transcript so the dashboard sees it live."""
        pod = self.pod_for(phase, topic)
        record_solo_step(pod, round_no, kind, output)
        if self.transcripts_dir:
            write_transcripts(pod, self.transcripts_dir)

    def close(self, phase: str, reason: str = "") -> None:
        """Emit a terminal `close` step for a solo pod's phase when it
        completes, so the dashboard marks the pod **closed** (it moves from the
        active pane to the historical list). `reason` is a short summary line
        (e.g. "intake converged, 2 rounds", "mission approved v1")."""
        pod = self.pods.get(phase)
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
