# ORG_AUDIT.md

> A working guide for: (1) understanding how `D:\LLM\LLM_Organization` is
> intended to function, (2) auditing that the documented intent is actually
> captured in the code (a spec-to-code traceability audit), and (3) doing a
> full code audit for correct wiring, dead code, stubs in the production
> path, and silent errors.
>
> Written from a close reading of the spec (`EPIC.md`, `REPO_CHANGES.md`,
> `MISSION.md`, `stories/`), the runtime (`runtime/`), the role contracts
> (`roles/`, `org/`), the test suite (`tests/`), and the prior run audits
> (`RUN_AUDIT.md`, `LOG_AUDIT.md`).

---

## 1. How the repo is intended to function

### 1.1 The one-paragraph purpose

`LLM_Organization` is a **company of LLM agents**. Given an initial prompt, it
runs a **bounded, 8-phase pipeline** that (a) clarifies and codifies a mission,
(b) bootstraps a departmental org, (c) plans / staffs / executes work
top-down, and (d) evaluates and decides (continue / complete / escalate) in a
**bounded self-improving loop**. Every step produces a **coherent, auditable
record** — state files, an append-only `history/` audit trail, pod transcripts,
and per-role memory — with strict **visibility / communication / pod
invariants enforced by construction** (in code, not by prompt). The whole thing
is **offline-by-design**: a deterministic `StubBackend` (scripted per role)
lets every loop, budget, and schema check run without a live model; a real
backend is wired behind the same `LLMBackend` interface.

### 1.2 The 8-phase pipeline

The top-level working unit is a **department** (led by a `department_head`),
containing **teams** (led by `manager`s), containing **ICs**. Each level is
created in its **own phase**. Phases 1–3 run **once**; Phases 4–8 form the
**cycle loop** (they repeat on "continue", bounded by `max_iterations`).

| # | Phase | Module | What happens |
|---|-------|--------|--------------|
| 1 | **Intake** | `runtime/intake.py` (`run_intake`) | The Leader asks clarifying questions (bounded rounds). Convergence is gated on the Leader **restating the goal** (`restated_goal`) — a fuzzy goal must not short-circuit intake. If no goal is established yet, the first question is the hard-coded "What is the organization's goal?". At the question budget, the Leader proceeds with its best understanding, **explicitly marking assumptions**. Writes an **informal** mission draft to `state/mission_draft.md` (NOT `MISSION.md`). |
| 2 | **Mission** | `runtime/mission.py` (`run_mission`) | The Leader refines the informal draft into the **formal, versioned** `MISSION.md`; the **user approves** (the only write path to the mission). The Leader also **proposes the departments + priority order** (a `department_proposal` field in its output schema). On a revisit (`--revisit`), the version continues (v1 → v2 → …) and the draft is seeded from the current mission + the Phase-1 informal draft. |
| 3 | **Org bootstrap** | `runtime/org.py` (`bootstrap`) | Creates the proposed **departments** + hires `department_head`s (one per department, in priority order; falls back to `org_recommendation` if the proposal is absent). The **required governance departments (HR, Safety, Morality) are always present** (non-fireable). The Leader **allots department headcount caps** (% of the total cap). **Pod A** (all heads + the Leader) finalizes headcount per department (the Leader has final say). The **"devil's advocate" role is always created** (a Leader's direct report). Headcount is recorded in the **mission addendum**. |
| 4 | **Plan** | `runtime/plan.py` (`run_plan`) | Per department: **Leader+head clarification pod** (kind `clarification`) → the head **authors the department policy** (a department-level artifact, owned by the head, may detail team roles) → the head **hires `manager`s** → the head **allots team/IC headcount** (% of the department cap) → **head+manager clarification pods** → **Pod B** (all managers + the head) finalizes headcount (the head has final say). The team caps are recorded in the policy. |
| 5 | **Staff** | `runtime/staff.py` (`run_staff`) | `manager`s **create ICs** + assign tasks (within the team cap; a hire exceeding the cap is blocked with a **visible `team_cap_reached` event, never silent**) → **manager+ic clarification pods**. |
| 6 | **Execute** | `runtime/execute.py` (`run_execute`) | ICs **execute tasks** (they may self-edit their own work files). **Execution pods form** on A/B/C triggers (disagreement / cross-team / routing rule) + a **collaboration pod** (IC+manager) when the IC flags a collaboration need. Pod decisions are carried forward (decision artifacts + seeded member memory). |
| 7 | **Evaluate** | `runtime/session.py` (`_run_reporting_pods`, `_evaluate_progress`) | **Reporting pods** (kind `reporting`, 2-member parent+child) run **before** the Leader's synthesis: `ic→manager`, `manager→department_head`, `department_head→Leader`. Each surfaces the child's status / results / fire-replace-keep decisions + headcount changes to the parent. The **"devil's advocate" runs its gut check** (primed to doubt, heavy moral emphasis) and returns a verdict (`clean` / `flag: <findings>`). The **Leader evaluates progress** against the mission's success criteria (verdict `complete` / `continue` / `escalate`). |
| 8 | **Decide** | `runtime/session.py` (`_decide`) | The Leader decides **continue / complete / escalate**. A **`flag` from the devil's advocate is consumed** — it forces a re-check or blocks a stop. A headcount reassignment can trigger a reorg. "continue" re-enters Phase 4 (the loop repeats). Bounded by `max_iterations` (on the last iteration the bounded check forces "complete"). |

### 1.3 The conceptual model + architypes

| Unit | Level | Led by (architype, tier) | Created in |
|------|-------|--------------------------|------------|
| **Department** | top-level working unit | `department_head` (tier 1) | Phase 3 |
| **Team** | within department | `manager` (tier 2) | Phase 4 |
| **IC** | within team | `ic` (tier 3) | Phase 5 |
| **Department policy** | department-level artifact (owned by the head) | authored by `department_head`, after the Leader+head clarification pod | Phase 4 |

The **architypes do not change**: `leader` (tier 0) → `department_head`
(tier 1) → `manager` (tier 2) → `ic` (tier 3). The `department` **field** on
`Role` holds the department slug; `reports` holds the direct parent's id (the
reporting chain). The **devil's advocate** is a special role reporting
directly to the Leader, outside the normal department chain. All existing
architype checks (`is_head`, `department_heads()`, `worker_output_schema`,
…) work as-is — no rename, no legacy migration.

### 1.4 The headcount cap chain

A top-down cap chain; each level is allotted by the parent and bounded by the
level above:

| Cap | Allotted by | As a % of | Where |
|-----|-------------|-----------|-------|
| **Total** | env (`HEAD_COUNT_TOTAL`) | — | config |
| **Department** | Leader (Phase 3) | total | Phase 3 + Pod A |
| **Team** | `department_head` (Phase 4) | department cap | Phase 4 + Pod B |
| **IC count** | `manager` (Phase 5) | team cap | Phase 5 |

A hire that would exceed a cap is **blocked / escalated** (never silent).
Headcount is **recorded** in the **mission addendum** + each department
**policy** (the department's headcount per team).

### 1.5 The pod system

Pods are **bounded deliberations**: each runs for a **capped number of
rounds** (`max_rounds`, defaulting to the per-kind `POD_KIND_DEFAULT_ROUNDS`),
then the **initiator returns a result**. Kinds:

| Pod | Members | Purpose | Phase |
|-----|---------|---------|-------|
| **Clarification: Leader + `department_head`** | 2 (parent+child) | clarify the department's mission (before work) | 4 |
| **Clarification: `department_head` + `manager`** | 2 (parent+child) | clarify the team's mission | 4/5 |
| **Clarification: `manager` + `ic`** | 2 (parent+child) | clarify the IC's task | 5 |
| **Reporting: `ic` → `manager`** | 2 (parent+child) | IC reports status/results (after work) | 7 |
| **Reporting: `manager` → `department_head`** | 2 (parent+child) | manager reports to the head | 7 |
| **Reporting: `department_head` → Leader** | 2 (parent+child) | head reports to the Leader | 7 |
| **Headcount finalization Pod A** | all `department_head`s + Leader | finalize headcount per department | 3 |
| **Headcount finalization Pod B** | all `manager`s + the `department_head` | finalize manager/IC headcount | 4 |
| **Execution pod (A/B/C)** | multi-member | collaboration during IC work (disagreement / cross-team / routing rule) | 6 |
| **Collaboration pod (IC + manager)** | 2 | the IC needs help; the manager sets up the pod with the stakeholders | 6 |

**Pod invariants (validated by `pods.form_pod`):** 2–6 members; **max
1-tier spread** across all members (the 2-member pods are a valid 1-tier
spread — tiers (0,1), (1,2), or (2,3)); the **communication gate** passes
(every member can talk to every other); the **starter** manages the
conversation; the **senior member** shares the outcome out; chained pods carry
**decision artifacts** up.

> **Note (a real drift found and fixed in this audit):** the head→Leader
> reporting pod is formed for each **operational** department head. The
> **required governance heads (hr / safety / morality) are skipped** —
> consistent with the Phase-4 **clarification** pod, which already excludes
> them (they are governance, with no work teams to report on). An earlier
> version formed a reporting pod for *every* head (including the three
> governance heads), which broke the flat per-role script alignment in
> `tests/test_phases.py` (the Phase-8 loop never repeated). See §2.6.

### 1.6 The "devil's advocate" role

A **single red-team auditor** reporting **directly to the Leader** (always
created in bootstrap; mandatory; **not** a department). It sits **outside**
the normal reporting chain so the people it checks cannot shape what it sees.

- **Cross-department read access** — one of the only roles (with the Leader)
  that can read other departments' directories (scoped in
  `permissions.py` / `org/tiers.py`).
- **"Listens" to any pod the Leader is in AND any pod the heads are in** (it
  observes the deliberations, not just the final reports).
- **Primed to doubt** — it does not accept claims as true; it checks them
  against what the pipeline has actually produced (e.g. a head claiming
  "$1k revenue" is doubted if the pipeline hasn't run yet).
- **Heavy moral emphasis** — it flags immoral/improper actions (e.g.
  "generate revenue by bypassing a website's robots.txt" is flagged).
- **Phase-7 hook** — in Evaluate it returns a verdict (`clean` /
  `flag: <findings>`); in **Phase 8** a `flag` is consumed by the Leader to
  **force a re-check or block a stop** (don't ship low-quality/immoral
  outcomes).

### 1.7 The cycle loop

Phases 1–3 run **once**. The cycle loop is **Phase 4 → 5 → 6 → 7 → 8**,
repeating while Decide says "continue" (the org can adapt its
structure/headcount on each iteration). It is **bounded** by
`max_iterations` (on the last iteration the bounded check forces "complete")
**and goal-based** (the Leader can stop early on a "complete" verdict). A
headcount reassignment in Decide can trigger a reorg. `SessionResult.phases`
is `{1..8: count}` and `SessionResult.cycles` counts the loop iterations.

### 1.8 The invariants (enforced by construction)

- **A role can only read its team's department directory.**
- **Department heads and the Leader cannot read any code** — they see work
  only as it is brought to them (reports, summaries, decision artifacts). The
  Leader's cross-department read is **scoped** (`tiers.can_read`), and the
  Leader **cannot read code** (`tiers.can_read_code`); the devil's advocate
  has the scoped cross-department read.
- **Communication** is chain-of-command + team-mates + the Leader (apex); no
  reaching into another sub-agent's direct reports.
- **Pods** require max 1-tier spread (2–6 size); the starter manages; the
  senior shares the outcome; chained pods carry decision artifacts up.

These are enforced in `org/tiers.py` (the tier math + rule checks) and
`runtime/permissions.py` (the ownership + read rules) — **not by prompt**.

### 1.9 The LLM backend chain

A chain of **wrappers** around a **raw backend**, built by
`Session.build_backend` / `make_backend` (`runtime/llm_api.py`). Call flow is
outermost → innermost:

- **`MemoryBackend`** (`runtime/llm.py`) — isolated per-role memory (loaded
  from / saved to `state/role_memory/` around every run, so roles remember
  their past).
- **`TimingBackend`** — per-role / per-department timing (feeds the
  efficiency meter).
- The README's process diagram also describes a **routing layer** (complexity
  routing + thinking budget — `runtime/complexity.py` is the likely home) and
  a **timeout layer** (idle timeout + wall-clock backstop).
- **Raw backend** — `OpenAIBackend` (`LLM_BACKEND=api`: a real model behind a
  structured-output tool call with retries) or `StubBackend`
  (`LLM_BACKEND=stub`: scripted per role — the offline path).

Every backend implements the same `LLMBackend.invoke(role, context, …)`
interface, so the pipeline is backend-agnostic.

> **Wiring target:** confirm the *actual* chain assembled by
> `Session.build_backend` matches the documented one (memory → routing →
> timeout → raw). A wrapper that is described but not wired is a **silent
> capability gap** (e.g. complexity routing or the idle timeout would simply
> be absent). See §3.4.

### 1.10 State files + observability

| File / dir | Written by | Read by |
|------------|-----------|---------|
| `MISSION.md` | Phase 2 (the only write path; user-approved) | Phase 4+ (the mission digest), the Leader's evaluation |
| `state/mission_draft.md` | Phase 1 (informal) | Phase 2 (seed) |
| `state/org_chart.json` | Phase 3 (re-saved on revisit) | `--revisit` (load), the org chart |
| `state/checkpoint.json` | after each phase | crash recovery (`resume_from_phase`) |
| `state/role_memory/*.json` | around every run (per role) | `MemoryBackend` (load) |
| `departments/<dept>/` (policy + team dirs) | Phase 3 (policy), Phase 4+ (work) | the department's roles, the dashboard |
| `history/*.jsonl` (intake, mission_edits, org_events, cycles, tool_calls, invocations, code_edits, self_edits, efficiency, …) | every phase (append-only) | the dashboard, the run audits |
| `pods/transcripts/*` (+ decision artifacts) | every pod | the dashboard, chained pods |
| `reports/` (offloading plans + evaluation reports) | Phase 7 (evaluation) | the Leader, the run audits |
| `archives/` | rolled-over sessions (size-capped) | — |

**Observability** (`observability/dashboard.py` + `web/`) is a **read-only,
stdlib-only** dashboard that tails `history/*.jsonl`, `state/`, and
`pods/transcripts/` and serves a local web UI (http://127.0.0.1:8090). It is
**operator-owned and agent-write-locked** — the pipeline never writes to it.

### 1.11 Offline by design

The code ships with a deterministic `StubBackend` (scripted per role) so every
loop, budget, and schema check is testable **without a live model**. The test
suite (`tests/`) is **offline and deterministic**. A real backend is wired
behind the same interface (see `SETUP.md`).

> **Caveat (a real test fragility found in this audit):** `StubBackend`
> **reuses the last script entry once the script is exhausted**. Tests that
> drive the Leader with a **flat per-role script** (one entry per Leader
> invoke) therefore depend on the **exact invoke count** per phase being
> correct. If the code makes a different number of invokes than the test
> assumes, the script falls out of alignment — and because the exhausted last
> entry is often a `{"verdict": "complete"}`, the misalignment can **still
> produce the expected verdict** (a **false positive**). See §2.6 + §3.11.

---

## 2. Auditing that the intent is captured in the code (spec-to-code audit)

This is a **traceability audit**: for every concrete requirement in the spec,
confirm the code **implements** it, it is **wired** (called in the right
phase, with the right args, and the result is consumed), it is
**observable** (produces the expected state/log/artifact), and it is
**meaningfully tested** (the test would fail if the code were wrong).

### 2.1 Sources of truth (ranked)

1. **`EPIC.md`** — the authoritative spec of the 8-phase process (the phases,
   the pods, the headcount, the devil's advocate, the invariants, the stories
   + tasks).
2. **`REPO_CHANGES.md`** — the original requirements (the 8-phase process +
   the dashboard data fix).
3. **`stories/*.md`** — per-story execution detail (the files, functions,
   logic).
4. **`MISSION.md`** — the runtime mission (the success criteria the Leader
   evaluates against).
5. **Module docstrings** — the per-module intent (e.g. `runtime/session.py`,
   `runtime/pods.py`).
6. **`tests/`** — the executable spec (what the code is expected to do).

> The spec and the tests can **disagree** (a drift). When they do, the **EPIC
> is the tie-breaker** (it is the authoritative spec), and the disagreement is
> a **finding**.

### 2.2 Methodology (step by step)

**Step 1 — Inventory the intent.** Read the sources of truth (2.1) and
extract every **concrete requirement**: a phase, a pod (kind + members +
phase), a cap (level + allotter + bound), a role (the devil's advocate), a
state file (writer + reader), a config knob, an invariant, a CLI flag. Record
each as a row in the traceability matrix (2.3).

**Step 2 — Build the traceability matrix.** For each requirement, fill in:
the **spec location** (file + section), the **code location**
(`file:function`), the **test** that covers it, and the **observable
evidence** (the state file / log line / artifact / dashboard field that
proves it ran).

**Step 3 — Verify each requirement** (four checks):

- **(a) Implemented** — read the code, confirm the logic matches the spec
  (not just the name).
- **(b) Wired** — confirm it is **called** in the right phase, with the right
  arguments, and the **result is consumed** (not computed and dropped). Trace
  the call chain from `Session.run`.
- **(c) Observable** — confirm the behavior produces the expected evidence
  (run a stubbed scenario, or inspect a real run's `history/` / `state/` /
  `pods/`).
- **(d) Meaningfully tested** — confirm a test covers it **and** the test
  would **fail** if the code were wrong (i.e. it is not a false positive —
  see 2.6).

**Step 4 — Classify the findings** (2.5).

**Step 5 — Report** (2.7).

### 2.3 The traceability matrix (template)

| Requirement | Spec location | Code location | Test | Observable evidence | Implemented? | Wired? | Observable? | Meaningfully tested? | Finding |
|-------------|---------------|---------------|------|---------------------|--------------|--------|-------------|----------------------|---------|
| e.g. "head→Leader reporting pod, Phase 7, operational heads only" | EPIC §2 (pod table) | `session._run_reporting_pods` | `test_phases.test_cycle_repeats_on_continue` | the pod transcript + the Leader's Phase-7 invokes | ✅ | ✅ | ✅ | ✅ (with caveat) | — |
| e.g. "Pod A finalizes department headcount" | EPIC §2 | `org.allot_department_caps` | `test_headcount` (pending per EPIC Story 9) | the mission addendum | ? | ? | ? | ❌ (no test) | **gap: untested** |

### 2.4 Verification techniques

- **Read the code, not the name.** A function called `run_plan` might not do
  what "plan" implies. Confirm the logic.
- **Trace the call chain.** From `Session.run`, follow each phase call
  (`run_intake` → `run_mission` → `bootstrap` → `run_plan` → `run_staff` →
  `run_execute` → `_run_reporting_pods` → `_evaluate_progress` → `_decide`).
  Confirm each is called **once per the spec**, in order, with the right
  args, and the result is consumed.
- **Run a stubbed scenario.** Use `StubBackend` to drive a minimal org (one
  department) and confirm the phase sequence + the pod sequence + the state
  files. (This is what `tests/test_phases.py` does.)
- **Inspect a real run.** Use `history/*.jsonl`, `state/`,
  `pods/transcripts/`, `reports/` from a live run to confirm the observable
  evidence (this is what `RUN_AUDIT.md` / `LOG_AUDIT.md` do).
- **Check the invariants.** Confirm `pods.form_pod` validates size / 1-tier
  spread / communication gate, and `permissions.py` / `org/tiers.py` enforce
  the read rules.
- **Diff the spec against the code for the "silent" requirements.** The
  hardest requirements to verify are the **negative** ones ("the Leader never
  reads code", "a hire exceeding the cap is blocked, never silent", "the
  governance heads get no clarification pod"). Confirm the **enforcement code
  exists and is called**, not just the happy path.

### 2.5 Finding classification

| Class | Meaning | Example (this repo) |
|-------|---------|---------------------|
| **Gap** | Spec'd, but not implemented (or not wired). | Pending tests (`test_headcount`, `test_clarification_pods`, `test_execution_pods` per EPIC Story 9) — the mechanisms are implemented but untested. |
| **Drift** | Implemented, but differently than spec'd. | The reporting pod formed for *every* head (including governance) instead of operational heads only (now fixed). |
| **Dead** | Implemented, but no longer intended (stale spec or stale code). | A config knob that is defined but never read. |
| **Untested** | Implemented + wired, but no meaningful test. | Pod A / Pod B finalization. |
| **False positive** | A test passes, but would not catch a bug (misaligned flat script + `StubBackend` last-entry reuse). | `test_phases` before the reporting-pod fix. |

### 2.6 Known pitfalls (from this repo) — what to watch for

1. **The reporting-pod drift (a real bug, found + fixed in this audit).** The
   head→Leader reporting pod was formed for **every** department head,
   including the three **required governance heads** (hr / safety / morality)
   that bootstrap always creates. The spec (and `tests/test_phases.py`)
   expect the pod for each **operational** department. The extra pods broke
   the flat per-role script alignment (13 Leader invokes per iteration
   instead of 7), so the Phase-8 loop never repeated (`phases[4] == 1`
   instead of 2). The fix: skip `head.is_required` in
   `session._run_reporting_pods`, consistent with the Phase-4 clarification
   pod. **Lesson:** a requirement that says "for each X" needs the **scope of
   X** confirmed (operational vs. all), and the **sibling mechanisms** (the
   clarification pod) are a free consistency check.
2. **False-positive flat scripts.** `StubBackend` reuses the last entry when
   the script is exhausted. A test that drives the Leader with a flat
   per-role script depends on the **exact invoke count** per phase. If the
   code makes a different number of invokes, the script misaligns — and
   because the exhausted last entry is often a `{"verdict": "complete"}`, the
   misalignment **still produces the expected verdict**. **Lesson:** for any
   test that asserts a loop / phase count, confirm it **would fail** if the
   code made one extra (or one fewer) invoke — e.g. by asserting on an
   intermediate observable (the pod transcript count, the
   `history/cycles.jsonl` line count), not just the final verdict.
3. **Redundant / orphaned state.** `REPO_CHANGES.md` flags that
   `history/efficiency_metrics.jsonl` and `efficiency_reports.jsonl` duplicate
   data already in `efficiency.jsonl`; `RUN_AUDIT.md` D8 flags
   `self_edits.jsonl` as a verbatim mirror of `code_edits.jsonl`. **Lesson:**
   every state file that is written should be **read by a consumer**; a file
   that is only written (or is a mirror) is dead weight (or a divergence
   risk).
4. **The dashboard tailing a log the run never produced.** `RUN_AUDIT.md` D9:
   `dashboard.py` tails `history/halt_events.jsonl`, which the run never
   created. **Lesson:** the observability layer's inputs must be confirmed to
   actually be produced by the pipeline.
5. **Debug artifacts left at the repo root.** Throwaway scripts (e.g.
   `debug_leader_invokes.py`, `_debug_calls.py` — both removed in this audit
   pass) can accumulate at the root. **Lesson:** the audit includes a
   root-level sweep for throwaway files (see §3.5).

### 2.7 Report template (spec-to-code audit)

```
# SPEC-TO-CODE AUDIT — <date>
## Scope
<the spec files + the code modules audited>
## Traceability matrix
<the filled-in matrix from 2.3>
## Findings
| # | Requirement | Class | Severity | Evidence | Remediation |
|---|-------------|-------|----------|----------|-------------|
## Summary
<the headline: how many requirements are fully captured, and the top gaps / drifts>
```

---

## 3. Full code audit (wiring, dead code, stubs, silent errors)

This is a **code-correctness audit**: confirm every module is **correctly
wired** (called where it should be, with the right args, results consumed),
there is **no dead code** (unused functions / imports / files), **no stubs in
the production path** (placeholders standing in for real logic), and **no
silent errors** (swallowed exceptions, masking defaults, missing validation,
uncovered retries).

### 3.1 Scope

The production code: `runtime/` (the session runtime), `roles/` (the role
contracts), `org/` (the tier math + rule checks), `observability/` (the
dashboard), and the CLI entry points (`run_session.py`, `reset_org.py`,
`run_org.bat`). The test suite (`tests/`) is audited separately for
**meaningfulness** (§3.11), not for dead code.

### 3.2 Methodology (step by step)

1. **Static analysis** (§3.3) — linters / type checkers for unused imports /
   functions, undefined names, type errors.
2. **Call-graph / wiring audit** (§3.4) — build the call graph from the entry
   points; find unreachable code (dead) and reachable-but-dropped results
   (wiring).
3. **Dead-code detection** (§3.5) — functions / classes / files / config
   knobs that are never referenced.
4. **Stub detection** (§3.6) — placeholders in the production path.
5. **Silent-error detection** (§3.7) — swallowed exceptions, masking
   defaults, missing validation, uncovered retries.
6. **Config audit** (§3.8) — every config knob is read and used.
7. **State-file audit** (§3.9) — every state file is written by the right
   phase and read by a consumer.
8. **Invariant audit** (§3.10) — the invariants are actually enforced.
9. **Test-coverage + meaningfulness audit** (§3.11).
10. **Report** (§3.12).

### 3.3 Static analysis

Run (from the repo root, in the repo's venv):

- **`pyflakes`** — unused imports, undefined names, unused variables.
- **`vulture`** — dead code (unused functions / classes / attributes). Tune
  the threshold; expect false positives on dynamically-referenced code
  (functions called by name from a dispatch table or a test).
- **`pylint`** — broader lint (unused-import, unnecessary-pass, …).
- **`mypy`** — type errors (catches `None` returned where a value is
  expected, missing args, …).
- **`ruff`** (if available) — a fast all-in-one (pyflakes + pycodestyle +
  pyupgrade + …).

> **Interpretation:** static analysis finds **candidates**, not confirmed dead
> code. A function flagged by `vulture` might be called **dynamically** (by
> name from a dispatch table, a config, or a test). Confirm each candidate by
> searching for **string references** (the function name as a string) before
> declaring it dead.

### 3.4 Call-graph / wiring audit

**Build the call graph from the entry points:**

- `run_session.py` → `Session.build_backend` + `Session.run`
- `reset_org.py` → the wipe logic
- `observability/dashboard.py` → the read-only tailing

**From `Session.run`, trace the phase chain** and confirm each is **wired**:

```
Session.run
  → run_intake (Phase 1)
  → run_mission (Phase 2)
  → bootstrap (Phase 3)        → allot_department_caps (Pod A)
  → [cycle loop, Phases 4–8, bounded by max_iterations]
      → run_plan (Phase 4)     → the Leader+head clarification pod,
                                 generate_head_policies, _allot_team_caps (Pod B)
      → run_staff (Phase 5)    → the manager+ic clarification pods
      → run_execute (Phase 6)  → the execution pods (A/B/C) + the collaboration pod
      → _run_reporting_pods (Phase 7)
                                 → ic→manager / manager→head / head→Leader reporting pods
      → _evaluate_progress (Phase 7)
                                 → the devil's-advocate gut check + the Leader's synthesis
      → _decide (Phase 8)      → the flag consumption + continue/complete/escalate
```

**For each call, confirm three things:**

1. **It is called** (not dead) — in the right phase, the right number of
   times.
2. **The arguments are correct** — the right org / backend / caps / config.
3. **The result is consumed** — not computed and dropped. (E.g. a pod's
   decision must be carried into the next phase / the Leader's prompt / the
   member memory, not just logged.)

> **A concrete wiring gap to check:** the README (§1.9) describes a backend
> chain of `MemoryBackend → routing → timeout → raw`, but confirm the *actual*
> chain assembled by `Session.build_backend` matches it (`runtime/complexity.py`
> is the likely home of the routing layer). A wrapper that is described but
> not wired is a **silent capability gap** (the complexity routing / idle
> timeout would simply be absent).

### 3.5 Dead-code detection

- **Unused functions / classes** — from `vulture` / `pyflakes`, confirmed by
  a string-reference search.
- **Unused imports** — from `pyflakes` / `ruff`.
- **Unused files** — a module that is never imported (search for
  `import <module>` and `from <module> import`). E.g. confirm
  `runtime/dispatch.py` (the old 1243-line monolith) is either deleted or a
  **thin re-export shim** — not a second copy of the logic.
- **Unused config knobs** — a knob in `config.py` / `.env.example` that is
  never read (§3.8).
- **Unused state files** — a file that is written but never read (§3.9).
- **Root-level sweep** — throwaway debug scripts / scratch files at the repo
  root (in this audit pass, `debug_leader_invokes.py` and `_debug_calls.py`
  were found and removed).

> **The re-export shim case:** `runtime/dispatch.py` is supposed to be a
> **thin re-export shim** (EPIC Story 2). Confirm it only re-exports (no
> duplicated logic). If it still holds the old monolith logic, that's **dead
> weight + a divergence risk** (two copies of the same logic).

### 3.6 Stub detection

Find **placeholders standing in for real logic** in the production path:

- **`raise NotImplementedError`** — a function that is not implemented. If it
  is in the production path (called by `Session.run`), it's a **critical
  stub**.
- **`TODO` / `FIXME` / `XXX` / `HACK`** — grep for these; a `TODO` in the
  production path is a **candidate stub**.
- **A bare `pass` in a function body** — a function that does nothing. If it
  is supposed to do something (per the spec), it's a **stub**.
- **A hardcoded return** — a function that returns a constant (e.g.
  `return "complete"`, `return []`, `return 0`) where it should compute a
  value. If it's in the production path, it's a **stub** (the real logic is
  missing).
- **An uninitialized variable** — `= None` that is never set before use.
- **A commented-out body** — the real logic is commented out, replaced by a
  placeholder.

> **Distinguish test stubs from production stubs.** `StubBackend` is a
> **legitimate** stub (the offline path). A stub is a **problem** only if it's
> in the **production** path (the `LLM_BACKEND=api` path, or a phase module
> that should compute a value). Confirm each stub's **intended backend**
> (stub vs. api) before flagging it.

### 3.7 Silent-error detection

Find **places where a failure is swallowed or masked**:

- **Bare `except:`** — catches everything, including `KeyboardInterrupt` /
  `SystemExit`. Almost always a bug.
- **`except Exception:` that continues** — catches an error, logs it (or
  not), and continues. If the error should have stopped the run, this is a
  **silent error**.
- **`except` that returns a default** — e.g. `except: return []` masks a
  failure as an empty result.
- **`.get(key, default)` with a masking default** — e.g.
  `verdict = out.get("verdict", "complete")` masks a missing verdict as
  "complete" (this is exactly the mechanism that made the reporting-pod
  misalignment a **false positive** — see §2.6 #1–2).
- **`or` defaults** — e.g. `value = x or "default"` masks a
  falsy-but-valid value.
- **Missing validation** — a function that assumes a key / shape is present
  but does not check. With direct indexing it's a loud `KeyError`; with
  `.get` + a default it's **silent**.
- **A retry path that doesn't cover all failure types** — `LOG_AUDIT.md` F5:
  the retry covered **truncation** but not **malformed envelopes**, so two ICs
  silently produced nothing and were never replaced. Confirm the retry /
  fallback covers **every** failure type that can occur.
- **A failed action that is not recovered** — `RUN_AUDIT.md` D6: the Leader's
  automation action failed ("could not hire the automation IC") and the run
  proceeded without it, with no retry / fallback. Confirm a failed corrective
  action is either retried or escalated, not silently dropped.

> **The "visible, never silent" rule.** The spec repeatedly says failures must
> be **visible** (e.g. "a hire exceeding the cap is blocked with a visible
> `team_cap_reached` event, never silent"). Confirm each such failure produces
> a **visible event / log line / escalation**, not a silent default.

### 3.8 Config audit

For **every** config knob (in `runtime/config.py` / `.env.example`), confirm
it is:

1. **Defined** (in `config.py` / `.env.example`).
2. **Read** (loaded by the config loader / `make_backend`).
3. **Consumed** (used by a phase module / the backend).

A knob that is defined but never consumed is **dead** (or a **wiring gap** —
the knob was added but the consuming code was not wired).

> **The knobs to check (from the spec):** `HEAD_COUNT_TOTAL` (the total cap),
> the department / team cap defaults, `clarification_pod_rounds`,
> `reporting_pod_rounds`, the headcount-finalization-pod rounds,
> `routing_rules` (the execution-pod Trigger C), `MAX_ITERATIONS`,
> `EFFICIENCY_FLOOR`, `LLM_BACKEND`, `LLM_MODEL`, `LLM_BASE_URL`.

### 3.9 State-file audit

For **every** state file (§1.10), confirm it is:

1. **Written** by the right phase (the writer is correct).
2. **Read** by a consumer (the reader is correct).
3. **Not redundant** (not a verbatim mirror of another file — see §2.6 #3).

A file that is **written but never read** is **dead** (or a divergence risk).
A file that is **read but never written** is a **wiring gap** (the consumer
expects a file the pipeline never produces — e.g. `RUN_AUDIT.md` D9, the
dashboard tailing `halt_events.jsonl`).

> **The redundant-file case:** `REPO_CHANGES.md` flags
> `efficiency_metrics.jsonl` + `efficiency_reports.jsonl` as duplicating
> `efficiency.jsonl`; `RUN_AUDIT.md` D8 flags `self_edits.jsonl` as a mirror
> of `code_edits.jsonl`. Confirm each is either **consumed** (by the
> dashboard / the Leader) or **removed**.

### 3.10 Invariant audit

For **each invariant** (§1.8), confirm the **enforcement code exists and is
called**:

- **Read isolation** ("a role can only read its team's department directory")
  — confirm `permissions.py` / `org/tiers.py` enforce it, and it's called on
  every read.
- **No code reading** ("heads + the Leader cannot read code") — confirm
  `tiers.can_read_code` enforces it.
- **Communication** (chain-of-command + team-mates + the Leader) — confirm
  the communication gate is enforced.
- **Pod invariants** (2–6 size, max 1-tier spread, communication gate) —
  confirm `pods.form_pod` validates them, and it's called on **every** pod
  (clarification, reporting, headcount, execution, collaboration).

> **The scoped-read case:** the Leader's cross-department read is **scoped**
> (`tiers.can_read`) and the Leader **cannot read code**
> (`tiers.can_read_code`); the devil's advocate has the scoped
> cross-department read. Confirm these **scopes** are correct — **not
> over-broad** (a scope that is too wide is a **silent invariant violation**)
> and **not under-broad** (the devil's advocate must actually be able to read
> other departments' directories, or its gut check is blind).

### 3.11 Test-coverage + test-meaningfulness audit

- **Coverage** — confirm every **production** function (in `runtime/`,
  `roles/`, `org/`) is covered by a test. Use a coverage tool
  (`coverage.py`) to find uncovered functions. Cross-check the actual
  `tests/` directory against the test list in EPIC Story 9 (done:
  `test_phases`, `test_intake_mission_unchanged`, `test_department_policy`,
  `test_department_proposal`, `test_prompts`; pending: `test_headcount`,
  `test_clarification_pods`, `test_execution_pods`).
- **Meaningfulness** — for each test, confirm it **would fail** if the code
  were wrong (i.e. it is not a false positive). The two known fragilities
  (§2.6 #1, #2) are the ones to check:
  - A test that asserts a **loop / phase count** — confirm it would fail if
    the code made one extra (or one fewer) invoke (assert on an intermediate
    observable, not just the final verdict).
  - A test that drives a **flat per-role script** — confirm the script
    alignment is correct (the exact invoke count per phase matches the code).
- **The pending tests** — the pending tests from EPIC Story 9 are
  **coverage gaps** (the mechanisms are implemented but untested). Flag them.

### 3.12 Report template (full code audit)

```
# FULL CODE AUDIT — <date>
## Scope
<the modules audited>
## Static analysis
<the pyflakes / vulture / pylint / mypy findings, confirmed>
## Wiring
| Module / function | Called where? | Args correct? | Result consumed? | Finding |
## Dead code
| Item | Type (function / import / file / knob / state) | Confirmed dead? | Remediation |
## Stubs
| Item | Location | Production path? | Intended backend | Remediation |
## Silent errors
| Item | Location | Mechanism (bare except / masking default / missing validation / uncovered retry) | Remediation |
## Config
| Knob | Defined? | Read? | Consumed? | Finding |
## State files
| File | Written by | Read by | Redundant? | Finding |
## Invariants
| Invariant | Enforcement code | Called? | Scope correct? | Finding |
## Test coverage + meaningfulness
| Function / test | Covered? | Meaningful? | Finding |
## Summary
<the headline: the top wiring gaps, dead code, stubs, and silent errors>
```

---

## 4. Appendix

### 4.1 Entry points

- `run_session.py` — the main CLI (`--interactive` / `--revisit` /
  `--dry-run` / `--fresh`).
- `reset_org.py` — the wipe (`--yes`): wipes `departments/`, `state/`,
  `MISSION.md`, `history/`, `pods/`, `reports/`, `archives/`.
- `run_org.bat` — a one-shot live run.
- `observability/dashboard.py` — the read-only dashboard (`--port 8090`).

### 4.2 Module map (production, confirmed against the tree)

| Module | Role |
|--------|------|
| `runtime/session.py` | the 8-phase pipeline + the cycle loop + the reporting pods + the evaluate/decide bodies |
| `runtime/intake.py` | Phase 1 (Intake) — the clarifying Q&A loop |
| `runtime/mission.py` | Phase 2 (Mission) — draft + user approval + the department proposal |
| `runtime/org.py` | Phase 3 (Org bootstrap) — the required departments, the headcount allotment + Pod A, the devil's advocate, the mission addendum |
| `runtime/plan.py` | Phase 4 (Plan) — the clarification pods, the department policy, the team caps + Pod B |
| `runtime/staff.py` | Phase 5 (Staff) — the manager workflow (ICs, tasks, the team-cap enforcement) |
| `runtime/execute.py` | Phase 6 (Execute) — IC execution, the execution pods (A/B/C), the collaboration pod |
| `runtime/pods.py` | the pod mechanics (`form_pod`, `run_pod`, the kinds, the invariants) |
| `runtime/dispatch_common.py` | the shared helpers (extracted from the old `dispatch.py`) |
| `runtime/dispatch.py` | the thin re-export shim (the old monolith — verify it holds no duplicated logic) |
| `runtime/llm.py` | the `LLMBackend` interface + `StubBackend` + `MemoryBackend` + `TimingBackend` |
| `runtime/llm_api.py` | `OpenAIBackend` (the real backend) + `make_backend` |
| `runtime/config.py` | the config knobs (the single source — verify every knob is consumed) |
| `runtime/context.py` | context building for the role invokes |
| `runtime/coerce.py` | output coercion / envelope validation (verify — the envelope errors in `LOG_AUDIT.md` F5 point here) |
| `runtime/complexity.py` | complexity routing (the likely home of the routing layer in §1.9 — verify it is wired into the backend chain) |
| `runtime/efficiency.py` | the efficiency meter (the `M = 0.5·base + 0.5·coverage` formula — `RUN_AUDIT.md` D4) |
| `runtime/guard.py` | a guard (verify its role — likely a communication / visibility guard) |
| `runtime/history.py` | the `history/*.jsonl` audit trail |
| `runtime/timing.py` | timing / efficiency measurement |
| `runtime/permissions.py` | the ownership + read rules |
| `roles/base.py` | the `Role` contract |
| `roles/leader.py` | the Leader contract + the output schema (incl. the department proposal) |
| `roles/worker.py` | the worker contract |
| `org/tiers.py` | the tier math + the rule checks (read isolation, no code reading, communication) |
| `observability/dashboard.py` + `web/` | the read-only dashboard |

> Rows marked **verify** are the ones a first-pass audit should confirm
> against the code (their role is inferred from the spec + the prior run
> audits, not yet read line-by-line).

### 4.3 Config knobs (to verify in the audit)

`HEAD_COUNT_TOTAL`, the department / team cap defaults,
`clarification_pod_rounds`, `reporting_pod_rounds`, the
headcount-finalization-pod rounds, `routing_rules`, `MAX_ITERATIONS`,
`EFFICIENCY_FLOOR`, `LLM_BACKEND`, `LLM_MODEL`, `LLM_BASE_URL`.

### 4.4 State files (to verify in the audit)

`MISSION.md`, `state/mission_draft.md`, `state/org_chart.json`,
`state/checkpoint.json`, `state/role_memory/*.json`, `departments/<dept>/`,
`history/*.jsonl`, `pods/transcripts/*`, `reports/`, `archives/`.

### 4.5 Prior audit findings (references)

- `RUN_AUDIT.md` — the run-data audit (fabricated revenue, dropped
  efficiency data, broken pod counter, stale checkpoint, redundant logs, the
  dashboard tailing a missing log).
- `LOG_AUDIT.md` — the log audit (the abnormal run end, the solo/zero-round
  pods, the thinking-token overwhelm, the truncated tool calls, the
  un-retried malformed envelopes, the asymmetric staffing).
- `REPO_CHANGES.md` — the original requirements (the 8-phase process + the
  dashboard data fix + the redundant `efficiency_metrics` /
  `efficiency_reports` files).

> These prior audits are **run-level** (they audit a specific run's data).
> This document (`ORG_AUDIT.md`) is a **code-level** guide (how to audit the
> code itself). Use them together: the run audits find **behavioral** issues
> (what the code did wrong in a run), the code audit finds **structural**
> issues (what the code is wired to do, and where it is dead / stubbed /
> silent).

### 4.6 Notes from this audit pass

- **Fixed:** `session._run_reporting_pods` now skips the required governance
  heads (hr / safety / morality) when forming the head→Leader reporting pod —
  consistent with the Phase-4 clarification pod. This restored the expected
  leader-invoke count per iteration; `tests/test_phases.py` passes (the
  Phase-8 loop repeats on "continue" and is bounded by `max_iterations`).
- **Removed:** two throwaway debug scripts at the repo root
  (`debug_leader_invokes.py`, `_debug_calls.py`).
- **Known environment caveat (not a code bug):** running the full suite from
  certain working directories raises `PermissionError` on session teardown
  (a sandboxed-directory issue); the tests themselves pass when run in a
  writable directory. Flag it if it recurs.
