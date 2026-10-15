# Story 4 — Pods

## Goal

Add the **pod types** the 8-phase process needs. There are four kinds, each
running for a **capped number of iterations** before the **initiator returns a
result**:

1. **Clarification pods** — a deliberate 2-member parent+child pod that
   **clarifies the child's mission** (before work).
2. **Reporting pods** — a 2-member parent+child pod where the **child reports
   to the parent** (after work): IC→manager, manager→head, head→leader.
3. **Headcount-finalization pods** — Pod A (all heads + leader) + Pod B (all
   managers + the head).
4. **Execution pods (A/B/C)** + the **collaboration pod** (IC+manager) — the
   A/B/C-triggered multi-member pods an IC spins up during Execute.

All pods validate against the **existing invariants** (size, 1-tier spread,
communication gate).

## Files

- `runtime/pods.py` — **modify** (the pod types + the capped-iterations logic).
- `runtime/plan.py` — **modify** (the leader+head + head+manager clarification
  pods + Pod B).
- `runtime/staff.py` — **modify** (the manager+ic clarification pod).
- `runtime/execute.py` — **modify** (the execution pods A/B/C + the
  collaboration pod).
- `runtime/org.py` — **modify** (Pod A, in Org bootstrap).
- `runtime/session.py` — **modify** (the reporting pods, in Phase 7 — see
  Story 1).

## Detailed changes

### 4.1 `runtime/pods.py` — the pod `kind` + capped iterations

The current `form_pod(...)` / `run_pod(...)` form + run a pod (the deliberation
with the agenda / rounds / close). Add:

1. **A `kind` parameter** — the pod type. Add a `kind` argument to `form_pod` /
   `run_pod` (and the pod record) with one of: `"clarification"`,
   `"reporting"`, `"headcount"`, `"execution"`, `"collaboration"`. The `kind`
   drives the **context** (the purpose the pod is asked to address) + the
   **default round count**.
2. **Capped iterations** — every pod runs for a **capped number of
   iterations/rounds** (`max_rounds`), then the **initiator returns a result**
   (the next-steps / the outcome). The current pod already has a round bound
   (`POD_MAX_ROUNDS`); make the **default round count explicit per pod kind**
   (a config knob per kind, e.g. `CLARIFICATION_POD_ROUNDS`,
   `REPORTING_POD_ROUNDS`, `HEADCOUNT_POD_ROUNDS`, `EXECUTION_POD_ROUNDS`).
   After the cap, the **initiator** (the parent / the caller) is invoked to
   return the **result** (the pod's outcome + the next steps).
3. **The pod context per kind** — the context the pod is given depends on the
   kind:
   - **Clarification**: "Clarify the child's mission. The child is
     `<child_role>`. Produce a clarified mission + any constraints."
   - **Reporting**: "`<child_role>` reports to `<parent_role>`. Surface the
     child's status / results / fire-replace-keep decisions + headcount
     changes."
   - **Headcount**: "Finalize the headcount per `<scope>`. `<final_sayer>` has
     final say."
   - **Execution** / **Collaboration**: the existing A/B/C / collaboration
     context.

### 4.2 Clarification pods (before work)

A **distinct, deliberate 2-member parent+child pod** that clarifies the
child's mission. The membership is the same as the reporting pods (a
parent+child pair); only the `kind` (and the context) differs.

- **leader + `department_head`** (Phase 4, `plan.py`): clarifies the
  department's mission. **After it, the head authors the department policy**
  (Story 5). Tiers (0,1).
- **`department_head` + `manager`** (Phase 4, `plan.py`): clarifies the team's
  mission. Tiers (1,2).
- **`manager` + `ic`** (Phase 5, `staff.py`): clarifies the IC's task. Tiers
  (2,3).

Each is formed via `form_pod([parent, child], kind="clarification")` and run
via `run_pod(..., kind="clarification")` (capped iterations). The **outcome**
(the clarified mission) is carried forward (into the policy / the IC's task /
the headcount allotment).

### 4.3 Reporting pods (after work)

A **2-member parent+child pod** where the child **reports to the parent**. The
membership is the same as the clarification pods; the `kind` is
`"reporting"`. Run in **Phase 7 (Evaluate)** (Story 1):

- **`ic` → `manager`**: the IC reports status / results.
- **`manager` → `department_head`**: the manager reports to the head.
- **`department_head` → leader**: the head reports to the leader.

Each is formed via `form_pod([child, parent], kind="reporting")` and run via
`run_pod(..., kind="reporting")` (capped iterations). The **outcome** (the
child's report — the status / results / fire-replace-keep decisions / headcount
changes) is surfaced to the parent + the leader (the evaluation).

### 4.4 Headcount-finalization pods

- **Pod A** (Phase 3, `org.py`): **ALL `department_head`s + the leader**
  finalize the headcount per department. The **leader has final say**.
  Multi-member, tiers (0,1). Formed via `form_pod([leader, *heads],
  kind="headcount")`.
- **Pod B** (Phase 4, `plan.py`): **all `manager`s + the `department_head`**
  finalize the manager/IC headcount. The **head has final say**. Multi-member,
  tiers (1,2). Formed via `form_pod([head, *managers], kind="headcount")`.

The Pod A / Pod B outcomes are the **final** department caps / team caps
(Story 3).

### 4.5 Execution pods (A/B/C) + collaboration pod (Execute)

In `execute.py` (Story 2), the IC can spin up (each capped-iterations):

- **Execution pod, Trigger A (disagreement)** — the manager disagrees with the
  IC's approach.
- **Execution pod, Trigger B (cross-team)** — the IC's work spans multiple
  teams.
- **Execution pod, Trigger C (routing rule)** — the IC's task type matches a
  routing rule.
- **Collaboration pod (IC + manager)** — the IC needs collaboration with
  another role/department; the manager propagates the need by setting up the
  pod (continues until the IC can complete the task).

These are the **existing** `_check_pod_triggers` A/B/C logic (moved to
`execute.py` from `dispatch_common.py`), now with the `kind`
(`"execution"` / `"collaboration"`) + the capped-iterations.

### 4.6 Validate all pods

Every pod (all four kinds) validates against the **existing invariants**
(`org/tiers.py::validate_pod`): the size (2–6, or the config bounds), the
**1-tier spread**, and the **communication gate** (`can_communicate`). A pod
that fails validation is **not formed** (the reason is logged). The
clarification / reporting pods are 2-member parent+child pairs with a 1-tier
spread — they always pass (the parent+child pair is within the communication
gate).

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the pod tests (a new
> `tests/test_clarification_pods.py` + `tests/test_execution_pods.py` — see
> Story 9) + the existing `tests/test_pods.py` / `tests/test_pod_triggers.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
