# STORIES — Audit follow-up work

> **STATUS: PENDING USER APPROVAL — do NOT begin executing any of these
> stories until the user approves this markdown.**

This document organizes the audit-follow-up requests (all related to
`AUDIT.md` findings) into actionable stories. Each story lists its **type**,
the **request(s)** it addresses, **context**, **acceptance criteria**,
**affected files**, **dependencies**, and any **open questions** that need
answering before execution.

---

## How to read this

- **Type**
  - **Implement** — a code change.
  - **Investigate-Explain** — analysis + a recommendation, producing a doc
    (no pipeline behavior change yet).
  - **Cleanup** — remove / edit (docs, leftover dirs, audit text).
  - **Verify** — confirm the current behavior already satisfies the request.
- **Waves** group the stories into an execution order by risk and dependency.
- Stories marked **⚠️** have an **open question** that must be answered before
  they can be executed.
- Story IDs continue the repo's existing `S1`–`S12` convention (these are
  `S13`–`S26`).

---

## Request → Story mapping

| # | Request (as given) | Story |
|---|---|---|
| 1 | Mermaid diagram | S13 |
| 2 | Implement trade-off logic | S22 |
| 3 | Mission + reduced runtime / improved efficiency | S22 |
| 4 | Solo pods should track any role's work done outside of a pod | S21 |
| 5 | Default run should use `--revisit`; revisit from last known checkpoint → last phase → fresh-run if no `Mission.md` | S15 |
| 6 | If `mission.md` doesn't exist, make sure the environment is cleared (run reset-org before continuing) | S16 |
| 7 | Enforce all invariants (audit §2.4) | S14 |
| 8 | Remove the reference to missing docs in audit §2.6 | S25 |
| 9 | Per audit §3.1, validate if `stories/` is referenced by any other process; if not, remove | S26 |
| 10 | Make sure `reports/` gets the same treatment as similar directories managed by the org | S18 |
| 11 | Add observability to the README | S19 |
| 12 | 4.5 F-1: explain why the knobs are dropped but also explicitly referenced; deprecated code that can be removed? need to be rewired in? | S20 |
| 13 | Make sure `state/checkpoint.json` and `pods/transcripts/` are removed via reset_org | S17 |
| 14 | Explain how you would decompose dispatch and llm_api | S24 |
| 15 | Output the steps in `DECOMP_SCRIPTS.md` | S24 |
| 16 | Mermaid diagram rendered natively within the README (output in the root or reference in the README) | S13 |

---

## Overview

| Story | Title | Type | Wave | Priority | Notes |
|---|---|---|---|---|---|
| S13 | Mermaid diagram rendered natively in the README | Implement | 1 | High | Request #1, #16 |
| S19 | Add observability to the README | Implement | 1 | Medium | Request #11 |
| S25 | Remove audit §2.6 missing-docs references | Cleanup | 1 | Low | Request #8 |
| S20 | F-1 knobs: explain why dropped + referenced; deprecate or rewire? | Investigate-Explain | 1 | Medium | Request #12 |
| S24 | Decompose `dispatch` + `llm_api`: explain + `DECOMP_SCRIPTS.md` | Investigate-Explain → Implement | 1 | Medium | Request #14, #15 |
| S26 | Validate `stories/` references; remove if none | Verify → Cleanup | 1 | Low | Request #9 |
| S17 | Verify reset_org removes `state/checkpoint.json` + `pods/transcripts/` | Verify | 2 | Low | Request #13 — likely already satisfied |
| S18 | `reports/` same treatment as similar org-managed dirs | Implement | 2 | Low | Request #10 |
| S16 | Clear the environment when no `Mission.md` (reset before continuing) | Implement | 2 | High | Request #6 |
| S15 | Default run uses `--revisit`; revisit from checkpoint → last phase → fresh | Implement | 2 | High | Request #5 |
| S14 | Enforce all invariants (audit §2.4) | Implement | 3 | High | Request #7 |
| S21 | Solo pods track any role's work done outside a pod | Implement | 3 | Medium | Request #4 |
| S22 | Efficiency trade-off in the Phase 3–6 loop (time-to-complete + headcount; incentivize fewer roles / more automation) | Implement | 4 | High | Request #2, #3 |

---

## Wave 1 — Low-risk docs/cleanup + investigation

> These are low-risk (docs, audit edits, analysis) and produce understanding
> that later waves rely on. Safe to start first.

### S13 — Mermaid diagram rendered natively in the README

- **Type:** Implement
- **Requests:** #1, #16
- **Context:** The full-process Mermaid diagram already exists, embedded in
  `AUDIT.md` §7.3. The user wants it **rendered natively within the README**.
  On GitHub/GitLab a Mermaid block renders natively **only if the block is in
  the rendered Markdown** — i.e., directly in `README.md`. "Referencing" an
  external `.md` file will **not** render its diagram in the README.
- **Open question (minor):** Embed directly in `README.md` (recommended — the
  only way it renders natively there), and/or also keep a copy in a root
  `PROCESS.md`? Default: **embed in `README.md`**, optionally also write a
  root `PROCESS.md` with the same block.
- **Acceptance criteria:**
  - [x] A ` ```mermaid ` block of the full-process diagram is present in
        `README.md` (new "Process diagram" section, after the pipeline) and
        renders natively on GitHub/GitLab.
  - [ ] The diagram is validated (renders with no syntax error) — **pending
        user check**: copied verbatim from `AUDIT.md` §7.3 (the validated
        source); please confirm it renders.
  - [ ] (Optional) A root `PROCESS.md` carries the same block — **skipped**
        (README-only per the default).
- **Affected files:** `README.md`; (optional) `PROCESS.md`.
- **Dependencies:** None (diagram already exists in `AUDIT.md` §7.3 to copy).

### S19 — Add observability to the README

- **Type:** Implement
- **Requests:** #11
- **Context:** Audit finding F-2 / L-3: the `README.md` "Layout" block does
  not list `observability/` (which exists and is operator-owned,
  agent-write-locked).
- **Acceptance criteria:**
  - [x] `observability/` is listed in the `README.md` "Layout" block.
  - [x] A short "Observability" subsection describes the read-only dashboard
        (how to start it: `python observability/dashboard.py --port 8090`; that
        it tails `history/*.jsonl`, `state/`, `pods/transcripts/`; that it is
        operator-owned and agent-write-locked).
- **Affected files:** `README.md`.
- **Dependencies:** None.

### S25 — Remove audit §2.6 missing-docs references

- **Type:** Cleanup
- **Requests:** #8
- **Context:** Audit §2.6 ("Documentation gaps — referenced-but-missing docs")
  documents that `Organization_Outline.md`, `EXECUTION_CHECKLIST.md`, and
  `OBSERVABILITY_CHECKLIST.md` are referenced but absent. The user wants this
  reference removed from the audit.
- **Acceptance criteria:**
  - [x] `AUDIT.md` §2.6 (the missing-docs section) is removed.
  - [x] Any cross-references to §2.6 elsewhere in `AUDIT.md` (the §4.0
        README/SETUP rows and the §5.6 bullet) are updated so there are no
        dangling references. §8 M-1 remains — it is an independent, accurate
        consolidated finding (it does not reference §2.6, and the repo files
        genuinely still cite those docs).
  - [x] Section numbering in `AUDIT.md` remains consistent after removal.
- **Affected files:** `AUDIT.md`.
- **Dependencies:** None.

### S20 — F-1 knobs: explain why dropped + referenced; deprecate or rewire?

- **Type:** Investigate-Explain
- **Requests:** #12
- **Context (from `runtime/config.py`):** In Story 8 (B18/C2), 4 knobs
  (`POD_MAX_ROUNDS`, `DIRECT_IC_CAP`, `HISTORY_WINDOW_SESSIONS`,
  `ARCHIVE_CAP_MB`) were plumbed into `ENV_TO_CONFIG` (consumed by their
  single consumers). The **other 4** (`POD_MIN_ROLES`, `POD_MAX_ROLES`,
  `CONTEXT_BUDGET_TOKENS`, `ROLE_MEMORY_MAX_ENTRIES`) were **intentionally
  dropped** from the map so that, if set in `.env`, the "unused .env key"
  warning fires (visible, not silently ignored). They are still listed in
  `.env.example`.
- **Analysis to produce:**
  - These are **unwired knobs, not deprecated code** — they were considered
    but never connected to a consumer. The hardcoded values live elsewhere:
    - `POD_MIN_ROLES` / `POD_MAX_ROLES` → pod size bounds are hardcoded in
      `org/tiers.py::validate_pod` (2–6).
    - `CONTEXT_BUDGET_TOKENS` → token budget in `runtime/context.py`
      (`estimate_tokens` / `bounded_assembly`).
    - `ROLE_MEMORY_MAX_ENTRIES` → memory cap in `runtime/llm.py`
      (`MemoryBackend`).
  - Two options:
    - **(a) Wire them in** — parameterize the hardcoded bounds so the knobs
      take effect.
    - **(b) Remove them from `.env.example`** — since they are not consumed,
      drop them from the template to avoid implying they are active.
- **Recommendation (produced):** **(a) Wire them in.** All four are genuine
  tuning knobs whose consumers already exist (`org/tiers.py`,
  `runtime/context.py`, `runtime/llm.py`), and `.env.example` already implies
  they are active — so making them active is the consistent choice and gives
  the user real control (pod size bounds, context token budget, role-memory
  cap). If you prefer minimal scope, **(b) remove from `.env.example`** is also
  clean (a one-line-per-knob doc change, no code change).
- **Open question (blocks the fix only):** Wire them in (a) or remove from the
  template (b)? (The current "warning fires" behavior is intentional and
  acceptable either way.)
- **Acceptance criteria:**
  - [x] A written explanation of why the 4 knobs are dropped yet still
        referenced, and that they are unwired (not deprecated) — recorded above.
  - [x] A recommendation (wire-in vs. remove-from-template) recorded —
        **(a) wire-in** (see above).
  - [x] **Done (option (a) — wired in):** `POD_MIN_ROLES`/`POD_MAX_ROLES` →
        `org/tiers.py::validate_pod` (via `form_pod`/`chained_pod`),
        `CONTEXT_BUDGET_TOKENS` → `runtime/context.py::bounded_assembly` (via
        `run_pod`/`_pod_ctx`), `ROLE_MEMORY_MAX_ENTRIES` →
        `runtime/llm.py::MemoryBackend` (via `build_backend`). All plumbed
        through `runtime/config.py` `ENV_TO_CONFIG`.
- **Affected files:** `runtime/config.py`, `.env.example`; (if wiring)
  `org/tiers.py`, `runtime/context.py`, `runtime/llm.py`.
- **Dependencies:** None for the explanation; the fix depends on the user's
  (a)/(b) choice.

### S24 — Decompose `dispatch` + `llm_api`: explain + `DECOMP_SCRIPTS.md`

- **Type:** Investigate-Explain → (later) Implement
- **Requests:** #14, #15
- **Context:** Audit finding L-5: `runtime/dispatch.py` (32.6KB) and
  `runtime/llm_api.py` (37.1KB) are the two largest modules. `dispatch` mixes
  decomposition, upward reports, IC self-edit gating, and pod triggers;
  `llm_api` mixes the streaming client, structured-output (tool call)
  handling, validation/quarantine, idle-timeout, and retries.
- **Acceptance criteria:**
  - [x] A written explanation of how to decompose each module (proposed
        sub-modules, their responsibilities, and the public API each keeps) —
        in `DECOMP_SCRIPTS.md`.
  - [x] `DECOMP_SCRIPTS.md` created at the repo root with the **step-by-step
        decomposition plan** (ordered steps, file moves, import updates, and a
        verification checkpoint after each step).
  - [x] The plan is **non-breaking** (each step leaves the suite green).
  - [ ] (Later, as a separate implement story) the decomposition is executed
        per `DECOMP_SCRIPTS.md`.
- **Decomposition (detailed in `DECOMP_SCRIPTS.md`; flat modules to match the
  `runtime/` convention):**
  - `dispatch.py` → `dispatch_context.py` (context builders: `mission_digest`,
    `_leader/_head/_manager/_ic_ctx`), `dispatch_edits.py` (IC self-edit
    gating), `dispatch_pods.py` (pod triggers); `dispatch.py` keeps `dispatch()`
    + role lifecycle + helpers.
  - `llm_api.py` → `llm_parse.py` (output parsing / validation / truncation /
    recovery, as free functions); `llm_api.py` keeps `OpenAIBackend` +
    `make_backend`.
- **Affected files:** `DECOMP_SCRIPTS.md` (new); (later) `runtime/dispatch.py`,
  `runtime/llm_api.py` + new sub-modules + their tests.
- **Dependencies:** None for the plan; execution is a later story.

### S26 — Validate `stories/` references; remove if none

- **Type:** Verify → Cleanup
- **Requests:** #9
- **Context:** Audit §3.1 / D-2: `stories/` is empty, untracked, and
  (per the audit) not referenced by code or docs. The user wants this
  validated, and the dir removed if unreferenced.
- **Acceptance criteria:**
  - [x] A repo-wide search (code + docs + config + `.gitignore` + scripts)
        confirms `stories/` is referenced by **no** process (only `AUDIT.md`
        documents the anomaly + git history).
  - [x] `stories/` is removed (was empty, untracked).
  - [ ] If referenced: document + keep — **N/A** (it was unreferenced).
- **Affected files:** `stories/` (remove if unreferenced).
- **Dependencies:** None. (Note: this new `STORIES.md` lives at the repo root,
  **not** inside `stories/`, so removing `stories/` does not affect it.)

---

## Wave 2 — State / reset / run-mode

> These change how runs start and how state is wiped. S16/S15 are the core
> run-mode logic; S17/S18 are reset/housekeeping.

### S17 — Verify reset_org removes `state/checkpoint.json` + `pods/transcripts/`

- **Type:** Verify
- **Requests:** #13
- **Context (from `reset_org.py`):** `_collect_targets()` collects
  `DEPARTMENTS_DIR`, `STATE_DIR`, `PODS_DIR`, `REPORTS_DIR`, `ARCHIVES_DIR`
  (each if `os.path.isdir`), `MISSION_FILE` (if exists), and `history/*.jsonl`.
  With `--yes`, each dir target is `shutil.rmtree`'d. So the **whole `state/`
  dir** (which contains `checkpoint.json` and `role_memory/`) and the **whole
  `pods/` dir** (which contains `transcripts/` and `artifacts/`) are deleted.
- **Assessment:** The request is **already satisfied** — `checkpoint.json`
  and `transcripts/` are removed because their parent dirs are `rmtree`'d.
- **Confirmation (S17 done):** Verified in `reset_org.py` — `_collect_targets()`
  includes `STATE_DIR` (`state/`) and `PODS_DIR` (`pods/`) in the targets list
  (each if `os.path.isdir`), and `main()` does `shutil.rmtree(t)` for each dir
  target. So `state/checkpoint.json` (inside `state/`) and `pods/transcripts/`
  (inside `pods/`) are removed when `state/` and `pods/` are `rmtree`'d. No gap
  found; no code change needed.
- **Acceptance criteria:**
  - [x] Confirm (by reading `reset_org.py`) that `state/` and `pods/` are
        `rmtree`'d, so `state/checkpoint.json` and `pods/transcripts/` are
        removed.
  - [x] Record the confirmation in this story (no code change expected).
  - [ ] (Only if a gap is found) add explicit removal of the two paths.
- **Affected files:** `reset_org.py` (verify only; change only if a gap is
  found).
- **Dependencies:** None.

### S18 — `reports/` same treatment as similar org-managed dirs

- **Type:** Implement
- **Requests:** #10
- **Context:** Audit §3.1 / D-1: `reports/` is referenced (`.gitignore`,
  `reset_org.py` `REPORTS_DIR`, README) but **absent on disk** (created on
  demand by `HistoryStore.write_evaluation_report`). Its siblings:
  `archives/` (present, empty), `history/` (present, `.gitkeep`), `pods/`,
  `state/`, `departments/` (present from a prior run). `reset_org.py` already
  lists `REPORTS_DIR` and `rmtree`s it; `.gitignore` already ignores its
  contents.
- **Interpretation:** "Same treatment as similar directories managed by the
  org" = make `reports/` consistent with its managed siblings — present on
  disk (with a `.gitkeep`, like `history/`) so it is not the one missing dir,
  while keeping the existing `reset_org.py` + `.gitignore` handling.
- **Confirmation (S18 done):** Created `reports/.gitkeep` so the `reports/` dir
  is present on disk (consistent with `history/`, `archives/`, `departments/`).
  `reset_org.py` already wipes `reports/` (via `REPORTS_DIR` in
  `_collect_targets()`), and `.gitignore` already ignores `reports/offloading/*`
  + `reports/evaluation/*` (with `.gitkeep` re-includes) — the top-level
  `reports/.gitkeep` is not ignored (so it is tracked). No `.gitignore` /
  `reset_org.py` changes needed.
- **Acceptance criteria:**
  - [x] Verify how each managed state dir (`history/`, `archives/`, `reports/`,
        `pods/`, `state/`, `departments/`) is handled by `reset_org.py` and
        `.gitignore`.
  - [x] Make `reports/` consistent with its siblings (e.g. create
        `reports/.gitkeep` so the dir is present, matching `history/`).
  - [x] `reset_org.py` continues to wipe `reports/` contents (and/or the dir)
        the same way it wipes its siblings.
  - [x] `.gitignore` continues to ignore `reports/` contents with a
        `.gitkeep` re-include (consistent with the other state dirs).
- **Affected files:** `reports/` (create `.gitkeep`), `.gitignore`,
  `reset_org.py` (verify/align).
- **Dependencies:** None.

### S16 — Clear the environment when no `Mission.md` (reset before continuing)

- **Type:** Implement
- **Requests:** #6
- **Context:** When `MISSION.md` does not exist, the run should treat it as a
  **fresh run** — and before continuing, **make sure the environment is
  cleared** (i.e., run the equivalent of `reset_org` so stale generated state
  from a prior run does not leak into the fresh run).
- **Acceptance criteria:**
  - [x] When `MISSION.md` is absent, the run triggers a reset of the generated
        state (reuse `reset_org._collect_targets()` / the same wipe logic)
        before proceeding as a fresh run.
  - [x] The reset is visible (logged / printed), consistent with the
        "visible, never silent" philosophy.
  - [x] A fresh run with no `MISSION.md` starts from a clean slate (no stale
        `state/`, `pods/`, `departments/`, `history/*.jsonl`).
  - [x] Coordinated with S15 (the fresh-run branch) so the decision logic is
        in one place.
- **Affected files:** `run_session.py`, `reset_org.py` (reuse wipe logic),
  `runtime/session.py` (fresh-run branch).
- **Dependencies:** S15 (shared run-mode decision logic).

**Confirmation (Wave 2):** `reset_org.py` now exposes a reusable
`wipe_state(verbose=True) -> list` (the same wipe logic as `reset_org --yes`,
built on `_collect_targets()`). In `run_session.py`, the run-mode decision
(`_decide_run_mode`, S15) returns a fresh run when `MISSION.md` is absent (or
`--fresh` is given), and `main()` calls `reset_org.wipe_state(verbose=True)`
before proceeding — the clear is visible (each deleted path is printed, plus
"Organization reset complete."). The decision logic is in one place (S15's
`_decide_run_mode`), and a revisit run does NOT clear (it resumes).

### S15 — Default run uses `--revisit`; revisit from checkpoint → last phase → fresh

- **Type:** Implement
- **Requests:** #5
- **Context:** The user wants the **default** run to use `--revisit` (rather
  than a fresh run). A revisit should resume from the **last known
  checkpoint** (`state/checkpoint.json`); if there is **no checkpoint**,
  resume from the **last phase**; if there is **no `MISSION.md`**, switch to
  a **fresh run** (which, per S16, clears the environment first).
- **Resume precedence (to implement):**
  1. `MISSION.md` absent → **fresh run** (clear environment per S16).
  2. `state/checkpoint.json` present → resume from the **checkpointed phase /
     cycle**.
  3. No checkpoint → resume from the **last phase** (determine "last phase"
     from available state, e.g. the highest phase with recorded output / the
     phase before the current one).
- **Open question (minor, resolved):** "Last phase" with no checkpoint is
  handled by re-clarifying from Phase 1 (the existing revisit behavior — the
  intake re-clarifies the goal, the mission continues, the org bootstraps
  additively). A revisit from a checkpoint at phase 3 or 4 skips Phases 1-3
  (the org + mission are loaded) and resumes from Phase 4.
- **Acceptance criteria:**
  - [x] `run_session.py` defaults to `--revisit` when no mode flag is given.
  - [x] Revisit resumes from `state/checkpoint.json` when present.
  - [x] Revisit falls back to the last phase when there is no checkpoint.
  - [x] Revisit switches to a fresh run (clearing the environment per S16)
        when `MISSION.md` is absent.
  - [x] The resume decision is visible (logged which mode + resume point was
        chosen).
- **Affected files:** `run_session.py`, `runtime/session.py`,
  `runtime/mission.py` (`load_mission`), `state/checkpoint.json`.
- **Dependencies:** S16 (fresh-run branch).

**Confirmation (Wave 2):** `run_session.py` now defaults to revisit (no mode
flag → revisit). The run-mode decision is in one place —
`_decide_run_mode(args, mission_path, checkpoint_path)` returns
`(mode, resume_point, resume_from_phase)`:
- `--fresh` (explicit) → fresh.
- `MISSION.md` absent → fresh (S16: clear the environment).
- `state/checkpoint.json` present → revisit from the checkpointed phase/cycle
  (a checkpoint at phase 3 or 4 → `resume_from_phase=4`, which skips Phases
  1-3 and resumes from Phase 4).
- No checkpoint → revisit from the last phase (re-clarify from Phase 1,
  `resume_from_phase=1`).

The decision is visible (`[run-mode] mode=…, resume from: …,
resume_from_phase=…`), and `runtime/session.py`'s `run()` accepts a
`resume_from_phase` param — when `resume_from_phase >= 4 and revisit`, Phases
1-3 are skipped (the org + mission are loaded in the revisit branch) and the
run resumes from Phase 4 (the dispatch continues); `intake`/`mission` are
passed as `None` (handled by `_escalate`).

---

## Wave 3 — Invariants + solo pods

### S14 — Enforce all invariants (audit §2.4)

- **Type:** Implement
- **Requests:** #7
- **Context:** Audit §2.4 lists the invariants and which are enforced.
  Currently **advisory (not enforced)** in the live path:
  - `can_read` — a role can only read its team's department directory.
  - `can_read_code` — department heads + the Leader cannot read any code.
  - `cross_team_read` — cross-team read restrictions.
  Already enforced: `validate_pod` (pod size/spread) and the permission layer
  (sandbox / mission lock / meta-rule lock). The rule math already exists in
  `org/tiers.py`; what is missing is a **code-read / read gate** in the
  pipeline to wire the invariants in.
- **Acceptance criteria:**
  - [ ] A read gate is added to the pipeline (e.g. in `runtime/dispatch.py` /
        `runtime/pods.py`) that consults `org.tiers.can_read`,
        `org.tiers.can_read_code`, and `org.tiers.cross_team_read` before a
        role reads a department dir or any code path.
  - [ ] Department heads and the Leader are blocked from reading code paths
        (visible refusal, consistent with the permission layer's style).
  - [ ] A role is blocked from reading another team's department directory
        (per `can_read` / `cross_team_read`).
  - [ ] Tests added covering each enforced invariant (block + allow cases).
  - [ ] The "advisory" notes in `org/tiers.py` docstrings are updated to
        "enforced" (or removed).
- **Affected files:** `org/tiers.py` (docstrings), `runtime/dispatch.py`,
  `runtime/pods.py`, `runtime/permissions.py` (gate integration), `tests/`.
- **Dependencies:** None. (Conceptually aligns with the permission layer.)

### S21 — Solo pods track any role's work done outside a pod

- **Type:** Implement
- **Requests:** #4
- **Context:** Today, solo pods (`runtime/pods.py::SoloTracker`) track the
  **Leader's** per-phase work (P1/P2/P3/P5/P6) so the dashboard can watch the
  Leader. The user wants solo pods to track **any role's** work done **outside
  of a pod** (not just the Leader's) — i.e., whenever a role does work that is
  not part of a multi-role pod, it is recorded as a solo pod.
- **Acceptance criteria:**
  - [ ] `SoloTracker` (or an equivalent) is generalized so **any role** can
        have solo-pod records for its out-of-pod work.
  - [ ] When a role performs work outside a pod (e.g. a head/manager/IC
        decomposition step, a self-edit, an upward report), it is recorded as
        a solo pod (transcript + jsonl) like the Leader's are.
  - [ ] The dashboard can view any role's solo pods (not only the Leader's).
  - [ ] Existing Leader solo-pod behavior is preserved (no regression).
  - [ ] Tests added for a non-Leader role producing a solo pod.
- **Affected files:** `runtime/pods.py` (`SoloTracker`), `runtime/session.py`,
  `runtime/dispatch.py` (record out-of-pod work), `observability/dashboard.py`
  (view any role's solo pods), `tests/`.
- **Dependencies:** None. (Aligns with the observability flow.)

---

## Wave 4 — Efficiency trade-off (fully specified)

> S22 and S23 are **synonymous** and are merged into a single story (S22). The
> open questions have been resolved with the user.

### S22 — Efficiency trade-off in the Phase 3–6 loop

- **Type:** Implement
- **Requests:** #2, #3 (merged — the trade-off logic **is** the efficiency
  mechanism)
- **Context:** The Leader, when deciding how the org functions across the
  Phase 3–6 loop, weighs two things:
  1. **Mission objective** — can the mission be completed (or its recurring
     target met) with acceptable quality?
  2. **Efficiency** — time-to-complete (total loop time, time per
     phase/department/role) and headcount/compute used.

  **The incentive:** if the mission can be completed with **LESS headcount /
  compute time**, that is **encouraged**. The key metric is **wall-clock
  uptime** (local compute) — LLM invocations / token cost are secondary since
  the model is locally hosted. **Scope:** the Phase 3–6 loop (the Leader's own
  per-phase work is already efficient; the org is slowed by too many ICs).
  **Constraints:** keep the user-approval gate, don't reduce mission quality,
  keep the invariants, keep it auditable.

- **The two levers:**
  1. **Dynamic headcount control** — the Leader/heads generate fewer roles
     (ICs) as needed and can offload/fire/replace them dynamically (see the
     firing rules below).
  2. **Automation over headcount** — for a recurring task, a head/manager
     spins up an IC to **write a Python script**, the script is created, the
     IC is **fired** if not needed for other work, and the recurring task is
     then done by **executing the script** (subprocess / tool call) instead of
     an IC each time.

- **Firing rules (from the user):**
  - A role can fire its **direct report** only.
  - Firing **cascades**: if that direct report has its own reports, the whole
    subtree is fired.
  - The **cascade size** (number of roles that would be fired) is **included
    in the request for HR approval** on the firing (not raised separately).
  - **Exception:** leader replacement (special case).
  - Everyone else persists — firing is bounded to the direct-report chain.

- **Efficiency score & threshold (from the user):**
  - *Measured per Phase 3–6 loop iteration (wall-clock, local compute):*
    `T_total` (total loop time), `T_p3…T_p6` (per phase), `T_dept` (per active
    department), `T_role` (per role), `H_peak` (peak concurrent headcount),
    `C` (total role-minutes = Σ active time per role = "compute-uptime"),
    `N_created` (roles spun up), and `M_satisfaction` (0–1, see below).
  - *Efficiency score:*
    `E = M_satisfaction / ( 0.5 · (T_total / T_ref) + 0.5 · (C / C_ref) )`
    where `T_ref` = **running average of `T_total` over the last 3
    iterations**, `C_ref` = **running average of `C` over the last 3
    iterations**, and the weights are fixed at 0.5 / 0.5 (not dynamically
    tuned).
  - *Threshold:* a **single** `EFFICIENCY_FLOOR` (default ~0.4). When
    `E < EFFICIENCY_FLOOR`, the Leader **must** take an efficiency action —
    reduce headcount, automate a recurring task, or (if the mission is
    satisfied) stop.
  - *Surfacing:* the **full per-phase / per-department / per-role breakdown**
    + `H_peak` + `C` + `N_created` + `E` are added to the Leader's Phase 5/6
    prompt (so the trade-off is explicit) and to the dashboard (a new
    **Efficiency** panel).

- **`M_satisfaction` (generalized for terminal AND recurring goals):**
  A plain progress-to-endpoint assumes a clear endpoint, but the org goal may
  be **recurring** (e.g. "continually deliver X% return on a process"). So the
  numerator is a 0–1 **mission-satisfaction** that handles both:
  - **Terminal mission** (clear endpoint): fraction of terminal success
    criteria met (→ 1.0 when complete).
  - **Recurring mission** (recurring target, e.g. X% return each cycle):
    attainment of the recurring target for the current cycle, e.g.
    `min(1, actual_return / target_return)` (optionally smoothed over recent
    cycles). "Satisfied" = the recurring target is met.
  The efficiency formula is unchanged; only the meaning of the numerator
  generalizes.

- **Acceptance criteria:**
  - [ ] The Phase 3–6 loop is instrumented with wall-clock timing
        (`T_total`, `T_p3…T_p6`, `T_dept`, `T_role`, `H_peak`, `C`,
        `N_created`) and the metrics are surfaced (auditable + dashboard
        **Efficiency** panel).
  - [ ] `M_satisfaction` is computed and handles both terminal and recurring
        goals (per the definition above).
  - [ ] `E` is computed per iteration (running-average references over the
        last 3 iterations, fixed 0.5/0.5 weights).
  - [ ] The Leader's Phase 5/6 prompt includes the full breakdown + `E` and a
        **mandate** to keep `E` high (minimize headcount/compute subject to
        mission satisfaction).
  - [ ] When `E < EFFICIENCY_FLOOR`, the Leader takes a visible efficiency
        action (reduce headcount / automate / stop).
  - [ ] Dynamic headcount control works: the Leader/heads can offload/fire
        roles (per the firing rules, with the cascade size included in the HR
        approval request).
  - [ ] The automation flow works: a recurring task → IC writes a script → IC
        fired → script executed instead of an IC.
  - [ ] No regression in mission quality / the existing invariants; the
        user-approval gate is preserved; everything is auditable.
  - [ ] Tests added: efficiency measurement, `E` computation, the
        `EFFICIENCY_FLOOR` trigger, the firing cascade + HR request, and the
        automation flow.

- **Affected files:** `runtime/session.py` (instrument the loop, Phase 5/6
  prompt + mandate), `runtime/org.py` (dynamic headcount, firing cascade + HR
  request), `runtime/dispatch.py` (per-phase/dept/role timing, automation
  flow), `runtime/context.py` (efficiency metrics into the prompt),
  `observability/dashboard.py` (Efficiency panel), `tests/`.
- **Dependencies:** None (fully specified). Builds on the existing
  `fire()` / `required_approver()` / `replace_leader()` in `runtime/org.py`.

---

## Suggested execution order

| Wave | Stories | Why this order |
|---|---|---|
| **1** | S13, S19, S25, S20, S24, S26 | Low-risk docs/cleanup + investigation; produces understanding (knobs, decomposition plan, `stories/` status) that later waves rely on. |
| **2** | S17, S18, S16, S15 | State/reset/run-mode. S17/S18 are housekeeping; S16/S15 are the core run-mode logic (S16 depends on S15's fresh-run branch). |
| **3** | S14, S21 | Invariants + solo pods (behavior changes with clear acceptance criteria). |
| **4** | S22 | Efficiency trade-off in the Phase 3–6 loop (fully specified). |

Within Wave 2, do **S15 → S16** (S16 reuses S15's fresh-run branch) and
**S17 → S18** (both touch reset/housekeeping).

---

## Clarifications needed before full execution

| Story | Open question | Blocking? |
|---|---|---|
| S13 | Embed in `README.md` only, or also a root `PROCESS.md`? | No — default: embed in `README.md` (+ optional `PROCESS.md`) |
| S15 | How to determine "last phase" when there is no checkpoint? | No — default: derive from phase outputs, fallback Phase 1 |
| S20 | Wire the 4 knobs in, or remove them from `.env.example`? | No — blocks only the S20 fix (explanation is independent) |

**All waves can proceed without any blocking clarification.** The S22
(efficiency trade-off) open questions have been resolved with the user.

---

## Progress

### Wave 1 — COMPLETE (awaiting test confirmation)

| Story | Status | What changed |
|---|---|---|
| S13 | ✅ done | Mermaid process diagram embedded in `README.md` (new "Process diagram" section). |
| S19 | ✅ done | `observability/` added to the README Layout block + a new "Observability" subsection. |
| S25 | ✅ done | `AUDIT.md` §2.6 removed; §4.0 + §5.6 cross-references cleaned up (no dangling refs). |
| S20 | ✅ done (wired in) | F-1 knob analysis + **option (a) implemented**: the 4 knobs (`POD_MIN_ROLES`, `POD_MAX_ROLES`, `CONTEXT_BUDGET_TOKENS`, `ROLE_MEMORY_MAX_ENTRIES`) are now plumbed through `config.py` to their consumers (`validate_pod`, `bounded_assembly`, `MemoryBackend`). |
| S24 | ✅ plan produced | `DECOMP_SCRIPTS.md` created (step-by-step decomposition plan for `dispatch.py` + `llm_api.py`). |
| S26 | ✅ done | `stories/` validated as unreferenced and removed. |

**Test run (user):** `python -m pytest tests/` → **176 passed, 1 failed**. The
single failure was `tests/test_config.py::test_dropped_knob_warns` — a test that
asserted the *old* behavior (that `POD_MIN_ROLES` was a *dropped* knob firing
the "unused .env key" warning). S20's wire-in made that premise stale (the knob
is now a *known* key, so no warning fires).

**Fix:** updated that test to `test_unknown_knob_warns` — it now asserts the
warning fires for a genuinely-unknown/typo'd key (`POD_MIN_ROLE`, missing the
S), which is the warning's actual purpose. The S20 plumbing itself is green (all
other 176 tests pass, including the pod/context/memory suites).

**Please re-run:** `python -m pytest tests/ -q` to confirm all **177** pass.
Also please confirm the README Mermaid diagram renders (S13).

### Wave 2 — COMPLETE (awaiting test confirmation)

| Story | Status | What changed |
|---|---|---|
| S17 | ✅ done | Verified `reset_org.py` wipes `state/` (via `STATE_DIR`) and `pods/` (via `PODS_DIR`) — so `state/checkpoint.json` + `pods/transcripts/` are removed. Confirmation recorded in the S17 section. |
| S18 | ✅ done | Created `reports/.gitkeep` so the `reports/` dir is present on disk (consistent with its managed siblings `history/`, `archives/`, `departments/`). Verified `reset_org.py` already wipes `reports/` and `.gitignore` already ignores its contents. Confirmation recorded in the S18 section. |
| S16 | ✅ done | Refactored `reset_org.py` to expose a reusable `wipe_state(verbose=True)`; a fresh run (no `MISSION.md`, or `--fresh`) calls it before proceeding (visible clear). Confirmation recorded in the S16 section. |
| S15 | ✅ done | `run_session.py` now defaults to revisit; added the `--fresh` flag + `_decide_run_mode()` (the run-mode decision in one place) + a visible `[run-mode]` log; `runtime/session.py`'s `run()` accepts `resume_from_phase` (a revisit from a checkpoint at phase 3/4 skips Phases 1-3 and resumes from Phase 4). Confirmation recorded in the S15 section. |

**Test run (user):** Please run `python -m pytest tests/ -q` to confirm all
tests pass with the Wave 2 changes (S15–S18). Also please confirm:
- A fresh run (no `MISSION.md`, or `--fresh`) clears the generated state
  (S16) — the deleted paths are printed.
- A revisit run (the default) resumes from the checkpoint / last phase (S15)
  — the `[run-mode]` log shows the mode + resume point.
- `reset_org.py --yes` still works (the `wipe_state()` refactor didn't break
  it).

---

## Approval

- [x] User approves the story set (S13–S26) and the wave ordering.
- [x] S22 (efficiency trade-off) open questions answered (Wave 4 unblocked).
- [x] Green light to start **Wave 1** (given).
- [ ] User confirms the S13 / S15 / S20 defaults (S13: README-only — done;
      S20: wire-in vs. remove — **pending**; S15: revisit semantics — Wave 2).
- [ ] Test confirmation for Wave 1 (see Progress above).

---

*End of STORIES.md*
