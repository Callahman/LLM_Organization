# AUDIT — LLM_Organization

Comprehensive audit of the `D:\LLM\LLM_Organization` repository: the overall
process, every directory, every file, the code, and how everything
interconnects — plus instructions (and the embedded diagram) for creating a
Mermaid diagram of the entire process.

---

## 0. Audit metadata

| Field | Value |
|---|---|
| Repository | `D:\LLM\LLM_Organization` |
| Project | "Organization" — a company of LLM agents running a bounded 6-phase pipeline |
| Language | Python 3.10+ (venv interpreter: CPython 3.11) |
| Dependencies | stdlib-only core; optional `python-dotenv`, `pytest`, `httpx` |
| VCS | Git — remote `origin`; `master` in sync with `origin/master`; story branches `S1`–`S12` + `Track_A_Dashboard`; PRs #4–#13 merged; head commit `3ee30ab "Remove old epic"`; working tree clean |
| Audit date | 2025-11-27 |
| Audit method | Static review (inventory, documentation, code, imports, state files) + operator-verified test run |
| Exclusions | `.venv/` (virtual environment, ~3,000 files), `__pycache__/`, `*.pyc`, `.git/` internals |
| Test status | **All tests pass** (verified by the operator). A sandboxed audit run shows `PermissionError` because pytest temp dirs resolve outside `D:\LLM` — environmental, not a code defect. |
| Status | In progress — details filled in as the audit advances (§9 audit log) |

---

## 1. Audit plan (comprehensive)

### 1.1 Objectives

1. **Understand the overall process** — what the repository does, end to end:
   the 6-phase pipeline, the entry points, the lifecycle (fresh run,
   `--revisit`, `--dry-run`, reset), and the invariants the design enforces.
2. **Review every directory** — purpose, contents, health (tracked vs
   generated vs empty vs missing-when-expected).
3. **Review every file** — role in the system, dependencies, size, quality
   notes, and any anomaly.
4. **Review the code** — architecture, correctness, robustness, security
   (the permission layer), testing, and documentation gaps.
5. **Map interconnections** — module dependency graph, phase data flow, state
   (file) flow, configuration flow, and the observability flow.
6. **Produce a Mermaid diagram** of the entire process — with explicit
   instructions on *where* to create it and *how* to render it, plus the
   diagram itself embedded in this document.

### 1.2 Scope and exclusions

**In scope** (all files under the repo root, excluding):

- `.venv/` — the virtual environment (third-party packages, interpreter).
- `__pycache__/`, `*.py[cod]` — compiled artifacts.
- `.git/` — VCS internals (only its *state* is reviewed: branches, log,
  status, remotes).

**In scope, though generated:** `state/`, `departments/`, `pods/`,
`history/`, `MISSION.md` — these are runtime-generated state, but they are
audited because they document what a live run produced and how the
pipeline's outputs are shaped.

### 1.3 Methodology — workstreams

The audit is organized into six workstreams (WS). Each has a checklist;
results are recorded in the matching section of this document.

| WS | Workstream | Question answered | Section |
|---|---|---|---|
| WS1 | Overall process review | What does the system do, end to end? | §2 |
| WS2 | Directory-by-directory review | What is in each directory, and is it healthy? | §3 |
| WS3 | File-by-file review | What is each file's role, and are there anomalies? | §4 |
| WS4 | Code review | Is the code correct, robust, secure, tested, documented? | §5 |
| WS5 | Interconnection analysis | How do the parts connect (modules, data, state, config)? | §6 |
| WS6 | Mermaid diagram | Where/how to create the process diagram — and the diagram | §7 |

### 1.4 Per-workstream checklists

**WS1 — Overall process review**
- [x] Identify the project's purpose and the pipeline's phases (1–6).
- [x] Identify all entry points (`run_session.py`, `reset_org.py`,
      `run_org.bat`) and their flags/modes.
- [x] Trace the lifecycle: fresh run → `--revisit` → `--dry-run` → reset.
- [x] Identify the invariants the design claims to enforce (read scope,
      no-code-read for heads/leader, communication, pod rules) and which are
      actually enforced vs. documented-as-advisory.
- [x] Identify the LLM backend chain and the offline stub.
- [x] Note documentation gaps (referenced-but-missing docs).

**WS2 — Directory-by-directory review**
- [x] Inventory every top-level directory (and key subdirectories).
- [x] Classify each: source / generated-state / tooling / docs / empty /
      missing-when-expected.
- [x] Cross-check against `.gitignore`, `reset_org.py`, and the README layout
      (are all referenced dirs present? are all present dirs accounted for?).
- [x] Note anomalies (empty dirs, missing dirs, untracked dirs).

**WS3 — File-by-file review**
- [x] Inventory every in-scope file with size.
- [x] For each source file: role, key exports, imports (internal/external).
- [x] For each doc file: purpose, accuracy vs. the code.
- [x] For each state/artifact file: what produced it, shape, consumer.
- [x] Flag anomalies (empty files, stale files, orphaned files, size
      surprises).

**WS4 — Code review**
- [x] Architecture: module responsibilities, layering, dependency direction.
- [x] Correctness: loop/budget bounds, schema validation, coercion, retries.
- [x] Robustness: timeouts, atomic writes, checkpointing, error visibility.
- [x] Security: permission layer (sandbox, mission lock, meta-rule lock),
      secrets handling, agent self-edit gating.
- [x] Testing: coverage map (test file → module), offline determinism.
- [x] Documentation: docstring quality, in-code "Story N" conventions,
      referenced-but-missing docs.
- [x] Findings recorded with severity (Critical / High / Medium / Low / Info).

**WS5 — Interconnection analysis**
- [x] Module dependency graph (from import analysis).
- [x] Phase data flow (what each phase reads/writes, what it hands to the
      next).
- [x] State (file) flow: producers → file → consumers.
- [x] Configuration flow: `.env` → `load_config` / `make_backend` → session.
- [x] Observability flow: runtime → `history/*.jsonl` / `pods/` → dashboard.

**WS6 — Mermaid diagram**
- [x] State *where* to create the diagram (file location(s)).
- [x] State *how* to create/render it (editor, extensions, CLI, hosting).
- [x] Embed the diagram of the entire process.
- [ ] (Optional, later) Additional diagrams: org chart, state flow.

### 1.5 Definition of done

The audit is "done" when:

1. §2–§6 are complete (every workstream checklist item checked).
2. §7 contains the where/how instructions **and** a valid, embedded Mermaid
   diagram of the entire process.
3. §8 consolidates all findings into a single severity-ranked table with
   recommendations.
4. §9 (audit log) records the progression.

---

## 2. WS1 — Overall process review

### 2.1 What the repository is

The project is a **company of LLM agents**. It takes an initial prompt and,
through a **bounded pipeline of intake → mission → org bootstrap → execution
→ synthesis → evaluation**, produces a coherent, **auditable** record of
work. Visibility / communication / pod invariants are enforced "by
construction" (rule math in `org/tiers.py` + gates in `runtime/`).

The core is **stdlib-only** (`dataclasses`, `json`, `pathlib`, `abc`,
`threading`, `http.server`); `httpx` is imported **lazily** only by the real
backend, so the offline stub path and the test suite need no network
dependency.

Two execution backends sit behind one `LLMBackend` interface
(`runtime/llm.py`):

- **`OpenAIBackend`** (`runtime/llm_api.py`, `LLM_BACKEND=api`) — the shipped
  default. Any OpenAI-compatible chat endpoint (the `.env.example` /
  `run_org.bat` pre-fill a local **KoboldCpp** server hosting
  **Qwen3.8-27B** on port 5001). Structured output is a **forced tool call**
  (`submit_output`) by default (`LLM_STRUCTURED=tools`); a legacy
  `json_object` mode exists (`LLM_STRUCTURED=json`).
- **`StubBackend`** (`LLM_BACKEND=stub`) — deterministic, scripted per role;
  every loop/budget/schema check runs offline. This is what the tests use.

### 2.2 The pipeline (Phases 1–6)

| Phase | Name | Module | What happens | Bounded by | Output / audit |
|---|---|---|---|---|---|
| 1 | **Intake** | `runtime/intake.py` | The Leader asks clarifying questions; the user answers; the Leader re-scores confidence (0–1). First question is hard-coded to "What is the organization's goal?" when no `MISSION.md` exists. Convergence requires confidence ≥ threshold **and** a non-empty `restated_goal`. | `QUESTION_BUDGET_ROUNDS` (default 5); at exhaustion the Leader proceeds with **explicitly marked assumptions** | `history/intake.jsonl` |
| 2 | **Mission codification** | `runtime/mission.py` | The Leader drafts `MISSION.md`; the **user approves or rejects** (the only write path to the mission). On rejection the Leader re-asks with feedback. Version continues on a revisit (v1 → v2 → …). | `MISSION_REASK_BUDGET` (default 3) | `MISSION.md`; `history/` mission-edit log |
| 3 | **Org bootstrap + resourcing** | `runtime/org.py` | Department heads are proposed by the Leader; **HR reviews**; directories + policy markdowns are created. Required departments (**HR, Safety, Morality**) are always present. Supports `hire` / `fire` / `_offload` / `replace_leader` / `run_leader_replacement_vote`. | `DIRECT_IC_CAP` (a manager is hired at the cap) | `departments/`; `state/org_chart.json`; `history/` org events |
| 4 | **Top-down dispatch** | `runtime/dispatch.py` | Work propagates **leader → heads → managers → ICs**; results propagate **up** in structured reports. ICs may **self-edit code** (gated by `runtime/permissions.apply_code_edits`). Pod triggers form deliberation pods mid-dispatch. The Leader never reads code. | per-tier decomposition; IC work steps get a larger timeout backstop | upward reports; `history/` (`code_edits`, `tool_calls`, `cycles`); `pods/` |
| 5 | **Synthesis** | `runtime/session.py::_synthesis` | The Leader checks progress against the mission's success criteria **and** whether the deliverable can be improved; pod decisions are carried up. Produces a verdict: `complete` / `continue` / `escalate`. | — | verdict; solo-p5 transcript |
| 6 | **Evaluation** | `runtime/session.py::_evaluate` | A bounded **continue/complete** decision (the self-improving loop). A **no-op cycle** (zero work dispatched) is surfaced as an escalation, never a silent "complete". | `MAX_ITERATIONS` (default 2) | evaluation report; solo-p6 transcript |

**Iteration:** Phases 4–5 repeat up to `MAX_ITERATIONS`; Phase 6 decides
whether to loop again. A visible **escalation** (with diagnosis) terminates
the session when the mission is rejected, a halt is global, or a no-op cycle
occurs.

**Solo leader pods:** the Leader's per-phase work (P1/P2/P3/P5/P6) is tracked
as solo pods (`runtime/pods.py::SoloTracker`) so the observability dashboard
can watch the Leader, not just the multi-role pods.

### 2.3 Entry points and lifecycle

| Entry point | Purpose | Modes / flags |
|---|---|---|
| `run_session.py` | Run the pipeline against the configured backend | `--interactive` (prompt at the intake Q&A + mission approval gates); `--revisit` (re-clarify goal, continue mission version, bootstrap additively, re-save org chart); `--dry-run` (run end-to-end but write state to a throwaway temp dir via `os.chdir`). Default: **unattended** (auto-answer / auto-approve callbacks). |
| `reset_org.py` | Wipe generated state for a clean slate | default = dry run (prints targets); `--yes` = delete. Targets: `departments/`, `state/`, `MISSION.md`, `history/*.jsonl`, `pods/`, `reports/`, `archives/`. |
| `run_org.bat` | One-shot live run (Windows) | Opens 3 windows: (1) KoboldCpp server (port 5001, `--jinja --jinjatools`), waits on `/v1/models`; (2) observability dashboard (`observability/dashboard.py --port 8090`); (3) `run_session.py --interactive` in the batch's own window. |

**Lifecycle:**
- **Fresh run:** no `MISSION.md` → Phase 1 opens with the hard-coded goal
  question → mission v1 → org bootstrap → dispatch → synthesis → evaluation.
- **`--revisit`:** `load_mission` reads the current `MISSION.md` (version +
  text) → Phase 1 re-clarifies against it → Phase 2 continues the version and
  seeds the draft from the current mission → Phase 3 adds roles only (never
  drops/overwrites) → org chart re-saved to `state/org_chart.json`.
- **Crash recovery (Story 1):** `state/checkpoint.json` records the phase /
  cycle / timestamp so a crashed run is recoverable; role memory is written
  atomically.
- **Reset:** `reset_org.py --yes` wipes the generated state.

### 2.4 The invariants (claimed vs. enforced)

| Invariant | Where defined | Enforced? |
|---|---|---|
| A role can only read its team's department directory | `org/tiers.py::can_read` | Rule math present; **read gating is advisory** in the live path (no code-read gate exists to wire it into). |
| Department heads + the Leader cannot read any code | `org/tiers.py::can_read_code` | **Documented as NOT yet enforced** (advisory, Story 10 A11) — the gap is stated in the docstring so it is visible, not silently dead. |
| Communication = chain-of-command + team-mates + Leader (apex) | `org/tiers.py::can_communicate` | Rule math present (used by pod/communication logic). |
| Pods: 2–6 size, max 1-tier spread | `org/tiers.py::validate_pod` | **Enforced** in `runtime/pods.py::form_pod`. |
| Agent self-edits stay in the workspace; mission + meta-rules locked | `runtime/permissions.py` | **Enforced** (sandbox, mission lock, meta-rule lock; `observability/` operator-locked). |

### 2.5 The LLM backend chain (how `Session` uses the backend)

`Session` never calls the raw backend; `runtime/session.py::build_backend`
wraps it in layers:

```
MemoryBackend( RoutingBackend( TimeoutBackend( raw ) ) )
```

- **`TimeoutBackend`** (`runtime/llm.py`) — per-invoke wall-clock backstop
  (default 3600s; the *primary* bound is the api backend's progress-based
  **idle** timeout, `LLM_IDLE_TIMEOUT_SECONDS`). A slow call raises a visible
  `LLMTimeoutError`.
- **`RoutingBackend`** (`runtime/complexity.py`) — routes every invoke by
  task complexity (`classify_complexity`: complex → thinking on, simple →
  off) and bounds HIGH-thinking invokes via `ThinkingBudget`
  (`THINKING_BUDGET`, default 10); logs to `history/invocations.jsonl`.
- **`MemoryBackend`** (`runtime/llm.py`) — folds each role's **isolated**
  short-term memory into its prompt before the invoke and appends the
  interaction after it; persists to / loads from `state/role_memory/`
  (atomic writes; pruned to active roles).

`raw` is selected by `runtime/llm_api.py::make_backend()` from the
environment: `LLM_BACKEND=api` → `OpenAIBackend`; `stub` (or unset) →
`StubBackend`.


## 3. WS2 — Directory-by-directory review

### 3.1 Top-level directory inventory

| Directory | Class | Tracked? | Contents | Health / notes |
|---|---|---|---|---|
| `runtime/` | **Source** (core) | yes | 17 modules: the session runtime | The heart of the system. See §4.2. |
| `org/` | **Source** | yes | `tiers.py`, `__init__.py` | Dependency-light rule math (invariants). |
| `roles/` | **Source** | yes | `base.py`, `leader.py`, `worker.py`, `__init__.py` | Role contracts + output schemas. |
| `tests/` | **Source** (tests) | yes | 22 `test_*.py` + `__init__.py` | Offline, deterministic. See §5.5. |
| `observability/` | **Source** (operator-owned) | yes | `dashboard.py`, `web/` (`app.js`, `index.html`, `style.css`) | Read-only stdlib dashboard; **agent-write-locked** by `runtime/permissions.py`. |
| `departments/` | **Generated state** | git-ignored (contents) | 4 policy dirs: `analytics`, `hr`, `morality`, `safety` | Created by Phase 3. Each holds a stub `*_POLICY.md`. |
| `state/` | **Generated state** | git-ignored (contents) | `org_chart.json`, `checkpoint.json`, `role_memory/` (5 files) | Saved org chart, crash checkpoint, per-role memory. |
| `pods/` | **Generated state** | git-ignored (contents) | `transcripts/` (16 pods × md+jsonl); `artifacts/` referenced | Phase 4 deliberation records. |
| `history/` | **Generated state** | git-ignored (contents) | `.gitkeep` only (logs are run-generated) | Audit JSONL (`intake`, `mission_edits`, `org_events`, `code_edits`, `tool_calls`, `cycles`, `invocations`, `escalations`, …) that the dashboard tails. |
| `archives/` | **Generated state** | git-ignored (contents) | empty | Rolled-over sessions beyond the rolling window. Present but empty. |
| `reports/` | **Generated state** | git-ignored (contents) | **absent on disk** | Referenced by `.gitignore`, `reset_org.py` (`REPORTS_DIR`), README layout. Created on demand by the code (`makedirs`). **Low** anomaly — see §8. |
| `stories/` | **Untracked / empty** | no | empty | Not in `.gitignore`, not tracked, not referenced by code or docs. **Low** anomaly (leftover). |
| `.venv/` | **Tooling** (excluded) | git-ignored | virtual environment | Excluded from audit. |
| `__pycache__/` | **Artifact** (excluded) | git-ignored | compiled bytecode | Excluded from audit. |

### 3.2 Cross-checks

- **`.gitignore` vs. disk:** every git-ignored state dir is accounted for.
  `reports/` is git-ignored and referenced but not present on disk (created
  on demand) — consistent, minor.
- **`reset_org.py` targets vs. disk:** `departments/`, `state/`, `pods/`,
  `archives/` present; `reports/` absent (guarded by `os.path.isdir`);
  `MISSION.md` present; `history/*.jsonl` none (only `.gitkeep`). All safe.
- **README "Layout" block vs. disk:** lists `org/`, `roles/`, `departments/`,
  `runtime/`, `pods/`, `state/role_memory/`, `history/`, `archives/`,
  `reports/`, `tests/` — all present except `reports/` (on-demand). The
  README layout does **not** list `observability/` (it exists and is
  operator-owned) — a minor doc omission.
- **Empty / untracked dirs:** `archives/` (empty, expected — no rollover yet)
  and `stories/` (empty, untracked, unreferenced — leftover).

### 3.3 Anomalies (WS2)

| ID | Dir | Anomaly | Severity |
|---|---|---|---|
| D-1 | `reports/` | Referenced (`.gitignore`, `reset_org.py`, README) but absent on disk; created on demand. | Low |
| D-2 | `stories/` | Empty, untracked, unreferenced by code or docs (leftover). | Low |
| D-3 | `archives/` | Empty (expected — no session rollover yet). | Info |

---

## 4. WS3 — File-by-file review

File roles and dependencies. Sizes are approximate (KB). Internal imports
are the ones that matter for the interconnection map (§6).

### 4.1 Root files (entry points, config, docs)

| File | Size | Role | Key exports / behavior | Internal deps | Notes |
|---|---|---|---|---|---|
| `run_session.py` | 6.9 | **Main entry point** | `main()`; `_unattended_callbacks()`; `_interactive_callbacks()` | `runtime.config`, `runtime.llm_api`, `runtime.session`, `roles.leader` | Loads `.env` (dotenv, optional); builds `Session` with `make_backend()` + `make_leader()` + `load_config()`; flags `--interactive` / `--revisit` / `--dry-run`. `--dry-run` uses `os.chdir` to a temp dir (CWD-relative path assumption). Passes `initial_prompt=""` (Phase 1 starts from the Leader's role info). |
| `reset_org.py` | 2.0 | **Reset entry point** | `main()`; `_collect_targets()` | — (stdlib only) | Dry-run by default; `--yes` deletes `departments/`, `state/`, `MISSION.md`, `history/*.jsonl`, `pods/`, `reports/`, `archives/`. |
| `run_org.bat` | 2.0 | **One-shot live run** | batch script | — | Starts KoboldCpp (port 5001, `--jinja --jinjatools`), waits on `/v1/models`, starts the dashboard (port 8090), runs `run_session.py --interactive`. Paths at the top are user-adjustable. |
| `requirements.txt` | 0.3 | Dependencies | — | — | `python-dotenv>=1.0`, `pytest>=8.0`, `httpx>=0.27` (core is stdlib-only). |
| `.env.example` | 4.6 | Config template | — | — | Documents every knob; pre-fills the localhost KoboldCpp/Qwen setup (`LLM_BACKEND=api`, port 5001). **Note:** `POD_MIN_ROLES` / `POD_MAX_ROLES` / `CONTEXT_BUDGET_TOKENS` / `ROLE_MEMORY_MAX_ENTRIES` are listed here but **intentionally not mapped** by `runtime/config.py` (dead knobs — an "unused .env key" warning fires). See §5.1 / §8. |
| `.env` | 4.6 | Active config (git-ignored) | — | — | Present on disk. |
| `.gitignore` | 1.3 | VCS ignore rules | — | — | Ignores `.env`, `.venv/`, `__pycache__/`, pytest caches, and the generated-state dir contents (with `.gitkeep` re-include). |
| `README.md` | 4.0 | **Primary doc** | — | — | Overview, pipeline, invariants, layout, offline-by-design, quick start. |
| `SETUP.md` | 18.2 | **Setup & rollout doc** | — | — | Step-by-step (git, venv, deps, tests), configuration table, LLM backend, permission layer, troubleshooting, "what done looks like". |
| `MISSION.md` | 0.2 | **Generated state** (mission) | — | — | v1, minimal ("a data pipeline" / "works"). Written by Phase 2; loaded on a revisit. Git-ignored. |
| `AUDIT.md` | — | **This document** | — | — | The audit. |

### 4.2 `runtime/` — the session runtime (17 modules)

| File | Size | Role | Key exports | Internal deps | Notes |
|---|---|---|---|---|---|
| `__init__.py` | 0.3 | Package doc | — | — | Lists the modules. |
| `config.py` | 3.4 | **Central config loader** (D1) | `load_config()`; `ENV_TO_CONFIG`; `LLM_BACKEND_KEYS` | — | Maps `.env` org-tuning knobs → `Session` config keys (with casts); warns on unknown/unused `.env` keys (only keys actually in the `.env` file, to avoid Windows shell-var noise). All pod/context knobs are plumbed to their consumers (the 4 previously-dropped ones were wired in by S20). |
| `llm.py` | 9.5 | **Backend interface + wrappers** | `Reasoning`; `LLMBackend`; `StubBackend`; `LLMTimeoutError`; `TimeoutBackend`; `MemoryBackend` | `runtime.context` | `TimeoutBackend` runs the invoke in a daemon thread (portable timeout). `MemoryBackend` adds per-role isolated memory + persistence (atomic writes, pruned to active roles). |
| `llm_api.py` | 37.1 | **Real (api) backend** | `OpenAIBackend`; `make_backend()`; `validate_and_quarantine()`; `OpenAIOutputError` | `runtime.llm`, `roles.base` | OpenAI-compatible client (httpx, lazy import). Forced `submit_output` tool call for structured output; validation + quarantine of malformed output; idle timeout; bounded retries on timeout. The largest runtime module. |
| `intake.py` | 6.9 | **Phase 1** | `run_intake()`; `IntakeResult` | `roles.base`, `runtime.llm`, `runtime.complexity`, `runtime.coerce`, `runtime.guard` | Clarifying Q&A loop; hard-coded goal question when no `MISSION.md`; `restated_goal` convergence gate; budget exhaustion → marked assumptions; audit to `history/intake.jsonl`. |
| `mission.py` | 5.5 | **Phase 2** | `run_mission()`; `load_mission()`; `MissionResult`; `_render_mission()` | `roles.base`, `runtime.intake`, `runtime.llm`, `runtime.guard`, `runtime.complexity` | Mission draft + user permission flow; version continues on revisit; the only write path to `MISSION.md`; re-ask budget. |
| `org.py` | 27.7 | **Phase 3** | `bootstrap()`; `OrgState`; `hire()`; `fire()`; `_offload()`; `replace_leader()`; `run_leader_replacement_vote()`; `required_approver()` | `roles.base`, `roles.worker`, `runtime.mission`, `runtime.complexity` | Org bootstrap + resourcing; required departments (HR/Safety/Morality) always present; IC cap; department/team dir creation; org-chart save/load. |
| `dispatch.py` | 32.6 | **Phase 4** | `dispatch()`; `mission_digest()`; `_check_pod_triggers()`; `_apply_ic_self_edits()`; `_repair_edit_paths()`; `_retry_refused_edits()` | `roles.base`, `roles.worker`, `runtime.org`, `runtime.llm`, `runtime.complexity`, `runtime.history`, `runtime.permissions`, `runtime.coerce`, `runtime.pods` | Top-down decomposition + upward reports; IC self-edits gated by permissions; pod triggers; the largest pipeline module. |
| `pods.py` | 16.4 | **Pod mechanics** | `form_pod()`; `chained_pod()`; `run_pod()`; `senior_member()`; `write_transcripts()`; `write_decision_artifact()`; `form_solo_pod()`; `record_solo_step()`; `SoloTracker` | `org.tiers`, `roles.base`, `runtime.llm`, `runtime.complexity`, `runtime.coerce`, `runtime.context` | Pod formation (validated by `org.tiers`), conversation, artifacts, transcripts; solo leader pods. |
| `context.py` | 4.5 | **Memory + prompt** | `RoleMemory`; `MemoryEntry`; `assemble_prompt()`; `bounded_assembly()`; `estimate_tokens()` | — | Per-role bounded short-term memory (cross-team carry-over); four-part prompt construction; bounded assembly with deterministic truncation (agenda never dropped). |
| `complexity.py` | 4.0 | **Complexity routing** | `classify_complexity()`; `ThinkingBudget`; `RoutingBackend`; `detect_disagreement()`; `parse_phase()` | `runtime.llm`, `runtime.history` | Pure router (complex → thinking on, simple → off); HIGH-thinking budget; logs to `history/invocations.jsonl`. |
| `history.py` | 6.4 | **Audit trail** | `HistoryStore` | — | JSONL audit trail, decision journal, rolling window, archives, evaluation reports. Thread-safe. |
| `permissions.py` | 5.0 | **Permission layer** (self-mod) | `write_file()`; `apply_code_edits()`; `can_edit()`; `edit_reason()`; `resolve()` | — | Enforces sandbox (stay in workspace), mission lock (`MISSION.md` leader-only), meta-rule lock (permission module + `org/tiers.py` + `roles/base.py` read-only for everyone); `observability/` operator-locked. |
| `guard.py` | 1.7 | **Callback guard** (Story 11 B11) | `guarded_call()`; `UserApprovalError` | — | Bounded-retry wrapper for user-approval callbacks (visible note, escalate on final failure). |
| `coerce.py` | 1.7 | **Tolerant coercion** | `as_float()`; `as_str_list()`; `as_dict_list()` | — | Pure helpers so every reader degrades gracefully on a free-form LLM output. |
| `session.py` | 26.3 | **Session runtime** | `Session`; `build_backend()`; `SessionResult` | `roles.base`, `runtime.llm`, `runtime.intake`, `runtime.mission`, `runtime.org`, `runtime.dispatch`, `runtime.pods`, `runtime.history`, `runtime.complexity` | Drives Phases 1–6 + the BAU rule + escalation + the Phase 6 self-improving loop; builds the backend chain; checkpointing (crash recovery). |

### 4.3 `org/`, `roles/`, `tests/`, `observability/`

| File | Size | Role | Key exports | Internal deps | Notes |
|---|---|---|---|---|---|
| `org/__init__.py` | 0.1 | Package doc | — | — | — |
| `org/tiers.py` | 6.4 | **Rule math (invariants)** | `tier_of()`; `can_read()`; `can_read_code()`; `cross_team_read()`; `can_communicate()`; `pod_spread()`; `validate_pod()`; `policy_path()`; `is_code_path()` | — | Dependency-light (operates on any `Role`-like object). `can_read_code` / `cross_team_read` documented as **not yet enforced** (advisory, Story 10 A11). |
| `roles/__init__.py` | 0.5 | Package doc | — | — | — |
| `roles/base.py` | 5.7 | **Role contract** | `Role`; `validate_envelope()`; `spin_personality()`; `spin_sub_architype()`; `ARCHITYPES`; `OUTPUT_ENVELOPE_KEYS`; `REQUIRED_ENVELOPE_KEYS` | — | The `Role` dataclass (identity + structured contract + reporting line); shared output envelope validation; deterministic identity spin for dynamically-created roles (SHA-256, not built-in `hash`). **Meta-rule-locked** (read-only for every role). |
| `roles/leader.py` | 6.9 | **The Leader** | `make_leader()`; `LEADER_MANDATE`; `LEADER_OUTPUT_SCHEMA` | `roles.base` | The only active personality at startup; rich output schema (phase-specific extensions: questions, assumptions, mission_draft, org_recommendation, decomposition, verdict, leader_replacement, resourcing). |
| `roles/worker.py` | 4.2 | **Worker output schemas** | `worker_output_schema()`; `HEAD_OUTPUT_SCHEMA`; `MANAGER_OUTPUT_SCHEMA`; `IC_OUTPUT_SCHEMA` | — | Gives dynamically-spun worker roles a real forced shape (fixes the Phase-4 free-form `decomposition` crash). |
| `tests/__init__.py` | 0.2 | Test package | — | — | — |
| `tests/test_*.py` (22) | — | **Offline tests** | — | per-module | One per area: `coerce`, `complexity`, `config`, `context`, `dashboard`, `dispatch`, `envelope`, `history`, `intake`, `llm_api`, `memory`, `mission`, `observability_hooks`, `org`, `permissions`, `pods`, `pod_triggers`, `session`, `tiers`. See §5.5. |
| `observability/dashboard.py` | 16.4 | **Read-only dashboard** | — | — (stdlib only) | `http.server` (ThreadingHTTPServer); tails `history/*.jsonl`, `state/`, `pods/transcripts/`; serves `web/`. Operator-owned; agent-write-locked. |
| `observability/web/index.html` | — | Dashboard UI (markup) | — | — | — |
| `observability/web/app.js` | 23.0 | Dashboard UI (logic) | — | — | Largest web file. |
| `observability/web/style.css` | — | Dashboard UI (style) | — | — | — |

### 4.4 Generated state / artifact files

| File | Size | Producer | Shape / content | Consumer | Notes |
|---|---|---|---|---|---|
| `state/org_chart.json` | 6.9 | `runtime/org.py` (Phase 3) | `{"roles": {<id>: {…Role…}}}` — e.g. `head_analytics`, `head_hr`, … | `run_session.py --revisit` (loads it) | Saved org chart. |
| `state/checkpoint.json` | 0.1 | `runtime/session.py` (checkpointing) | `{"phase": 4, "cycle": 1, "ts": …}` | crash recovery | Story 1. |
| `state/role_memory/{head_analytics,ic1,ic2,leader,mgr1}.json` | 0.4–2.6 | `MemoryBackend.save_state` | `{"max_entries": N, "entries": [{summary, source, team, ts}]}` | `MemoryBackend.load_state` | Per-role isolated memory (5 roles). Atomic writes. |
| `departments/{analytics,hr,morality,safety}/*_POLICY.md` | ~0.1 | `runtime/org.py` (Phase 3) | `# <DEPT> POLICY` (owned by `<head>`; sections per team) | department heads (governance) | Stub policies. |
| `pods/transcripts/pod_*.md` + `.jsonl` (16 pods) | ~0.2–0.5 | `runtime/pods.py::write_transcripts` | md: pod header (starter, members, agenda, decision, rounds, closed) + transcript; jsonl: structured | dashboard; audit | 16 pods: `pod_head_analytics_{4,6,8,10,12}`, `pod_mgr1_{3,5,7,9,11}`, `solo_leader_p{1..6}`. |
| `history/.gitkeep` | 0.0 | — | marker | — | Logs are run-generated (git-ignored). |
| `MISSION.md` | 0.2 | `runtime/mission.py` (Phase 2) | `# MISSION (v1)` + purpose/success criteria/scope/… | intake (revisit), mission (revisit) | Git-ignored. |

### 4.5 Anomalies (WS3)

| ID | File | Anomaly | Severity |
|---|---|---|---|
| F-1 | `.env.example` | Lists 4 knobs (`POD_MIN_ROLES`, `POD_MAX_ROLES`, `CONTEXT_BUDGET_TOKENS`, `ROLE_MEMORY_MAX_ENTRIES`) that `runtime/config.py` **intentionally does not map** (dead — an "unused .env key" warning fires). The doc implies they are active. **Resolved by S20**: the 4 knobs are now plumbed to their consumers (wired in). | Medium |
| F-2 | `README.md` "Layout" | Does not list `observability/` (which exists and is operator-owned). | Low |
| F-3 | `state/checkpoint.json` | Present from a prior live run (phase 4, cycle 1) — a stale checkpoint; a fresh run overwrites it. | Info |
| F-4 | `pods/transcripts/` | 16 pods from a prior live run (generated state). | Info |

---

## 5. WS4 — Code review

### 5.1 Architecture and design

**Strengths**
- **Clean layering.** `org/tiers.py` (pure rule math) ← `roles/` (contracts)
  ← `runtime/` (pipeline) ← entry points. Dependencies point one way
  (toward the leaves); no cycles observed.
- **Stdlib-only core.** `httpx` is imported lazily only by the api backend,
  so the offline stub path and the tests need no network dependency.
- **Single `LLMBackend` interface** with composable wrappers
  (`TimeoutBackend` → `RoutingBackend` → `MemoryBackend`), built by an
  explicit, testable factory (`session.build_backend`).
- **Consistent design philosophy: "visible, never silent."** Every
  degradation path (budget exhaustion, malformed output, timeout, refused
  edit, no-op cycle) is surfaced (a note, a log entry, an escalation), not
  swallowed.
- **`Story N (X)` comment convention** ties code to the story branches
  (S1–S12), making the rationale traceable.
- **Pure functions for the invariants** (`classify_complexity`,
  `validate_pod`, `can_read`, `coerce.*`) so the loop/budget/schema logic is
  unit-testable offline.

**Observations**
- **`runtime/dispatch.py` (32.6KB) and `runtime/llm_api.py` (37.1KB)** are
  large; `dispatch` in particular mixes decomposition, upward reports,
  self-edit gating, and pod triggers. A candidate for future decomposition
  (not a defect).
- **CWD-relative path assumption.** The pipeline writes to relative paths
  (`history/`, `departments/`, `state/`, `pods/`, `MISSION.md`);
  `run_session.py --dry-run` relies on `os.chdir` to redirect them. This is
  a deliberate, documented choice but couples the pipeline to the working
  directory.
- **Config dead-knobs.** 4 `.env` knobs are intentionally unmapped by
  `runtime/config.py` (so the "unused" warning fires) but are still listed in
  `.env.example` as if active (finding F-1).

### 5.2 Correctness

- **Loop/budget bounds are real.** Intake (`QUESTION_BUDGET_ROUNDS`), mission
  re-asks (`MISSION_REASK_BUDGET`), dispatch iterations (`MAX_ITERATIONS`),
  pod rounds, and the HIGH-thinking budget (`THINKING_BUDGET`) are all
  bounded, with a visible exit on exhaustion (assumptions, escalation,
  forced close, LOW fallback).
- **Schema validation + quarantine.** `roles/base.py::validate_envelope`
  checks the required envelope keys (`summary` + `confidence`) and type-checks
  the optional ones; `runtime/llm_api.py::validate_and_quarantine` quarantines
  malformed tool-call output. Bounded retries on malformed output.
- **Tolerant coercion.** `runtime/coerce.py` (`as_float` / `as_str_list` /
  `as_dict_list`) means every reader degrades gracefully when a key arrives as
  the wrong type (a free-form string instead of a dict/list) — no
  `AttributeError` crash.
- **Deterministic identity spin.** `spin_personality` / `spin_sub_architype`
  use a SHA-256 digest (not the per-process-randomized built-in `hash`), so
  the same role id maps to the same identity across runs (persisted memory
  stays consistent).
- **Convergence gate.** Intake requires a non-empty `restated_goal` in
  addition to confidence ≥ threshold, preventing premature convergence on a
  fuzzy goal.
- **No-op cycle guard.** A Phase 4 that dispatches zero work is surfaced as an
  escalation, never a silent "complete".

### 5.3 Robustness

- **Timeouts (two-layer).** The *primary* bound is the api backend's
  progress-based **idle** timeout (`LLM_IDLE_TIMEOUT_SECONDS`; fails only when
  the model stops emitting chunks, so a long-but-active think never trips it).
  The wall-clock `TimeoutBackend` (default 3600s) is a large **backstop** that
  catches what the idle bound misses. Both are config-driven.
- **Bounded retries on timeout.** A `Read`/`Connect`/`Pool` timeout retries the
  whole streaming request from the start (a stateless HTTP request — no
  resume) with backoff; parse / non-timeout errors are never retried.
- **Atomic writes.** Role memory and the org chart are written
  `<name>.json.tmp` then swapped in with `os.replace` — a crash mid-write
  leaves the previous good state intact (no partial JSON).
- **Checkpointing (crash recovery, Story 1).** `state/checkpoint.json`
  records the phase / cycle / timestamp; role memory is pruned to active roles
  (plus the leader) before saving so it does not grow without bound.
- **Daemon-thread timeout.** `TimeoutBackend` runs the invoke in a daemon
  thread, so a timeout never blocks process exit and the underlying httpx call
  is bounded to the same bound (no long-lived zombie thread).
- **Guarded user-approval callbacks.** `guarded_call` retries a flaky
  operator callback (bounded) and escalates visibly on final failure.

### 5.4 Security

- **Permission layer (self-mod).** Every agent self-edit goes through
  `runtime/permissions.write_file` (via `apply_code_edits`, which records
  refusals visibly). Three invariants, each covered by
  `tests/test_permissions.py`:
  - **Sandbox** — a path that resolves outside the workspace (e.g. `..` or a
    symlink escape) is refused.
  - **Mission lock** — `MISSION.md` is writable only by the `leader`.
  - **Meta-rule lock** — the permission module itself (plus `org/tiers.py` and
    `roles/base.py`) is read-only for *every* role, including the leader — an
    agent can never edit the rules that bound it.
  - **`observability/` operator-locked** — no agent can write into it.
- **Secrets handling.** `.env` is git-ignored; `LLM_API_KEY` (the
  `.env.example` value is `not-needed`) is not committed. No secrets found in
  the tree.
- **Agent self-edit gating in dispatch.** IC `code_edits` are path-repaired
  (`_repair_edit_paths`), refused edits are retried (`_retry_refused_edits`),
  and every write is permission-gated — so a free-form IC edit cannot escape
  the sandbox or touch a locked file.

### 5.5 Testing

- **Offline and deterministic.** All 22 test files run against the
  `StubBackend` (scripted per role) — no live model, no network. The
  loop/budget/schema logic is exercised without a backend.
- **Coverage map (test file → area):**

  | Test file | Area |
  |---|---|
  | `test_coerce.py` | tolerant coercion |
  | `test_complexity.py` | complexity routing + thinking budget |
  | `test_config.py` | config loader (D1) |
  | `test_context.py` | memory + prompt + bounded assembly |
  | `test_dashboard.py` | observability dashboard |
  | `test_dispatch.py` | Phase 4 dispatch |
  | `test_envelope.py` | shared output envelope |
  | `test_history.py` | audit trail / rolling window |
  | `test_intake.py` | Phase 1 intake |
  | `test_llm_api.py` | api backend (validation/quarantine) |
  | `test_memory.py` | per-role memory |
  | `test_mission.py` | Phase 2 mission |
  | `test_observability_hooks.py` | observability wiring |
  | `test_org.py` | Phase 3 org / resourcing |
  | `test_permissions.py` | permission layer (sandbox/locks) |
  | `test_pods.py` | pod mechanics |
  | `test_pod_triggers.py` | pod triggers (Phase 4) |
  | `test_session.py` | full pipeline / BAU halt / checkpoint |
  | `test_tiers.py` | tier math / invariants |

- **Status:** **All tests pass** (verified by the operator). A sandboxed audit
  run is blocked only by pytest temp dirs resolving outside `D:\LLM`
  (`PermissionError`) — environmental, not a code defect.

### 5.6 Documentation

- **Docstrings are strong** — every module and most functions carry a
  purpose, a worked example, and (where relevant) the in-code "Story N (X)"
  rationale.
- **`.env.example` dead-knobs** (F-1) — the config doc implies 4 knobs are
  active that the code intentionally does not map — **Medium** finding.
  **Resolved by S20**: the 4 knobs are now plumbed to their consumers (wired in).

---

## 6. WS5 — Interconnection analysis

### 6.1 Module dependency graph (from import analysis)

Arrows point **from** the importer **to** the imported module. Leaves
(no internal deps) at the bottom.

```
Entry points
  run_session.py ──► runtime.config , runtime.llm_api , runtime.session , roles.leader
  reset_org.py ──► (stdlib only)
  run_org.bat  ──► (launches run_session.py + observability/dashboard.py)

runtime.session ──► runtime.intake , runtime.mission , runtime.org ,
                    runtime.dispatch , runtime.pods , runtime.history ,
                    runtime.complexity , runtime.llm , roles.base
runtime.dispatch ─► runtime.org , runtime.llm , runtime.complexity ,
                    runtime.history , runtime.permissions , runtime.coerce ,
                    runtime.pods , roles.base , roles.worker
runtime.pods ────► org.tiers , runtime.llm , runtime.complexity ,
                   runtime.coerce , runtime.context , roles.base
runtime.org ─────► runtime.mission , runtime.complexity , roles.base ,
                   roles.worker
runtime.mission ─► runtime.intake , runtime.llm , runtime.guard ,
                   runtime.complexity , roles.base
runtime.intake ──► runtime.llm , runtime.complexity , runtime.coerce ,
                   runtime.guard , roles.base
runtime.complexity ► runtime.llm , runtime.history
runtime.llm_api ──► runtime.llm , roles.base
runtime.llm ──────► runtime.context
runtime.config ───► (none)
runtime.permissions ► (none)
runtime.history ───► (none)
runtime.guard ─────► (none)
runtime.coerce ────► (none)
runtime.context ───► (none)
org.tiers ─────────► (none)
roles.leader ──────► roles.base
roles.base ────────► (none)
roles.worker ──────► (none)
observability.dashboard ► (none — reads files on disk, not code)
```

**Observations**
- **No dependency cycles.** The graph is a DAG; `runtime.session` is the
  top-level orchestrator, `runtime.dispatch` the largest fan-out.
- **Leaves are the pure/testable core:** `org.tiers`, `roles.base`,
  `runtime.context`, `runtime.coerce`, `runtime.guard`, `runtime.history`,
  `runtime.permissions`, `runtime.config`.
- **`observability/dashboard.py` is decoupled from the runtime** — it shares
  no code, only the on-disk artifacts (`history/*.jsonl`, `state/`,
  `pods/transcripts/`). This is what makes it safely operator-owned and
  agent-write-locked.

### 6.2 Phase data flow (what each phase reads/writes and hands on)

```
Phase 1 (intake)
  reads:  MISSION.md (if present — sets goal_established), intake transcript
  writes: history/intake.jsonl
  hands:  IntakeResult (confidence, assumptions, transcript) ──► Phase 2

Phase 2 (mission)
  reads:  IntakeResult, MISSION.md (revisit: version + text)
  writes: MISSION.md (only write path), history/ (mission-edit log)
  hands:  MissionResult (approved, version, draft) ──► Phase 3

Phase 3 (org bootstrap + resourcing)
  reads:  MissionResult, state/org_chart.json (revisit)
  writes: departments/ (dirs + policy md), state/org_chart.json,
          history/ (org events)
  hands:  OrgState (roles: heads/managers/ICs, reporting lines) ──► Phase 4

Phase 4 (dispatch)
  reads:  OrgState, MISSION.md (digest)
  writes: history/ (code_edits, tool_calls, cycles), pods/ (transcripts +
          decision artifacts), state/ (role memory via MemoryBackend)
  hands:  upward reports (structured) + pod decisions ──► Phase 5

Phase 5 (synthesis)
  reads:  upward reports, pod decisions
  writes: solo-p5 transcript
  hands:  verdict (complete / continue / escalate) ──► Phase 6

Phase 6 (evaluation)
  reads:  verdict, dispatch results
  writes: evaluation report, solo-p6 transcript, history/ (escalations)
  hands:  continue (another Phase 4–5 cycle, bounded by MAX_ITERATIONS)
          or complete ──► SessionResult
```

**Carry-over paths (how context moves across meetings):**
1. **Intra-team** — each role's isolated `RoleMemory` (folded into its prompt
   before every invoke).
2. **Pod decision → members' later intra-team meetings** —
   `MemoryBackend.seed_cross_team` seeds a `pod:<id>` entry.
3. **Pod decisions → the Leader's synthesis** — Phase 5 carries the pods'
   closed decisions up.

### 6.3 State (file) flow: producers → file → consumers

| File | Producer | Consumer(s) | Notes |
|---|---|---|---|
| `MISSION.md` | Phase 2 (`runtime/mission.py`) | Phase 1 (revisit: `goal_established`), Phase 2 (revisit: seed), Phase 3 (digest), `reset_org.py` (wipes) | The only write path is the approved mission. |
| `state/org_chart.json` | Phase 3 (`runtime/org.py`) | `run_session.py --revisit` (loads) | Saved org chart. |
| `state/checkpoint.json` | `runtime/session.py` (checkpointing) | crash recovery | Story 1. |
| `state/role_memory/*.json` | `MemoryBackend.save_state` | `MemoryBackend.load_state` | Per-role isolated memory; atomic writes; pruned to active roles. |
| `departments/*_POLICY.md` | Phase 3 (`runtime/org.py`) | department heads (governance) | Stub policies. |
| `history/*.jsonl` | Phase 1 (`intake`), Phase 2 (`mission_edits`), Phase 3 (`org_events`), Phase 4 (`code_edits`, `tool_calls`, `cycles`), `RoutingBackend` (`invocations`), `Session` (`escalations`, halts, evaluation) | `observability/dashboard.py` (tails); `HistoryStore` (rolling window + archives) | The audit trail. |
| `pods/transcripts/*` | `runtime/pods.py::write_transcripts` | `observability/dashboard.py`; audit | Pod + solo-pod records. |
| `pods/artifacts/*` | `runtime/pods.py::write_decision_artifact` | audit | Pod decision artifacts. |
| `archives/` | `HistoryStore` (rolling window rollover) | — | Beyond the rolling window. |
| `reports/evaluation/` | `HistoryStore.write_evaluation_report` | — | Evaluation reports. |

### 6.4 Configuration flow

```
.env (git-ignored)
  │
  ├─► runtime.config.load_config()
  │      maps non-LLM_* org-tuning knobs → Session config dict (with casts);
  │      warns on unknown/unused .env keys (only keys in the .env file).
  │      Session config keys: confidence_threshold, question_budget,
  │      mission_reask_budget, pod_max_rounds, direct_ic_cap,
  │      history_window_sessions, archive_cap_mb, timeout_seconds,
  │      ic_timeout_seconds, max_iterations, thinking_budget.
  │
  └─► runtime.llm_api.make_backend()
         reads LLM_* keys directly: LLM_BACKEND (stub|api), LLM_MODEL,
         LLM_BASE_URL, LLM_API_KEY, LLM_STRUCTURED (tools|json),
         LLM_MAX_TOKENS, LLM_IDLE_TIMEOUT_SECONDS, LLM_MAX_RETRIES.
         → OpenAIBackend (api) or StubBackend (stub).
```

- **Two timeout backstops** are config-driven: `LLM_TIMEOUT_SECONDS`
  (wall-clock, default 3600s) and `LLM_IC_TIMEOUT_SECONDS` (per-invoke). The
  *primary* bound is the api backend's idle timeout (`LLM_IDLE_TIMEOUT_SECONDS`).

### 6.5 Observability flow

```
runtime (live)
  │  appends JSONL / writes transcripts
  ▼
history/*.jsonl  +  pods/transcripts/*  +  state/
  │  (on disk; the only coupling — no shared code)
  ▼
observability/dashboard.py  (ThreadingHTTPServer, read-only, stdlib)
  │  tails the files; serves web/ (index.html, app.js, style.css)
  ▼
browser (http://127.0.0.1:8090)
```

- **Decoupled by design:** the dashboard imports no runtime code; it only
  reads the on-disk artifacts. This is what makes it safely operator-owned
  and agent-write-locked by `runtime/permissions.py`.
- **Live pod transcripts** grow per round, so the dashboard shows the active
  pod's conversation without a restart.

---

## 7. WS6 — Mermaid diagram of the entire process

### 7.1 Where to create it

Recommended locations (pick one; all are valid):

| Location | Path | Why |
|---|---|---|
| **Dedicated doc (recommended)** | `D:\LLM\LLM_Organization\docs\PROCESS.md` (create the `docs/` dir) | Keeps the diagram with the other process docs; easy to reference from `README.md`. |
| **Repo root** | `D:\LLM\LLM_Organization\PROCESS.md` | Simplest; no new dir. |
| **Embedded in `README.md`** | a new "Process" section in `README.md` | The diagram lives next to the overview. |
| **Embedded in `AUDIT.md`** | §7.3 of this document | Already done — the diagram is embedded below. |

Because the repo has an `origin` remote, if that host is **GitHub** or
**GitLab**, pushing the `.md` file renders the Mermaid **natively** (no extra
tooling).

### 7.2 How to create / render it

1. **Write the fenced block.** Put the diagram inside a ` ```mermaid ` fenced
   code block in a Markdown file. The diagram in §7.3 is ready to copy.
2. **Render it** (any one of):
   - **GitHub / GitLab** — push the `.md` to `origin`; Mermaid renders
     natively in the rendered Markdown.
   - **VS Code** — install the **"Markdown Preview Mermaid Support"**
     extension, open the `.md`, and use the Markdown preview
     (`Ctrl+Shift+V`).
   - **mermaid-cli (MMDc)** — export an image:
     `npx @mermaid-js/mermaid-cli -i PROCESS.md -o process.svg`
     (also supports `.png` / `.pdf`).
   - **mermaid.live** — paste the diagram into <https://mermaid.live> to
     edit, preview, and export online.
3. **Validate before committing.** Paste the diagram into
   <https://mermaid.live> — it should render with no syntax error. The
   embedded diagram below is a valid `flowchart TD`.

### 7.3 The diagram (embedded)

The entire process: entry points → configuration → the LLM backend chain →
the 6-phase pipeline → state files → observability. Cylinder nodes
`[(…)]` are on-disk state files; the backend-chain subgraph shows the **call
flow** (outermost wrapper → innermost raw backend).

```mermaid
flowchart TD
    subgraph ENTRY["Entry points"]
        RS["run_session.py<br/>(--interactive / --revisit / --dry-run)"]
        RO["reset_org.py<br/>(--yes)"]
        BAT["run_org.bat<br/>(one-shot live run)"]
    end

    ENV[(".env")]
    CFG["runtime/config.py<br/>load_config()"]
    MKB["runtime/llm_api.py<br/>make_backend()"]

    subgraph BACKEND["LLM backend chain (built by session.build_backend)<br/>call flow: outermost → innermost"]
        MB["MemoryBackend<br/>(isolated per-role memory)"]
        RB["RoutingBackend<br/>(complexity routing + thinking budget)"]
        TB["TimeoutBackend<br/>(idle timeout + wall-clock backstop)"]
        RAW["raw backend<br/>OpenAIBackend (api) / StubBackend (stub)"]
    end

    subgraph PIPE["6-phase pipeline (runtime/session.py)"]
        P1["Phase 1 · Intake<br/>clarifying Q&A"]
        P2["Phase 2 · Mission<br/>draft + user approval"]
        P3["Phase 3 · Org bootstrap<br/>+ resourcing"]
        P4["Phase 4 · Dispatch<br/>top-down + upward reports"]
        P5["Phase 5 · Synthesis<br/>verdict"]
        P6["Phase 6 · Evaluation<br/>continue / complete"]
    end

    MISSION[("MISSION.md")]
    ORGCHART[("state/org_chart.json")]
    CKPT[("state/checkpoint.json")]
    MEM[("state/role_memory/*.json")]
    DEPT[("departments/*_POLICY.md")]
    HIST[("history/*.jsonl")]
    PODS[("pods/transcripts/*")]

    subgraph OBS["Observability (operator-owned, agent-write-locked)"]
        DASH["observability/dashboard.py<br/>(read-only, stdlib)"]
        WEB["web/ (index.html, app.js, style.css)"]
        BROWSE["browser<br/>http://127.0.0.1:8090"]
    end

    DONE["SessionResult"]

    BAT --> RS
    BAT --> DASH
    ENV --> CFG
    ENV --> MKB
    CFG --> RS
    MKB --> RAW
    RS --> MB
    MB --> RB
    RB --> TB
    TB --> RAW

    RS --> P1
    P1 --> P2 --> P3 --> P4
    P4 --> P5 --> P6
    P6 -->|continue (bounded by MAX_ITERATIONS)| P4
    P6 -->|complete| DONE

    P2 -->|approve (only write path)| MISSION
    P3 --> DEPT
    P3 --> ORGCHART
    P1 --> HIST
    P2 --> HIST
    P3 --> HIST
    P4 --> HIST
    P4 --> PODS
    MB --> MEM
    RS --> CKPT

    HIST --> DASH
    PODS --> DASH
    DASH --> WEB --> BROWSE

    RO -->|wipe| DEPT
    RO -->|wipe| ORGCHART
    RO -->|wipe| MISSION
```

### 7.4 Optional follow-up diagrams (not yet created)

- **Org chart** — the `OrgState` reporting lines (leader → heads → managers
  → ICs) as a `flowchart` (data: `state/org_chart.json`).
- **State flow** — a `sequenceDiagram` of a single run: producers → files →
  consumers over time (data: §6.3).

---

## 8. Consolidated findings and recommendations

Severity: **Critical > High > Medium > Low > Info**. No Critical or High
findings.

| ID | Sev | Area | Finding | Recommendation |
|---|---|---|---|---|
| M-1 | Medium | Docs | `Organization_Outline.md`, `EXECUTION_CHECKLIST.md`, `OBSERVABILITY_CHECKLIST.md` are referenced by `README.md`, `SETUP.md`, and `org/tiers.py` / `roles/leader.py` docstrings but are absent (head commit "Remove old epic"). Design rationale is partially orphaned. | Restore the docs, or update the references to point at the surviving rationale (the strong module docstrings + `SETUP.md`). |
| M-2 | Medium | Config | `.env.example` lists 4 knobs (`POD_MIN_ROLES`, `POD_MAX_ROLES`, `CONTEXT_BUDGET_TOKENS`, `ROLE_MEMORY_MAX_ENTRIES`) that `runtime/config.py` **intentionally does not map** (dead — an "unused .env key" warning fires). The doc implies they are active. | Mark the 4 knobs as "not currently wired" in `.env.example` (or re-wire them in `runtime/config.py` if they are meant to be live). |
| M-3 | Medium | Invariants | `can_read_code` and `cross_team_read` (`org/tiers.py`) are **documented as not yet enforced** in the live path (advisory, Story 10 A11) — there is no code-read gate to wire them into. | Either implement a code-read gate in the pipeline and wire the two invariants in, or keep the explicit "advisory" note so the gap stays visible (current state is acceptable — it is documented, not silently dead). |
| L-1 | Low | Layout | `reports/` is referenced (`.gitignore`, `reset_org.py`, README) but absent on disk; created on demand by the code. | No action needed (consistent). Optionally add a `.gitkeep` so the dir is present. |
| L-2 | Low | Layout | `stories/` is empty, untracked, and unreferenced by code or docs (leftover). | Remove it, or track/populate it if it has a purpose. |
| L-3 | Low | Docs | `README.md` "Layout" block does not list `observability/` (which exists and is operator-owned). | Add `observability/` to the README layout. |
| L-4 | Low | Architecture | The pipeline writes to CWD-relative paths; `run_session.py --dry-run` relies on `os.chdir`. Couples the pipeline to the working directory. | Acceptable (documented). If more isolation is wanted, thread a base-dir parameter instead of `os.chdir`. |
| L-5 | Low | Architecture | `runtime/dispatch.py` (32.6KB) and `runtime/llm_api.py` (37.1KB) are large; `dispatch` mixes decomposition, upward reports, self-edit gating, and pod triggers. | Candidate for future decomposition (not a defect). |
| I-1 | Info | State | `archives/` is empty (expected — no session rollover yet). | No action. |
| I-2 | Info | State | `state/checkpoint.json` is a stale checkpoint from a prior live run (phase 4, cycle 1); a fresh run overwrites it. | No action. |
| I-3 | Info | State | `pods/transcripts/` holds 16 pods from a prior live run (generated state). | No action. |
| I-4 | Info | Security | **Positive:** the permission layer (sandbox, mission lock, meta-rule lock, `observability/` operator-lock) is enforced and fully covered by `tests/test_permissions.py`; no secrets in the tree; `.env` git-ignored. | No action. |
| I-5 | Info | Testing | **Positive:** all tests pass (operator-verified); the suite is offline and deterministic (`StubBackend`), with one test file per area (22 files). | No action. |
| I-6 | Info | Architecture | **Positive:** the module dependency graph is a clean DAG with no cycles; the pure/testable core sits at the leaves; the dashboard is decoupled from the runtime (shares only on-disk artifacts). | No action. |

### 8.1 Overall assessment

The repository is **well-architected and healthy**: a clean, acyclic module
graph; a stdlib-only core with a swappable LLM backend; real loop/budget
bounds with a consistent "visible, never silent" degradation philosophy; a
strong, tested permission layer; atomic writes and checkpointing for crash
recovery; and an offline, deterministic test suite (all passing). The findings
are minor: a few documentation gaps (M-1, L-3), a config-doc inconsistency
(M-2), one documented-but-unenforced invariant (M-3), and a couple of leftover
directories (L-1, L-2). None affect correctness or security.

---

## 9. Audit log (progression)

| # | Step | Result |
|---|---|---|
| 1 | Explored the repo structure (all directories + files, sizes). | Inventoried ~100 in-scope files across 13 top-level dirs; excluded `.venv/`, `__pycache__/`, `.git/`. |
| 2 | Read the key files (README, SETUP, entry points, `runtime/`, `org/`, `roles/`, config, state, artifacts). | Understood the 6-phase pipeline, the backend chain, the invariants, the permission layer, and the generated state. |
| 3 | Mapped interconnections (import analysis of every module). | Built the module dependency graph (§6.1) — a clean DAG, no cycles. |
| 4 | Checked VCS state (branches, log, status, remotes). | Git repo, `master` in sync with `origin`, story branches S1–S12 + `Track_A_Dashboard`, PRs #4–#13 merged, working tree clean. |
| 5 | Ran the test suite in the audit sandbox. | Blocked by `PermissionError` (pytest temp dirs outside `D:\LLM`) — environmental. **Operator confirmed all tests pass.** |
| 6 | Wrote `AUDIT.md` in batches (via a sentinel + edit): metadata + plan (§0–§1), process review (§2), directory review (§3), file review (§4), code review (§5), interconnections (§6), Mermaid diagram + where/how (§7), consolidated findings + audit log (§8–§9). | This document is complete. |

**Status: audit complete.** All six workstreams (WS1–WS6) are checked off in
§1.4; the Mermaid diagram is embedded in §7.3 with where/how instructions in
§7.1–§7.2; findings are consolidated in §8.

---

*End of AUDIT.md*
