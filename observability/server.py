"""The observability dashboard — the HTTP server.

A small HTTP server renders a localhost dashboard with live charts: the
``_Handler`` serves the static web assets (``web/``), a one-shot JSON state
endpoint (``/api/state``), and a Server-Sent-Events stream (``/api/stream``)
that pushes the ``Watcher``'s snapshot every ``POLL_INTERVAL`` seconds.
``make_server`` binds a handler to a watcher; ``_watch_loop`` is the
watcher-thread body (poll the logs forever — the dashboard must never break).

**Decomposition (Phase 6):** extracted from ``observability/dashboard.py``
(the thin ``main()`` entry point + facade stay there; the log watcher moved
to ``observability/watcher.py``).
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")

POLL_INTERVAL = 1.0


# --- HTTP server -------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    watcher: Optional["object"] = None  # bound by make_server()

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path: str, ctype: str) -> None:
        try:
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
        except OSError:
            self._send(404, b"not found", "text/plain")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                data = json.dumps(self.watcher.snapshot())
                self.wfile.write(f"data: {data}\n\n".encode())
                self.wfile.flush()
                time.sleep(POLL_INTERVAL)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # the client went away

    def do_GET(self):  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._serve_file(
                os.path.join(WEB_DIR, "index.html"),
                "text/html; charset=utf-8")
        elif path.startswith("/web/"):
            name = os.path.basename(path)
            ctype = ("application/javascript"
                     if name.endswith(".js") else "text/css")
            self._serve_file(os.path.join(WEB_DIR, name), ctype)
        elif path == "/api/state":
            self._send(200, json.dumps(self.watcher.snapshot()).encode(),
                       "application/json")
        elif path == "/api/stream":
            self._stream()
        else:
            self._send(404, b"not found", "text/plain")


def make_server(watcher: "object", host: str, port: int) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (_Handler,), {"watcher": watcher})
    return ThreadingHTTPServer((host, port), handler)


# --- entry point -------------------------------------------------------------

def _watch_loop(watcher: "object") -> None:
    while True:
        time.sleep(POLL_INTERVAL)
        try:
            watcher.poll()
        except Exception:
            pass  # the dashboard must never break; keep polling


__all__ = ["HERE", "WEB_DIR", "POLL_INTERVAL", "make_server", "_watch_loop"]
