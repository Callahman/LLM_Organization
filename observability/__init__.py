"""observability — the operator-owned, read-only real-time dashboard.

The Organization's state (``history/*.jsonl``, ``state/``,
``pods/transcripts/``) is tailed and rendered as a local web UI. This package
is **agent-write-locked** (``observability/`` is locked in
``runtime/permissions.py``) — the pipeline never writes to it.

Modules:
- `dashboard` — the thin **entry point**: ``main()`` wires the log watcher +
  the HTTP server and serves the UI (``python observability/dashboard.py``).
  It re-exports the full public API (a facade).
- `watcher`   — the ``Watcher``: tails the org's JSONL logs + pod transcripts
  and maintains in-memory state (``poll()`` on the watcher thread;
  ``snapshot()`` read by the server).
- `server`    — the HTTP server: the ``_Handler`` (static web assets,
  ``/api/state``, the ``/api/stream`` SSE), ``make_server`` (binds a handler
  to a watcher), and ``_watch_loop`` (the watcher-thread body).

Where to find what (the dashboard decomposition):
- "How do I start the dashboard?" -> ``dashboard.main`` (run
  ``observability/dashboard.py``).
- "Where is the log-tailing / in-memory state?" -> ``watcher.Watcher``.
- "Where is the HTTP handler / the SSE stream / the server factory?" ->
  ``server._Handler`` / ``server.make_server`` / ``server._watch_loop``.
"""
