"""Phase 4 — Role lifecycle + IC work invokes (the dispatch's role plumbing).

The dispatch spins up the managers/ICs it decomposes onto (`_ensure_role` —
through the approval matrix + the org-size cap), fires them through the HR
approver (`_fire_role`), invokes ICs with **one corrective retry** on a
failure (`_invoke_ic` — error containment: one IC hiccup must not kill the
run), and builds the bounded upward reports (`_work_path`,
`_upward_report`) through which work propagates up the line of command.

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there).
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from roles.base import Role, spin_personality, spin_sub_architype
from roles.worker import worker_output_schema
from runtime.org import (
    OrgState,
    hire,
    fire,
    ResourcingError,
    ResourcingVetoed,
    MAX_ORG_ROLES,
)
from runtime.llm import LLMBackend


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
    # Story 11 (B16): total org-size cap — refuse a hire that would exceed the
    # cap (visible note, never silent).
    if len(org.roles) >= MAX_ORG_ROLES:
        print(
            f"[dispatch] org-size cap reached ({MAX_ORG_ROLES}) — refusing to "
            f"hire {role_id} (visible note, never silent).",
            file=sys.stderr,
        )
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
    nudge = (
        "\n\n[RETRY] Your previous reply for this task was not a valid "
        "structured call (its JSON arguments were malformed or missing). "
        "Call the submit_output tool exactly once; its arguments must be ONE "
        "complete JSON object matching your role's output schema. Do not "
        "emit placeholder or dummy calls."
    )
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


__all__ = [
    "_ensure_role",
    "_fire_role",
    "_invoke_ic",
    "_work_path",
    "_upward_report",
]
