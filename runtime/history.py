"""Audit trail + archives.

- **Decision journal**: decision ↔ transcripts + artifacts ↔ mission section ↔
  outcome (the audit path from "what the organization said, in which pods" to
  "what happened").
- **Rolling window**: keep the last N sessions (and/or a size cap).
- **Size-capped archives**: oldest moved first; beyond the cap, oldest deleted.
- **Cross-team-read log**: who read what, why (the duplication-check reads).
- **Halt-event log**: Safety/Morality halts.
- **Evaluation reports**: Phase 8 self-improving loop output.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional


# The role-hierarchy level derived from the architype (Leader/Head/Manager/IC)
# — the "level in hierarchy" the invocations log records alongside the architype.
HIERARCHY_LEVEL = {
    "leader": "Leader",
    "department_head": "Head",
    "manager": "Manager",
    "ic": "IC",
}


def _role_identity(role: Any) -> Dict[str, Any]:
    """The FULL role identity for the invocations log: the role name (id), its
    level in the hierarchy (Leader/Head/Manager/IC), its architype, its
    sub-architype, its department, its team, and its personality — so the
    dashboard can segment invocations by the role's full identity, not just the
    role id. Every field is read defensively (a role may be a partial object)."""
    architype = getattr(role, "architype", "") or ""
    return {
        "name": getattr(role, "id", "") or "",
        "level": HIERARCHY_LEVEL.get(architype, architype or "unknown"),
        "architype": architype or "unknown",
        "sub_architype": getattr(role, "sub_architype", "") or "",
        "department": getattr(role, "department", "") or "",
        "team": getattr(role, "team", "") or "",
        "personality": getattr(role, "personality", "") or "",
    }


class HistoryStore:
    """The organization's audit trail. All writes are append-only JSONL so the
    audit path is resolvable from any recorded decision."""

    def __init__(
        self,
        history_dir: str = "history",
        archives_dir: str = "archives",
        window_sessions: int = 50,
        archive_cap_mb: int = 1024,
        max_log_bytes: int = 5 * 1024 * 1024,
    ):
        self.history_dir = history_dir
        self.archives_dir = archives_dir
        self.window_sessions = window_sessions
        self.archive_cap_mb = archive_cap_mb
        self.max_log_bytes = max_log_bytes
        # serialize all appends (and the rotation) so no two
        # writers interleave or double-rotate (a zombie thread or a future
        # concurrent-LLM-call refactor would otherwise create same-file races).
        self._lock = threading.Lock()
        os.makedirs(history_dir, exist_ok=True)
        os.makedirs(archives_dir, exist_ok=True)

    # --- append-only JSONL helpers -----------------------------------------

    def _append(self, filename: str, record: Dict[str, Any]) -> str:
        path = os.path.join(self.history_dir, filename)
        # serialize the size-check + rotation + write so no two
        # writers interleave or double-rotate (the check-then-act at the size
        # check was racy).
        with self._lock:
            # Log rotation: when a log grows past the cap, rotate it (rename to
            # <name>.<n>.jsonl) and start fresh. Rotated files stay in the
            # history dir so the audit path remains resolvable.
            if os.path.exists(path) and os.path.getsize(path) >= self.max_log_bytes:
                self._rotate(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def _rotate(self, path: str) -> None:
        """Rotate a log file: rename to <name>.<n>.jsonl (n = first free) and
        start a fresh file. Numbered so the order of rotation is preserved."""
        base, ext = os.path.splitext(path)  # base = .../intake, ext = .jsonl
        n = 1
        while os.path.exists(f"{base}.{n}{ext}"):
            n += 1
        os.replace(path, f"{base}.{n}{ext}")

    # --- invocation (reasoning) log ----------------------------------------

    def log_invocation(
        self,
        role_id: str,
        phase: int,
        requested: str,
        granted: str,
        department: str = "",
        role: Optional[Any] = None,
    ) -> str:
        """Record a role invocation and the reasoning level requested vs
        granted (the audit trail for where "thinking" was used). Carries the
        role's **full identity** (when `role` is the `Role` object): the role
        name (id), its level in the hierarchy (Leader/Head/Manager/IC), its
        architype, its sub-architype, its department, its team, and its
        personality — so the dashboard can segment invocations by the role's
        full identity, not just the role id. Also carries a `ts` so the
        dashboard can chart granted-level distribution over time (A0). When
        `role` is None only the role id (+ the explicit `department`) is
        recorded (backward compatibility)."""
        rec = {"role": role_id, "phase": phase,
               "requested": requested, "granted": granted,
               "ts": time.time()}
        if role is not None:
            rec.update(_role_identity(role))
        elif department:
            rec["department"] = department
        return self._append("invocations.jsonl", rec)

    # --- decision journal --------------------------------------------------

    def log_decision(
        self,
        decision: str,
        transcripts: Optional[List[str]] = None,
        artifacts: Optional[List[str]] = None,
        mission_section: str = "",
        outcome: str = "",
    ) -> str:
        """Record a decision and its audit path (transcripts + artifacts ↔
        mission section ↔ outcome)."""
        return self._append(
            "decision_journal.jsonl",
            {
                "decision": decision,
                "transcripts": transcripts or [],
                "artifacts": artifacts or [],
                "mission_section": mission_section,
                "outcome": outcome,
            },
        )

    # --- observability logs (tiled by the dashboard; the org never reads them)

    def log_code_edit(self, role_id: str, path: str, ok: bool,
                      error: str = "", department: str = "") -> str:
        """Record one agent self-edit result (``history/code_edits.jsonl``) —
        the source for the "code edited over time" metric. Carries `department`
        so the dashboard can segment edits by team without re-deriving it from
        the path (A0)."""
        return self._append(
            "code_edits.jsonl",
            {"ts": time.time(), "role": role_id, "path": path,
             "ok": bool(ok), "error": error, "department": department},
        )

    def log_code_volume(self, role_id: str, path: str, file_type: str,
                        lines: int, department: str = "") -> str:
        """Record one applied code write's volume (``history/code_volume.jsonl``)
        — the source for the "code volume over time" metric (item 10). ``lines``
        is the number of **physical** lines in the written file; ``file_type`` is
        the extension (``.md``, ``.py``, ``.json``, ...). Carries ``department``
        so the dashboard can segment volume by team without re-deriving it from
        the path."""
        return self._append(
            "code_volume.jsonl",
            {"ts": time.time(), "role": role_id, "path": path,
             "file_type": file_type, "lines": int(lines),
             "department": department},
        )

    def log_tool_call(self, stat: Dict[str, Any]) -> str:
        """Record one backend call's stats (``history/tool_calls.jsonl``) —
        ``{ts, role, mode, outcome, error, latency}``; the source for the
        "tool calls over time" metric."""
        return self._append("tool_calls.jsonl", dict(stat))

    def log_stream(self, stream_id: str, role_id: str, model: str,
                   kind: str, text: str, label: str = "",
                   reasoning: str = "") -> str:
        """Record one chunk of a model call's streamed output
        (``history/stream.jsonl``) — ``{ts, stream_id, role, model, kind,
        text, label, reasoning}``; ``kind`` is ``thinking`` / ``content`` /
        ``tool_call``. ``label`` is the role's full label (id · sub_architype
        · (personality) · department); ``reasoning`` is the level actually
        used (HIGH/MEDIUM/LOW). The source for the dashboard's live "model
        stream" window (short-term)."""
        return self._append(
            "stream.jsonl",
            {"ts": time.time(), "stream_id": stream_id, "role": role_id,
             "model": model, "kind": kind, "text": text, "label": label,
             "reasoning": reasoning},
        )

    def log_cycle(self, phase: int, cycle: int, started: float,
                  ended: float) -> str:
        """Record one phase's duration (``history/cycles.jsonl``) — the source
        for the "uptime per iteration" metric."""
        return self._append(
            "cycles.jsonl",
            {"ts": ended, "phase": phase, "cycle": cycle,
             "started": started, "duration": round(ended - started, 3)},
        )

    def log_headcount(self, headcount: int, event: str, role_id: str,
                      department: str = "") -> str:
        """Record a headcount snapshot on a resourcing event (hire/fire) —
        ``history/headcount.jsonl`` (``{ts, headcount, event, role,
        department}``). The source for the dashboard's headcount-over-time
        plot: a point on **every** hire and fire, so the plot updates
        continuously instead of once per phase (the per-phase sampling in
        ``efficiency_metrics.jsonl`` only moves on a phase boundary)."""
        return self._append(
            "headcount.jsonl",
            {"ts": time.time(), "headcount": int(headcount), "event": event,
             "role": role_id, "department": department},
        )

    def log_cycle_summary(self, cycle: int, started: float, ended: float,
                          phases: Dict[int, float], headcount: int,
                          verdict: str) -> str:
        """Record one **cycle-level** summary (``history/cycle_summaries.jsonl``)
        — ``{ts, cycle, started, ended, duration, phases, headcount,
        verdict}``. The source for the dashboard's org-flow panel: **one row
        per cycle** (the per-phase rows in ``cycles.jsonl`` make the flow look
        like it has too many cycles — a 3-cycle run renders ~15 rows).
        ``duration`` is the wall-clock span of the whole iteration (Phases
        4-8), and ``phases`` is the per-phase breakdown (``{phase: seconds}``)."""
        return self._append(
            "cycle_summaries.jsonl",
            {"ts": ended, "cycle": cycle, "started": started, "ended": ended,
             "duration": round(ended - started, 3), "phases": phases,
             "headcount": int(headcount), "verdict": verdict},
        )

    # --- halt-event log ----------------------------------------------------

    def log_halt(self, department: str, scope: str, reason: str) -> str:
        """Log a Safety/Morality halt (scoped or global). Carries a `ts` so the
        dashboard can chart halts over time (A0)."""
        return self._append(
            "halt_events.jsonl",
            {"ts": time.time(), "department": department, "scope": scope,
             "reason": reason},
        )

    # --- evaluation reports ------------------------------------------------

    def write_evaluation_report(self, report: Dict[str, Any]) -> str:
        """Write a Phase 8 evaluation report to `reports/evaluation/`."""
        eval_dir = os.path.join(
            os.path.dirname(self.history_dir), "reports", "evaluation"
        )
        os.makedirs(eval_dir, exist_ok=True)
        ts = report.get("ts", "report")
        path = os.path.join(eval_dir, f"{ts}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return path

    # --- rolling window + archives -----------------------------------------

    def _list_sessions(self) -> List[str]:
        """Session files in the history dir, oldest first (by name)."""
        files = [
            f for f in os.listdir(self.history_dir)
            if f.endswith(".jsonl")
        ]
        return sorted(files)

    def apply_window(self) -> int:
        """Move old sessions to the archives so only the last N stay in the
        history dir. Returns the number of files moved."""
        files = self._list_sessions()
        moved = 0
        while len(files) - moved > self.window_sessions:
            old = files[moved]
            src = os.path.join(self.history_dir, old)
            dst = os.path.join(self.archives_dir, old)
            os.replace(src, dst)
            moved += 1
        return moved

    def enforce_archive_cap(self) -> int:
        """Delete the oldest archived files beyond the size cap (MB). Returns
        the number of files deleted."""
        cap_bytes = self.archive_cap_mb * 1024 * 1024
        archived = sorted(
            f for f in os.listdir(self.archives_dir) if f.endswith(".jsonl")
        )
        total = sum(
            os.path.getsize(os.path.join(self.archives_dir, f)) for f in archived
        )
        deleted = 0
        for f in archived:  # oldest first
            if total <= cap_bytes:
                break
            size = os.path.getsize(os.path.join(self.archives_dir, f))
            os.remove(os.path.join(self.archives_dir, f))
            total -= size
            deleted += 1
        return deleted

    def maintain(self) -> Dict[str, int]:
        """Apply the rolling window and enforce the archive cap."""
        return {
            "moved_to_archive": self.apply_window(),
            "deleted_from_archive": self.enforce_archive_cap(),
        }


class StreamAggregator:
    """Aggregates streamed chunks per invoke and writes ONE bounded record per
    invoke to ``history/stream.jsonl`` (instead of one record per chunk, which
    was ~23MB per 91-minute run). The dashboard's live window still gets every
    chunk in-memory via :meth:`on_chunk`; only the on-disk log is aggregated.

    Per-kind text (``thinking`` / ``content`` / ``tool_call``) is capped at
    ``max_chars`` both in memory and on disk (a ``<kind>_truncated`` marker
    carries the original length). The buffer is flushed when the corresponding
    invoke's ``on_call`` fires (:meth:`flush`)."""

    def __init__(self, store: "HistoryStore", max_chars: int = 4000):
        self.store = store
        self.max_chars = max_chars
        self._buffers: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def on_chunk(self, stream_id: str, role_id: str, model: str, kind: str,
                 text: str, label: str = "", reasoning: str = "") -> None:
        """Buffer a streamed chunk (in-memory, for the live dashboard)."""
        with self._lock:
            buf = self._buffers.get(stream_id)
            if buf is None:
                buf = self._buffers[stream_id] = {
                    "role": role_id,
                    "model": model,
                    "label": label,
                    "reasoning": reasoning,
                    "kinds": {},
                }
            # Cap per-kind growth at max_chars (bounds memory + disk).
            cur = buf["kinds"].get(kind, "")
            if len(cur) < self.max_chars:
                buf["kinds"][kind] = cur + text

    def flush(self, stat: Dict[str, Any]) -> None:
        """Write ONE bounded record for the invoke whose ``on_call`` fired
        (correlated by ``stream_id``). A no-op when the stat carries no
        ``stream_id`` or the buffer is already empty."""
        stream_id = stat.get("stream_id")
        if not stream_id:
            return
        with self._lock:
            buf = self._buffers.pop(stream_id, None)
        if buf is None:
            return
        rec: Dict[str, Any] = {
            "ts": stat.get("ts"),
            "stream_id": stream_id,
            "role": buf["role"],
            "model": buf["model"],
            "label": buf["label"],
            "reasoning": buf["reasoning"],
            "phase": stat.get("phase"),
            "outcome": stat.get("outcome"),
            "kinds": {},
        }
        for kind, text in buf["kinds"].items():
            if len(text) > self.max_chars:
                rec["kinds"][kind] = text[: self.max_chars]
                rec["kinds"][kind + "_truncated"] = len(text)
            else:
                rec["kinds"][kind] = text
        self.store._append("stream.jsonl", rec)
