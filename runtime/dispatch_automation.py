"""Phase 4 — Automation over headcount (S22).

For a recurring task, the dispatch spins up an IC to **write a Python
script**, the script is **created** (written to ``<script_dir>/<slug>.py``),
the IC is **fired** (if not needed for other work), and the recurring task is
then done by **executing the script** (subprocess / tool call) instead of an
IC each time. All steps are logged visibly (never silent).

**Decomposition (Phase 3):** extracted from `runtime/dispatch.py` (the
dispatch core + facade stay there).
"""

from __future__ import annotations

import os
import time

from runtime.llm import LLMBackend
from runtime.complexity import classify_complexity
from runtime.dispatch_role_work import _ensure_role, _fire_role


def _automation_slug(task: str) -> str:
    """A short directory slug for an automation task (the script filename)."""
    out = []
    for ch in (task or "task").lower():
        out.append(ch if ch.isalnum() else "-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:40] or "task"


def run_automation(org, leader, eff, backend, approver_fn, history=None,
                   script_dir="automations"):
    """S22: the **automation over headcount** flow — for a recurring task, spin
    up an IC to **write a Python script**, the script is **created** (written to
    ``<script_dir>/<slug>.py``), the IC is **fired** (if not needed for other
    work), and the recurring task is then done by **executing the script**
    (subprocess / tool call) instead of an IC each time.

    ``eff`` is the Leader's efficiency action dict (``action="automate"``,
    ``task`` the recurring task, ``target`` the role/department, ``reasoning``).
    All steps are logged visibly (never silent).
    """
    task = eff.get("task") or eff.get("target") or "(unspecified recurring task)"
    reasoning = eff.get("reasoning", "")
    # The script path (where the automation script lives).
    os.makedirs(script_dir, exist_ok=True)
    script_path = os.path.join(script_dir, _automation_slug(task) + ".py")
    # Step 1: spin up an IC to write the script (hired through the approval
    # matrix, like any other dispatch role).
    ic_id = "auto-" + _automation_slug(task)
    ic = _ensure_role(org, leader, ic_id, "ic", "automations", "automations",
                      approver_fn)
    if ic is None:
        if history is not None:
            history._append("efficiency_reports.jsonl",
                            {"ts": time.time(), "action": "automate",
                             "task": task,
                             "error": "could not hire the automation IC"})
        return {"task": task, "script_path": script_path, "ic_fired": None,
                "error": "could not hire the automation IC"}
    # Step 2: the IC writes the Python script for the recurring task.
    ctx = (
        f"PHASE 4 (automation IC {ic.id}): write a Python script for the "
        f"recurring task. Task: {task} Set `script` to the FULL Python script "
        f"(a self-contained script that performs the recurring task end to "
        f"end) and `summary` to a one-line summary of what the script does."
    )
    out = backend.invoke(ic, ctx,
                         reasoning=classify_complexity(4, ic, {}), phase=4)
    script = out.get("script", "") if isinstance(out, dict) else ""
    # Step 3: the script is created (written to a file).
    if script:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
    org.log_event("automation_script_created", leader.id, ic.id,
                  {"task": task, "script_path": script_path,
                   "reasoning": reasoning})
    if history is not None:
        history._append("efficiency_reports.jsonl",
                        {"ts": time.time(), "action": "automate",
                         "task": task, "script_path": script_path,
                         "reasoning": reasoning})
    # Step 4: the IC is fired (if not needed for other work) — the recurring
    # task is now done by executing the script instead of an IC each time.
    _fire_role(org, leader, ic.id, f"automation: {reasoning}", approver_fn,
               history)
    # Step 5: the automation is active (a visible log — the script is executed
    # via subprocess when the recurring task is due).
    org.log_event("automation_active", leader.id, ic.id,
                  {"task": task, "script_path": script_path})
    return {"task": task, "script_path": script_path, "ic_fired": ic.id}


__all__ = ["_automation_slug", "run_automation"]
