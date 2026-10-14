# AUDIT.md — Audit Plan and Findings

**Status:** Plan only. Execution is awaiting user approval. The Findings sections (§6) are
skeletons to be populated as each audit is performed.

## 1. Purpose

Perform a three-part audit of the organization repo and record results in three deliverables:

| Deliverable | Subject |
|---|---|
| `LOG_AUDIT.md` | Strange behavior in the logs from the last run |
| `RUN_AUDIT.md` | Concerning data collected from the last run |
| `DEPARTMENT_AUDIT.md` | Per-department code evaluation: quality, volume, production-ready vs stubs |

All three deliverables are written to the repo root.

## 2. Scope and Repo Layout (recon)

Relevant areas identified during reconnaissance:

- `history/` — last run's logs: active `stream.jsonl` (~1.5 MB) plus rotated
  `stream.1.jsonl`…`stream.18.jsonl` (~5 MB each, ~96 MB total; timestamps 10/13
  2:11 PM → 7:27 PM), and supporting logs: `tool_calls.jsonl`, `invocations.jsonl`,
  `efficiency.jsonl`, `code_edits.jsonl`, `self_edits.jsonl`, `mission_edits.jsonl`,
  `org_events.jsonl`, `cycles.jsonl`, `intake.jsonl`, `efficiency_metrics.jsonl`,
  `efficiency_reports.jsonl`.
- `observability/` — dashboard (`dashboard.py`, `web/app.js`, `web/index.html`, `web/style.css`).
- `departments/` — 8 departments: `analytics`, `commercial` (125 files), `engineering`
  (186 files; sub-teams `pipelines`, `platform`, `product`), `finance_compliance`,
  `hr`, `morality`, `operations`, `safety`. Six of the eight contain a single
  `*_POLICY.md` file only (stubs); `engineering` and `commercial` contain real code.
- `pods/transcripts/` — 132 pod transcript files.
- `roles/` — `base.py`, `leader.py`, `worker.py`.
- `runtime/` — core engine (`dispatch.py` 57 KB, `llm_api.py` 45 KB, `session.py` 35 KB,
  `org.py`, `pods.py`, `efficiency.py`, `guard.py`, `coerce.py`, `permissions.py`, …).
- `state/` — `org_chart.json` (99 KB), `checkpoint.json`.
- `reports/evaluation/cycle1.json` — evaluation output.
- `tests/` — 23 test files.

## 3. Audit A — Log Audit → `LOG_AUDIT.md`

Goal: detail any strange behavior in the last run's logs.

1. **Identify the run.** Confirm the last run's boundaries from `history/cycles.jsonl`
   and stream file timestamps; treat `stream.jsonl` (active) + the most recent rotated
   `stream.N.jsonl` files as the run under audit.
2. **Inventory event types.** Parse `stream.jsonl` in chunks (do not load ~96 MB at
   once); build a count of each event type and note anything unexpected.
3. **Tool-call and invocation health.** Cross-reference `tool_calls.jsonl` and
   `invocations.jsonl`: failures, retries, timeouts, non-zero exits, repeated identical
   failures.
4. **Error/exception sweep.** Scan for exception text, guard trips (`runtime/guard.py`),
   coerced events (`runtime/coerce.py`), permission denials (`runtime/permissions.py`),
   and LLM API errors (`runtime/llm_api.py`).
5. **Pod health.** For `pods/transcripts/` (132 files): pods that opened but never
   closed, empty or malformed transcripts, transcripts with only one participant where
   a multi-role pod was expected.
6. **Org-event consistency.** Compare `org_events.jsonl` (hire/fire/replace sequence)
   against the final `state/org_chart.json` to spot events that don't reconcile.
7. **Classify anomalies.** For each: timestamp, event, surrounding context, severity
   (info / warning / critical), and a hypothesis of cause.
8. **Write `LOG_AUDIT.md`:** summary of the run, anomaly table, and any patterns
   (e.g., recurring failure modes).

## 4. Audit B — Run Data Audit → `RUN_AUDIT.md`

Goal: review the data collected from the last run and indicate anything concerning.

1. **Inventory collected data:** `efficiency.jsonl` (132 KB), `code_edits.jsonl`
   (57 KB), `self_edits.jsonl` (40 KB), `mission_edits.jsonl` (9 KB), `intake.jsonl`,
   `cycles.jsonl`, `efficiency_metrics.jsonl`, `efficiency_reports.jsonl`,
   `reports/evaluation/cycle1.json`.
2. **Code-edit integrity.** Sample N entries from `code_edits.jsonl`; verify each maps
   to a real file change in the current tree (file exists, content matches claim).
3. **Self-edit review.** Inspect `self_edits.jsonl`: did the org modify its own runtime
   code? Flag any self-modification as a concern with specifics.
4. **Metric derivability.** Check that efficiency metrics in
   `efficiency_metrics.jsonl` / `efficiency_reports.jsonl` can actually be derived
   from raw events; flag metrics that don't reconcile with the source data.
5. **Dashboard data path.** Confirm the dashboard consumes the same data the audit
   sees (watcher tails in `dashboard.py`); note any divergence between raw logs and
   what the dashboard would render.
6. **Org-chart vs policy.** Compare `state/org_chart.json` role counts and caps against
   each department's `POLICY.md` headcount claims.
7. **Record hygiene.** Look for missing/duplicate records, timestamp gaps, and
   unreferenced data.
8. **Write `RUN_AUDIT.md`:** summary, concerns table (severity + evidence), and
   recommended follow-ups.

## 5. Audit C — Department Code Audit → `DEPARTMENT_AUDIT.md`

Goal: per-department evaluation of code quality, code volume (less is more), and the
split between production-ready code and stubs.

Context from recon: 6 of 8 departments are single-file POLICY stubs; `engineering`
(186 files) and `commercial` (125 files) hold the actual code.

1. **Per-department inventory:** enumerate files, lines of code by file type, and
   separate code from documentation.
2. **Quality pass:** read the code modules in `engineering` and `commercial`
   (sub-teams: `pipelines`, `platform`, `product`; `acquisition`, `analytics`,
   `billing`, `offers`, `retention`); note glaring concerns — bugs, security issues,
   dead code, TODO/FIXME density, error handling, untested paths.
3. **Volume assessment:** lines per department and per sub-team; flag over-engineering
   or redundant modules (less is more).
4. **Classification:** for each module, classify as **production-ready** (complete,
   working, exercised), **partial** (some functionality, gaps), or **stub**
   (placeholder/empty). Produce a per-department percentage split.
5. **Test coverage:** map `tests/` (23 files) to department code; note untested
   production modules.
6. **Write `DEPARTMENT_AUDIT.md`:** per-department sections (quality, volume,
   production-ready vs stub split, concerns) plus a summary table across all 8
   departments.

## 6. Findings

### 6.1 `LOG_AUDIT.md` findings
*(To be populated during execution.)*

### 6.2 `RUN_AUDIT.md` findings
*(To be populated during execution.)*

### 6.3 `DEPARTMENT_AUDIT.md` findings
*(To be populated during execution.)*

## 7. Execution Notes

- **Order:** A → B → C (log context informs the data audit; the code audit is independent).
- **Read-only:** the audit must not modify the repo except to write the three
  deliverable markdowns.
- **Large files:** stream logs total ~96 MB; always parse in chunks.
- **Stop condition:** after each deliverable is written, report to the user before
  proceeding to the next audit (unless the user says to run all three in sequence).
