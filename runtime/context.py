"""Context, memory & prompt construction.

- **Per-role short-term memory** (bounded, seeds prompts; cross-team
  carry-over entries) — `RoleMemory`.
- **Prompt construction** from the four-part outline:
  `{role} + {objective} + {short-term memory} + {prior conversation}`.
- **Bounded assembly** (agenda + inter-round summaries + speaker-relevant
  digests) with **deterministic truncation** (oldest summaries dropped first,
  never the agenda) and **extractive summarization** (digests come from each
  speaker's `summary` field).
- **Isolated pod contexts**: prior speakers' outputs are included in the new
  speaker's prompt, so each speaker builds on what the others have said.

Token counting is a deterministic whitespace-token estimate (no model needed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


def estimate_tokens(text: str) -> int:
    """A deterministic token estimate (whitespace-separated tokens)."""
    return len(text.split()) if text else 0


# --- Per-role short-term memory --------------------------------------------

@dataclass
class MemoryEntry:
    summary: str
    source: str  # "intra-team" | "pod:<id>" | "report" | "mission"
    team: str = ""
    ts: float = 0.0


class RoleMemory:
    """A role's bounded short-term memory. It seeds the role's prompt and
    carries cross-team (pod) entries into subsequent intra-team meetings."""

    def __init__(self, max_entries: int = 20):
        self.max_entries = max_entries
        self.entries: List[MemoryEntry] = []

    def add(self, entry: MemoryEntry) -> None:
        self.entries.append(entry)
        if len(self.entries) > self.max_entries:
            self.entries = self.entries[-self.max_entries:]

    def add_summary(self, summary: str, source: str, team: str = "", ts: float = 0.0) -> None:
        self.add(MemoryEntry(summary=summary, source=source, team=team, ts=ts))

    def seed(self) -> str:
        """The short-term-memory section for the prompt (most recent last)."""
        if not self.entries:
            return "(none yet)"
        return "\n".join(f"- ({e.source}) {e.summary}" for e in self.entries)

    def cross_team(self) -> List[MemoryEntry]:
        """Cross-team (pod) carry-over entries."""
        return [e for e in self.entries if e.source.startswith("pod:")]

    def __len__(self) -> int:
        return len(self.entries)

    # --- Persistence (across runs) -----------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the memory (for `MemoryBackend.save_state`)."""
        return {
            "max_entries": self.max_entries,
            "entries": [
                {"summary": e.summary, "source": e.source,
                 "team": e.team, "ts": e.ts}
                for e in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoleMemory":
        """Deserialize a memory (for `MemoryBackend.load_state`)."""
        mem = cls(max_entries=data.get("max_entries", 20))
        for e in data.get("entries", []):
            mem.entries.append(MemoryEntry(
                summary=e.get("summary", ""),
                source=e.get("source", "intra-team"),
                team=e.get("team", ""),
                ts=e.get("ts", 0.0),
            ))
        return mem


# --- Four-part prompt construction -----------------------------------------

def assemble_prompt(
    role,
    objective: str,
    memory: Optional[RoleMemory] = None,
    prior_conversation: str = "",
) -> str:
    """Assemble a role's prompt from the four-part outline:
    `{role} + {objective} + {short-term memory} + {prior conversation}`."""
    parts: List[str] = []
    parts.append(
        f"ROLE:\n{role.mandate}\n"
        f"(architype={role.architype}, sub-architype={role.sub_architype}, "
        f"personality={role.personality})"
    )
    parts.append(f"OBJECTIVE:\n{objective}")
    mem = memory.seed() if memory is not None else "(none yet)"
    parts.append(f"SHORT-TERM MEMORY:\n{mem}")
    parts.append(f"PRIOR CONVERSATION:\n{prior_conversation or '(none yet)'}")
    return "\n\n".join(parts)


# --- Bounded assembly ------------------------------------------------------

def bounded_assembly(
    agenda: str,
    summaries: List[Tuple[str, str]],
    budget_tokens: int = 4000,
) -> str:
    """Assemble a bounded context: the **agenda** (never dropped) +
    inter-round **summaries** (extractive, from each speaker's `summary`
    field). `summaries` is a list of `(label, summary_text)` in chronological
    order. When over budget, the **oldest summaries are dropped first**
    (deterministic truncation); the agenda is always kept.
    """
    agenda_text = f"AGENDA:\n{agenda}"
    used = estimate_tokens(agenda_text)
    if used >= budget_tokens:
        # The agenda alone exceeds the budget; it is still kept (never the
        # agenda). No room for summaries.
        return agenda_text

    included: List[str] = []
    # Include newest-first while they fit; stop (drop all older) at the first
    # that does not fit.
    for label, text in reversed(summaries):
        line = f"[{label}] {text}"
        cost = estimate_tokens(line)
        if used + cost > budget_tokens:
            break
        included.append(line)
        used += cost
    included.reverse()

    parts = [agenda_text] + included
    return "\n".join(parts)
