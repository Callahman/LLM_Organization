"""Phase 4 — Top-down dispatch (core context assembly).

The leader decomposes the mission into **department objectives** → department
heads decompose into **team objectives** → managers decompose into **IC
tasks** → ICs do the work in their team directories. Work propagates **up**
in **structured reports** (bounded summaries + artifact pointers) — the leader
never reads code; its synthesis reflects IC-level work **via the chain of
command**.

No tier is skipped in assignments. The **mission digest** is in scope for
leaders/heads (a bounded summary of the mission, not the full markdown).

**Pods A/B/C multi-trigger** (an add-on to the dispatch, never a
replacement): after each team's IC work, a pod forms when any trigger fires —
A (disagreement across the IC work outputs), B (a `cross_team`-marked
objective), C (a routing-rule task type). The pod's decision is then carried
**all three ways**: written to `pods/artifacts/` (+ the `HistoryStore`
decision journal), carried up to the leader's Phase 5 synthesis, and seeded
into the members' memory as a cross-team `pod:<id>` entry (via
`MemoryBackend.seed_cross_team` — a no-op for a plain `StubBackend`).

**Decomposition (Phase 3):** this file keeps the core context assembly —
`mission_digest`, the leader/head/manager/IC/policy context builders, the
policy read/write helpers, the defensive `_decomposition_list`, and
`generate_head_policies`. The `dispatch` runner moved to
`runtime/dispatch_main.py`; the role lifecycle + IC work invokes (including
the upward-report builders `_work_path` / `_upward_report`) to
`runtime/dispatch_role_work.py`; the self-edits to
`runtime/dispatch_self_edits.py`; the efficiency actions to
`runtime/dispatch_efficiency.py`; the automation flow to
`runtime/dispatch_automation.py`; and the pods A/B/C triggers to
`runtime/dispatch_pod_triggers.py`. This file re-exports the full public API
(backward-compatible facade).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from roles.base import Role
from runtime.org import OrgState
from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.dispatch_role_work import _work_path, _upward_report  # noqa: E402,F401


def mission_digest(mission: Dict[str, Any]) -> str:
    """A bounded digest of the mission (purpose + success criteria + scope) —
    what leaders/heads see, not the full MISSION.md."""
    parts = []
    for key in ("purpose", "success_criteria", "scope"):
        val = mission.get(key, "")
        if isinstance(val, list):
            val = "; ".join(str(v) for v in val)
        if val:
            parts.append(f"{key}: {val}")
    return " | ".join(parts) if parts else "(no mission digest)"


def _leader_ctx(digest: str, head_ids: List[str],
                efficiency_panel: str = "") -> str:
    base = (
        "PHASE 4: decompose the mission into department objectives. "
        f"Mission digest: {digest} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`department_objectives` key is a NON-EMPTY JSON array of objects, "
        "each exactly {\"head_id\": <str>, \"objective\": <str>}. "
        f"The head_id MUST be one of the existing department heads: {head_ids}. "
        "Do NOT invent new head_ids — only assign objectives to the heads that "
        "already exist in the org."
    )
    # Story 22: the Leader is invoked with the efficiency panel (per-role /
    # per-department invoke time) so it can act on an inefficient role or
    # department.
    if efficiency_panel:
        base += " " + efficiency_panel
    return base


def _head_ctx(head: Role, objective: str, digest: str) -> str:
    return (
        f"PHASE 4 (head {head.id}): decompose the department objective into "
        f"team objectives. Objective: {objective} | Mission digest: {digest} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`team_objectives` key is a JSON array of objects, each exactly "
        "{\"manager_id\": <str>, \"team\": <str>, \"objective\": <str>} (or "
        "{\"ic_id\": <str>, \"team\": <str>, \"objective\": <str>} if you "
        "direct ICs directly). `team` is the team's directory name (a short "
        "slug, e.g. \"pipelines\") — it becomes the team work dir "
        "(departments/<dept>/<team>/) where the team's ICs write their work."
    )


def _manager_ctx(manager: Role, objective: str, policy: str = "") -> str:
    return (
        f"PHASE 4 (manager {manager.id}): decompose the team objective into "
        f"IC tasks. Objective: {objective} | Department policy (follow it, and "
        f"give your ICs tasks that satisfy it): {policy or '(none)'} "
        "Set `decomposition` to a JSON OBJECT (not a string) whose "
        "`ic_tasks` key is a JSON array of objects, each exactly "
        "{\"ic_id\": <str>, \"task\": <str>}."
    )


def _ic_ctx(ic: Role, task: str, policy_summary: str = "") -> str:
    # The exact team work root (departments/<dept>/<team>/). The IC must write
    # there — a bare top-level dir is refused by the permission layer as
    # out_of_scope, so the prompt names the real root, shows a correct/wrong
    # pair, and forbids the role's own id as a directory (the default the
    # model falls into when no concrete root is given).
    if ic.department and ic.team:
        team_root = f"departments/{ic.department}/{ic.team}"
        path_rules = (
            f"Every path MUST start with {team_root}/ — e.g. correct: "
            f"{team_root}/README.md; wrong: {ic.team}/README.md or "
            f"{ic.id}/README.md (a bare top-level dir, or your own id as a "
            f"directory, is refused as out_of_scope)."
        )
    else:
        team_root = "your team directory"
        path_rules = (
            "Write under your team directory (departments/<dept>/<team>/); a "
            "bare top-level path is refused as out_of_scope."
        )
    return (
        f"PHASE 4 (IC {ic.id}): do the work in your team directory. Your team "
        f"work directory is {team_root}/ — write ALL files there. {path_rules} "
        f"Department policy summary (follow it): {policy_summary or '(none)'} "
        f"Task: {task} Set `summary` to a one-line summary of the work done "
        f"and `work_path` to the path of the work (under {team_root}/). If "
        "your work requires changing code, set `code_edits` to a JSON array "
        "of objects, each exactly {\"path\": <str>, \"content\": <str>}. Each "
        f"edit is gated by the permission layer: write under {team_root}/ "
        "only; the mission and the rules are read-only."
    )


def _policy_ctx(head: Role, mission_digest: str, existing_policy: str,
                directive: str) -> str:
    """The head's Phase 4 policy-generation context. The head is invoked
    BEFORE it decomposes into managers to produce (a) the full department
    POLICY markdown and (b) a POLICY_SUMMARY that distils the key policy points
    for ICs. Context = Mission + the head's existing policy (Department
    Instructions) + the boss's directive (the leader's department objective, or
    the head's mandate for a required dept) + the role's memory (auto-folded by
    the MemoryBackend)."""
    return (
        f"PHASE 4 (head {head.id}): author your department's POLICY so your "
        f"managers and ICs have a clear instruction on how their work fulfils "
        f"the org's goal. Mission: {mission_digest} | Your directive: "
        f"{directive} | Your existing policy (update it, don't start from "
        f"scratch): {existing_policy or '(none yet)'} Set `policy` to the FULL "
        f"policy markdown (how work is broken down, standards, how managers and "
        f"ICs report) and `policy_summary` to a SHORT summary of the key policy "
        f"points (a few lines) that ICs will be given directly. Set `summary` "
        f"to a one-line summary and `confidence` to a number 0-1."
    )


def _read_policy(dept: str, departments_dir: str) -> str:
    """The existing content of a department's policy markdown ("" if missing)."""
    if not dept:
        return ""
    path = os.path.join(departments_dir, dept, f"{dept.upper()}_POLICY.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write_policy(dept: str, policy_text: str, departments_dir: str) -> None:
    """Write a department's policy markdown (creating the dir if needed)."""
    if not dept or not policy_text:
        return
    dept_dir = os.path.join(departments_dir, dept)
    os.makedirs(dept_dir, exist_ok=True)
    with open(os.path.join(dept_dir, f"{dept.upper()}_POLICY.md"), "w",
              encoding="utf-8") as f:
        f.write(policy_text)


def _decomposition_list(out: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    """Safely read a list from a role's ``decomposition`` object, tolerating the
    shapes the real LLM free-forms: a dict (canonical), a bare list (the model
    collapsed the object into the list itself), or a string/number/None (the
    model ignored the forced schema). Returns a list of dicts (empty if none).

    This is the defensive half of the Phase-4 fix: even if the model ignores
    the forced ``submit_output`` schema, a string ``decomposition`` degrades to
    "no work to dispatch" (visible + logged) instead of an ``AttributeError``
    crash on ``.get(...)``."""
    rec = (out or {}).get("decomposition")
    if isinstance(rec, dict):
        val = rec.get(key)
    elif isinstance(rec, list):
        val = rec
    else:
        return []
    if not isinstance(val, list):
        return []
    return [v for v in val if isinstance(v, dict)]


def generate_head_policies(
    backend: LLMBackend,
    org: OrgState,
    dept_objectives: List[Dict[str, Any]],
    mission_digest: str,
    departments_dir: str = "departments",
) -> Dict[str, Dict[str, str]]:
    """Phase 4 (pre-decomposition): every department head — operational AND
    required (HR/Safety/Morality) — is invoked to author its department POLICY
    (full markdown, written to ``departments/<dept>/<DEPT>_POLICY.md``) and a
    POLICY_SUMMARY (the key points ICs are given directly). This runs BEFORE
    any head decomposes into managers, so managers/ICs have a clear instruction
    on how their work fulfils the org's goal.

    The head's context = Mission + its existing policy (Department
    Instructions) + its directive (the leader's department objective if the
    leader assigned one, else the head's mandate) + its memory (auto-folded by
    the MemoryBackend).

    Returns ``{head_id: {"policy": <full text>, "policy_summary": <summary>}}``.
    """
    # A head's directive: the leader's department objective if assigned, else
    # the head's own mandate (a required dept gets no operational objective).
    objective_by_head = {
        obj.get("head_id", ""): obj.get("objective", "")
        for obj in dept_objectives
        if isinstance(obj, dict)
    }
    policies: Dict[str, Dict[str, str]] = {}
    for head in org.department_heads():
        directive = (
            objective_by_head.get(head.id, "")
            or head.mandate
            or "your department's governance responsibilities"
        )
        existing = _read_policy(head.department, departments_dir)
        out = backend.invoke(
            head, _policy_ctx(head, mission_digest, existing, directive),
            reasoning=classify_complexity(4, head, {}),
            phase=4,
        )
        policy = out.get("policy", "") if isinstance(out, dict) else ""
        policy_summary = (
            out.get("policy_summary", "") if isinstance(out, dict) else ""
        )
        if policy:
            _write_policy(head.department, policy, departments_dir)
        policies[head.id] = {
            "policy": policy,
            "policy_summary": policy_summary,
        }
    return policies


# --- Backward-compatible facade --------------------------------------------
# The dispatch API moved to focused modules (Phase 3); re-export the full
# public API so `from runtime.dispatch import ...` keeps working unchanged.

from runtime.dispatch_role_work import (  # noqa: E402,F401
    _ensure_role,
    _fire_role,
    _invoke_ic,
)
from runtime.dispatch_self_edits import (  # noqa: E402,F401
    _self_edit_log,
    _repair_edit_paths,
    _ic_pre_read,
    _run_self_edits,
    _retry_refused_edits,
    _apply_ic_self_edits,
)
from runtime.dispatch_efficiency import (  # noqa: E402,F401
    _efficiency_panel_text,
    _reassign_role,
    _process_efficiency,
)
from runtime.dispatch_automation import (  # noqa: E402,F401
    _automation_slug,
    run_automation,
)
from runtime.dispatch_pod_triggers import (  # noqa: E402,F401
    _task_types,
    _pod_topic,
    _check_pod_triggers,
)
from runtime.dispatch_main import dispatch  # noqa: E402,F401

__all__ = [
    # core (kept here)
    "mission_digest",
    "_leader_ctx",
    "_head_ctx",
    "_manager_ctx",
    "_ic_ctx",
    "_policy_ctx",
    "_read_policy",
    "_write_policy",
    "_decomposition_list",
    "generate_head_policies",
    # core (kept in dispatch_role_work; re-exported here)
    "_work_path",
    "_upward_report",
    # facade re-exports (moved to focused modules)
    "dispatch",
    "_ensure_role",
    "_fire_role",
    "_invoke_ic",
    "_self_edit_log",
    "_repair_edit_paths",
    "_ic_pre_read",
    "_run_self_edits",
    "_retry_refused_edits",
    "_apply_ic_self_edits",
    "_efficiency_panel_text",
    "_reassign_role",
    "_process_efficiency",
    "_automation_slug",
    "run_automation",
    "_task_types",
    "_pod_topic",
    "_check_pod_triggers",
]
