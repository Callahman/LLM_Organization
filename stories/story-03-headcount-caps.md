# Story 3 — Headcount caps + allotment

## Goal

Add the **headcount cap chain** — a top→bottom chain of caps that bounds the
org's size:

`Total (env) → Department (% of total, allotted by the leader) → Team (% of the department cap, allotted by the head) → IC count (within the team cap)`

A hire that would exceed a cap is **blocked / escalated**. Headcount is
**recorded** in the **mission addendum** + each department **policy**.

## Files

- `runtime/config.py` — **modify** (add the `HEAD_COUNT_TOTAL` knob).
- `.env.example` — **modify** (document the new knobs).
- `runtime/org.py` — **modify** (Phase 3: the leader allots department caps;
  the cap enforcement).
- `runtime/plan.py` — **modify** (Phase 4: the head allots team/IC caps; the
  cap enforcement).
- `runtime/staff.py` — **modify** (Phase 5: enforce the team/IC cap on IC
  hires).

## Detailed changes

### 3.1 `runtime/config.py` — the total cap knob

Add to `ENV_TO_CONFIG`:

```python
"HEAD_COUNT_TOTAL": ("head_count_total", int),
```

`head_count_total` is the **total cap** — the maximum number of roles
(ICs + managers + heads) the org may have. It is read from the env
(`HEAD_COUNT_TOTAL`) and handed to `Session` (which passes it to
`org.bootstrap` and the phase modules).

### 3.2 The cap-chain data structures

Represent the cap chain as follows (carried on the org / the phase results):

- **Total cap**: `config["head_count_total"]` (int).
- **Department caps**: a dict `{department_slug: int}` — the cap per
  department, allotted by the leader in Phase 3. The sum of the department
  caps must be ≤ the total cap.
- **Team caps**: a dict `{(department_slug, team_slug): int}` — the cap per
  team, allotted by the head in Phase 4. The sum of the team caps within a
  department must be ≤ the department cap.
- **IC counts**: the number of active ICs within a team — enforced against the
  team cap in Phase 5.

Store the department caps + team caps on the org (e.g. `org.department_caps`
and `org.team_caps`), or carry them in the phase results (`PlanResult`,
`StaffResult`). The exact location is up to the implementation, but the cap
chain must be **queryable** at each hire.

### 3.3 Phase 3 (Org bootstrap) — the leader allots department caps

In `org.bootstrap` (or a new `org.allot_department_caps`), after the
departments are created + the `department_head`s hired:

1. **The leader allots the department caps** — invoke the leader (or read its
   output) to get the `{department_slug: cap}` mapping. Each cap is a **% of
   the total** (or an absolute count that sums to ≤ the total). The leader
   decides the allocation (it has the global view).
2. **Enforce** — the sum of the department caps must be ≤ the total cap. If it
   exceeds, the leader re-allots (bounded retry) or the excess is escalated.
3. **Pod A** (Story 4) — the headcount-finalization pod (all `department_head`s
   + the leader) finalizes the headcount per department (the leader has final
   say). The Pod A outcome is the **final** department caps.
4. **Record** — the department caps are recorded in the **mission addendum**
   (see 3.6).

### 3.4 Phase 4 (Plan) — the head allots team/IC caps

In `plan.run_plan` (Story 2), after the head hires the managers:

1. **The head allots the team/IC caps** — for each team, the head allots a cap
   (a **% of the department cap**). The head decides the allocation (it has the
   department view).
2. **Enforce** — the sum of the team caps within the department must be ≤ the
   department cap. If it exceeds, the head re-allots (bounded retry) or the
   excess is escalated.
3. **Pod B** (Story 4) — the headcount-finalization pod (all `manager`s + the
   head) finalizes the manager/IC headcount (the head has final say). The Pod B
   outcome is the **final** team caps.
4. **Record** — the team caps are recorded in the **department policy** (see
   3.6).

### 3.5 Phase 5 (Staff) — enforce the team/IC cap on IC hires

In `staff.run_staff` (Story 2), when the manager hires ICs:

1. **Enforce** — the number of active ICs within a team must be ≤ the team cap.
   A hire that would exceed the team cap is **blocked** (the manager is told
   the cap is reached) or **escalated** (to the head).
2. Reuse the existing `org.hire` path (which already enforces
   `DIRECT_IC_CAP` for the per-manager IC cap) — add the **team cap** check on
   top.

### 3.6 Record headcount (mission addendum + policy)

- **Mission addendum**: after Phase 3 (Pod A), append a **headcount addendum**
  to the mission (either a section in `MISSION.md` or a separate
  `state/headcount_addendum.md`). It records the **total cap** + the
  **department caps** (the `{department_slug: cap}` mapping). This is the
  org-level headcount record.
- **Department policy**: in Phase 4 (after Pod B), the head's department policy
  (the markdown from 3.4) includes the **team caps** (the
  `{(department, team): cap}` mapping for the department) — the department's
  headcount per team. The policy is the department-level headcount record.

### 3.7 Cap-enforcement helper

Add a helper (e.g. `org.cap_check(cap, current) -> (ok, reason)`) that, given a
cap and the current count, returns whether a hire is allowed. Reuse it at each
level (department / team / IC). A refused hire is **visible** (the reason is
logged + fed back to the hiring role for a corrective retry, matching the
existing "visible, never silent" philosophy).

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the headcount tests (a new
> `tests/test_headcount.py` — see Story 9) + the existing `tests/test_org.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
