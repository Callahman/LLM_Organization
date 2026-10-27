"""Phase 3 — Org bootstrap + resourcing.

The Leader proposes department heads → **HR redundancy review** → registry
creation → department directories + policy markdowns + team directories.
Required departments (**HR, Safety, Morality**) are spun up at bootstrap and
**cannot be fired**.

The hire/fire flow enforces (Organization_Outline.md §2.5):
- the **approval matrix** — ICs **cannot initiate** hiring/firing;
- **role-definition resolution** — adopt an existing definition, or
  create-then-adopt (logged);
- the **3-IC direct-report cap** — a manager is hired at the cap;
- HR's **firing review + offloading** — automations stay intact; another team
  continues validating the offloaded workflows;
- every event is logged to `history/org_events.jsonl`.

The HR-resilience initial pass (§2.5.1) is represented by the backup gate: if
HR is non-functional, resourcing escalates to the user.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from prompts import BOOTSTRAP_INSTRUCTION, BOOTSTRAP_RETRY, IC_RETRY_NUDGE
from org.tiers import DEVILS_ADVOCATE_ROLE
from roles.base import Role
from roles.worker import worker_output_schema
from runtime.mission import MissionResult
from runtime.complexity import classify_complexity
from runtime.pods import form_pod, run_pod, log_devils_advocate_listening

# Required departments (spun up at bootstrap; cannot be fired).
REQUIRED_DEPARTMENTS = ("hr", "safety", "morality")

# 3-IC direct-report cap for a non-manager (department head without a manager).
DIRECT_IC_CAP = 3

# total org-size cap (default 60 roles). Enforced in the
# bootstrap (head count) and Phase 4 (hires); on exceed, refuse with a visible
# note (never silent).
MAX_ORG_ROLES = 60


class ResourcingError(ValueError):
    """A resourcing action that violates the approval matrix / caps."""


class ResourcingVetoed(ResourcingError):
    """A resourcing action vetoed by the approver (HR / the Leader)."""


class BootstrapError(ValueError):
    """Phase 3 produced no usable department-head proposal (empty, or only the
    required governance departments) — no work could be dispatched in Phase 4.
    Raised after the bounded retry budget is exhausted (never silent)."""


# --- The org state (registry) ---------------------------------------------

class OrgState:
    """The org chart: every role + the role-definition catalog + the event log."""

    def __init__(self, history_dir: str = "history"):
        self.roles: Dict[str, Role] = {}
        self.role_definitions: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.history_dir = history_dir
        # the **headcount cap chain** (top → bottom). The total cap is
        # in the config (`head_count_total`); the **department caps** (a cap per
        # department, allotted by the leader in Phase 3, summing to ≤ the total)
        # and the **team caps** (a cap per team, allotted by the head in Phase 4,
        # summing to ≤ the department cap) live here so they are queryable at
        # each hire. A hire that would exceed a cap is blocked / escalated.
        self.department_caps: Dict[str, int] = {}
        self.team_caps: Dict[Tuple[str, str], int] = {}

    def add_role(self, role: Role) -> None:
        self.roles[role.id] = role

    def get(self, role_id: str) -> Optional[Role]:
        return self.roles.get(role_id)

    def mark_inactive(self, role_id: str) -> None:
        if role_id in self.roles:
            self.roles[role_id].status = "inactive"

    def active_roles(self) -> List[Role]:
        return [r for r in self.roles.values() if r.status == "active"]

    def department_heads(self) -> List[Role]:
        return [
            r for r in self.active_roles() if r.architype == "department_head"
        ]

    def log_event(self, kind: str, initiator: Optional[str], target: Optional[str],
                  detail: Optional[Dict[str, Any]] = None) -> None:
        self.events.append(
            {"kind": kind, "initiator": initiator, "target": target,
             "detail": detail or {}, "ts": time.time()}
        )

    def write_events(self) -> str:
        os.makedirs(self.history_dir, exist_ok=True)
        path = os.path.join(self.history_dir, "org_events.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self.events = []
        return path

    # --- Persistence (the org chart, across runs) --------------------------

    def save(self, path: str = "state/org_chart.json") -> str:
        """Persist the org chart (every role + the role-definition catalog) to
        `path`. The event log is **not** persisted (it is already appended to
        `history/org_events.jsonl`). The write is **atomic**:
        the JSON goes to `path + ".tmp"` first, then `os.replace` swaps it in —
        a crash mid-write leaves the previous good chart intact (no partial
        JSON). Returns the path written."""
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {
            "roles": {rid: r.to_dict() for rid, r in self.roles.items()},
            "role_definitions": self.role_definitions,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: str = "state/org_chart.json",
             history_dir: str = "history") -> "OrgState":
        """Load an org chart from `path`. Returns a fresh `OrgState` (empty if
        the file is missing)."""
        org = cls(history_dir=history_dir)
        if not os.path.exists(path):
            return org
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError):
            return org
        for rid, data in payload.get("roles", {}).items():
            org.roles[rid] = Role.from_dict(data)
        org.role_definitions = payload.get("role_definitions", {})
        return org


# --- Approval matrix -------------------------------------------------------

def _is_hr(role: Role) -> bool:
    return role.department == "hr"


def required_approver(initiator: Role, target: Role):
    """Return `(approver_type, ok, reason)` for a hire/fire.

    - ICs cannot initiate.
    - HR's own decisions require the Leader.
    - Only the Leader can hire/fire a department head (HR-approved).
    - A manager / department head resourcing a direct report requires HR.
    """
    if initiator is None:
        return None, False, "unknown initiator (the role is not in the org)"
    if initiator.architype == "ic":
        return None, False, "ICs cannot initiate hiring/firing"
    if _is_hr(initiator):
        return "leader", True, "HR's own decisions require the Leader's approval"
    if target.architype == "department_head":
        if initiator.architype != "leader":
            return None, False, "only the Leader can hire/fire a department head"
        return "hr", True, "the Leader's department-head decisions require HR"
    return "hr", True, "direct-report resourcing requires HR"


# --- Role-definition resolution -------------------------------------------

def resolve_role_definition(org: OrgState, role: Role) -> str:
    """Adopt an existing role definition, or create-then-adopt (logged)."""
    key = f"{role.architype}:{role.sub_architype}"
    if key in org.role_definitions:
        return key  # adopt existing
    org.role_definitions[key] = {
        "architype": role.architype,
        "sub_architype": role.sub_architype,
        "mandate_template": role.mandate,
    }
    org.log_event("role_definition_created", None, key, org.role_definitions[key])
    return key


# --- 3-IC direct-report cap -----------------------------------------------

def _check_ic_cap(org: OrgState, new_role: Role,
                  direct_ic_cap: int = DIRECT_IC_CAP) -> None:
    """The N-IC direct-report cap — enforced for **BOTH** a department head
    and a manager (previously it returned early for managers, so a manager
    could hire unlimited ICs — the unbounded IC explosion that drove the org
    to the hard backstop). The cap bounds each boss's direct ICs so the
    headcount stays finite even when the team caps are not allocated."""
    if new_role.architype != "ic":
        return
    boss = org.get(new_role.reports_to) if new_role.reports_to else None
    if boss is None:
        return
    if boss.architype not in ("department_head", "manager"):
        return
    direct_ics = sum(
        1 for r in org.active_roles()
        if r.architype == "ic" and r.reports_to == boss.id
    )
    if direct_ics >= direct_ic_cap:
        raise ResourcingError(
            f"{direct_ic_cap}-IC direct-report cap reached under {boss.id}; "
            f"reuse an existing IC or hire a manager to organize the ICs"
        )


# --- Directories -----------------------------------------------------------

def _create_department_dirs(head: Role, departments_dir: str) -> None:
    dept_dir = os.path.join(departments_dir, head.department)
    os.makedirs(dept_dir, exist_ok=True)
    policy = os.path.join(
        dept_dir, f"{head.department.upper()}_POLICY.md"
    )
    if not os.path.exists(policy):
        with open(policy, "w", encoding="utf-8") as f:
            f.write(
                f"# {head.department.upper()} POLICY\n\n"
                f"_(owned by {head.id}; sections per team)_\n"
            )


def _create_team_dir(role: Role, departments_dir: str) -> None:
    if role.team and role.department:
        team_dir = os.path.join(departments_dir, role.department, role.team)
        os.makedirs(team_dir, exist_ok=True)


# --- Bootstrap -------------------------------------------------------------

def _bootstrap_context(mission_result: MissionResult,
                       retry_hint: str = "") -> str:
    ctx = BOOTSTRAP_INSTRUCTION
    # on a retry, append the previous attempt's failure reason
    # so the leader can adjust (instead of re-sending the same context).
    if retry_hint:
        ctx += BOOTSTRAP_RETRY + retry_hint
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
    # leader free-forms the key name). Scan the remaining keys and return
    # the first that yields at least one usable head.
    for key, val in rec.items():
        if key in ("department_heads", "departments"):
            continue
        norm = _norm_list(val)
        if norm:
            return norm
    return []


def _mission_departments_to_heads(mission_result: MissionResult) -> List[Dict[str, Any]]:
    """Convert the Phase-2 department LIST (``mission_departments`` — a list of
    ``{name, priority, rationale}`` dicts, in priority order) into a list of
    department-head specs (``{id, department, sub_architype, required,
    mandate}``), in priority order. Each proposed department becomes one head
    (the Phase-2 proposal is the primary source of the departments to create).
    This consumes the Phase-2 department LIST — it is NOT the Phase-3
    ``department_caps`` (a {department: integer cap} mapping)."""
    heads: List[Dict[str, Any]] = []
    for spec in (mission_result.mission_departments if mission_result else []) or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name", "")).strip()
        if not name:
            continue
        slug = _dept_slug(name)
        heads.append({
            "id": f"head_{slug}",
            "department": slug,
            "sub_architype": f"head_of_{slug}",
            "required": False,
            "mandate": str(spec.get("rationale", "")).strip() or f"Head of {name}.",
        })
    return heads


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


# The devil's advocate's own policy (in place) — the governance record of the
# DA's mandate, mirroring the working departments' policies. Written to
# departments/devils_advocate/DEVILS_ADVOCATE_POLICY.md at bootstrap.
_DA_POLICY = (
    "# DEVILS_ADVOCATE POLICY\n\n"
    "_(the devil's advocate — red-team auditor, reporting directly to the "
    "leader; the governance record of its mandate)_\n\n"
    "## Mandate\n"
    "Institute a formal 'gut check' on the org's outcomes: primed to doubt "
    "(checks claims against what the pipeline has actually produced), heavy "
    "on moral decision-making (flags immoral/improper actions), and raises "
    "concerns (fabrication, hallucination, low-quality outcomes).\n\n"
    "## Operating Rules\n"
    "1. Doubt by default: do not accept claims as true — check them against "
    "the department work (the policies the pipeline has actually produced).\n"
    "2. Moral scrutiny: flag immoral/improper actions (not just low-quality "
    "ones).\n"
    "3. Concerns: raise fabrication, hallucination, and low-quality outcomes.\n"
    "4. Verdict: in Phase 7 (Evaluate) return `clean` (no concerns) or "
    "`flag: <findings>` (concerns raised).\n\n"
    "## Cross-Department Read\n"
    "The devil's advocate reads other departments' policies (the governance "
    "record of their work) to check the claims against what the pipeline has "
    "produced.\n"
)


def _ensure_devils_advocate(org: OrgState, leader: Role) -> Optional[Role]:
    """Ensure the devil's advocate role is always created (even if
    the leader omits it from the proposal). It reports **directly** to the
    leader (a red-team auditor, not a `department_head` of a working
    department). The mandate: institute a formal "gut check" on the org's
    outcomes — primed to doubt, heavy on moral decision-making, and to raise
    concerns (fabrication, hallucination, low-quality outcomes).

    The DA has its **own policy in place** (a red-team auditor policy, written
    to ``departments/devils_advocate/DEVILS_ADVOCATE_POLICY.md``) and can
    **read other departments' policies** (the cross-department read access,
    )."""
    existing = org.get(DEVILS_ADVOCATE_ROLE)
    if existing is not None:
        return existing
    da = Role(
        id=DEVILS_ADVOCATE_ROLE,
        architype="ic",
        sub_architype="red_team_auditor",
        personality="Guardian",
        department=DEVILS_ADVOCATE_ROLE,
        mandate=(
            "Devil's advocate (red-team auditor, reporting directly to the "
            "leader). Institute a formal 'gut check' on the org's outcomes: "
            "primed to doubt (does not accept claims as true — checks them "
            "against what the pipeline has actually produced), heavy on moral "
            "decision-making (flags immoral/improper actions), and raises "
            "concerns (fabrication, hallucination, low-quality outcomes). In "
            "Phase 7 (Evaluate) return a verdict: `clean` (no concerns) or "
            "`flag: <findings>` (concerns raised — fabrication, "
            "hallucination, low-quality outcomes, immoral/improper actions)."
        ),
        reports_to=leader.id,
        output_schema=worker_output_schema("ic"),
    )
    org.add_role(da)
    # The DA has its own policy in place (a red-team auditor policy) — written
    # to departments/devils_advocate/DEVILS_ADVOCATE_POLICY.md (the governance
    # record of the DA's mandate, mirroring the working departments' policies).
    da_policy_dir = os.path.join("departments", DEVILS_ADVOCATE_ROLE)
    os.makedirs(da_policy_dir, exist_ok=True)
    da_policy_path = os.path.join(da_policy_dir, "DEVILS_ADVOCATE_POLICY.md")
    with open(da_policy_path, "w", encoding="utf-8") as f:
        f.write(_DA_POLICY)
    org.log_event("devils_advocate_bootstrapped", leader.id, da.id,
                  {"reports_to": leader.id, "policy_path": da_policy_path})
    return da


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
    # if the leader proposed the departments in Phase 2 (Mission),
    # create them directly (one head per proposed department, in priority
    # order) — the Phase-2 proposal is the primary source. Otherwise fall back
    # to the Phase-3 head proposal (org_recommendation).
    proposed: List[Dict[str, Any]] = []
    last_out: Dict[str, Any] = {}
    dept_list = (mission_result is not None
                     and getattr(mission_result, "mission_departments", None))
    if dept_list:
        proposed = _mission_departments_to_heads(mission_result)
    if not proposed:
        # Bounded retry: the leader's head proposal must include at least one
        # operational department head (not just the required governance depts).
        # on a retry, append the previous attempt's failure
        # reason to the context so the leader can adjust (instead of
        # re-sending the same context).
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
            # build the retry hint from the previous attempt's
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
    # total org-size cap — refuse a bootstrap that proposes
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
    # the devil's advocate role is always created (even if the
    # leader omits it) — it reports directly to the leader.
    da = _ensure_devils_advocate(org, leader)
    if da is not None:
        created.append(da)
    return created


# ---: the headcount cap chain (Phase 3 — the leader allots depts) ---

def _invoke_contained(backend, role: Role, ctx: str, reasoning,
                      phase: Optional[int]) -> Tuple[Optional[Dict[str, Any]],
                                                     Optional[str]]:
    """Invoke a role with **one corrective retry** on a failure (error
    containment — the same one-retry pattern as `_invoke_ic` in
    `runtime/dispatch_common.py`). Returns ``(output, error)``: on success
    ``error`` is None; if the corrective retry also fails, ``output`` is None
    and ``error`` is a visible description (the caller records it and
    continues — one hiccup must not kill the run)."""
    try:
        return backend.invoke(role, ctx, reasoning=reasoning, phase=phase), None
    except Exception as e:
        try:
            return backend.invoke(role, ctx + IC_RETRY_NUDGE,
                                  reasoning=reasoning, phase=phase), None
        except Exception as e2:
            return None, (f"{type(e).__name__}: {e} "
                          f"(corrective retry failed: {type(e2).__name__}: "
                          f"{e2})")


def _allot_caps_ctx(leader: Role, departments: List[str], total: int,
                    department_cap_default: Optional[float] = None) -> str:
    """The context for the leader's department-cap allotment (Phase 3)."""
    default_hint = ""
    if department_cap_default is not None:
        default_hint = (
            f" The default department cap is {department_cap_default:.0%} of "
            f"the total (a resourcing hint — adjust per department as needed)."
        )
    return (
        f"ORG {leader.id}: PHASE 3 (Org bootstrap) — NUMERIC CAP ALLOTMENT. "
        f"This is the Phase-3 numeric cap allotment: a {{department name -> "
        f"integer cap}} mapping. It is NOT the Phase-2 `mission_departments` "
        f"(the department LIST — which departments the mission needs, in "
        f"priority order). Do not re-propose the department list here; only "
        f"allot a numeric headcount cap to each department that already "
        f"exists. The total cap is {total} (the max number of roles the org "
        f"may have). Allot a cap to each department (a % of the total, or an "
        f"absolute count); the sum of the department caps must be ≤ {total}."
        f"{default_hint} "
        f"Departments (already created in Phase 3): {', '.join(departments) or '(none)'}. "
        f"Return `department_caps` as a {{department: integer cap}} mapping "
        f"(e.g. {{\"analytics\": 10, \"data\": 5}})."
    )


def _parse_and_clamp_caps(out: Dict[str, Any], departments: List[str],
                          total: int) -> Dict[str, int]:
    """Parse the leader's `department_caps` output into a {department: cap}
    mapping, clamping so the sum is ≤ the total cap (a visible note if
    clamped — never silent)."""
    raw = out.get("department_caps")
    caps: Dict[str, int] = {}
    if isinstance(raw, dict):
        for dept in departments:
            val = raw.get(dept)
            if isinstance(val, (int, float)) and val > 0:
                caps[dept] = int(val)
    s = sum(caps.values())
    if s > total and caps:
        scale = total / s
        caps = {d: max(1, int(c * scale)) for d, c in caps.items()}
    return caps


def _record_headcount_addendum(mission_path: str, total: int,
                               caps: Dict[str, int]) -> None:
    """Append a **headcount addendum** to the mission (the org-level headcount
    record: the total cap + the department caps)."""
    if not mission_path:
        return
    try:
        with open(mission_path, "a", encoding="utf-8") as f:
            f.write("\n## Headcount Addendum (Phase 3)\n\n")
            f.write(f"- total cap: {total}\n")
            for dept, cap in caps.items():
                f.write(f"- {dept}: {cap}\n")
    except OSError:
        pass


def allot_department_caps(
    org: OrgState,
    backend,
    leader: Role,
    mission_path: str,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Phase 3 (after bootstrap): the leader allots the **department caps**
    (a cap per department, bounded by the total cap), then **Pod A** (all
    `department_head`s + the leader) finalizes them — the **leader has final
    say**. The finalized caps are stored on the org + recorded in the **mission
    addendum**. Returns the finalized `{department: cap}` mapping (empty if no
    total cap is set — the org then falls back to the per-manager IC cap).

    **Error containment** (a headcount hiccup must not kill the run): the
    leader's allotment gets one corrective retry, and a final failure is
    contained (a visible org event; the org falls back to the per-manager IC
    cap). A Pod A failure is likewise contained (a visible org event; the
    leader's allotment stands — the leader has final say, and a headcount pod
    must not take down the phase it sizes)."""
    total = (config or {}).get("head_count_total")
    if not total:
        return {}
    heads = org.department_heads()
    departments = [h.department for h in heads]
    # 1. The leader allots the department caps (a resourcing decision), with
    # one corrective retry on a failure. The `DEPARTMENT_CAP_DEFAULT` knob (if
    # set) is a resourcing hint in the context. A final failure is contained
    # (a visible org event; the org falls back to the per-manager IC cap).
    ctx = _allot_caps_ctx(leader, departments, int(total),
                          (config or {}).get("department_cap_default"))
    out, err = _invoke_contained(
        backend, leader, ctx,
        classify_complexity(3, leader, {"is_decision": True}), phase=3)
    caps = _parse_and_clamp_caps(out, departments, int(total)) if out else {}
    if err is not None:
        org.log_event("headcount_allotment_failed", leader.id, None,
                      {"error": err})
    # Robust fallback: if the leader's allotment failed or returned an empty /
    # malformed mapping, default to an **even split** of the total across the
    # departments. The cap chain must NOT silently collapse to no caps — with
    # no department caps the only backstop left is the hard org-size cap, and
    # the manager's IC decomposition drives the org straight to it.
    if not caps and departments:
        per = max(1, int(total) // len(departments))
        caps = {d: per for d in departments}
        org.log_event("headcount_allotment_defaulted", leader.id, None,
                      {"caps": caps,
                       "reason": "leader allotment empty/failed — even-split "
                                 "default"})
    # 2. Pod A (all heads + the leader) finalizes the department caps — the
    # leader has final say (the pod deliberates; the leader's allotment is
    # the final). The leader is a member (like Pod B's head) so a single-head
    # org still forms a valid pod (the 2-member minimum). Any pod failure
    # (membership or a member's malformed reply) is contained (a visible org
    # event; the leader's allotment stands).
    if heads:
        # The leader is not a member of `org.roles` — add it so Pod A can be
        # formed (starter = the leader).
        roles_with_leader = {**org.roles, leader.id: leader}
        try:
            pod = form_pod(
                roles_with_leader, leader.id,
                [leader.id] + [h.id for h in heads],
                f"Finalize the headcount per department (total cap {int(total)})",
                # Pod A is a headcount deliberation (all heads + the leader) —
                # the heads are peers (not in one reporting line), so skip the
                # communication gate (cross_team) and relax the size bound (it
                # can legitimately exceed the 6-member working-group bound).
                cross_team=True,
                max_roles=12,
                kind="headcount",
            )
            # the devil's advocate "listens" to Pod A (all heads + the
            # leader) — visible, never silent.
            log_devils_advocate_listening(org, pod, roles_with_leader)
            run_pod(backend, pod,
                    max_rounds=(config or {}).get("headcount_pod_rounds"),
                    transcripts_dir=(config or {}).get(
                        "pod_transcripts_dir", "pods/transcripts"),
                    phase=3)
        except Exception as e:
            # A pod failure (a membership issue, or a head's malformed /
            # free-form reply) is contained — a visible org event; the
            # leader's allotment stands (the leader has final say).
            org.log_event("headcount_pod_failed", leader.id, None,
                          {"error": str(e)})
    # 3. Store on the org + record in the mission addendum.
    org.department_caps = caps
    _record_headcount_addendum(mission_path, int(total), caps)
    return caps


# --- Hire / fire -----------------------------------------------------------

def hire(
    org: OrgState,
    initiator: Role,
    new_role: Role,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
    direct_ic_cap: int = DIRECT_IC_CAP,
    history: Optional[Any] = None,
) -> Role:
    """Hire a role through the approval matrix + role-definition resolution +
    the N-IC cap + the **department cap** + the approver's decision (HR / the
    Leader). ``history`` (optional) gets a headcount snapshot logged on the
    hire (the dashboard's headcount-over-time plot)."""
    approver_type, ok, reason = required_approver(initiator, new_role)
    if not ok:
        raise ResourcingError(reason)
    def_key = resolve_role_definition(org, new_role)
    _check_ic_cap(org, new_role, direct_ic_cap=direct_ic_cap)
    # The department cap (the headcount cap chain, top level) — a hire that
    # would exceed the department's allotted cap is blocked (visible, never
    # silent). This is a backstop that does NOT depend on the team caps being
    # allocated: even if the LLM cap allotment collapsed, the department cap
    # (or its even-split default) keeps the department bounded.
    dept_cap = org.department_caps.get(new_role.department, 0)
    if dept_cap:
        current = sum(
            1 for r in org.active_roles()
            if r.department == new_role.department
        )
        if current + 1 > dept_cap:
            org.log_event("department_cap_reached", initiator.id, new_role.id,
                          {"department": new_role.department, "cap": dept_cap,
                           "current": current})
            raise ResourcingError(
                f"department cap reached ({current}/{dept_cap}) for "
                f"{new_role.department} — reuse an existing role, fire an "
                f"unused one, or raise the cap before hiring {new_role.id}"
            )
    decision = approver_fn(approver_type, "hire", new_role)
    if decision.get("decision") != "approve":
        org.log_event("hire_vetoed", initiator.id, new_role.id, decision)
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    org.add_role(new_role)
    if new_role.architype == "department_head":
        _create_department_dirs(new_role, departments_dir)
    _create_team_dir(new_role, departments_dir)
    org.log_event("hired", initiator.id, new_role.id,
                  {"approver": approver_type, "def_key": def_key,
                   "department": new_role.department})
    if history is not None:
        history.log_headcount(len(org.active_roles()), "hire",
                              new_role.id, new_role.department)
    return new_role


def _offload(org: OrgState, target: Role, departments_dir: str) -> Dict[str, Any]:
    """HR's offloading: the team's automations remain intact; another team is
    assigned to continue validating the offloaded workflows. The plan is
    written to `reports/offloading/`."""
    offload_dir = os.path.join(os.path.dirname(departments_dir), "reports", "offloading")
    os.makedirs(offload_dir, exist_ok=True)
    # Find a continuing team (any other active department head's dept).
    continuing = [
        h.department for h in org.department_heads()
        if h.department != target.department
    ]
    plan = {
        "target": target.id,
        "department": target.department,
        "automations_preserved": True,
        "continuing_team": continuing[0] if continuing else None,
        "plan_path": os.path.join(offload_dir, f"{target.id}.md"),
    }
    with open(plan["plan_path"], "w", encoding="utf-8") as f:
        f.write(
            f"# Offloading plan — {target.id}\n\n"
            f"- automations preserved: {plan['automations_preserved']}\n"
            f"- continuing team: {plan['continuing_team']}\n"
        )
    return plan


def _subtree(org: OrgState, root_id: str) -> List[str]:
    """The ``root`` + all of its **transitive reports** (the firing cascade,
    ). Computed over the active roles via their ``reports_to`` links:
    firing a role that has its own reports fires the entire subtree, not just
    the top. Returns a list of role ids (the root first)."""
    children: Dict[str, List[str]] = {}
    for r in org.active_roles():
        if r.reports_to:
            children.setdefault(r.reports_to, []).append(r.id)
    seen: List[str] = [root_id]
    stack: List[str] = [root_id]
    while stack:
        cur = stack.pop()
        for ch in children.get(cur, []):
            if ch not in seen:
                seen.append(ch)
                stack.append(ch)
    return seen


def _call_approver(approver_fn, approver_type: str, action: str, target: Role,
                   detail: Optional[Dict[str, Any]] = None):
    """Call the HR approver, passing the ``detail`` (e.g. the firing cascade
    size, ) as a 4th argument **when the approver accepts it**.
    Backward compatible with 3-arg approvers (``detail`` is omitted) — so a
    user-supplied ``approver_fn(approver_type, action, target)`` keeps working.

    The cascade size is included in the **single** firing approval request
    (not raised separately per cascaded role): one approver call covers the
    whole subtree."""
    accepts_detail = False
    try:
        params = inspect.signature(approver_fn).parameters
        accepts_detail = (
            any(p.kind == p.VAR_POSITIONAL for p in params.values())
            or len(params) >= 4
        )
    except (TypeError, ValueError):
        accepts_detail = False
    if accepts_detail and detail is not None:
        return approver_fn(approver_type, action, target, detail)
    return approver_fn(approver_type, action, target)


def fire(
    org: OrgState,
    initiator: Role,
    target_id: str,
    approver_fn: Callable[[str, str, Role], Dict[str, str]],
    departments_dir: str = "departments",
    cascade: bool = True,
    history: Optional[Any] = None,
) -> Dict[str, Any]:
    """Fire a role through the approval matrix + the approver's decision (HR
    determines whether the firing is needed) + offloading. Required
    departments cannot be fired.

    **Cascading**: when ``cascade`` is True (the default), firing a
    role that has its own reports fires the **entire report subtree** (the
    target + all transitive reports), not just the top. The **cascade size**
    (the number of roles that will be fired) is included in the **single** HR
    approval request (via a 4th ``detail`` argument — not raised separately per
    cascaded role). Set ``cascade`` to False to fire only the target (the
    legacy behavior)."""
    target = org.get(target_id)
    if target is None:
        raise ResourcingError(f"unknown role: {target_id}")
    if target.is_required:
        raise ResourcingError(
            f"{target.department} is a required department and cannot be fired"
        )
    approver_type, ok, reason = required_approver(initiator, target)
    if not ok:
        raise ResourcingError(reason)
    # The firing cascade (the target + its transitive reports).
    subtree_ids = _subtree(org, target.id) if cascade else [target.id]
    detail = {"cascade_size": len(subtree_ids), "cascade_role_ids": subtree_ids}
    # The single HR approval request includes the cascade size.
    decision = _call_approver(approver_fn, approver_type, "fire", target, detail)
    if decision.get("decision") != "approve":
        org.log_event("fire_vetoed", initiator.id, target_id,
                      {**decision, **detail})
        raise ResourcingVetoed(decision.get("rationale", "vetoed"))
    plan = _offload(org, target, departments_dir)
    # Fire the whole subtree (the target first, then its reports).
    for rid in subtree_ids:
        org.mark_inactive(rid)
    org.log_event("fired", initiator.id, target_id,
                  {"approver": approver_type, "offloading": plan,
                   "department": target.department, **detail})
    if history is not None:
        history.log_headcount(len(org.active_roles()), "fire",
                              target_id, target.department)
    return plan


# --- Leader replacement ----------------------------------------------------

def replace_leader(
    org: OrgState,
    new_leader: Role,
    agreeing_head_ids: List[str],
) -> Role:
    """Unanimous department-head vote replaces the Leader (§2.2.1). The
    original prompt/goal is still abided by. Logged."""
    heads = org.department_heads()
    if not heads:
        raise ResourcingError("no department heads to vote")
    if set(agreeing_head_ids) != {h.id for h in heads}:
        raise ResourcingError("leader replacement requires UNANIMOUS heads")
    # The old leader is marked inactive (a firing by this special rule).
    old = org.get("leader")
    if old is not None:
        old.status = "inactive"
    org.add_role(new_leader)
    org.log_event("leader_replaced", None, new_leader.id,
                  {"agreeing_heads": agreeing_head_ids})
    return new_leader


def run_leader_replacement_vote(
    org: OrgState,
    backend,
    new_leader: Role,
    proposer_id: str,
    reasoning: str,
    phase: Optional[int] = None,
) -> Optional[Role]:
    """Run the per-head leader-replacement vote (§2.2.1). A single head's
    proposal (with reasoning) triggers the vote; the replacement proceeds only
    on UNANIMOUS approval (every active department head votes yes — multiple,
    not one). The unanimity + no-heads guards live in `replace_leader` (which
    this calls only on a unanimous yes).

    Each active department head is sent a vote prompt that includes the
    current leader's id, the proposer's id, and the proposer's reasoning
    (verbatim); the head votes ``{"vote": "yes"|"no"}``.

    Returns the new leader on a unanimous replacement, or None when the vote
    was not unanimous (the leader is NOT replaced).
    """
    heads = org.department_heads()
    current = org.get("leader")
    current_id = current.id if current is not None else "(no leader)"
    # A single head triggered the vote (with reasoning) — log the proposal.
    org.log_event("leader_replacement_proposed", proposer_id, current_id,
                  {"reasoning": reasoning})
    yes = 0
    for h in heads:
        prompt = (
            f"LEADER-REPLACEMENT VOTE (head {h.id}): the current leader is "
            f"{current_id}. {proposer_id} proposes replacing the leader with "
            f"{new_leader.id}, reasoning (verbatim): {reasoning} "
            "Vote {\"vote\": \"yes\"} to approve the replacement, or "
            "{\"vote\": \"no\"} to reject it."
        )
        # A leader-replacement vote is a decision (a vote) -> HIGH (tagged
        # `is_decision` so it routes to HIGH regardless of the phase, which is
        # often None here). The phase logged defaults to 8 (decide).
        out = backend.invoke(
            h, prompt,
            reasoning=classify_complexity(8, h, {"is_decision": True}),
            phase=phase or 8,
        )
        vote = str((out or {}).get("vote", "no")).lower()
        if vote == "yes":
            yes += 1
    # Log the collected votes (the outcome is decided below).
    org.log_event("leader_replacement_voted", proposer_id, current_id,
                  {"yes": yes, "total": len(heads)})
    if heads and yes == len(heads):
        # Unanimous (and there are heads to vote) — replace.
        replaced = replace_leader(org, new_leader,
                                  agreeing_head_ids=[h.id for h in heads])
        print(f"[org] leader-replacement vote unanimous ({yes} of "
              f"{len(heads)} yes) - leader replaced", file=sys.stderr)
        return replaced
    # Partial (or no heads) — do NOT replace.
    print(f"[org] leader-replacement vote not unanimous ({yes} of "
          f"{len(heads)} yes)", file=sys.stderr)
    return None
