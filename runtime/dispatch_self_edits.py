"""Phase 4 — IC self-edits (code edits gated by the permission layer).

An IC may propose `code_edits` with its work. The dispatch **repairs** bare
top-level paths (`_repair_edit_paths` — only the role's own id/team; any other
out-of-scope path is left for the gate to refuse, so the repair can never
become a channel around the sandbox), the IC **reads** the code it is about to
change (`_ic_pre_read` — gated by the read gate; a cross-team read is logged,
a refused read is logged, both visible, never silent), **applies** the edits
(`_run_self_edits` — gated by the write gate; every result journaled), and
runs **one corrective retry** on refusal (`_retry_refused_edits` — bounded to
a single pass, no loop). Refusals, repairs, and the retry are all recorded
visibly (never silent).

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from roles.base import Role
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.history import HistoryStore
from runtime.permissions import apply_code_edits, read_file
from runtime.coerce import as_dict_list


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


__all__ = [
    "_self_edit_log",
    "_repair_edit_paths",
    "_ic_pre_read",
    "_run_self_edits",
    "_retry_refused_edits",
    "_apply_ic_self_edits",
]
