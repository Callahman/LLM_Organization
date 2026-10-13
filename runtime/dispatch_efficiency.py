"""Phase 4 — The Leader's efficiency actions (Story 22, S22).

The Leader is invoked with the **efficiency panel** (per-role /
per-department invoke time, cumulative) so it can act on an inefficient role
or department: **fire** (through HR resourcing — the firing cascades to its
report subtree), **reassign** (move it to a different team), **report** (to
the user, without acting), or **automate** (S22 — the automation-over-
headcount flow lives in `runtime/dispatch_automation.py`). All actions are
logged visibly (never silent).

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from runtime.dispatch_role_work import _fire_role


def _efficiency_panel_text(snap: Dict[str, Any]) -> str:
    """Render the efficiency panel (per-role + per-department invoke time,
    cumulative) as text for the Leader's Phase 4 context (Story 22)."""
    per_role = snap.get("per_role", {})
    per_dept = snap.get("per_department", {})
    lines = [
        "EFFICIENCY PANEL (per-role / per-department invoke time, cumulative):"
    ]
    if per_role:
        lines.append("  per-role:")
        for rid, t in sorted(per_role.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {rid}: {t:.1f}s")
    if per_dept:
        lines.append("  per-department:")
        for dept, t in sorted(per_dept.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {dept}: {t:.1f}s")
    if not per_role and not per_dept:
        lines.append("  (no invoke time recorded yet)")
    lines.append(
        "If a role or department is inefficient, set `efficiency` with an "
        "`action` (\"fire\" to fire it through HR resourcing — the firing "
        "cascades to its report subtree; \"reassign\" to move it to a "
        "different team, named in `new_team`; \"report\" to report the "
        "inefficiency to the user without acting) and `target` (the role id or "
        "department slug)."
    )
    return "\n".join(lines)


def _reassign_role(org, leader, target_id, new_team, reasoning, history) -> None:
    """Reassign a role to a different team (Story 22). The role's `team` (its
    work-directory slug) is changed; the move is logged visibly (never
    silent)."""
    role = org.get(target_id)
    if role is None:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "reassign",
                             "target": target_id, "reasoning": reasoning,
                             "error": "unknown role"})
        return
    if not new_team:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "reassign",
                             "target": target_id, "reasoning": reasoning,
                             "error": "no new_team specified"})
        return
    old_team = role.team
    role.team = new_team
    org.log_event("role_reassigned", leader.id, target_id,
                  {"old_team": old_team, "new_team": new_team,
                   "reasoning": reasoning})
    if history is not None:
        history._append("efficiency_reports.jsonl",
                        {"ts": time.time(), "action": "reassign",
                         "target": target_id, "old_team": old_team,
                         "new_team": new_team, "reasoning": reasoning})


def _process_efficiency(org, leader, eff: Dict[str, Any], approver_fn,
                        history) -> None:
    """Process the Leader's efficiency action (Story 22): fire / reassign /
    report an inefficient role or department. All actions are logged visibly
    (never silent)."""
    action = eff.get("action")
    target = eff.get("target")
    reasoning = eff.get("reasoning", "")
    if not action or not target:
        return
    if action == "fire":
        # Fire the inefficient role through HR resourcing (cascades to its
        # report subtree).
        _fire_role(org, leader, target, f"efficiency: {reasoning}",
                   approver_fn, history)
    elif action == "reassign":
        # Reassign the named role to a different team.
        _reassign_role(org, leader, target, eff.get("new_team"), reasoning,
                       history)
    elif action == "report":
        # Report the inefficiency to the user (no action).
        org.log_event("efficiency_reported", leader.id, target,
                      {"reasoning": reasoning})
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "report",
                             "target": target, "reasoning": reasoning})
    elif action == "automate":
        # A recurring task is being automated (an IC writes a Python script, is
        # fired, and the task is then done by executing the script). The actual
        # IC-writes-script -> fired -> script-executed flow is run by
        # ``run_automation`` (the caller, which has the backend); here we just
        # log the action visibly (never silent) so it is not mistaken for an
        # unknown action.
        org.log_event("efficiency_automate_requested", leader.id, target,
                      {"task": eff.get("task", target), "reasoning": reasoning})
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "automate",
                             "target": target,
                             "task": eff.get("task", target),
                             "reasoning": reasoning})
    else:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": action,
                             "target": target, "reasoning": reasoning,
                             "error": "unknown efficiency action"})


__all__ = ["_efficiency_panel_text", "_reassign_role", "_process_efficiency"]
