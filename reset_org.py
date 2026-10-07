"""Reset the organization — wipe the generated state so the next run starts
from a clean slate.

Deletes (recursively, relative to the project root):
- ``departments/`` — every department / team directory (the org structure).
- ``state/`` — the saved org chart + each role's memory.
- ``MISSION.md`` — the current mission.
- ``history/*.jsonl`` — the audit trails (org events, mission edits, intake,
  cycles, ...). The ``history/`` directory itself is kept.
- ``pods/`` — pod artifacts + transcripts (the Phase 4 deliberation records).
- ``reports/`` — the evaluation reports.
- ``archives/`` — the archived sessions (beyond the rolling window).

Without ``--yes`` the script only prints what it would delete (a dry run).
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil

# The generated artifacts to wipe (relative to the project root).
DEPARTMENTS_DIR = "departments"
STATE_DIR = "state"
MISSION_FILE = "MISSION.md"
HISTORY_GLOB = "history/*.jsonl"
PODS_DIR = "pods"
REPORTS_DIR = "reports"
ARCHIVES_DIR = "archives"


def _collect_targets() -> list:
    """Return the list of paths that would be deleted."""
    targets = []
    for d in (DEPARTMENTS_DIR, STATE_DIR, PODS_DIR, REPORTS_DIR, ARCHIVES_DIR):
        if os.path.isdir(d):
            targets.append(d)
    if os.path.exists(MISSION_FILE):
        targets.append(MISSION_FILE)
    targets.extend(sorted(glob.glob(HISTORY_GLOB)))
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset the organization (wipe generated state).")
    parser.add_argument(
        "--yes", action="store_true",
        help="actually delete (default: dry run — print what would be deleted).")
    args = parser.parse_args()

    targets = _collect_targets()
    if not targets:
        print("Nothing to reset — no generated state found.")
        return

    if not args.yes:
        print("Dry run — the following would be deleted (pass --yes to delete):")
        for t in targets:
            print(f"  {t}")
        return

    for t in targets:
        if os.path.isdir(t):
            shutil.rmtree(t)
        elif os.path.exists(t):
            os.remove(t)
        print(f"deleted: {t}")
    print("Organization reset complete.")


if __name__ == "__main__":
    main()
