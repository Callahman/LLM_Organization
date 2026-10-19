# EPIC: Refactor LLM_Organization to the 8-Phase Department Process

> Status: **Partially implemented** — **Stories 1–8 done** (the 8-phase Session
> restructure + the `dispatch.py` split into plan/staff/execute, plus the
> Phase-1 informal draft and the 8-phase label cleanup; the headcount cap chain
> (Story 3), the pods incl. the collaboration pod (Story 4), the department
> policy-after-pod (Story 5), the department proposal (Story 6), the config
> knobs incl. the routing rules + cap defaults (Story 7), and the 8-phase CLI
> logging (Story 8));
> **Stories 9–12 pending**.
> Scope: the `D:\LLM\LLM_Organization` codebase (runtime / org / roles / pods / CLI).

## 1. Overview

The current code implements a **6-phase** pipeline:

`Intake → Mission → Bootstrap → Dispatch → Synthesis → Evaluation`

The requirements (`REPO_CHANGES.md`) describe an **8-phase** process:

`Intake → Mission → Org bootstrap → Plan → Staff → Execute → Evaluate → Decide`

The central structural change: the top-level working unit is a **department**
(led by a `department_head`), containing **teams** (led by `manager`s),
containing **ICs**. Each level is created in its **own phase**, and the
monolithic Phase-4 `dispatch` is split into three phases (Plan / Staff /
Execute).

Cross-cutting mechanisms are added:
- **Headcount caps** — a cap chain from a **total** cap (env) down to
  **department** caps (% of total, allotted by the leader), **team** caps
  (% of the department cap, allotted by the head), and **IC** counts (within
  the team cap). Headcount is finalized by **pods** (all heads + leader; all
  managers + the head) and recorded in the mission addendum + each policy.
- **Pods** — four kinds, each running for a **capped number of iterations**
  before the initiator returns a result: **clarification pods** (a deliberate
  2-member parent+child pod that clarifies the child's mission), **reporting
  pods** (a 2-member parent+child pod where the child reports to the parent —
  IC→manager, manager→head, head→leader), **headcount-finalization pods** (all
  heads + leader; all managers + the head), and **execution pods** (the A/B/C-
  triggered multi-member pods an IC spins up during Execute).
- **A "devil's advocate" role** — a single red-team auditor reporting
  **directly to the leader** (always created in bootstrap; one of the only roles
  that can read other departments' directories). It institutes a formal **"gut
  check"** on the org's outcomes: it is **primed to doubt** what it hears (it
  does not accept claims as true) and weighs **moral decision-making** heavily —
  flagging fabrication, hallucination, and immoral/improper actions. It
  **"listens"** to any pod the leader or the heads are in, returns a verdict in
  Phase 7 (Evaluate), and a `flag` is consumed in Phase 8 (Decide) to force a
  re-check or block a stop.

**The architypes do not change** — `leader`, `department_head`, `manager`, `ic`
are used as-is. The `department` **field** on `Role` holds the department slug
(unchanged).

## 2. Conceptual Model (new)

| Unit | Level | Led by (architype, unchanged) | Created in |
|------|-------|-------------------------------|------------|
| **Department** | top-level working unit | `department_head` | Phase 3 (Org bootstrap) |
| **Team** | within department | `manager` | Phase 4 (Plan) |
| **IC** | within team | `ic` | Phase 5 (Staff) |
| **Department policy** | a department-level artifact (owned by the head; **may detail team roles** — the head's choice) | authored by `department_head`, **after a leader+head clarification pod** | Phase 4 (Plan) |

**Headcount cap chain** (top → bottom):

| Cap | Allotted by | As a % of | Where |
|-----|-------------|-----------|-------|
| **Total** | env (`HEAD_COUNT_TOTAL`) | — | config |
| **Department** | leader (Phase 3) | total | Phase 3 + Pod A |
| **Team** | `department_head` (Phase 4) | department cap | Phase 4 + Pod B |
| **IC count** | `manager` (Phase 5) | team cap | Phase 5 |

**Pod types** (each runs for a **capped number of iterations/rounds**, then the
**initiator returns a result**):

| Pod | Members | Purpose | Phase |
|-----|---------|---------|-------|
| **Clarification: leader + `department_head`** | 2 (parent+child) | clarify the department's mission | 4 (Plan) |
| **Clarification: `department_head` + `manager`** | 2 (parent+child) | clarify the team's mission | 4 (Plan) |
| **Clarification: `manager` + `ic`** | 2 (parent+child) | clarify the IC's task | 5 (Staff) |
| **Reporting: `ic` → `manager`** | 2 (parent+child) | IC reports status/results to the manager | 7 (Evaluate) |
| **Reporting: `manager` → `department_head`** | 2 (parent+child) | manager reports to the head | 7 (Evaluate) |
| **Reporting: `department_head` → leader** | 2 (parent+child) | head reports to the leader | 7 (Evaluate) |
| **Headcount finalization Pod A** | ALL `department_head`s + leader | finalize headcount per department | 3 (Org bootstrap) |
| **Headcount finalization Pod B** | all `manager`s + the `department_head` | finalize manager/IC headcount | 4 (Plan) |
| **Execution pod (A/B/C)** | multi-member | collaboration during IC work | 6 (Execute) |

## 3. Phase Mapping (old → new)

| New Phase | Old Phase | What happens |
|-----------|-----------|--------------|
| 1. **Intake** | 1. Intake | **Largely unchanged.** Leader asks clarifying questions (bounded rounds); a confidence threshold decides when to stop. **Convergence is gated on the leader restating the goal (`restated_goal` — a fuzzy goal must not short-circuit the intake); if no goal is established yet, the first question is the hard-coded "What is the organization's goal?"; at budget exhaustion the leader proceeds with its best understanding, explicitly marking assumptions. Refines MISSION.md (**informal**) and saves the draft to `state/` (`state/mission_draft.md`).** |
| 2. **Mission** | 2. Mission | **Largely unchanged** (now also: leader **proposes the departments** + priority order, which Phase 3 creates). Refines MISSION.md into a **formal, versioned** doc; user approves. **On a revisit (`start_version` set), the version continues (v1 → v2 → ...) and the draft is seeded from the current mission + the Phase-1 informal draft.** |
| 3. **Org bootstrap** | 3. Bootstrap | Creates the proposed **departments** + hires `department_head`s; leader **allots department headcount caps** (% of total); **Pod A** (all heads + leader) finalizes headcount per department |
| 4. **Plan** | (part of 4. Dispatch) | Per department: **leader+head clarification pod** → head **authors the department policy** → head **hires `manager`s** → head **allots team/IC headcount** (% of department cap) → **head+manager clarification pods** → **Pod B** (all managers + head) finalizes headcount |
| 5. **Staff** | (part of 4. Dispatch) | `manager`s **create ICs** + assign tasks → **manager+ic clarification pods** |
| 6. **Execute** | (part of 4. Dispatch) | ICs **execute tasks**; **execution pods form** (A/B/C triggers) + a **collaboration pod** (IC+manager) when the IC needs help |
| 7. **Evaluate** | 5. Synthesis + 6. Evaluation | **Status pods** (manager+IC, head+manager, leader+heads) surface fire/replace/keep + headcount changes; the **"devil's advocate" role** runs its **gut check** (doubts claims, flags immoral/improper actions) and returns a verdict (`clean` / `flag`); leader **evaluates progress** against the mission |
| 8. **Decide** | 6. Evaluation | **Continue / complete / escalate** (headcount reassignment can trigger a reorg); a **`flag` from the devil's advocate is consumed** — it forces a re-check or blocks a stop |

## 4. Key Decisions

1. **Intake + Mission largely unchanged** — Phase 1 is the existing `run_intake`
   clarifying Q&A loop; Phase 2 is the existing `run_mission`. The only
   additions to Phase 2 are the **department proposal** (the leader proposes the
   departments + priority order) and the **informal draft** saved to `state/`
   after Phase 1. The core Intake/Mission logic, schemas, and the
   `_write_mission` path are unchanged.

2. **Architypes unchanged** — `leader` → `department_head` → `manager` → `ic`
   (tiers 0, 1, 2, 3). No rename, no legacy migration, no alias churn. All
   existing architype checks (`is_head`, `department_heads()`,
   `worker_output_schema`, etc.) work as-is.

3. **Department = top-level working unit** — the `department` field on `Role`
   holds the department slug (unchanged).

4. **Headcount cap chain** — a **total** cap (from env) → **department** caps
   (allotted by the leader in Phase 3, as a % of total) → **team** caps
   (allotted by the head in Phase 4, as a % of the department cap) → **IC**
   counts (within the team cap, Phase 5). The caps are enforced at each level
   (a hire that would exceed the cap is blocked / escalated).

5. **Headcount finalization pods** —
   - **Pod A** (Phase 3): ALL `department_head`s + the leader finalize headcount
     per department; the leader has final say.
   - **Pod B** (Phase 4): all `manager`s + the `department_head` finalize the
     manager/IC headcount; the head has final say.
   - Headcount is **recorded** in the **mission addendum** + each department
     **policy** (the department's headcount per team).

6. **Clarification + reporting pods** — two kinds of **distinct, deliberate
   2-member parent+child pods**, each running for a **capped number of
   iterations/rounds** before the **initiator returns a result**. These are
   **distinct** from the A/B/C-triggered execution pods:
   - **Clarification** (before work — clarifies the child's mission):
     - **leader + `department_head`** (Phase 4): clarifies the department's
       mission. After it, the head **authors the department policy**.
     - **`department_head` + `manager`** (Phase 4): clarifies the team's mission.
     - **`manager` + `ic`** (Phase 5): clarifies the IC's task.
   - **Reporting** (after work — the child reports to the parent):
     - **`ic` → `manager`**: the IC reports status/results.
     - **`manager` → `department_head`**: the manager reports to the head.
     - **`department_head` → leader**: the head reports to the leader (Phase 7,
       Evaluate).
   - All validate against the existing pod invariants (2 members; a valid
     1-tier spread at each level — tiers (0,1), (1,2), (2,3); the communication
     gate passes).

7. **Department policy authored by the department head** — in the **Plan phase
   (Phase 4)**, the `department_head` authors the department policy **after**
   the leader+head clarification pod. The policy is a **department-level
   artifact** (owned by the head), but it **may detail specific team roles /
   team-level policy** — that is up to the head. The existing
   `generate_head_policies` mechanism is kept (moved into `plan.py`, preceded by
   the pod). The `permissions.py` department-policy ownership rule is
   **unchanged** (the `department_head` owns the policy).

8. **Execution pods (A/B/C) + collaboration pod** — during **Execute (Phase 6)**,
   an IC can spin up (each running for a **capped number of iterations**, then
   the initiator returns a result):
   - **Execution pod, Trigger A (disagreement)** — the manager disagrees with
     the IC's approach.
   - **Execution pod, Trigger B (cross-team)** — the IC's work spans multiple
     teams.
   - **Execution pod, Trigger C (routing rule)** — the IC's task type matches a
     routing rule.
   - **Collaboration pod (IC + manager)** — the IC needs collaboration with
     another role/department; the manager propagates the need by setting up the
     necessary pods with the appropriate stakeholders (continues until the IC can
     complete the task).
   - (These are the existing `_check_pod_triggers` A/B/C logic, now in
     `execute.py`.)

9. **Module split** — the monolithic `runtime/dispatch.py` (1243 lines) is split:
   - `runtime/dispatch_common.py` — shared helpers (extracted from dispatch.py):
     `mission_digest`, `_ensure_role`, `_fire_role`, `_invoke_ic`, the
     self-edit helpers, `_check_pod_triggers`, `_upward_report`,
     `_decomposition_list`, the efficiency-panel helpers, `run_automation`.
   - `runtime/plan.py` — **Phase 4 (Plan)**: the head workflow (policy, teams,
     managers, headcount).
   - `runtime/staff.py` — **Phase 5 (Staff)**: the manager workflow (ICs, tasks).
   - `runtime/execute.py` — **Phase 6 (Execute)**: IC execution + execution pods.
   - `runtime/dispatch.py` — deleted (or kept as a thin re-export shim).

10. **Department proposal in the Mission phase** — the leader proposes the
    departments + priority order in Phase 2 (Mission); Phase 3 (Org bootstrap)
    creates them. The `roles/leader.py` output schema gains a department-proposal
    field.

11. **Informal vs formal mission** — Phase 1 (Intake) saves an **informal**
    mission draft to `state/mission_draft.md` (NOT the top-level `MISSION.md`).
    Phase 2 (Mission) refines it into the **formal, versioned** `MISSION.md`.

12. **Cycle loop** — Phases 1–3 run once. The cycle loop is
    **Phase 4 (Plan) → Phase 5 (Staff) → Phase 6 (Execute) → Phase 7 (Evaluate)
    → Phase 8 (Decide)**, repeating while Decide says "continue" (the org can
    adapt its structure/headcount on each iteration). Bounded by
    `max_iterations`. A headcount reassignment in Decide can trigger a reorg.

13. **A "devil's advocate" role (a leader's direct report / red-team auditor)**
    — a formal **"gut check"** on the org's outcomes, **not** a department:
    - A **single role** reporting **directly to the leader** (always created in
      Org bootstrap; mandatory). It sits **outside** the normal reporting chain
      so the people it checks cannot shape what it sees.
    - **Cross-department read access** — one of the only roles that can read
      other departments' directories (granted via `permissions.py`).
    - **"Listens" to any pod the leader is in AND any pod the heads are in**
      (it observes those deliberations, not just the final reports).
    - **Primed to doubt** — it does not accept information as true; it checks
      claims against what the pipeline has actually produced (e.g. a head
      claiming "$1k revenue" is doubted if the pipeline hasn't run yet).
    - **Heavy emphasis on moral decision-making** — it flags immoral/improper
      actions (e.g. "generate more revenue by bypassing a website's robots.txt"
      is flagged as improper).
    - **Phase 7 hook** — in Evaluate it returns a verdict (`clean` /
      `flag: <findings>`); in **Phase 8 (Decide)** a `flag` is consumed by the
      leader to **force a re-check** or **block a stop** (don't ship
      low-quality/immoral outcomes).

14. **Prompts are auditable** — the pipeline's prompts (and parts of prompts)
    are extracted into a dedicated `prompts/` location, each with a comment
    above it indicating how/where it is used (for auditing + suggesting changes).

## 5. Stories + Tasks (to-do list)

> Format: **Story** (a coherent slice of value) → **Tasks** (the to-do items).
> Check a task off as it is done.

### Story 1 — 8-Phase Session restructure (`runtime/session.py`)

**Status: DONE** — `Session.run` is the 8-phase sequence; the cycle loop wraps
Phases 4–8 (Phases 1–3 run once, bounded by `max_iterations`); the Phase-1
informal draft is written to `state/mission_draft.md` and refined into the
formal `MISSION.md` in Phase 2; the 8-phase labels are applied across the
prompts, `solo.record`, the `EfficiencyMeter`, and the dashboard. (The Phase-2
**department proposal** is Story 6 — still pending.)

- [x] Restructure `Session.run` to the 8 phases: Intake → Mission → Org
      bootstrap → Plan → Staff → Execute → Evaluate → Decide.
- [x] Keep **Intake (Phase 1) = `run_intake`** and **Mission (Phase 2) =
      `run_mission`** largely unchanged (only add the department proposal to
      Phase 2 [Story 6] and the informal draft after Phase 1 [done]).
- [x] Wire the **cycle loop** (Phase 4 → 5 → 6 → 7 → 8) repeating on "continue",
      bounded by `max_iterations`; update the `cycles` counter + `history.log_cycle`.
- [x] Update `SessionResult.phases` to `{1..8: count}`.
- [x] Update `solo.record` phase labels (Plan/Staff/Execute) + the
      `EfficiencyMeter.record_phase` wiring (phases 4–8).
- [x] Keep `Session._synthesis` / `Session._evaluate` as the Evaluate / Decide
      bodies (optionally rename to `_evaluate_progress` / `_decide`).

### Story 2 — Split `dispatch.py` into plan / staff / execute (`runtime/`)

**Status: DONE** — `runtime/dispatch.py` is a thin re-export shim; the shared
helpers live in `runtime/dispatch_common.py`, and the three phase modules
(`runtime/plan.py` Phase 4, `runtime/staff.py` Phase 5, `runtime/execute.py`
Phase 6) hold the head / manager / IC workflows.

- [x] Extract `runtime/dispatch_common.py` (pure move of the shared helpers —
      no logic change).
- [x] Create `runtime/plan.py` (Phase 4): the **head workflow** — leader+head
      clarification pod → department policy → hire managers → allot team/IC
      headcount → head+manager clarification pods → Pod B.
- [x] Create `runtime/staff.py` (Phase 5): the **manager workflow** — hire ICs
      → assign tasks → manager+ic clarification pods.
- [x] Create `runtime/execute.py` (Phase 6): IC execution → self-edits →
      execution pods (A/B/C) → collaboration pod.
- [x] Delete `runtime/dispatch.py` (or keep a thin re-export shim for external
      importers).

### Story 3 — Headcount caps + allotment (`runtime/org.py`, `plan.py`, `config.py`)
**Status: DONE** — the full cap chain is in place.
- [x] The **total headcount cap** (`HEAD_COUNT_TOTAL`) is read from env
      (`config.py`) and handed to the phase modules.
- [x] Phase 3 (Org bootstrap): `org.allot_department_caps` — the leader
      **allots department caps** (bounded by the total), then **Pod A** (all
      heads + leader) finalizes them (the leader has final say).
- [x] Phase 4 (Plan): `plan._allot_team_caps` — the head **allots team/IC caps**
      (bounded by the department cap), then **Pod B** (all managers + head)
      finalizes them (the head has final say).
- [x] The **cap chain** (total → department → team → IC) is enforced — a hire
      that would exceed a cap is blocked (`staff._team_cap_ok`; a visible
      `team_cap_reached` event, never silent).
- [x] Headcount is **recorded** in the **mission addendum**
      (`org._record_headcount_addendum`) + the department **policy** (the team
      caps, Story 5).

### Story 4 — Pods (`runtime/pods.py`, `plan.py`, `staff.py`, `execute.py`)
**Status: DONE** — all five pod kinds are formed in their phases.
- [x] **Clarification pods** (2-member parent+child, before work):
      leader+`department_head` (`plan.py`), `department_head`+`manager`
      (`staff.py`), `manager`+`ic` (`execute.py`).
- [x] **Reporting pods** (2-member parent+child, after work, Phase 7):
      `ic`→`manager`, `manager`→`department_head`, `department_head`→leader
      (`session._run_reporting_pods`).
- [x] **Headcount finalization Pod A** (all `department_head`s + leader, Phase 3)
      — leader has final say (`org.allot_department_caps`).
- [x] **Headcount finalization Pod B** (all `manager`s + the head, Phase 4) —
      head has final say (`plan._allot_team_caps`).
- [x] **Execution pods (A/B/C)** in `execute.py`: Trigger A (disagreement),
      Trigger B (cross-team), Trigger C (routing rule) — the existing
      `_check_pod_triggers` logic (`kind="execution"`).
- [x] **Collaboration pod** (IC + manager, `kind="collaboration"`) — when the
      IC's work flags a collaboration need (`collaborate`), the manager sets up
      the pod (`execute.run_execute`); the IC retries its work with the pod's
      outcome.
- [x] **Capped iterations**: every pod runs for a **capped number of
      iterations/rounds** (`max_rounds`, defaulting to the per-kind
      `POD_KIND_DEFAULT_ROUNDS`), then the **initiator returns a result**
      (`pods.run_pod`).
- [x] Validate **all** pods against the existing invariants (size, 1-tier
      spread, communication gate) — `pods.form_pod`.

### Story 5 — Department policy (`runtime/plan.py`, `runtime/permissions.py`)
**Status: DONE** — the policy is authored after the clarification pod.
- [x] `generate_head_policies` is **called from `plan.run_plan`**, **preceded
      by the leader+head clarification pod** (the head authors the policy after
      the pod; the pod → policy sequencing is strict, and the policy context
      includes the pod's clarified mission).
- [x] The policy is a **department-level artifact** (owned by the head); it
      **may detail specific team roles / team-level policy** (the head's choice),
      including the department's team caps (Story 3).
- [x] `permissions.py` department-policy ownership rule **unchanged** (the
      `department_head` owns the policy).

### Story 6 — Department proposal in the Mission phase (`roles/leader.py`, `runtime/mission.py`, `runtime/org.py`)
**Status: DONE** — the leader proposes the departments + priority order in Phase
2 (a `department_proposal` field in `LEADER_OUTPUT_SCHEMA`); `MissionResult`
carries them; `bootstrap` creates them in Phase 3 (one head per proposed
department, in priority order), falling back to `org_recommendation` if the
proposal is absent.

- [x] Add a **department-proposal** field to `LEADER_OUTPUT_SCHEMA` (the
      departments + priority order) — the shape `bootstrap` reads.
- [x] `MissionResult` carries the proposed departments.
- [x] `bootstrap` accepts the proposed departments (fall back to
      `org_recommendation` if the new field is absent).

### Story 7 — Config (`runtime/config.py`, `.env.example`)
- [x] Add the **headcount knobs**: `HEAD_COUNT_TOTAL` (total cap),
      department/team cap defaults.
- [x] Add the **pod knobs**: clarification-pod rounds, headcount-finalization-pod
      rounds, execution-pod triggers (`routing_rules`).
- [x] Document all new knobs in `.env.example`.

### Story 8 — CLI (`run_session.py`, `reset_org.py`)
- [x] Update the run-mode / phase logging to the 8 phases (`resume_from_phase`:
      a checkpoint at phase 3+ resumes from Phase 4).
- [x] `reset_org.py` unchanged (wipes `departments/`, `state/`, `MISSION.md`,
      `history/`, `pods/`, `reports/`, `archives/`).

### Story 9 — Tests (`tests/`)
- [ ] `test_phases.py` — the 8-phase structure + cycle loop (repeats on
      "continue", bounded by `max_iterations`).
- [ ] `test_intake_mission_unchanged.py` — Intake (Phase 1) + Mission (Phase 2)
      largely unchanged; the informal draft is saved to `state/` (not
      `MISSION.md`); Phase 2 writes the formal `MISSION.md`.
- [ ] `test_headcount.py` — the cap chain (total → department → team → IC);
      allotment in Phase 3/4; Pod A + Pod B; headcount recorded in mission +
      policies; a hire exceeding a cap is blocked.
- [ ] `test_clarification_pods.py` — the three clarification pods form, validate
      (2 members, 1-tier spread, communication gate), and carry their
      clarifications forward.
- [ ] `test_execution_pods.py` — the A/B/C execution pods (disagreement /
      cross-team / routing rule) + the collaboration pod (IC+manager).
- [ ] `test_department_policy.py` — the `department_head` (NOT the IC) authors
      the department-scoped policy **after** the leader+head pod.
- [x] `test_department_proposal.py` — the leader proposes departments in Mission;
      Org bootstrap creates them.
- [ ] `test_prompts.py` — the pipeline's prompts live in the `prompts/`
      location with usage comments.

### Story 10 — Docs
> Enumerate the files that need updating (from a scan of the repo).
- [ ] `README.md` — **the main doc**: update the pipeline description (Phases
      1–6 → 1–8), the process diagram, the invariants, and the quick start to
      the 8-phase process + headcount.
- [ ] `.env.example` — add the new headcount + pod knobs.
- [ ] `SETUP.md` — update the configuration-knobs section (new headcount/pod
      knobs).
- [ ] Module docstrings: `runtime/session.py`, `runtime/dispatch_common.py`
      (new), `runtime/plan.py` (new), `runtime/staff.py` (new),
      `runtime/execute.py` (new), `runtime/org.py`, `runtime/pods.py`.
- [ ] **Not updated** (historical / reference): `AUDIT.md`, `LOG_AUDIT.md`,
      `RUN_AUDIT.md`, `DEPARTMENT_AUDIT.md`, `REPO_CHANGES.md`, `MISSION.md`
      (structure unchanged), `EPIC.md` (this file).

### Story 11 — Prompts directory (`prompts/`)
- [ ] Create a `prompts/` directory (or a single `prompts.py` module) to store
      the pipeline's prompts (and parts of prompts).
- [ ] Extract the prompts currently built inline in `runtime/llm_api.py`
      (`_context`) and the phase modules: the **intake** context, **mission**
      context, **leader** context, **head** context, **manager** context, **IC**
      context, **policy** context, and the **pod** prompts (agenda / rounds /
      close).
- [ ] Add a **comment above each prompt/part** indicating **how/where it is used**
      (which phase / which role / which pod), for auditing + suggesting changes.

### Story 12 — "Devil's advocate" role (a leader's direct report / red-team auditor) (`runtime/org.py`, `runtime/pods.py`, `runtime/session.py`, `runtime/permissions.py`)
- [ ] Add a **single "devil's advocate" role** reporting **directly to the
      leader** (always created in Org bootstrap; mandatory — a formal **"gut
      check"** on the org's outcomes, not a department).
- [ ] Grant it **cross-department read access** — one of the only roles that can
      read other departments' directories (via `permissions.py`).
- [ ] Make it **"listen" to any pod the leader is in AND any pod the heads are
      in** (it observes those deliberations, not just the final reports).
- [ ] **Prime it to doubt** — its mandate does not accept information as true;
      it checks claims against what the pipeline has actually produced.
- [ ] Give it a **heavy emphasis on moral decision-making** — it flags
      immoral/improper actions, not just factual errors.
- [ ] **Phase 7 hook** — in Evaluate it returns a verdict (`clean` /
      `flag: <findings>`); in **Phase 8 (Decide)** a `flag` is consumed by the
      leader to **force a re-check** or **block a stop**.
- [ ] Update the leader's **department proposal** to always include this role
      (mandatory — not optional).

## 6. Dependencies + Ordering

```
Story 2 (split dispatch)  ── foundational
   │
   ├── Story 4 (pods)  [depends on 2]
   ├── Story 5 (department policy)  [depends on 2, 4]
   ├── Story 3 (headcount)  [depends on 2]
   │
   └── Story 1 (Session restructure)  [depends on 2, 3, 4, 5]
            │
            └── Story 8 (CLI)  [depends on 1]

Story 6 (department proposal)  [independent of the split]
Story 7 (config)  [independent, parallel]
Story 12 (devil's advocate role)  [depends on 2, 4; touches org + pods + session + permissions]

Story 9 (tests)  [depends on 1–8, 12]
Story 10 (docs)  [depends on all]
Story 11 (prompts)  [depends on 2]
```

**Suggested execution order:**
1. Story 2 (split dispatch) — extract `dispatch_common.py`, create
   `plan.py`/`staff.py`/`execute.py`.
2. Story 4 (pods) — clarification + reporting + headcount-finalization +
   execution pods (all capped-iterations).
3. Story 3 (headcount) — cap chain + allotment + finalization pods.
4. Story 5 (department policy) — head authors the policy after the leader+head pod.
5. Story 6 (department proposal) + Story 7 (config) — Mission + knobs.
6. Story 12 (devil's advocate role) — a leader's direct report / red-team
   auditor: cross-department read + listens to leader/head pods + primed to
   doubt + moral emphasis + Phase-7 verdict → Phase-8 consequence.
7. Story 1 (Session restructure) + Story 8 (CLI) — wire the 8 phases + logging.
8. Story 11 (prompts) — extract the prompts into `prompts/`.
9. Story 9 (tests) — verify end-to-end offline.
10. Story 10 (docs) — finalize the doc files.

## 7. Verification

- **Offline (StubBackend)**: run the full 8-phase pipeline with the stub
  backend (`LLM_BACKEND=stub`) and confirm each phase runs in order (Intake
  first), the cycle loop repeats on "continue", and the org structure
  (departments → teams → ICs) is created across Phases 3/4/5.
- **Intake + Mission unchanged**: confirm Phase 1 is the Intake clarifying Q&A
  loop and Phase 2 is the Mission (now + department proposal); the informal
  draft is saved to `state/` (not `MISSION.md`); Phase 2 writes the formal
  `MISSION.md`.
- **Architypes unchanged**: confirm the org still uses
  `leader`/`department_head`/`manager`/`ic` (tiers 0/1/2/3) — no rename.
- **Headcount**: confirm the cap chain (total → department → team → IC); the
  leader allots department caps (Phase 3) + Pod A; the head allots team/IC caps
  (Phase 4) + Pod B; headcount is recorded in the mission addendum + policies; a
  hire exceeding a cap is blocked.
- **Clarification pods**: confirm all three deliberate pods form, validate
  (2 members, a valid 1-tier spread, the communication gate at each level), run
  for a capped number of iterations, and carry their clarifications forward.
- **Reporting pods**: confirm the reporting pods (IC→manager, manager→head,
  head→leader) form, validate, run for a capped number of iterations, and
  surface the child's report to the parent (Phase 7).
- **Capped iterations**: confirm every pod runs for a capped number of
  iterations/rounds, then the initiator returns a result.
- **Execution pods**: confirm the A/B/C execution pods (disagreement /
  cross-team / routing rule) + the collaboration pod (IC+manager) form during
  Execute.
- **"Devil's advocate" role**: confirm it is always created (a leader's direct
  report), can read other departments' directories (cross-department read
  access), "listens" to the leader's and heads' pods, is primed to doubt
  (doubts a head's "$1k revenue" claim if the pipeline hasn't run), flags
  immoral/improper actions (e.g. bypassing robots.txt), returns a Phase-7
  verdict, and a `flag` is consumed in Phase 8 to force a re-check / block a
  stop.
- **Department policy**: confirm the `department_head` (NOT the IC) authors the
  department-scoped policy **after** the leader+head pod; the `permissions.py`
  ownership rule is unchanged.
- **Prompts**: confirm the pipeline's prompts live in the `prompts/` location,
  each with a usage comment above it.
- **Reset**: confirm `reset_org --yes` wipes the departments (they live under
  `departments/`).
- **CLI**: confirm `run_session.py --fresh` / `--revisit` / `--dry-run` work
  with the 8-phase logging.

## 8. Risks + Mitigations

- **Module split** (extracting shared helpers) — mitigate by extracting
  `dispatch_common.py` first (pure move, no logic change), then building the
  three phase modules on top.
- **Headcount is a new cross-cutting concern** (caps + allotment + finalization
  pods + recording) — mitigate by adding it as its own Story (Story 3) with a
  clear cap chain, and by reusing the existing `hire`/`fire`/`replace_leader`
  paths (which already enforce `DIRECT_IC_CAP`) for the cap enforcement.
- **Clarification + reporting + headcount-finalization pods are new pod types**
  (deliberate, not A/B/C-triggered) — mitigate by validating each against the
  existing pod invariants and keeping them distinct from the execution pods.
- **"Devil's advocate" role** (a new leader's direct report + cross-department
  read access + pod "listening" + a Phase-7/8 hook) — mitigate by making it a
  distinct Story (Story 12) and by scoping the cross-department read access
  tightly in `permissions.py` (the devil's advocate — and the leader — are the
  only ones that can read other departments' directories).
- **Department-policy timing** (the policy depends on the leader+head pod
  completing first) — mitigate by sequencing the pod → policy strictly in
  `plan.py` (the policy context includes the pod's clarification).
- **Cycle-loop semantics** (whether Plan/Staff re-run each cycle) — the epic
  keeps them in the cycle (matching current behavior). If the intent is "create
  structure once, cycle only Execute/Evaluate/Decide", the loop can be narrowed
  — flag for confirmation.
- **Prompt extraction** (moving inline prompts into `prompts/`) — mitigate by
  doing it as a pure move (the prompt text is unchanged), with a usage comment
  above each, so behavior is preserved and the prompts are auditable.
