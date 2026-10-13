# Decomposition Plan

A plan to split the large, mixed-responsibility files in **Tier 1** and **Tier 2**
into smaller, single-concern modules — **without changing behavior** and **without
breaking any existing import**.

- **Tier 1 (5 files):** `runtime/dispatch.py`, `runtime/llm_api.py`, `runtime/session.py`,
  `runtime/org.py`, `observability/web/app.js`
- **Tier 2 (7 files):** `observability/dashboard.py`, `org/tiers.py`, `runtime/pods.py`,
  `runtime/intake.py`, `runtime/mission.py`, `roles/base.py`, `roles/leader.py`

Total: **12 files** audited; **7 proceed** (items 1–6, 8) and **5 are skipped**
(items 7, 9, 10, 11, 12 — the post-revert audit found those files already at or below
their target sizes, so splitting them would reduce nothing).

> **Revision (post-revert audit):** the "current" line counts below were corrected
> against the reverted baseline. Five of the original twelve items target files that
> are already small; three of them literally specified a post-split size *larger* than
> the file is today. Those items are marked **SKIPPED**. A **hard gate** now applies
> to every phase: the **largest file's line count must actually decrease** — a whole-
> class *move* that leaves an 800-line module does not count (a prior attempt on
> item 2 proved this: 877 → 78 + 866).

---

## Guiding principles

1. **No behavior change.** Every move is a pure refactor: code is relocated, not
   rewritten. Public function signatures, defaults, and return shapes stay identical.
2. **Backward-compatible facades.** After a split, the **original file re-exports the
   full public API** (both what it keeps and what moved to a new module). No importer
   needs to change. This is the primary safety mechanism.
3. **Single concern per module.** Each new module owns one responsibility area.
4. **Incremental + verifiable.** Each file is decomposed in its own step; after each
   step the offline test suite must be green before proceeding.
5. **Name the new module by its concern**, not by the old file (e.g. `pod_artifacts.py`,
   not `pods_2.py`).

> **Note on symbol boundaries:** responsibility areas below are identified precisely;
> a few internal helper names (noted inline) should be confirmed against the source
> during implementation. The area-to-module mapping is stable regardless.

---

## Tier 1

### 1. `runtime/dispatch.py` (1218 → ~340)

**Responsibilities today:** Phase 4 orchestration (`run_dispatch`), mandate
decomposition + structured-report assembly + confidence thresholds, role spinning
(via `org.hire`) + cap enforcement, pod convening + solo-step recording, automation
execution (`run_automation`), permission wiring (self-edit routing + code-edit/tool-call
logging), and efficiency instrumentation.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/dispatch.py` | `run_dispatch` orchestration + phase flow + efficiency instrumentation (thin `meter` calls). **Facade** re-exporting the public API. | 340 |
| `runtime/decompose.py` | Mandate splitting, structured-report assembly, confidence-threshold logic (the decomposition + report helpers). | 260 |
| `runtime/automation.py` | `run_automation` + script creation + subprocess execution (S22 lever 2). | 160 |
| `runtime/dispatch_pods.py` | Pod convening during dispatch + solo-pod step recording for the leader's out-of-pod work. | 150 |
| `runtime/dispatch_resourcing.py` | Role spinning (delegates to `org.hire`) + cap enforcement. | 120 |
| `runtime/dispatch_audit.py` | Permission wiring: self-edit routing (`write_file`/`apply_code_edits`/`read_file`) + code-edit/tool-call logging. | 140 |

**Notes / risks:**
- `run_dispatch` is the orchestrator; after extraction it should mostly *call* into the
  new modules. Keep it readable as the Phase 4 entry point.
- `dispatch_pods.py` depends on `runtime/pods.py` (see item 8) — decompose `pods.py`
  first or in the same phase.
- Efficiency instrumentation stays in `dispatch.py` (it is a thin set of `meter` calls,
  not a distinct module).

---

### 2. `runtime/llm_api.py` (877 → ~500)

**Responsibilities today:** `make_backend()` factory; `OpenAIBackend` (httpx
streaming, progress-based idle timeout, bounded retry on timeout/truncation,
tool-call parsing, content/text-shape fallback, stream emission, tool-call stats);
module-level helpers (`TOOL_NAME`, `TOOL_DESCRIPTION`, `_role_label`,
`_tool_call_problem`, `validate_and_quarantine`, `OpenAIOutputError`).
**Note:** `RoutingBackend` is **not** in this file — it lives in
`runtime/complexity.py` (alongside `classify_complexity` + `ThinkingBudget`) and is
imported from there by `runtime/session.py`.

**Technique (class-level split):** the file is dominated by a single ~700-line class,
so *moving the whole class* would not shrink the largest file (a prior attempt left an
~866-line module). Instead, extract the class's **pure parsing logic** into free
functions in `runtime/openai_parse.py`; the class methods become **thin delegations**
so the `OpenAIBackend._parse(...)` API stays callable and existing tests keep working.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/llm_api.py` | `make_backend()` factory only. **Facade** re-exporting the full public API. | 80 |
| `runtime/openai_backend.py` | `OpenAIBackend` (HTTP + streaming + idle timeout + retry + tool-call/stream emission + reporting) with thin delegation methods. | 500 |
| `runtime/openai_parse.py` | Free functions: `parse_completion`, `parse_tool_args`, `parse_json_documents`, `is_truncation`, `truncation_note`, `plausible_json_prefix`, `unbalanced_json`, `recover_tool_call`, `role_label`, `tool_call_problem`, `validate_and_quarantine`, `nested_type_warnings` + `OpenAIOutputError` + constants (`TOOL_NAME`, `TOOL_DESCRIPTION`, `_NESTED_OBJECT_KEYS`, `_TRUNCATION_ERR_PREFIXES`). | 400 |

**Notes / risks:**
- Keep the `LLMBackend` interface import in each new module (from `runtime.llm`).
- `validate_and_quarantine` is imported by `tests/test_envelope.py`; the facade keeps
  that working.
- The backend chain (Memory → Routing → Timeout → raw) is assembled in
  `session.build_backend`; it imports the classes by name, so the facade keeps that
  working unchanged.

---

### 3. `runtime/session.py` (732 → ~300)

**Responsibilities today:** `SessionResult`; `build_backend`; `Session`
(`__init__`, `run` main loop, `_phase`); BAU rules (`queue_user_input`, `halt_bau`,
`bau_active`); Phase 5 `_synthesis`; Phase 6 `_evaluate`; S22 `_finish_efficiency` /
`_efficiency_floor_action`; `_escalate`; checkpointing (`_active_role_ids`,
`_checkpoint`).

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/session.py` | `Session` class: `__init__`, `run`, `_phase`, `build_backend`. **Facade** re-exporting `SessionResult` + extracted entry points. | 300 |
| `runtime/session_result.py` | `SessionResult` dataclass. | 40 |
| `runtime/synthesis.py` | Phase 5: `run_synthesis(session, ...)` (extracted from `_synthesis`). | 120 |
| `runtime/evaluation.py` | Phase 6: `run_evaluation(session, ...)` (extracted from `_evaluate`). | 120 |
| `runtime/escalation.py` | Escalation path (`escalate(session, ...)`) + BAU rules (`BauController` or module fns for `queue_user_input`/`halt_bau`/`bau_active`). | 150 |
| `runtime/checkpoint.py` | Checkpointing: `active_role_ids(org)`, `checkpoint(session, ...)`. | 80 |
| `runtime/session_efficiency.py` | S22: `finish_efficiency(session, ...)`, `efficiency_floor_action(session, ...)`. | 100 |

**Notes / risks:**
- Extracted phase logic becomes **module functions that take `session`** (the stateful
  orchestrator stays in `session.py`). `Session.run` calls them.
- BAU + escalation are grouped because both are "stop / redirect the org" concerns.
- Keep `Session`'s public method names stable (it is constructed by `run_session.py`).

---

### 4. `runtime/org.py` (712 → ~260)

**Responsibilities today:** constants (`REQUIRED_DEPARTMENTS`, `DIRECT_IC_CAP`,
`MAX_ORG_ROLES`); errors; `OrgState`; approval matrix (`required_approver`, `_is_hr`,
`_call_approver`); role-definition resolution; IC cap; directory creation; Phase 3
`bootstrap` (+ head extraction/normalization); `hire` / `fire` (+ `_offload`,
`_subtree`); leader replacement.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/org.py` | Constants + errors + `OrgState` (the core registry). **Facade** re-exporting the full resourcing API. | 260 |
| `runtime/org_approvals.py` | Approval matrix: `required_approver`, `_is_hr`, `_call_approver`. | 90 |
| `runtime/org_bootstrap.py` | `bootstrap` + head extraction/normalization + required-department guarantee + IC cap + directory creation. | 250 |
| `runtime/org_resourcing.py` | `hire` + `fire` + `_offload` + `_subtree` + role-definition resolution. | 160 |
| `runtime/org_leader.py` | `replace_leader` + `run_leader_replacement_vote`. | 100 |

**Notes / risks:**
- Do **not** confuse `runtime/org.py` (Phase 3) with the `org/` package (`org/tiers.py`).
  New modules live under `runtime/`.
- `OrgState` is imported widely; keep it in `runtime/org.py` and re-export the rest so
  `from runtime.org import hire, fire, bootstrap, ...` keeps working.

---

### 5. `observability/web/app.js` (715 → ~60)

**Responsibilities today:** shared state + SSE client; canvas chart renderers; data
mapping; conversation monitor (active pod + historical pods); model-stream window;
five panels; `render()`.

**Target layout (multiple scripts, loaded in order):**

| File (load order) | Contents | ~Lines |
|---|---|---|
| `web/state.js` (1) | Shared globals: `state`, `expandedPods`, `$`, `PALETTE`. | 15 |
| `web/charts.js` (2) | Chart helpers (`prepCanvas`, `drawEmpty`, `fmtDur`, `timeBounds`, `valueAt`, `drawLegend`, `drawTimeSeries`, `drawBars`) + data mapping (`buildCumulativeSeries`, `PHASE_COLORS`, `buildCycleGroups`). | 300 |
| `web/monitor.js` (3) | Conversation monitor (`podEntryText`, `isAtBottom`, `renderMonitor`, `renderPodList`) + `renderModelStream`. | 160 |
| `web/panels.js` (4) | `renderHeadcountChips`, `renderHaltList`, `renderEfficiencyPanel`, `renderS22EfficiencyPanel`, `renderStaleness`. | 150 |
| `web/app.js` (5) | `setStatus`, `connect`, `render` (calls into the other modules), and the final `connect()` call. | 60 |

**Notes / risks:**
- These are **classic scripts** (no `import`/`export`), so they share the global
  lexical scope. Declare shared globals in the **first-loaded** file (`state.js`) so
  later files can reference them at runtime.
- `index.html` must add `<script>` tags for `state.js`, `charts.js`, `monitor.js`,
  `panels.js` **before** `app.js`.
- The dashboard already serves `/web/*` by basename (`_Handler.do_GET`), so **no
  server change** is needed to serve the new files.
- Verify in a browser (SSE + charts + monitor + stream) after the split.

---

## Tier 2

### 6. `observability/dashboard.py` (454 → ~70)

**Responsibilities today:** `Watcher` (tail logs + transcripts; pure `ingest_*`;
`poll`; `snapshot`; `seed_*`); HTTP `_Handler`; `make_server`; `_watch_loop`; `main`.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `observability/dashboard.py` | `_watch_loop` + `main()` entry point (imports `Watcher` + server). **Facade** re-exporting `Watcher`. | 70 |
| `observability/watcher.py` | `Watcher` class (ingest + poll + snapshot + seed). | 300 |
| `observability/server.py` | `_Handler` + `make_server`. | 80 |

**Notes / risks:**
- `main()` is the `python observability/dashboard.py` entry point; keep it here.
- `Watcher`'s pure `ingest_*` methods should stay unit-testable (no files) — move them
  intact.

---

### 7. `org/tiers.py` — SKIPPED (post-revert audit)

**Audit:** the file is **195 lines** (the plan's 443 estimate was stale). It is
already small and cohesive (tier constants + read/communication/pod rules). Splitting
it would produce 29–63-line fragments with no meaningful reduction of the largest
file. **Decision:** leave as-is.

---

### 8. `runtime/pods.py` (407 → ~190)

**Responsibilities today:** `Pod` dataclass; `form_pod` / `chained_pod` /
`senior_member`; `_pod_ctx`; `run_pod`; `write_transcripts` /
`write_decision_artifact`; solo-pod support (`form_solo_pod`, `record_solo_step`,
`SoloTracker`).

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/pods.py` | `Pod` + `form_pod` + `chained_pod` + `senior_member` + `run_pod` + `_pod_ctx` (core mechanics). **Facade** re-exporting artifact + solo APIs. | 190 |
| `runtime/pod_artifacts.py` | `write_transcripts` + `write_decision_artifact`. | 120 |
| `runtime/solo_pods.py` | `form_solo_pod` + `record_solo_step` + `SoloTracker`. | 100 |

**Notes / risks:**
- `run_pod` calls `write_transcripts`; import it from `pod_artifacts` (or keep the call
  via the facade).
- Decompose **before** `dispatch.py` (item 1), since `dispatch_pods.py` depends on it.

---

### 9. `runtime/intake.py` — SKIPPED (post-revert audit)

**Audit:** the file is **244 lines** (the plan's 379 estimate was stale). The plan's
own target (~250) is *larger* than the file is today, so the split as specified would
reduce nothing. **Decision:** leave as-is.

---

### 10. `runtime/mission.py` — SKIPPED (post-revert audit)

**Audit:** the file is **206 lines** (the plan's 375 estimate was stale). The plan's
own target (~220) is *larger* than the file is today, so the split as specified would
reduce nothing. **Decision:** leave as-is.

---

### 11. `roles/base.py` — SKIPPED (post-revert audit)

**Audit:** the file is **176 lines** (the plan's 374 estimate was stale). The plan's
own target (~250) is *larger* than the file is today, so the split as specified would
reduce nothing. **Decision:** leave as-is.

---

### 12. `roles/leader.py` — SKIPPED (post-revert audit)

**Audit:** the file is **196 lines** (the plan's 361 estimate was stale) and is ~150
lines of a single `LEADER_MANDATE` string constant plus `make_leader()`. Splitting it
would reduce the largest file by at most ~40 lines. **Decision:** leave as-is.

---

## Execution order

Each step is independent (facades preserve imports) and must leave the offline test
suite green before the next begins. **Revised order (post-revert audit):** items 7, 9,
10, 11, 12 are skipped; the remaining phases run by value (largest reduction first),
with `pods.py` before `dispatch.py` (dependency of `dispatch_pods.py`).

| Phase | Files | Rationale |
|---|---|---|
| **1** | `runtime/org.py` | 24 top-level units, pure function moves; 712 → ~260 (−63%). |
| **2** | `runtime/pods.py` | Needed before `dispatch.py`; proven split; 407 → ~190+. |
| **3** | `runtime/dispatch.py` | Largest; 30 top-level functions, pure moves; 1218 → ~340 (−72%). |
| **4** | `runtime/llm_api.py` | Class-level split (parse methods → free functions); 877 → ~500 (−43%). |
| **5** | `runtime/session.py` | Method extraction (module fns taking `session`); 732 → ~300 (−59%). |
| **6** | `observability/dashboard.py` | watcher/server are top-level units; 454 → ~70 (−85%). |
| **7** | `observability/web/app.js` | Function-level; verify in a browser; 715 → max ~300 (−58%). |

**Hard gate (per phase):** the **largest file's line count must actually decrease**,
verified by a line-count audit after each phase. A whole-class *move* that leaves an
800-line module does **not** count.

---

## Verification strategy

1. **Offline test suite green after every phase** (the project is offline-by-design via
   `StubBackend`).
2. **Import smoke test** per phase: for each original file, assert its full public API
   is still importable (the facade). E.g.
   `from runtime.org import hire, fire, bootstrap, OrgState` still works.
3. **No-diff behavior check:** run a bounded unattended session
   (`run_session.py` with `LLM_BACKEND=stub`) before and after; compare the resulting
   `history/*.jsonl` + `state/*` outputs (should be identical modulo timestamps).
4. **Browser check** for Phase H: SSE connects, charts render, active-pod + model-stream
   update, panels populate.
5. **Line-count audit (hard gate):** confirm the **largest file's line count actually
   decreased** and the new modules landed near their estimates.

---

## Non-goals

- **No API redesign.** Signatures, defaults, and return shapes are unchanged.
- **No renaming of public symbols** (facades re-export the original names).
- **No changes to the backend chain, pipeline phases, or invariants.**
- **No refactoring of Tier 3 files** (`style.css`, `efficiency.py`, `llm.py`,
  `permissions.py`) — out of scope.

---

## Resulting module count

| Area | Before | After |
|---|---|---|
| `runtime/` | 5 large files (org, pods, dispatch, llm_api, session) | 5 facades + **19** new focused modules (org ×4, pods ×2, dispatch ×5, llm_api ×2, session ×6) |
| `org/`, `roles/` | — | unchanged (items 7, 11, 12 skipped) |
| `observability/` | 1 py + 1 js | 1 entry + **2** py modules; **4** js modules |

Every original file remains a thin, backward-compatible facade; the new modules are
small, single-concern, and independently testable.
