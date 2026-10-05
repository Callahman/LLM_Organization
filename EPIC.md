# EPIC — Observability Dashboard (+ repo hygiene)

> Trackable plan: **EPIC → Stories → Tasks**. Iterate over multiple branches
> (one branch per Story, suggested names below). Status is tracked by checking
> off Tasks within each Story.

---

## Global rules (apply to every Story)

- **RULE — Testing is the user's job.** All testing is performed **by the
  user** and must be **ignored during coding**. The **user is the only one
  with permission to run `pytest -v`**. Do **not** run tests, do **not**
  attempt to execute pytest, and do **not** block on test results during any
  coding task. Tasks tagged `[test]` mean *write* the test coverage as part of
  the Story; **executing and verifying** it is the user's responsibility.
- **RULE — No new dependencies.** Dashboard stays stdlib-only (plus the
  existing `httpx` for the api backend).
- **Branch strategy:** one branch per Story (names suggested per Story).
  Track A (dashboard) is the main work; Track C (hygiene) and Track D
  (codebase health) can be folded in anytime.

---

## Scope decision (updated)

- **The deploy model / `TARGET_DIR` is DROPPED for now** — no new target
  directory, no `deploy.py`, no code copy. The org continues to run
  **in-repo** (existing/legacy behavior, unchanged). `TARGET_DIR` has been
  removed from `.env`.
- **Self-edit logic changes are DROPPED for now** — the existing
  permission/self-edit behavior is unchanged.
- This EPIC is therefore: **Track A (dashboard)** + **Track C (repo
  hygiene)** + **Track D (codebase health)**. The dropped items are parked at
  the bottom for possible later revisit.

---

## Decisions recorded

| # | Decision |
|---|----------|
| A6 | Health modules = **staleness gauge + error mix + halt pane** (only these three). |
| A3 | **No** "reads over time" chart for now. |
| A2 | **No** JS test harness needed. |
| Scope | **Deploy model / `TARGET_DIR` dropped for now; self-edit logic changes dropped for now.** Org runs in-repo (legacy). `TARGET_DIR` removed from `.env`. |

---

## EPIC overview

- **Track A — Dashboard** (the main work): enrich the observability logs, then
  fix/rework the six charts + pod panes + model stream, and add three health
  modules.
- **Track C — Hygiene** (small): stop test state leaking into the repo;
  one-time cleanup of existing test junk.
- **Track D — Codebase health** (bug fixes + refactors): wire the dead `.env`
  config knobs, fix the complexity-routing phase loss, and harden onboarding
  (`.env.example`, `run_org.bat` venv, `reset_org.py`). Source: the ranked repo
  audit (15 items, preserved as D1–D7).

---

## Track A — Dashboard

### Story A0 — Data enrichment (observability log fields)
- **branch:** `story/a0-data-enrichment`
- **depends on:** —
- **why:** Do this first so every later chart reads clean fields instead of
  pattern-matching strings in the frontend.
- **acceptance:**
  - `tool_calls.jsonl` rows carry `phase`, `department`, and `error_type`.
  - `code_edits.jsonl` rows carry `department`.
  - `invocations.jsonl` rows carry `ts`.
  - The dashboard `Watcher` tails `halt_events.jsonl`.
- **tasks:**
  - [ ] `tool_calls.jsonl`: add `phase` and `department` (resolve role→dept at
        log time, `runtime/llm_api.py` `_report`).
  - [ ] `tool_calls.jsonl`: add `error_type`
        (`timeout|truncation|parse|transport|other`), classified in
        `runtime/llm_api.py` where the diagnosis already exists.
  - [ ] `code_edits.jsonl`: add `department` (from the role's department; path
        fallback `departments/<dept>/…`) at the `dispatch.py` log sites.
  - [ ] `invocations.jsonl`: add `ts` (`runtime/history.py` `log_invocation`).
  - [ ] `Watcher.paths`: add `halt_events` + an `ingest_halt` + snapshot field
        (`observability/dashboard.py`).
  - [ ] `[test]` extend `tests/test_observability_hooks.py` +
        `tests/test_llm_api.py` for the new fields (user executes).

### Story A1 — Fix the pod panes (active pod, historical list, solo lifecycle)
- **branch:** `story/a1-pod-panes`
- **depends on:** A0
- **why:** Active-pod pane is stuck on `solo_leader_p1`; historical list is
  empty.
- **acceptance:**
  - Solo pods reach a terminal (closed) state when their phase completes.
  - Active-pod pane shows the **most recently updated** active pod.
  - Historical list includes solo pods and is populated from pre-existing
    transcripts at startup.
  - Pane labels disambiguate "active pod (transcript)" vs "model stream (last
    model call)".
- **tasks:**
  - [ ] Solo pod lifecycle: emit a terminal `close`-equivalent step when a solo
        phase completes (intake `converged`, mission approved, bootstrap done,
        synthesis/eval done) — `runtime/pods.py` / `runtime/session.py`.
  - [ ] `Watcher`: mark solo pods `closed` on the terminal step
        (`ingest_pod_transcript`).
  - [ ] Frontend: active-pod pane sorts by `updated` desc (not id) —
        `observability/web/app.js` `renderMonitor`.
  - [ ] Frontend: historical list includes solo pods (summary line e.g. "intake
        converged, 2 rounds") — `renderPodList`.
  - [ ] `Watcher.seed_transcripts`: ingest pre-existing transcripts as **closed
        history** (relax the suppress-for-listing behavior; keep it from
        re-showing stale *active* content).
  - [ ] Frontend: disambiguate pane labels.
  - [ ] `[test]` `tests/test_dashboard.py`: solo-closed, most-recent-active,
        seeded-history (user executes).

### Story A2 — Fix the cycle-duration chart
- **branch:** `story/a2-cycle-chart`
- **depends on:** A0
- **why:** Phases 1–3 are the same beige; y-axis labels are cut off; no totals.
- **acceptance:**
  - Distinct color per phase 1–6.
  - Y-axis labels not cut off.
  - Total-duration label atop each bar; per-phase breakdown on hover.
  - One-time "setup" (cycle 0) bar visually separated from iterations.
- **tasks:**
  - [ ] `app.js` `PHASE_COLORS`: define colors for phases 1–6 (drop the `#888`
        fallback).
  - [ ] `app.js` `drawBars`: widen left padding / fix cut-off y labels.
  - [ ] `app.js` `drawBars`: add total-duration label atop each bar.
  - [ ] `app.js` `drawBars`: hover tooltip with per-phase breakdown.
  - [ ] `app.js` `buildCycleGroups`/`drawBars`: visual separation of the
        one-time setup (cycle 0) bar vs iterations.
  - [ ] Manual verification checklist (no JS harness per decision A2).

### Story A3 — Rework the tool-calls chart
- **branch:** `story/a3-tool-calls-chart`
- **depends on:** A0
- **why:** Make failures legible (type + styling) and show who is calling.
- **acceptance:**
  - Outcome segmentation retained; second view/series split by role/department.
  - `error`/`retry` series rendered red with stripes/translucent fill; legend
    shows the `error_type` breakdown.
  - A caption/link points to the code-edits chart for file writes (the model
    has a single `submit_output` tool).
- **tasks:**
  - [ ] `app.js`: keep outcome segmentation; add a series/view split by
        department (stacked, colored by dept).
  - [ ] `app.js`: canvas stripe/translucent fill for `error`/`retry` series
        (red).
  - [ ] `app.js`: legend shows `error_type` breakdown.
  - [ ] `app.js`/`index.html`: caption/link to the code-edits chart ("file
        writes are tracked there; the model has a single `submit_output` tool").
  - [ ] (Deferred, per A3) No "reads over time" chart.

### Story A4 — Rework the code-edits chart
- **branch:** `story/a4-code-edits-chart`
- **depends on:** A0
- **why:** Segment by department (like agents-over-time); clarify applied vs
  refused; include markdown edits.
- **acceptance:**
  - Segmented by department with applied/refused (applied + striped refused).
  - Per-edit detail (path + refusal reason) available on hover/expand.
  - Empty state reads "no edit attempts yet" (a missing file ≠ "all refused").
- **tasks:**
  - [ ] `app.js`: segment by department (use A0's `department` field).
  - [ ] `app.js`: applied + striped-refused rendering per dept.
  - [ ] `app.js`: hover/expandable per-edit list (path + `error` reason).
  - [ ] `app.js`/`index.html`: empty-state text "no edit attempts yet".

### Story A5 — Rework the agents chart
- **branch:** `story/a5-agents-chart`
- **depends on:** A0
- **why:** The chart is flat (cumulative hires); current headcount is in the
  snapshot but never rendered; no activity view.
- **acceptance:**
  - Current headcount per department rendered (from `agents.by_department`).
  - "Model calls per department over time" activity series added.
  - Cumulative hire/fire series retained (or demoted to secondary).
- **tasks:**
  - [ ] `app.js`: render current headcount per department (bars or number
        chips from `agents.by_department` / `agents.total`).
  - [ ] `app.js`: add activity-over-time series (model calls per dept from
        `tool_calls` + A0's `department`).
  - [ ] `app.js`: keep/demote the cumulative hire/fire series.

### Story A6 — New health modules (staleness gauge + error mix + halt pane)
- **branch:** `story/a6-health-modules`
- **depends on:** A0
- **scope (per decision A6):** exactly these three — **staleness gauge**,
  **error mix**, **halt pane**. (Latency, disk sizes, pod throughput are
  out of scope.)
- **acceptance:**
  - Staleness gauge: seconds since the last stream chunk; warns past a
    threshold.
  - Error mix: stacked series of `timeout/truncation/parse/transport/other`
    over time.
  - Halt pane: lists Safety/Morality halt events (from `halt_events.jsonl`).
- **tasks:**
  - [ ] `dashboard.py`: expose "last stream chunk ts" in the snapshot (for the
        staleness gauge).
  - [ ] `app.js`/`index.html`: staleness gauge (seconds since last chunk; warn
        past a configurable threshold).
  - [ ] `app.js`: error-mix stacked series over time (from A0's `error_type`).
  - [ ] `dashboard.py` + `app.js`/`index.html`: halt pane (from A0's
        `halt_events` tail).
  - [ ] `[test]` `tests/test_dashboard.py`: staleness field, halt ingestion
        (user executes).

### Story A7 — Model-stream polish
- **branch:** `story/a7-model-stream`
- **depends on:** A0
- **why:** `[content]` lines are empty/whitespace in tools mode; `tool_call`
  is raw JSON.
- **acceptance:**
  - Whitespace-only `content` lines hidden.
  - `tool_call` rendered as a collapsed (expandable) JSON block.
  - `thinking` unchanged.
- **tasks:**
  - [ ] `app.js` `renderModelStream`: skip whitespace-only `content`.
  - [ ] `app.js`: render `tool_call` as a collapsed/expandable JSON block.

---

## Track C — Hygiene

### Story C1 — Stop test state leaking into the repo
- **branch:** `story/c1-test-leak`
- **depends on:** —
- **acceptance:** No test writes org state (transcripts, history, etc.) into
  the repo; `.gitignore` covers `__pycache__`/`.pytest_cache` **and the
  generated `departments/` tree**.
- **tasks:**
  - [ ] Audit tests for state leaking into the repo (`pods/transcripts/`
        currently holds pytest-generated transcripts referencing
        `pytest-of-…` temp paths); fix the offending test(s) to use temp dirs.
  - [ ] Confirm `.gitignore` covers `__pycache__` and `.pytest_cache`.
  - [ ] Add `departments/` to `.gitignore` (generated department state —
        `<dept>/<DEPT>_POLICY.md` + team dirs — is currently tracked by git).

### Story C2 — One-time cleanup of existing test junk (low priority)
- **branch:** `story/c2-junk-cleanup`
- **depends on:** C1
- **why:** The repo currently holds test-generated junk (pytest transcripts in
  `pods/transcripts/` referencing pytest temp paths).
- **acceptance:** Test-generated junk removed; the **live audit trail**
  (`history/*.jsonl` from real runs) is untouched.
- **tasks:**
  - [ ] Remove test-generated junk from `pods/transcripts/` (files referencing
        `pytest-of-…` temp paths).
  - [ ] Remove stale caches (`__pycache__`, `.pytest_cache`) if present.
  - [ ] Confirm the live audit trail (`history/*.jsonl` from real runs) is **not**
        touched.

---

## Track D — Codebase health

> Source: the ranked repo audit (15 items). The original rank is preserved on
> each task as `#N`. Grouped into stories D1–D7 (D1–D2 are the anchor bug
> fixes; the rest are robustness + polish).

### Story D1 — Centralize config (anchor; fixes #1, #7, #13)
- **branch:** `story/d1-central-config`
- **depends on:** —
- **why:** The `.env` org-tuning knobs are dead (#1) — `run_session.py` only
  puts `timeout_seconds`/`ic_timeout_seconds` in the config dict, so the
  pipeline silently uses hardcoded defaults. Config is also scattered across
  `run_session.py`, `llm_api.py`, and `session.py` defaults.
- **acceptance:**
  - A single `Config` loader reads `.env` with the correct key mapping and
    hands it to `Session`.
  - Setting e.g. `CONFIDENCE_THRESHOLD` in `.env` actually changes behavior.
  - Unknown/unused `.env` keys produce a visible warning.
- **tasks:**
  - [ ] `#1`/`#7` Build a `Config` loader that reads `.env` with the correct
        key mapping (`CONFIDENCE_THRESHOLD`→`confidence_threshold`,
        `QUESTION_BUDGET_ROUNDS`→`question_budget`,
        `MISSION_REASK_BUDGET`→`mission_reask_budget`, `POD_*`→`pod_*`,
        `DIRECT_IC_CAP`→`direct_ic_cap`, `CONTEXT_BUDGET_TOKENS`→
        `context_budget_tokens`, `ROLE_MEMORY_MAX_ENTRIES`→
        `role_memory_max_entries`, `HISTORY_WINDOW_SESSIONS`→
        `history_window_sessions`, `ARCHIVE_CAP_MB`→`archive_cap_mb`).
  - [ ] `#1` Pass the loaded config to `Session` (replace the inline 2-key
        dict in `run_session.py`).
  - [ ] `#13` Add a validation pass that warns on unknown/unused `.env` keys.
  - [ ] `[test]` assert a `.env` knob changes behavior (user executes).

### Story D2 — Fix complexity routing (anchor; fixes #2, #6, #8, #15)
- **branch:** `story/d2-routing`
- **depends on:** —
- **why:** `MemoryBackend` re-wraps the context (`"ROLE:…"`) before
  `RoutingBackend.parse_phase` runs, so the phase marker is gone; non-explicit
  invokes (Phase 2 mission, IC work) route to LOW and log `phase: -1`.
- **acceptance:**
  - The phase (or reasoning) is passed explicitly at each call site.
  - Phase 2 (mission) is granted HIGH.
  - `invocations.jsonl` logs the correct phase (no -1).
- **tasks:**
  - [ ] `#2`/`#8` Pass the phase (or reasoning) explicitly to the backend at
        each call site (compute via `classify_complexity`), instead of relying
        on `parse_phase` of a re-wrapped context.
  - [ ] `#2` Remove the now-dead `parse_phase` (or keep only the explicit case).
  - [ ] `#6` Fix the `phase: -1` in `log_invocation` (the `ts` half is A0).
  - [ ] `#15` `[test]` assert Phase 2 routes to HIGH and invocations log the
        correct phase (user executes).

### Story D3 — Onboarding & robustness (fixes #3, #4, #5)
- **branch:** `story/d3-onboarding`
- **depends on:** —
- **why:** `.env.example` is stale; `run_org.bat` ignores the venv;
  `reset_org.py` is incomplete.
- **acceptance:**
  - `.env.example` matches `.env` (all knobs present, aligned defaults).
  - `run_org.bat` uses the project venv python.
  - `reset_org.py` wipes all generated state (or a `--full` flag).
- **tasks:**
  - [ ] `#3` Sync `.env.example` to `.env` (add `LLM_IDLE_TIMEOUT_SECONDS`,
        `LLM_MAX_RETRIES`; align `LLM_MAX_TOKENS`, `CONFIDENCE_THRESHOLD`).
  - [ ] `#4` Make `run_org.bat` use the project venv python (activate or
        `.venv\Scripts\python`).
  - [ ] `#5` Make `reset_org.py` complete (add `pods/`, `reports/`,
        `archives/` — or a `--full` flag).

### Story D4 — Observability data polish (fixes #11, #12; A0-adjacent)
- **branch:** `story/d4-obs-polish`
- **depends on:** A0
- **why:** A non-fatal warning is logged in the `error` field; retry latency
  is cumulative (misleading).
- **acceptance:**
  - The nested-type warning is logged as a separate `warning` field.
  - Retry reports show per-attempt latency (not cumulative + backoff).
- **tasks:**
  - [ ] `#11` Log the nested-type warning as a separate `warning` field (not
        `error`).
  - [ ] `#12` Report per-attempt latency (not cumulative across retries +
        backoff sleeps).

### Story D5 — Backend-wrapping factory (fixes #9)
- **branch:** `story/d5-backend-factory`
- **depends on:** —
- **why:** The `MemoryBackend(RoutingBackend(TimeoutBackend(…)))` chain +
  `on_call`/`on_stream` wiring is implicit in `Session.__init__`.
- **acceptance:** A `build_backend()` factory makes the chain explicit and
  testable.
- **tasks:**
  - [ ] `#9` Extract a `build_backend()` factory for the backend chain +
        `on_call`/`on_stream` wiring.

### Story D6 — Tuning knobs (fixes #10)
- **branch:** `story/d6-knobs`
- **depends on:** D1
- **why:** `max_iterations=2` is hardcoded in `run_session.py`.
- **acceptance:** The Phase 4/5 iteration cap is tunable via config.
- **tasks:**
  - [ ] `#10` Add a config knob for `max_iterations` (currently hardcoded 2).

### Story D7 — `--dry-run` for the pipeline (fixes #14)
- **branch:** `story/d7-dry-run`
- **depends on:** —
- **why:** See what a run would do without mutating state.
- **acceptance:** `--dry-run` previews hires/mission draft without writing.
- **tasks:**
  - [ ] `#14` Add a `--dry-run` for the pipeline (preview without writing).

---

## Suggested execution order

1. **A0** (enables all dashboard charts)
2. **A1 → A2 → A3 → A4 → A5** (quick wins, watchable on the next run)
3. **A6, A7** (in parallel with Track C)
4. **C1 → C2** (anytime)
5. **D1 → D2** (the two anchor bug fixes — D1 un-deadens your `.env`)
6. **D3 → D4 → D5 → D6 → D7** (robustness + polish)

---

## Parked (dropped for now — may revisit later)

- **Deploy model / `TARGET_DIR`:** repo-as-immutable-source, org runs from a
  target dir, `deploy.py`, code copy. (Dropped per operator; `TARGET_DIR`
  removed from `.env`.)
- **Self-edit rework:** scope self-edit to the org + a dual-approval gate
  (HR + Self-editor / HR + Leader when HR edits self). (Dropped per operator.)
