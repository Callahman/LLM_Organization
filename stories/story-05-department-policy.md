# Story 5 — Department policy

## Goal

The **department policy** is authored by the **`department_head`**, in the
**Plan phase (Phase 4)**, **after a leader+head clarification pod**. The policy
is a **department-level artifact** (owned by the head) that **may detail
specific team roles / team-level policy** — that is up to the head. The
`permissions.py` department-policy ownership rule is **unchanged**.

## Files

- `runtime/plan.py` — **modify** (the policy generation, preceded by the
  leader+head clarification pod).
- `runtime/org.py` — **modify** (the existing `generate_head_policies` is
  moved / called from `plan.py`).
- `runtime/permissions.py` — **no change** (the ownership rule is unchanged).

## Detailed changes

### 5.1 Move the policy generation into `plan.py`

The current `org.generate_head_policies` (in `runtime/org.py`) generates the
department policies (the `<DEPT>_POLICY.md` files, one per department). In
`plan.run_plan` (Story 2), the policy generation is **called here, after the
leader+head clarification pod**:

1. **The leader+head clarification pod** (Story 4) — a deliberate 2-member
   parent+child pod that clarifies the department's mission (capped
   iterations).
2. **The head authors the department policy** — the existing
   `org.generate_head_policies` mechanism (or a new
   `plan.generate_department_policy`), called **after** the pod. The policy
   context includes the **clarification pod's outcome** (the clarified
   mission) — so the policy reflects the clarified mission.

> **Sequencing:** the pod → policy must be **strict** (the policy depends on
> the pod completing first). The policy context includes the pod's
> clarification.

### 5.2 The policy is a department-level artifact that may detail team roles

The policy is a **department-level artifact** (owned by the head), but it
**may detail specific team roles / team-level policy** — that is up to the
head. The policy markdown (the `<DEPT>_POLICY.md`) can include:

- The department's mission / purpose.
- The department's headcount (the team caps — Story 3).
- **Team roles** — the specific roles / responsibilities of the teams within
  the department (the head's choice).
- Any team-level policy (the head's choice).

The policy is **not** a per-team file (it is a single department-level file),
but its **content** may detail the teams.

### 5.3 `permissions.py` ownership rule — unchanged

The `permissions.py` department-policy ownership rule is **unchanged**: the
`department_head` **owns** the policy (the `<DEPT>_POLICY.md` file). The
existing `permissions.py` logic (the `policy_path` / the department-policy
ownership) is **not** modified. The head is the only role that may write the
policy (via the existing `org.generate_head_policies` path).

> **Note:** the `permissions.py` `PROTECTED` / `can_edit` logic does not treat
> the policy as a meta-rule — the head owns it (the existing behavior). Do not
> change this.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the department-policy test (a new
> `tests/test_department_policy.py` — see Story 9) + the existing
> `tests/test_dispatch.py` (`test_head_generates_policy_before_managers`) +
> `tests/test_permissions.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
