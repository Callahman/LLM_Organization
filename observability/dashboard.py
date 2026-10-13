"""Operator-owned real-time observability dashboard for the Organization.

Zero new dependencies (stdlib only) and fully self-contained (no CDN): a
watcher thread tails the organization's append-only JSONL logs (and the pod
transcript files) and maintains in-memory state; a small HTTP server renders
a localhost dashboard with live charts —

- **agents over time** (segmented by department),
- **code edits over time** (applied vs refused),
- **tool calls over time** (by outcome: tool_call / content_fallback / error),
- **cycle duration per iteration** (phase 4/5/6 durations),

plus a real-time **conversation monitor** (the active pod's transcript live,
last-N historical pods expandable). Historical pods only populate as pods are
spun up (transcript files created or rewritten after the dashboard starts);
prior runs' transcript files are seeded (suppressed) at startup.

The dashboard only READS the organization's state; agents can never write
here (``observability/`` is locked in ``runtime/permissions.py``).

**Decomposition (Phase 6):** this file is the thin entry point — ``main()``
wires the log watcher + the HTTP server. The ``Watcher`` moved to
``observability/watcher.py``; the HTTP server (``_Handler`` / ``make_server``
/ ``_watch_loop``) moved to ``observability/server.py``. This file re-exports
the full public API (backward-compatible facade).

Run:
    python observability/dashboard.py [--port 8090] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

# When run directly (``python observability/dashboard.py``), Python puts this
# file's directory on ``sys.path`` — not the project root — so ``import
# observability`` would fail. Add the root (the parent of ``observability/``)
# so the package imports below resolve; it's already on the path when this
# module is imported as ``observability.dashboard``.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from observability.watcher import (
    HIRE_KINDS,
    FIRE_KINDS,
    SNAPSHOT_CAP,
    Watcher,
)
from observability.server import (
    HERE,
    WEB_DIR,
    POLL_INTERVAL,
    make_server,
    _watch_loop,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Real-time observability dashboard (read-only).")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--root", default=os.path.dirname(HERE),
                    help="the Organization root (default: the repo root)")
    args = ap.parse_args()

    watcher = Watcher(args.root)
    # 'Historical pods' only populates as pods are spun up: seed the existing
    # transcript files' sizes (suppressing their prior content) BEFORE the
    # initial load, so only files created/changed after startup are ingested.
    watcher.seed_transcripts()
    watcher.poll()  # initial load (existing history)
    threading.Thread(target=_watch_loop, args=(watcher,), daemon=True).start()
    server = make_server(watcher, args.host, args.port)
    print(f"Observability dashboard: http://{args.host}:{args.port}"
          f"  (root: {args.root})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    # entry point (kept here)
    "main",
    # facade re-exports (moved to focused modules)
    "HIRE_KINDS",
    "FIRE_KINDS",
    "SNAPSHOT_CAP",
    "Watcher",
    "HERE",
    "WEB_DIR",
    "POLL_INTERVAL",
    "make_server",
    "_watch_loop",
]
