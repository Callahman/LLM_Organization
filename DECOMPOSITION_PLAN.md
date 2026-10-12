# Decomposition Plan

A plan to split the large, mixed-responsibility files in **Tier 1** and **Tier 2**
into smaller, single-concern modules — **without changing behavior** and **without
breaking any existing import**.

- **Tier 1 (5 files):** `runtime/dispatch.py`, `runtime/llm_api.py`, `runtime/session.py`,
  `runtime/org.py`, `observability/web/app.js`
- **Tier 2 (7 files):** `observability/dashboard.py`, `org/tiers.py`, `runtime/pods.py`,
  `runtime/intake.py`, `runtime/mission.py`, `roles/base.py`, `roles/leader.py`

Total: **12 files**, ~7,000 lines today.

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

### 1. `runtime/dispatch.py` (1073 → ~340)

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

### 2. `runtime/llm_api.py` (740 → ~150)

**Responsibilities today:** `make_backend()` factory; `OpenAIBackend` (httpx HTTP,
chunk streaming, progress-based idle timeout + wall-clock backstop, tool-call stats,
stream records); `RoutingBackend` (complexity classification, thinking budget,
invocation logging).

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/llm_api.py` | `make_backend()` factory only. **Facade** re-exporting `OpenAIBackend`, `RoutingBackend`. | 150 |
| `runtime/openai_backend.py` | `OpenAIBackend` (HTTP + streaming + idle timeout + backstop + tool-call/stream emission). | 420 |
| `runtime/routing_backend.py` | `RoutingBackend` (level classification via `classify_complexity`, thinking budget, invocation logging). | 200 |

**Notes / risks:**
- The backend chain (Memory → Routing → Timeout → raw) is assembled in
  `session.build_backend`; it imports the classes by name, so the facade keeps that
  working unchanged.
- Keep the `LLMBackend` interface import in each new module (from `runtime.llm`).

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

### 7. `org/tiers.py` (443 → ~120)

**Responsibilities today:** tier math (constants, `tier_of`, `is_head`, `is_leader`,
`is_code_path`); read rules (`can_read`, `cross_team_read`); code-read rule;
communication rule (`can_communicate`); pod rule (`validate_pod`).

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `org/tiers.py` | Tier math (constants, `tier_of`, `is_head`, `is_leader`, `is_code_path`). **Facade** re-exporting `can_read`, `cross_team_read`, `can_communicate`, `validate_pod` (and `POD_MIN_ROLES`/`POD_MAX_ROLES`). | 120 |
| `org/read_rules.py` | `can_read`, `cross_team_read`, code-read check. | 130 |
| `org/communication.py` | `can_communicate`. | 110 |
| `org/pod_rules.py` | `validate_pod` + `POD_MIN_ROLES`/`POD_MAX_ROLES`. | 100 |

**Notes / risks:**
- `tiers` is imported as a **module** everywhere (`from org import tiers`,
  `tiers.can_read(...)`). The facade **must** re-export all rule functions so those
  call sites keep working unchanged. This is the highest-compat-sensitivity split.

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

### 9. `runtime/intake.py` (379 → ~250)

**Responsibilities today:** `run_intake` (Phase 1 Q&A loop); intake result structure;
question/answer extraction + normalization; prompt assembly; confidence/assumption
logic.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/intake.py` | `run_intake` main loop. **Facade** re-exporting the result + support API. | 250 |
| `runtime/intake_support.py` | Intake result structure, question/answer extraction + normalization, prompt assembly, confidence/assumption logic. | 130 |

**Notes / risks:**
- Light split; `intake.py` is already fairly cohesive. Extract only the non-loop
  helpers.

---

### 10. `runtime/mission.py` (375 → ~220)

**Responsibilities today:** `run_mission` (Phase 2 flow + approval); `_render_mission`;
draft extraction/normalization; success-criteria parsing; versioning.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `runtime/mission.py` | `run_mission` flow + user-approval path. **Facade** re-exporting the doc API. | 220 |
| `runtime/mission_doc.py` | `_render_mission`, draft extraction/normalization, success-criteria parsing, versioning. | 150 |

**Notes / risks:**
- `_render_mission` is imported by `run_session.py` (`from runtime.mission import
  _render_mission`) — the facade keeps that working.

---

### 11. `roles/base.py` (374 → ~250)

**Responsibilities today:** `Role` dataclass (identity + contract + org linkage +
envelope); `to_dict`/`from_dict`; `label()`; `spin_personality()` /
`spin_sub_architype()`.

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `roles/base.py` | `Role` dataclass + `label()` + `to_dict`/`from_dict`. **Facade** re-exporting the spinners. | 250 |
| `roles/identity.py` | `spin_personality` + `spin_sub_architype` + identity constants. | 90 |

**Notes / risks:**
- Keep `to_dict`/`from_dict` as **methods** on `Role` (extracting them to module
  functions would change call sites). Only the spinners move.

---

### 12. `roles/leader.py` (361 → ~120)

**Responsibilities today:** `make_leader()`; leader output-schema builders (intake
questions/answers, mission draft, `org_recommendation`, synthesis verdict, evaluation,
efficiency action).

**Target layout:**

| File | Contents | ~Lines |
|---|---|---|
| `roles/leader.py` | `make_leader()`. **Facade** re-exporting the schema builders. | 120 |
| `roles/leader_schemas.py` | All leader output-schema builders (grouped by phase). | 240 |

**Notes / risks:**
- `make_leader()` is imported by `run_session.py` — the facade keeps that working.

---

## Execution order

Each step is independent (facades preserve imports) and must leave the offline test
suite green before the next begins. Suggested order (lowest dependency first):

| Phase | Files | Rationale |
|---|---|---|
| **A** | `roles/base.py`, `roles/leader.py`, `org/tiers.py` | Leaf modules, pure extraction, highest-compat facades. |
| **B** | `runtime/pods.py` | Needed before `dispatch.py`. |
| **C** | `runtime/llm_api.py` | Self-contained backend split. |
| **D** | `runtime/org.py` | Resourcing split. |
| **E** | `runtime/session.py` | Orchestrator split (uses backend + org). |
| **F** | `runtime/dispatch.py` | Largest; depends on `pods.py` (B). |
| **G** | `runtime/intake.py`, `runtime/mission.py` | Light Phase 1/2 splits. |
| **H** | `observability/dashboard.py`, `observability/web/app.js` | Independent; verify in a browser. |

Phases A–G are Python; H is the observability stack. H can run in parallel with A–G.

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
5. **Line-count audit:** confirm each original file shrank to its target and the new
   modules landed near their estimates.

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
| `runtime/` | 9 large files | 9 facades + **19** new focused modules |
| `org/` | 1 large file | 1 facade + **3** new modules |
| `roles/` | 2 large files | 2 facades + **2** new modules |
| `observability/` | 1 py + 1 js | 1 entry + **2** py modules; **4** js modules |

Every original file remains a thin, backward-compatible facade; the new modules are
small, single-concern, and independently testable.
