# Story 6 — Department proposal in the Mission phase

## Goal

The **leader proposes the departments** + priority order in the **Mission phase
(Phase 2)**. The **Org bootstrap (Phase 3)** then **creates** the proposed
departments. This decouples the department *proposal* (Phase 2, the leader's
global view) from the department *creation* (Phase 3, the org bootstrap).

## Files

- `roles/leader.py` — **modify** (add the `department_proposal` field to
  `LEADER_OUTPUT_SCHEMA`).
- `runtime/mission.py` — **modify** (`MissionResult` carries the proposed
  departments; the mission context asks for the proposal).
- `runtime/org.py` — **modify** (`bootstrap` accepts the proposed departments).

## Detailed changes

### 6.1 `roles/leader.py` — the `department_proposal` field

Add a **`department_proposal`** field to `LEADER_OUTPUT_SCHEMA` (the
departments + priority order the leader proposes). It is a top-level field
(phase-specific, like the existing `questions` / `decomposition` fields), so it
does not leak into the other phases:

```python
"department_proposal": {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "slug": {"type": "string"},        # the department slug (e.g. "analytics")
            "purpose": {"type": "string"},     # the department's mandate
            "priority": {"type": "number"},    # the priority order (1 = highest)
        },
        "required": ["slug"],
    },
},
```

The leader fills this in during the Mission phase (Phase 2) — it proposes the
departments (the slugs + purposes) + the priority order. The shape is what
`org.bootstrap` reads (6.3).

### 6.2 `runtime/mission.py` — carry the proposal

- **`MissionResult`**: add a field for the proposed departments (e.g.
  `department_proposal: List[Dict[str, Any]]`). The `run_mission` function
  extracts the `department_proposal` from the leader's output (tolerating the
  free-formed shapes — a list, a dict, a string) and carries it in
  `MissionResult`.
- **The mission context** (`_mission_context`): add a line asking the leader to
  fill `department_proposal` (the departments + priority order). E.g.:
  "Also set `department_proposal` to a list of the departments you propose
  (each with `slug`, `purpose`, `priority`)."

### 6.3 `runtime/org.py` — `bootstrap` accepts the proposal

The current `org.bootstrap` (Phase 3) creates the departments from the
`org_recommendation` (the leader's org recommendation in the mission). Update
it to **accept the proposed departments** (from `MissionResult.department_proposal`,
6.2):

1. **Read the proposal** — `bootstrap` reads the `department_proposal` (the
   list of proposed departments) from the mission result.
2. **Create the departments** — for each proposed department, `bootstrap`
   creates the department (the `departments/<slug>/` directory) + hires the
   `department_head` (the existing `org.hire` path, HR-approved).
3. **Fall back** — if the `department_proposal` is absent (e.g. an old mission
   that predates this field), fall back to the existing `org_recommendation`
   (the current behavior).

> **Ordering:** this story is **independent of the dispatch split** (Story 2) —
> it only touches the leader schema + the mission + the bootstrap. It can be
> done in parallel with Stories 3–5.

### 6.4 The "devil's advocate" role (cross-ref Story 12)

The **"devil's advocate" role** (Story 12) is a **single auditor reporting
directly to the leader** — a formal **"gut check"** on the org's outcomes
(**not** a department). It is **always created** in Org bootstrap (it is not
optional): the bootstrap ensures the role exists (even if the leader omits it
from the `department_proposal`). The leader's `department_proposal` (this
story) is updated to always include the role. See Story 12 for the details.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the department-proposal test (a new
> `tests/test_department_proposal.py` — see Story 9) + the existing
> `tests/test_mission.py` + `tests/test_org.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
