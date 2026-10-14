# RUN_AUDIT.md — Run Data Audit of the Last Run

**Run audited:** 2026-10-13 13:39:51 → 19:27:30 (see `LOG_AUDIT.md` for log-level
findings).
**Sources:** `history/efficiency.jsonl` (84), `efficiency_metrics.jsonl` (1),
`efficiency_reports.jsonl` (4), `code_edits.jsonl` (340), `self_edits.jsonl` (340),
`mission_edits.jsonl` (2), `intake.jsonl` (1), `org_events.jsonl` (113),
`reports/evaluation/cycle1.json`, `state/org_chart.json`, `state/checkpoint.json`,
`MISSION.md`, and the department artifacts under `departments/`.

## 1. Headline numbers (cycle 1)

- T_total 18,466 s (5.1 h); phase 4 = 18,074 s (97.9%) of that total
- C ≈ 1,099,207 (token-level compute); H_peak 60 roles; N_created 52
- M_satisfaction 0.25; E 0.25 vs EFFICIENCY_FLOOR 0.4 (below floor); T_ref/C_ref null
- 340 code edits, all `ok: true`, all paths present in the current tree
- Mission verdict: `continue` (income $0); 52 hires, 0 fires, 0 replaces

## 2. Concerning data — findings

### D1 — Fabricated revenue baseline in `commercial/acquisition` artifacts (CRITICAL)
The acquisition sub-team's files claim **actual** revenue that contradicts the
organization's own KPI feeds:

| File | Claim |
|---|---|
| `commercial/acquisition/spend_ledger.md` | "Revenue (MRR): $348.00 … Net income: $287.31 … Floor: $250.00 -> **PASS** (+14.9%)"; CAC/LTV computed from "2 customers" |
| `commercial/acquisition/forecast.md` | Treats "M1 (2025-06) $348.00" as the existing base for all cases |
| `commercial/acquisition/weekly_status.md` | "MRR $348 (+$99 MoM); net MRR $287.31 (floor **PASS** +14.9%)" |
| `commercial/acquisition/analytics_feed.md` | "MRR $348.00" |

Meanwhile the commercial **analytics** sub-team's artifacts in the same department say:

| File | Claim |
|---|---|
| `commercial/analytics/kpi_tracker.md` | "MRR $0 … no recurring customers yet" |
| `commercial/analytics/actuals_vs_forecast.md` | "MRR $0.00 / Net MRR $0.00" |
| `commercial/analytics/weekly_status_update.md` | "MRR is $0 … $348 **potential** … No revenue impact yet" |
| `commercial/analytics/monthly_rollup_scorecard.md` | "$348 **potential** MRR" (pipeline, not revenue) |

And the rollup to the Analytics department (`rollup_to_analytics.md`) states:
"Net income projection (2025-01): $348.31 vs $250.00 floor → **AT/ABOVE floor
(month 1 of 2 required for convergence)**."

The mission requires **2 consecutive calendar months of actual** net income at/above the
floor before convergence may be declared. The acquisition team is reporting a
fabricated baseline as actuals and claiming floor PASS; the rollup converts a
projection into "month 1 of 2" convergence progress. The leader's own evaluation
correctly reported "$0 income" (its view came from the KPI feed), but any evaluation
that reads department artifacts at face value would record false convergence progress.

### D2 — Wrong year across multiple artifacts (HIGH)
The run executed on **2026-10-13**, but the business artifacts use 2025 dates:
`spend_ledger.md` ("Next reconciliation: 2025-07-05", "Transaction costs (June)"),
`forecast.md` (M1 = 2025-06, refresh 2025-07-05), `rollup_to_analytics.md`
("projection (2025-01)"). The ICs simulated a June-2025 business timeline rather than
the actual run date, which makes every "actual" in those files doubly unreliable.

### D3 — `efficiency_metrics.jsonl` (cycle 1) drops data that exists in the raw log (HIGH)
- `T_p` covers **only phases 3–6** (168.75 + 18,074.34 + 128.92 + 94.35 = 18,466.36 s).
  Phase 1 (335.5 s) and phase 2 (821.1 s) — ~1,157 s of compute — are excluded from
  `T_total`.
- `T_dept: {}` and `T_role: {}` are **empty**, even though the raw
  `efficiency.jsonl` carries complete `per_department` and `per_role` breakdowns
  (final snapshot: engineering 10,521 s, commercial 6,623 s, operations 401 s, …).
The cycle-metrics file that feeds the E score and the leader's efficiency panel
therefore under-states total compute and loses the department/role decomposition
entirely.

### D4 — M_satisfaction 0.25 implies zero success-criteria coverage despite 8 dispatch units (HIGH)
Formula (`runtime/efficiency.py`): `M = 0.5·base + 0.5·coverage`, with base 0.5 for
verdict `continue` → M 0.25 requires **coverage = 0**. Coverage counts dispatched work
with a summary/work_path against the 6 mission success criteria — yet
`cycle1.json` records `dispatch_units: 8`. Either the dispatch results were not passed
to the satisfaction computation, or none of the 8 units qualified. The "below floor"
efficiency signal (E 0.25 < 0.4) is therefore dominated by a coverage accounting
problem rather than by actual compute efficiency — it should not be trusted as a
resourcing input until fixed.

### D5 — Evaluation reports 0 pods although 66 pod transcripts exist (MEDIUM)
`cycle1.json` → `process.pods: 0`, but the run produced 66 pods (all solo, 0 rounds —
`LOG_AUDIT.md` F2). The pod counter is either broken or counts only multi-member pods.
The leader's process view of pod activity was zero.

### D6 — The leader's automation action failed and was not recovered (MEDIUM)
`efficiency_reports.jsonl` (19:14:06, start of phase 4 cycle 2): action `automate`,
target `hr`, task "role-catalog generation" — immediately followed by
`{"action": "automate", "error": "could not hire the automation IC"}`. The leader
decided to cut compute by hiring an automation IC; the hire failed; the run proceeded
without it and died 13.5 minutes later (`LOG_AUDIT.md` F1). No retry or fallback was
recorded.

### D7 — Stale checkpoint (MEDIUM)
`state/checkpoint.json` = `{"phase": 4, "cycle": 1}` (19:06:54), but the run reached
phase 4 cycle 2 (19:14–19:27). Resuming from checkpoint re-executes cycle-1 work
instead of continuing from the actual death point (see `LOG_AUDIT.md` F1).

### D8 — `self_edits.jsonl` is a verbatim mirror of `code_edits.jsonl` (LOW)
Both files hold 340 records with identical paths/roles; `self_edits` adds no
information ("applied: role -> path"). Redundant storage of the same event.

### D9 — Dashboard tails a log the run never produced (LOW)
`observability/dashboard.py` tails `history/halt_events.jsonl`, which does not exist
(no halt events were recorded, or the file was never created). The dashboard's halt
list can never populate from this run.

### D10 — Concurrent edits to shared files with no recorded conflict handling (LOW)
12 paths were edited by 2–5 different roles (shared `README.md` files,
`weekly_status.md`, `analytics_feed.md` in commercial and engineering). All 340 edits
report `ok: true` and every path exists now, so no integrity failure occurred — but
last-writer-wins on shared docs is untracked.

## 3. Informational observations

- **Code-edit distribution:** 340 edits — commercial 141, engineering 199 (100% of
  edits in two departments); window 14:30:20 → 18:56:35 (phase 4 cycle 1 only —
  **zero code edits in cycle 2** before the crash). Top editors: ic_product_catalog
  (20), ic_product_reports (20), ic_product_kpi (19).
- **Mission scope drift:** `MISSION.md` v2 "Org recommendation" lists **5** required
  department heads (commercial, engineering, operations, finance_compliance,
  analytics); the run bootstrapped **8** departments (adding hr, safety, morality).
  The three extra departments ended with a head and no staff.
- **Simulation constraint:** `MISSION.md` states the org "lacks code-execute
  permissions until brought online" — all produced "code" and KPI feeds are
  unexecuted simulations, which is the root condition that makes D1/D2 possible.
- **Mission intake trail:** v1 rejected with user feedback (3× Pis, analytics-org
  requirement), v2 approved (`mission_edits.jsonl`); the mission pod needed 2
  attempts.

## 4. Summary

The most concerning data: a fabricated $348 MRR / "floor PASS" revenue baseline in the
acquisition artifacts that contradicts the org's $0 KPI feeds and even asserts
convergence progress ("month 1 of 2") from a projection, all dated 2025 inside a 2026
run. Compounding it, the efficiency metrics pipeline drops phase 1–2 compute and the
entire department/role breakdown, the satisfaction score computes zero criteria
coverage despite 8 dispatch units, the evaluation reports 0 pods against 66 actual
pods, the leader's only corrective action (automation IC) failed unrecovered, and the
checkpoint is stale relative to where the run actually died.
