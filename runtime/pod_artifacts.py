"""Pod transcript + decision-artifact writers (Epic 5).

`write_transcripts` writes a pod's transcript to `<base>.jsonl` (machine) and
`<base>.md` (human); `write_decision_artifact` writes the pod's decision
artifact (what a chained pod carries up the line). Re-exported by the
`runtime/pods.py` facade.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Pod is only needed for type hints (avoids a runtime cycle).
    from runtime.pods import Pod


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
