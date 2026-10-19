# Story 9 — Tests

> **Progress:** `tests/test_execution_pods.py` is written (the A/B/C execution
> pods `kind="execution"` + the collaboration pod (IC + manager) — formation,
> capped iterations, the IC retry, the no-`collaborate` case, and
> collaboration+execution coexistence). The remaining test files (Story 9's full
> scope) are still to be written.

## Goal

Add the **test coverage** for the 8-phase process + the new mechanisms
(headcount + pods + the department proposal + the prompts). The tests run
offline (the `LLM_BACKEND=stub` backend) and verify the structure + the
invariants end-to-end.

## Files

- `tests/test_phases.py` — **create** (the 8-phase structure + the cycle loop).
- `tests/test_intake_mission_unchanged.py` — **create** (Intake + Mission
  largely unchanged).
- `tests/test_headcount.py` — **create** (the cap chain + allotment + the
  finalization pods).
- `tests/test_clarification_pods.py` — **create** (the clarification +
  reporting pods).
- `tests/test_execution_pods.py` — **create** (the A/B/C execution pods + the
  collaboration pod).
- `tests/test_department_policy.py` — **create** (the head authors the policy).
- `tests/test_department_proposal.py` — **create** (the leader proposes
  departments).
- `tests/test_prompts.py` — **create** (the prompts are in `prompts/`).
- `tests/test_dispatch.py` — **modify** (update the imports if `dispatch.py`
  was deleted — see Story 2).

## Detailed changes

### 9.1 `tests/test_phases.py` — the 8-phase structure + the cycle loop

Verify the 8-phase structure + the cycle loop:

- **The 8 phases run in order** — Intake (1) → Mission (2) → Org bootstrap (3)
  → Plan (4) → Staff (5) → Execute (6) → Evaluate (7) → Decide (8).
- **The cycle loop repeats on "continue"** — when Phase 8 (Decide) returns
  "continue", the cycle repeats (Phase 4 again).
- **Bounded by `max_iterations`** — the cycle loop stops when `cycle` reaches
  `max_iterations`.
- **The `phases` dict is `{1..8: count}`** — the `SessionResult.phases` tracks
  the 8 phases.

Use the `LLM_BACKEND=stub` backend (offline) + a temp workspace (`tmp_path`).

### 9.2 `tests/test_intake_mission_unchanged.py` — Intake + Mission unchanged

Verify that Phase 1 (Intake) + Phase 2 (Mission) are largely unchanged:

- **Intake (Phase 1)** — the leader asks clarifying questions (the Q&A loop),
  and the **informal draft** is saved to `state/` (NOT `MISSION.md`).
- **Mission (Phase 2)** — the leader codifies the mission (the approval loop),
  and Phase 2 writes the **formal `MISSION.md`** (on user approval).
- **The informal draft is NOT `MISSION.md`** — the Phase 1 draft is saved to
  `state/` (a separate file), and only Phase 2 (on approval) writes
  `MISSION.md`.

### 9.3 `tests/test_headcount.py` — the cap chain + allotment

Verify the headcount cap chain:

- **The cap chain** — total → department → team → IC (each level is a % of the
  parent).
- **Allotment in Phase 3 / Phase 4** — the leader allots the department caps
  (Phase 3), the head allots the team/IC caps (Phase 4).
- **Pod A + Pod B** — the headcount-finalization pods (all heads + leader; all
  managers + head) finalize the caps.
- **Headcount recorded** — the headcount is recorded in the **mission
  addendum** (the total + department caps) + each **department policy** (the
  team caps).
- **A hire exceeding a cap is blocked** — a hire that would exceed the
  department / team / IC cap is **blocked** (the reason is visible).

### 9.4 `tests/test_clarification_pods.py` — the clarification + reporting pods

Verify the clarification + reporting pods:

- **The clarification pods form** — leader+head, head+manager, manager+ic (the
  2-member parent+child pods).
- **They validate** — 2 members, a valid 1-tier spread, the communication gate
  (at each level).
- **They carry their clarifications forward** — the clarified mission is
  carried into the policy / the IC's task / the headcount allotment.
- **The reporting pods form** — ic→manager, manager→head, head→leader (the
  2-member parent+child pods).
- **They surface the child's report** — the child's status / results are
  surfaced to the parent.
- **Capped iterations** — every pod runs for a capped number of iterations,
  then the initiator returns a result.

### 9.5 `tests/test_execution_pods.py` — the A/B/C execution pods

Verify the A/B/C execution pods + the collaboration pod:

- **Trigger A (disagreement)** — an execution pod forms when the manager
  disagrees with the IC's approach.
- **Trigger B (cross-team)** — an execution pod forms when the IC's work spans
  multiple teams.
- **Trigger C (routing rule)** — an execution pod forms when the IC's task type
  matches a routing rule.
- **The collaboration pod (IC+manager)** — a collaboration pod forms when the
  IC needs collaboration.
- **Capped iterations** — every pod runs for a capped number of iterations,
  then the initiator returns a result.

### 9.6 `tests/test_department_policy.py` — the head authors the policy

Verify the department policy:

- **The `department_head` (NOT the IC) authors the policy** — the policy is
  authored by the head, not the IC.
- **The policy is department-scoped** — the policy is a department-level
  artifact (the `<DEPT>_POLICY.md` file).
- **The policy is authored after the leader+head pod** — the policy is
  authored **after** the leader+head clarification pod (the policy context
  includes the pod's clarification).
- **The policy may detail team roles** — the policy content may detail the
  teams within the department.

### 9.7 `tests/test_department_proposal.py` — the leader proposes departments

Verify the department proposal:

- **The leader proposes departments in Mission** — the leader fills
  `department_proposal` (the departments + priority order) in Phase 2.
- **Org bootstrap creates them** — Phase 3 (Org bootstrap) creates the proposed
  departments (the `departments/<slug>/` directories + the `department_head`s).
- **The fall back** — if the `department_proposal` is absent, the bootstrap
  falls back to the `org_recommendation`.

### 9.8 `tests/test_prompts.py` — the prompts are in `prompts/`

Verify the prompts (Story 11):

- **The prompts live in `prompts/`** — the pipeline's prompts (and parts of
  prompts) are in the `prompts/` location.
- **Each has a usage comment** — each prompt / part has a comment above it
  indicating how/where it is used (the phase / the role / the pod).

### 9.9 `tests/test_dispatch.py` — update the imports

If `runtime/dispatch.py` was deleted (Story 2), update `tests/test_dispatch.py`
to import the new modules (`runtime.plan`, `runtime.staff`, `runtime.execute`,
`runtime.dispatch_common`) instead of `runtime.dispatch`. The test logic
(disagreement / dead-end / self-edit / pod-trigger tests) is **largely
unchanged** — only the imports change.

> **Ordering:** this story **depends on Stories 1–8 + 11** — the tests verify
> the 8-phase process + the new mechanisms. Do this after the code stories.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). This story IS the tests — run the new test files
> (`test_phases.py`, `test_headcount.py`, `test_clarification_pods.py`, etc.)
> and confirm they pass.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**
>   (e.g. a bug in the code under test), **still complete the code work** (do
>   not leave the tests half-written) and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and which
>   tests failed (if any), and that the user should run the test suite to
>   confirm. Do not silently skip this step.
