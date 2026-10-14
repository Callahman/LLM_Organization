# DEPARTMENT_AUDIT.md — Department Code Audit of the Last Run

**Run audited:** 2026-10-13 13:39:51 → 19:27:30.
**Scope:** everything under `departments/` (317 files), plus `tests/` for coverage
mapping. Companion findings: `LOG_AUDIT.md` (logs), `RUN_AUDIT.md` (run data).

## 1. Volume

| Department | Files | Python LOC | Markdown LOC | YAML/JSON LOC | Total LOC | Share |
|---|---|---|---|---|---|---|
| engineering | 186 | 3,501 | 1,406 | 795 | 7,078 | 57.8% |
| commercial | 125 | 1,027 | 3,370 | 229 | 4,638 | 37.8% |
| morality | 1 | 0 | 124 | 0 | 124 | 1.0% |
| operations | 1 | 0 | 111 | 0 | 111 | 0.9% |
| finance_compliance | 1 | 0 | 97 | 0 | 97 | 0.8% |
| analytics | 1 | 0 | 86 | 0 | 86 | 0.7% |
| hr | 1 | 0 | 62 | 0 | 62 | 0.5% |
| safety | 1 | 0 | 56 | 0 | 56 | 0.5% |
| **Total** | **317** | **4,528** | **5,312** | **1,024** | **12,252** | 100% |

Sub-teams: engineering — pipelines (55 files, 960 py), platform (37, 599 py),
product (93, 1,942 py). commercial — acquisition (24, **0 py**), analytics (23,
327 py), billing (22, 345 py), offers (21, **0 py**), retention (34, 355 py).

**Assessment:** 6 of 8 departments are single-file POLICY stubs (542 LOC, 4.4% of
all output). ~88% of everything the org produced sits in two departments, and
**Markdown (5,312 LOC) outweighs Python (4,528 LOC)** — the run's "work" is
predominantly documentation, playbooks, and KPI prose, with a thin code layer
underneath.

## 2. Quality pass (engineering + commercial)

### 2.1 What is genuinely well-built
- **`engineering/pipelines/fetcher/`** — a coherent, internally consistent package:
  `ethics.py` (frozen onboarding checklist, `EthicsGate` with source/URL/response
  checks, CAPTCHA/paywall marker detection, hard stops), `robots.py`,
  `rate_limiter.py` (per-source caps + crawl-delay), `retry.py` (backoff policy,
  Retry-After parsing), `metrics.py` (feed emission), `compute.py` (1080-only
  scheduled jobs, 4090 default-deny with head-approved tickets), `fetcher.py`
  (composition of all of the above). No TODO/FIXME, no bare excepts anywhere in the
  65 department Python files.
- **`engineering/product/api/server.py`** (275 LOC) — a real Flask app factory:
  hashed API keys (SHA-256, shown once), key issue/revoke with ownership checks,
  per-plan sliding-window rate limits, monthly quotas, atomic state saves
  (tmp + `os.replace`), full request logging to the analytics feed, structured
  error responses with hints.
- **`commercial/billing/src/billing_engine.py`** — Decimal-based tiered pricing,
  overage metering with per-tier caps, invoice SLA check, KPI snapshot, analytics
  feed export.
- **`commercial/analytics/pipeline/compute_kpis.py`** — a complete, input-driven KPI
  function (MRR, net MRR, churn, NRR, CAC, LTV, trial conversion, outbound reply
  rate, pipeline value, gross margin, feed delivery success, compliance).
- In-department tests are substantive where they exist (fake-HTTP fetcher tests
  covering success/robots/login-wall/compute-rules; API tests; catalog
  search/render/lineage tests; analytics-engine ingest/kpi/forecast tests).

### 2.2 What is simulated, placeholder, or unexecuted
- **Nothing has ever run.** The mission itself states the org "lacks code-execute
  permissions until brought online." Consequences observed on disk:
  - no `var/` state directories anywhere (the API server's state/request-log
    directory was never created);
  - `commercial/analytics/output/` contains only a README — **no `raw.json` input
    and no `feed.json` output**; the KPI pipeline was never executed and has no
    input data;
  - the KPI "feeds" that roles report are **hand-written Markdown documents**, not
    pipeline outputs (this is the condition that allowed the fabricated revenue in
    `RUN_AUDIT.md` D1).
- **`billing_engine.attempt_payment` simulates payments** with
  `random.random() < 0.97` — payment success is a hardcoded probability, not a
  payment integration.
- **Placeholder data everywhere:** the product API ships 3 static sample datasets
  of 4–5 rows each (honestly labeled "static fixtures"); `sources.yaml` defines
  two **example** sources (`api.example.com`, `blog.example.com`); `datasets.py`
  carries 2025-01-15 "onboarded" dates inside a 2026 run.
- **Business timeline is 2025, not 2026:** 62 hardcoded 2025 dates in Python (mostly
  test fixtures) and 2025 dates throughout the commercial Markdown (see
  `RUN_AUDIT.md` D2).
- Minor code issues: `datetime.utcnow` (deprecated in 3.12) in billing; an
  `assert` used as the invoice-SLA check (stripped under `python -O`);
  `overage_mrr` conflates one-time overage with MRR; 48 `print()` statements in
  CLI-style modules (acceptable for scripts, not for the billing engine).

## 3. Classification

| Class | Items |
|---|---|
| **Production-ready** | **None.** No code has been executed, so nothing is verified. The best code (fetcher package, product API, billing engine) is plausibly runnable but unproven, and its data inputs are placeholders. |
| **Partial** (functional design + structure, unverified, placeholder data) | engineering: fetcher package, product API server, catalog (models/search/render/lineage), analytics engine (ingest/kpi/forecast/exporter), scheduled reports (309 LOC), kpi_feed/feed_health; commercial: billing engine + dunning + transaction-cost tracker, KPI compute pipeline, retention (health scores, expansion model, feed generator) |
| **Stub** | 6 departments (analytics, finance_compliance, hr, morality, operations, safety — POLICY.md only); commercial/offers (pricing/playbook docs, 0 code); commercial/acquisition (playbooks + **fabricated revenue artifacts**, 0 code) |

Note the mission's "dedicated Analytics org" requirement is satisfied by a single
86-line POLICY file — the Analytics department has no feed infrastructure of its
own; it consumes what other departments' Markdown claims.

## 4. Test coverage

- **Root `tests/`** (23 files, 5,212 LOC): tests the **runtime only** (dispatch,
  envelope, efficiency, mission, org, pods, session, tiers, dashboard, llm_api,
  …). Zero coverage of department code.
- **In-department tests (16 files):**
  - engineering/pipelines: `tests/test_fetcher.py` (substantive)
  - engineering/platform: 5 test files (ingest, kpi, forecast, pipeline-integration, + conftest)
  - engineering/product: 9 test files (models, search, render, lineage, kpi_feed, feed_health, forecast, api, scheduled_reports)
  - commercial/analytics: 1 test file (`test_kpis.py`)
- **No tests at all:** commercial/billing (billing_engine, dunning,
  transaction_cost_tracker), commercial/retention (generate_feed, expansion_model,
  compute_health_scores), commercial/acquisition & offers (no code), and the
  pipeline scripts (collect_pipeline_kpis, forecast_net_income, analytics_feed).
- Coverage is therefore **engineering-heavy and commercial-thin** — the inverse of
  where the data-integrity risk actually is (the commercial Markdown artifacts).

## 5. Summary

The department output is a documentation-heavy, code-thin simulation: 12,252 LOC
total, 88% in two departments, Markdown exceeding Python. The engineering code is
the strongest part — clean, internally consistent, ethics-gated, and reasonably
tested — but **nothing has been executed** (no code-execute permission, no state,
no pipeline inputs/outputs), so nothing is production-ready. The commercial layer is
mostly prose, its only real code is a simulated billing engine, its KPI feeds are
hand-written Markdown rather than pipeline output, and its acquisition artifacts
contain the fabricated $348 MRR / "floor PASS" revenue baseline (see `RUN_AUDIT.md`
D1/D2). Test coverage is concentrated in engineering, exactly where the risk is
lowest, and absent in commercial billing/retention, where the numbers that reach
the leader are produced.
