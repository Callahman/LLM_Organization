# Observability Build Checklist

Goal: the **"best" version** — a real-time analytics + conversation-monitor
dashboard for the Organization, as a localhost web page.

## Recommended architecture

- **Data hooks** in the existing runtime → new append-only JSONL logs in
  `history/` (the dashboard tails these; the pipeline is untouched otherwise).
- **`observability/` is operator-owned**: locked in `runtime/permissions.py`
  so no agent can ever write into it (explicit invariant + tests), created
  only *after* the lock exists.
- **Zero new dependencies**: the dashboard is stdlib Python
  (`http.server` + Server-Sent Events) with a **self-contained frontend**
  (hand-rolled canvas charts, no CDN) so it works on an air-gapped box.
- **Read-only by construction**: the dashboard only reads the org's state;
  it launches standalone or as a third window in `run_org.bat`.

## Phase 1 — Data hooks ✅

- [x] **1.1** Timestamps on org events — `OrgState.log_event` adds `ts`
      (`runtime/org.py`); `department` added to the event detail of
      `bootstrapped` / `hired` / `fired` (`required_department_bootstrapped`
      already had it) so headcount can be segmented by department.
- [x] **1.2** Code-edit log — `HistoryStore.log_code_edit`
      (`history/code_edits.jsonl`: ts, role, path, ok, error); dispatch
      captures `apply_code_edits` results and logs each one (both call
      sites in `runtime/dispatch.py`).
- [x] **1.3** Tool-call stats — `OpenAIBackend.on_call` callback reports
      each call's `{ts, role, mode, outcome, error, latency}` (outcome:
      `tool_call` / `content_fallback` / `error`); `HistoryStore.log_tool_call`
      (`history/tool_calls.jsonl`); `Session.__init__` wires the callback
      when the backend supports it.
- [x] **1.4** Cycle timing — `HistoryStore.log_cycle`
      (`history/cycles.jsonl`: phase, cycle, started, duration); a
      `Session._phase` helper wraps every phase call in `run` and
      `run_cycle`.
- [x] **1.5** Live pod transcripts — `run_pod` gains an optional
      `transcripts_dir` and calls `write_transcripts` after the agenda and
      after each deliberation round, so the transcript file grows live
      (dispatch passes its `transcripts_dir` at both call sites).
- [x] **1.6** Tests for the hooks — `tests/test_observability_hooks.py`
      (HistoryStore log methods; `OpenAIBackend` outcome reporting via
      `on_call`, using the existing fake-`httpx` pattern; org-event
      timestamp + department).

## Phase 2 — Agent-immutable `observability/` ✅

- [x] **2.1** Explicit directory lock in `runtime/permissions.py`
      `can_edit`: any path under `observability/` is refused for every role
      (the fall-through already refused it; this makes it an explicit,
      documented invariant that survives future TOOLING/scoping changes).
- [x] **2.2** Tests — `tests/test_permissions.py`: `can_edit`/`write_file`
      refused for leader, department head, and IC (no temp dirs needed —
      the refusal happens before any write).
- [x] **2.3** Created `observability/` (after the lock) — `.gitkeep` with a
      note that the directory is operator-owned.

## Phase 3 — Dashboard ✅

- [x] **3.1** `observability/dashboard.py` — `Watcher`: tails
      `org_events.jsonl`, `code_edits.jsonl`, `tool_calls.jsonl`,
      `cycles.jsonl` (byte offsets) + re-reads `pods/transcripts/*.jsonl`
      on change; maintains in-memory state (headcount by department,
      edit/call/cycle records, pod status active|closed); `snapshot()` for
      the server. A daemon thread polls every 1s.
- [x] **3.2** HTTP server (stdlib `ThreadingHTTPServer`): `GET /`
      (index.html), `GET /web/*` (static), `GET /api/state` (JSON
      snapshot), `GET /api/stream` (SSE, 1s pushes).
- [x] **3.3** Frontend — `observability/web/index.html` + `app.js`
      (hand-rolled canvas renderers: stacked-area for agents-by-department
      and tool-calls-by-outcome, overlaid lines for code edits, bars for
      cycle duration per iteration; SSE client; live active-pod pane; last-N
      historical pods with expandable transcripts) + `style.css` (dark
      theme).
- [x] **3.4** Tests — `tests/test_dashboard.py`: Watcher ingestion +
      snapshot (pure, no files), file polling (temp dir), pod
      active-vs-closed, HTTP `/api/state` + `/` + `/api/stream` on an
      ephemeral port.
- [x] **3.5** `run_org.bat` — third window: start the dashboard
      (`python observability\dashboard.py --port 8090`) after the model is
      ready, before the pipeline.
- [x] **3.6** Static review pass — since nothing is executed in the build
      environment, every touched file was re-read line by line (session.py
      wraps, llm_api.py parse/invoke/report, dispatch.py both edit blocks,
      pods.py run_pod, org.py/history.py/permissions.py, dashboard.py,
      app.js in full, Role/OrgState signatures used by the tests). Two real
      bugs were caught and fixed this way: a missing `Optional` import in
      `pods.py` and a stale `can_edit` docstring.

## Verification — **not run, by operator instruction**

Per the operator: verification steps 1–3 (test runs, full suite, live
end-to-end) are **not** to be executed. The build stops at a reviewed,
unexecuted state. For the record, the commands that would run them:

- **V1** New/changed test files:
  ```
  cd /d D:\LLM\LLM_Organization
  python -m pytest tests\test_llm_api.py tests\test_observability_hooks.py tests\test_dashboard.py tests\test_permissions.py -q
  ```
- **V2** Full suite: `python -m pytest tests -q` (temp-dir tests included).
- **V3** Live end-to-end: `run_org.bat` → dashboard at
  `http://127.0.0.1:8090` shows agents, edits, tool calls, cycles, and the
  active pod in real time. Or standalone:
  `python observability\dashboard.py` (port 8090, clear of the model on
  5001 and the harness on 3080).

## Notes / caveats

- **Granularity**: 1s polling + 1s SSE push — fine for this scale.
- **Multi-run history**: the watcher tails the live `history/` files;
  rotated logs (`*.N.jsonl`) are not re-tailed (the audit path still
  resolves; the dashboard shows the current run).
- **Pod topic**: the transcript JSONL has no topic field, so pod panes are
  labeled by pod id (the `.md` transcripts keep the topic for humans).
- **Code-edit metric**: counts applied vs refused edits over time
  (per-edit line deltas were not captured — the results carry path/ok only).
- **Air-gap safe**: no CDN, no new pip packages; Chart.js-style rendering
  is ~250 lines of hand-rolled canvas code.
