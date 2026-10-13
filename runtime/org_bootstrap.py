"""Phase 3 — Org bootstrap: the Leader's department-head proposal.

The Leader proposes department heads (bounded retry until the proposal
includes at least one **operational** head), the proposal is extracted /
normalized from **any** of the shapes the leader produces, the total
org-size cap is enforced (Story 11, B16), each head goes through the HR
redundancy review, and the required governance departments (hr, safety,
morality) are always spun up (and cannot be fired).

**Decomposition (Phase 1):** extracted from `runtime/org.py` (the core
registry, constants, and errors stay there).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional

from roles.base import Role
from roles.worker import worker_output_schema
from runtime.mission import MissionResult
from runtime.complexity import classify_complexity
from runtime.org import (
    BootstrapError,
    MAX_ORG_ROLES,
    REQUIRED_DEPARTMENTS,
    OrgState,
    _create_department_dirs,
)


def _bootstrap_context(mission_result: MissionResult,
                       retry_hint: str = "") -> str:
    ctx = (
        "PHASE 3: propose the initial department heads for the mission. "
        "Produce org_recommendation with the department heads as a NON-EMPTY "
        "list — use the key `department_heads` (items: {id, department, "
        "sub_architype, required, mandate}) or, equivalently, the key "
        "`departments` (items: {name, head, mandate}). You MUST include the "
        "OPERATIONAL department heads that will actually do the mission's "
        "work — derive them from the mission's purpose / scope / "
        "org-recommendation section (the workstreams the mission names, e.g. "
        "income/operations, data, ml/compute, finance/reporting) — in "
        "ADDITION to the required governance departments (hr, safety, "
        "morality, which must also be included). The list must NOT be empty "
        "and must NOT contain only the required departments: without "
        "operational heads, Phase 4 cannot dispatch any work."
    )
    # Story 11 (B15): on a retry, append the previous attempt's failure reason
    # so the leader can adjust (instead of re-sending the same context).
    if retry_hint:
        ctx += (
            "\n\nPREVIOUS ATTEMPT FAILED — adjust your proposal. The leader "
            f"reply did not include an operational department head. "
            f"Diagnostic: {retry_hint}"
        )
    return ctx


def _has_operational_head(heads: List[Dict[str, Any]]) -> bool:
    """True if the proposal includes at least one **operational** department
    head (a head whose department is not one of the required governance
    departments). Without an operational head, Phase 4 cannot dispatch any
    work, so the bootstrap retries / fails rather than proceeding silently."""
    for spec in heads or []:
        if not isinstance(spec, dict):
            continue
        dept = str(spec.get("department", "")).strip().lower()
        if dept and dept not in REQUIRED_DEPARTMENTS:
            return True
    return False


def _dept_slug(name: str) -> str:
    """A filesystem-safe slug for a department name (lowercase, underscores) —
    the leader's free-text department names (e.g. 'Engineering / Data & ML')
    must become valid directory names."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "dept"


def _normalize_head_spec(d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a single department-head spec — in **any** of the shapes the
    leader produces — to ``{id, department, sub_architype, required, mandate}``.
    Accepts the canonical keys (``department``/``sub_architype``) and the
    leader's free-text keys (``name``/``head``). Returns ``None`` if the spec
    has no usable department name or head."""
    name = str(d.get("department", "") or d.get("name", "")).strip()
    head = str(d.get("sub_architype", "") or d.get("head", "")).strip()
    mandate = str(d.get("mandate", "")).strip()
    if not name and not head:
        return None
    rid = str(d.get("id", "")).strip() or f"head_{_dept_slug(name)}"
    return {
        "id": rid,
        "department": _dept_slug(name),
        "sub_architype": head,
        "required": bool(d.get("required", False)),
        "mandate": mandate,
    }


def _extract_department_heads(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract the proposed department heads from the leader's Phase 3 output,
    accepting the **multiple structures the leader actually produces** (not just
    the canonical ``org_recommendation.department_heads``). The real LLM leader
    may emit ``org_recommendation.departments`` (a list of ``{name, head,
    mandate}``), or free-form some *other* list-of-objects under
    ``org_recommendation`` (the key name varies run to run). Each spec is
    normalized to ``{id, department, sub_architype, required, mandate}``."""
    rec = out.get("org_recommendation") or {}
    if not isinstance(rec, dict):
        return []

    def _norm_list(val: Any) -> List[Dict[str, Any]]:
        if not (isinstance(val, list) and val):
            return []
        norm = [_normalize_head_spec(d) for d in val if isinstance(d, dict)]
        return [n for n in norm if n is not None]

    # 1. Canonical: org_recommendation.department_heads.
    norm = _norm_list(rec.get("department_heads"))
    if norm:
        return norm
    # 2. The leader's known shape: org_recommendation.departments.
    norm = _norm_list(rec.get("departments"))
    if norm:
        return norm
    # 3. Fallback: any other list-of-objects under org_recommendation (the
    #    leader free-forms the key name). Scan the remaining keys and return
    #    the first that yields at least one usable head.
    for key, val in rec.items():
        if key in ("department_heads", "departments"):
            continue
        norm = _norm_list(val)
        if norm:
            return norm
    return []


def _ensure_required(org: OrgState, departments_dir: str) -> List[Role]:
    """Ensure the required departments (hr, safety, morality) exist and are
    marked non-fireable."""
    created = []
    for dept in REQUIRED_DEPARTMENTS:
        existing = [
            r for r in org.active_roles()
            if r.architype == "department_head" and r.department == dept
        ]
        if existing:
            existing[0].is_required = True
            continue
        head = Role(
            id=f"head_{dept}",
            architype="department_head",
            sub_architype=f"head_of_{dept}",
            department=dept,
            mandate=f"Head of {dept.upper()}.",
            is_required=True,
            output_schema=worker_output_schema("department_head"),
        )
        org.add_role(head)
        _create_department_dirs(head, departments_dir)
        org.log_event("required_department_bootstrapped", None, head.id,
                      {"department": dept})
        created.append(head)
    return created


def bootstrap(
    org: OrgState,
    backend,
    leader: Role,
    mission_result: MissionResult,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
    additive: bool = False,
    head_retry_budget: int = 3,
    bootstrap_timeout_seconds: Optional[float] = None,
) -> List[Role]:
    """Phase 3: Leader proposes department heads → HR redundancy review →
    registry creation → directories. Required departments are always present.

    The leader's proposal MUST include at least one **operational** department
    head (a head whose department is not one of the required governance
    departments) — without it, no work can be dispatched in Phase 4. If the
    proposal is empty or contains only required departments, the bootstrap
    **retries** (bounded, `head_retry_budget`, default 3); if still empty
    after the retries, it raises a visible `BootstrapError` (never silent).

    In `additive` mode (a revisit), the bootstrap only **adds** roles — a
    proposed role whose id already exists in the org is skipped (never
    dropped / overwritten)."""
    # Bounded retry: the leader's head proposal must include at least one
    # operational department head (not just the required governance depts).
    proposed: List[Dict[str, Any]] = []
    last_out: Dict[str, Any] = {}
    # Story 11 (B15): on a retry, append the previous attempt's failure reason
    # to the context so the leader can adjust (instead of re-sending the same
    # context).
    retry_hint = ""
    for _ in range(max(1, head_retry_budget)):
        last_out = backend.invoke(
            leader, _bootstrap_context(mission_result, retry_hint=retry_hint),
            # The Leader's head proposal is a resourcing decision -> thinking on.
            reasoning=classify_complexity(3, leader, {"is_decision": True}),
            # The head proposal is a heavy operation (it proposes 5-6 department
            # heads, each with a mandate, and the downstream hires) — give it a
            # larger per-invoke budget than the flat default so it doesn't hit
            # the 300s timeout. `None` uses the default.
            timeout=bootstrap_timeout_seconds,
            phase=3,
        )
        candidate = _extract_department_heads(last_out)
        if _has_operational_head(candidate):
            proposed = candidate
            break
        # Story 11 (B15): build the retry hint from the previous attempt's
        # failure reason (the top-level / `org_recommendation` keys).
        rec = last_out.get("org_recommendation")
        rec_keys = (list(rec.keys()) if isinstance(rec, dict)
                    else type(rec).__name__)
        top_keys = list(last_out.keys()) if isinstance(last_out, dict) else []
        retry_hint = f"top-level keys: {top_keys}; org_recommendation: {rec_keys}"
    if not _has_operational_head(proposed):
        # Visible diagnostic: show exactly what the leader returned so the
        # cause is self-evident from the traceback (no re-run to debug).
        rec = last_out.get("org_recommendation")
        rec_keys = (list(rec.keys()) if isinstance(rec, dict)
                    else type(rec).__name__)
        top_keys = list(last_out.keys()) if isinstance(last_out, dict) else []
        raise BootstrapError(
            "Phase 3 produced no operational department heads "
            f"(after {head_retry_budget} attempts) — the org would have only "
            "the required governance departments (hr, safety, morality), so no "
            "work could be dispatched in Phase 4. Re-run the session.\n"
            f"  leader reply top-level keys: {top_keys}\n"
            f"  leader reply org_recommendation: {rec_keys}"
        )
    # Story 11 (B16): total org-size cap — refuse a bootstrap that proposes
    # more heads than the cap (visible note, never silent).
    current_roles = len(org.roles)
    if current_roles + len(proposed) > MAX_ORG_ROLES:
        raise BootstrapError(
            f"Phase 3 proposed {len(proposed)} department heads, but the org "
            f"already has {current_roles} roles — adding all heads would "
            f"exceed the total org-size cap ({MAX_ORG_ROLES}). Refusing the "
            "bootstrap (visible note, never silent). Re-run with a smaller "
            "org recommendation."
        )
    created: List[Role] = []
    for spec in proposed:
        head = Role(
            id=spec["id"],
            architype="department_head",
            sub_architype=spec.get("sub_architype", ""),
            department=spec.get("department", ""),
            mandate=spec.get("mandate", ""),
            is_required=spec.get("required", False),
            output_schema=worker_output_schema("department_head"),
        )
        if additive and org.get(head.id) is not None:
            # Additive-only: never drop / overwrite an existing role.
            continue
        # HR redundancy review (vetoes redundant hires).
        decision = approver_fn("hr", "hire", head)
        if decision.get("decision") != "approve":
            org.log_event("bootstrap_vetoed", leader.id, head.id, decision)
            continue
        org.add_role(head)
        _create_department_dirs(head, departments_dir)
        org.log_event("bootstrapped", leader.id, head.id,
                      {"required": head.is_required,
                       "department": head.department})
        created.append(head)

    # Required departments are always spun up (and cannot be fired).
    created.extend(_ensure_required(org, departments_dir))
    return created


__all__ = [
    "bootstrap",
    "_bootstrap_context",
    "_has_operational_head",
    "_dept_slug",
    "_normalize_head_spec",
    "_extract_department_heads",
    "_ensure_required",
]
