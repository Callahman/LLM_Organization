"""Verify-work preamble (the work-item checkpointing feature) — checks the
work-item checkpoint state and prints the resume plan.

Run this BEFORE a resume to see:
- The checkpoint's phase + cycle.
- The completed work items (departments / teams / ICs) per phase.
- The in-progress work item (the one that will be re-run from scratch).
- The resume plan (which work items will be skipped, which will be re-run).

This is a read-only script — it does not modify the checkpoint or the org.
"""

from __future__ import annotations

import json
import os
import sys

# the project root (this file's directory).
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# the phase labels (for the visible output).
_PHASE_LABELS = {
    3: "Phase 3 (Bootstrap)",
    4: "Phase 4 (Plan)",
    5: "Phase 5 (Staff)",
    6: "Phase 6 (Execute)",
    7: "Phase 7 (Evaluate)",
    8: "Phase 8 (Decide)",
}

# the work-item kind labels (for the visible output).
_KIND_LABELS = {
    "department": "department(s)",
    "team": "team(s)",
    "ic": "IC(s)",
}


def _load_checkpoint(checkpoint_path: str) -> dict:
    """Load the checkpoint (a corrupt / missing checkpoint returns {})."""
    if not os.path.exists(checkpoint_path):
        return {}
    try:
        with open(checkpoint_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"[verify-work] corrupt/unreadable checkpoint at "
              f"{checkpoint_path} ({e})", file=sys.stderr)
        return {}


def _phase_label(phase) -> str:
    """A visible label for a phase (a missing / unknown phase is '?')."""
    if isinstance(phase, int) and phase in _PHASE_LABELS:
        return _PHASE_LABELS[phase]
    return f"Phase {phase} (?)"


def main() -> None:
    print("=== Verify-work preamble (work-item checkpointing) ===")
    print()

    # the checkpoint path (from the config, or the default).
    checkpoint_path = os.path.join(PROJECT_ROOT, "state", "checkpoint.json")
    if not os.path.exists(checkpoint_path):
        print("No checkpoint found (state/checkpoint.json) — nothing to "
              "verify. A fresh run will start from Phase 1.")
        return

    cp = _load_checkpoint(checkpoint_path)
    if not cp:
        print("Checkpoint is empty / corrupt — nothing to verify.")
        return

    # the checkpoint's phase + cycle.
    cp_phase = cp.get("phase", "?")
    cp_cycle = cp.get("cycle", "?")
    print(f"Checkpoint: {_phase_label(cp_phase)}, cycle {cp_cycle}")
    print()

    # the completed work items per phase.
    completed = cp.get("completed_work_items", {})
    total_completed = 0
    if completed:
        print("Completed work items (will be SKIPPED on resume):")
        for phase in sorted(completed, key=lambda p: (isinstance(p, str), p)):
            items = completed[phase]
            if not isinstance(items, list):
                continue
            if not items:
                continue
            n = len(items)
            total_completed += n
            # the kinds (departments / teams / ICs).
            kinds = {}
            for item in items:
                if isinstance(item, dict):
                    kind = item.get("kind", "?")
                    kinds[kind] = kinds.get(kind, 0) + 1
            kind_str = ", ".join(
                f"{kinds.get(k, 0)} {v}" for k, v in kinds.items()
            ) if kinds else f"{n} item(s)"
            print(f"  {_phase_label(phase)}: {kind_str}")
        print()
    else:
        print("No completed work items (a fresh run or a crash before any "
              "work item completed).")
        print()

    # the in-progress work item.
    current = cp.get("current_work_item")
    if current:
        kind = current.get("kind", "?")
        phase = current.get("phase", "?")
        key = current.get("id", "?")
        print(f"In-progress work item (will be RE-RUN from scratch):")
        print(f"  {_phase_label(phase)}: {kind} '{key}'")
        print()
    else:
        print("No in-progress work item (the crash happened between work "
              "items, or before any work item started).")
        print()

    # the resume plan.
    print("Resume plan:")
    if total_completed > 0:
        print(f"  - {total_completed} completed work item(s) will be SKIPPED.")
    if current:
        print(f"  - 1 in-progress work item will be RE-RUN from scratch.")
    print("  - The phase-boundary checkpoint fires after each phase (a crash "
          "mid-phase loses at most that phase's work).")
    print()
    print("To resume: run `python run_session.py` (the default --revisit mode "
          "resumes from the checkpoint, skipping completed work items).")


if __name__ == "__main__":
    main()
