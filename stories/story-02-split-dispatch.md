# Story 2 — Split `dispatch.py` into plan / staff / execute

> **Status: Done** — `runtime/dispatch.py` is a thin re-export shim; the shared
> helpers live in `runtime/dispatch_common.py`, and the three phase modules
> (`runtime/plan.py` Phase 4, `runtime/staff.py` Phase 5, `runtime/execute.py`
> Phase 6) hold the head / manager / IC workflows.

## Goal

The monolithic `runtime/dispatch.py` (≈1243 lines) does the old Phase 4
(Dispatch): the leader decomposition → per-department head workflow →
per-team manager workflow → per-IC work → pod triggers → upward report. Split
it into:

- `runtime/dispatch_common.py` — the **shared helpers** (a pure move, no logic
  change).
- `runtime/plan.py` — **Phase 4 (Plan)**: the head workflow.
- `runtime/staff.py` — **Phase 5 (Staff)**: the manager workflow.
- `runtime/execute.py` — **Phase 6 (Execute)**: IC execution + execution pods.

`runtime/dispatch.py` is **deleted** (or kept as a thin re-export shim for any
external importers).

## Files

- `runtime/dispatch.py` — **delete** (or shim).
- `runtime/dispatch_common.py` — **create** (the shared helpers).
- `runtime/plan.py` — **create** (Phase 4).
- `runtime/staff.py` — **create** (Phase 5).
- `runtime/execute.py` — **create** (Phase 6).

## Detailed changes

### 2.1 `runtime/dispatch_common.py` — the shared helpers (pure move)

Move these **out of `dispatch.py`** (no logic change — a pure move). These are
used by more than one of the three phase modules:

- `mission_digest(mission_path)` — the **bounded mission digest** (the mission
  text, truncated to a bounded size). Used by plan / staff / execute.
- `_ensure_role(org, ...)` — **adopt-or-create a role definition** (the
  `org.hire` path that adopts an existing role or creates a new one).
- `_fire_role(org, role, ...)` — **fire a role** (the `org.fire` path, with the
  HR approval + the cascade).
- `_invoke_ic(backend, role, org, mission_path, config, ...)` — **invoke an
  IC** (the work + the corrective retry on a persistent failure). Used by
  execute.
- The **self-edit helpers** — `_apply_self_edits`, `_pre_read_code`, and the
  helpers that gate the IC's self-edit requests through the permission layer.
  Used by execute.
- `_check_pod_triggers(ic, org, ...)` — the **A/B/C pod triggers** (disagreement
  / cross-team / routing rule). Used by execute.
- `_upward_report(org, ...)` — the **upward report** (the IC's report bubbled up
  the line). Used by execute.
- `_decomposition_list(out, key)` — the **decomposition list** (tolerates the
  shapes the real LLM free-forms — a dict, a list, a string). Used by plan.
- The **efficiency-panel helpers** — `_efficiency_panel`, `_process_efficiency`,
  and the helpers that build the per-role / per-department invoke-time panel.
  Used by plan / execute.
- `run_automation(...)` — the **automation** (writing a script + firing an IC to
  run it). Used by execute.

> **Rule:** `dispatch_common.py` contains **only** helpers (no phase sequence).
> The three phase modules import from it. If a helper is used by only one phase
> module, it may stay in that module — but the ones listed above are shared and
> must move.

### 2.2 `runtime/plan.py` — Phase 4 (Plan): the head workflow

Create `run_plan(backend, leader, org, mission_path, config, cycle, ...) ->
PlanResult`. It does the **head workflow** (extracted from the old
`dispatch()`):

1. **The leader decomposition** — invoke the leader to get the
   `department_objectives` (the department → objective mapping). Use
   `_decomposition_list` (from `dispatch_common`) to tolerate the free-formed
   shapes. (This is the first step of the old `dispatch()`.)
2. **Per department** (for each department objective):
   1. **leader+head clarification pod** (Story 4) — a deliberate 2-member
      parent+child pod that clarifies the department's mission (capped
      iterations).
   2. **Department policy** — the head **authors the department policy** (the
      existing `org.generate_head_policies` mechanism, now called here,
      **after** the clarification pod). The policy is a department-level
      artifact that **may detail team roles** (the head's choice).
   3. **Hire managers** — the head hires the `manager`s for the department's
      teams (the existing `org.hire` path, HR-approved).
   4. **Allot team/IC headcount** (Story 3) — the head allots the team/IC caps
      (as a % of the department cap).
   5. **head+manager clarification pods** (Story 4) — a deliberate 2-member
      parent+child pod per team that clarifies the team's mission (capped
      iterations).
   6. **Pod B** (Story 4) — the headcount-finalization pod (all `manager`s +
      the head) that finalizes the manager/IC headcount (capped iterations).

`PlanResult` carries the per-department outcomes (the policy, the hired
managers, the allotted headcount, the clarification outcomes).

### 2.3 `runtime/staff.py` — Phase 5 (Staff): the manager workflow

Create `run_staff(backend, leader, org, mission_path, config, cycle, ...) ->
StaffResult`. It does the **manager workflow** (extracted from the old
`dispatch()`):

1. **Per team** (for each team with a `manager`):
   1. **Hire ICs** — the manager hires the `ic`s for the team (the existing
      `org.hire` path, HR-approved). Enforce the team/IC cap (Story 3).
   2. **Assign tasks** — the manager assigns the tasks to the ICs (the
      decomposition from the head's plan).
   3. **manager+ic clarification pods** (Story 4) — a deliberate 2-member
      parent+child pod per IC that clarifies the IC's task (capped iterations).

`StaffResult` carries the per-team outcomes (the hired ICs, the assigned tasks,
the clarification outcomes).

### 2.4 `runtime/execute.py` — Phase 6 (Execute): IC execution + execution pods

Create `run_execute(backend, leader, org, mission_path, config, cycle, ...) ->
ExecuteResult`. It does the **IC execution** (extracted from the old
`dispatch()`):

1. **Per IC** (for each active IC with a task):
   1. **Invoke the IC** — the work (the existing `_invoke_ic` from
      `dispatch_common`, with the corrective retry).
   2. **Self-edits** — the IC's self-edit requests, gated through the
      permission layer (the self-edit helpers from `dispatch_common`).
   3. **Execution pods (A/B/C)** — the `_check_pod_triggers` (from
      `dispatch_common`) forms an execution pod on Trigger A (disagreement) /
      Trigger B (cross-team) / Trigger C (routing rule) (capped iterations).
   4. **Collaboration pod** (Story 4) — if the IC needs collaboration with
      another role/department, the manager sets up the collaboration pod
      (IC+manager, capped iterations).
2. **The upward report** — `_upward_report` (from `dispatch_common`) bubbles the
   IC's report up the line.

`ExecuteResult` carries the per-IC outcomes (the work, the self-edits, the pod
outcomes, the upward report).

### 2.5 Delete `runtime/dispatch.py` (or shim)

- **Delete** `runtime/dispatch.py` once the three phase modules +
  `dispatch_common.py` are in place and `session.py` (Story 1) imports the new
  modules.
- **If** any external code (a test, a script) imports `runtime.dispatch`, keep a
  **thin re-export shim** (`from runtime.plan import run_plan; ...`) so the
  import does not break. Check the test suite (`tests/test_dispatch.py`) — it
  imports `runtime.dispatch`; either update those tests to import the new
  modules, or keep the shim.

> **Ordering:** this story is **foundational** — Story 1 (Session) imports the
> three phase modules, and Stories 3/4/5 add the headcount / pods / policy on
> top of them. Do this first.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Pay attention to `tests/test_dispatch.py` (it imports
> `runtime.dispatch`) — if you deleted the module, those tests must be updated
> to import the new modules (or the shim kept).
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
