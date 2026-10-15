# Story 12 — Mandatory "devil's advocate" department + combined morality/ethics

## Goal

Two changes to the department structure:

1. **The morality + ethics departments are combined** into one.
2. A **mandatory "devil's advocate" department** (always created in Org
   bootstrap) whose mandate is to **evaluate the other departments' work** +
   **raise concerns** (lies, hallucinations, inappropriate work). It is **one
   of the only departments that can read other departments' directories**
   (cross-department read access, scoped in `permissions.py`).

## Files

- `runtime/org.py` — **modify** (the mandatory department is always created;
  the morality + ethics combination).
- `runtime/permissions.py` — **modify** (the cross-department read access).
- `org/tiers.py` — **modify** (the `can_read` / `cross_team_read` logic for the
  devil's advocate).

## Detailed changes

### 12.1 `runtime/org.py` — the mandatory "devil's advocate" department

In `org.bootstrap` (Phase 3), the **mandatory "devil's advocate" department**
is **always created** (even if the leader omits it from the
`department_proposal`, Story 6):

1. **The department slug** — e.g. `devils_advocate` (no apostrophe — it is a
   slug). Define a constant (e.g. `DEVILS_ADVOCATE_DEPT = "devils_advocate"`).
2. **Always created** — `org.bootstrap` ensures the devil's advocate
   department is created (the `departments/devils_advocate/` directory) + the
   `department_head` is hired (the existing `org.hire` path, HR-approved). This
   is **in addition to** the leader's proposed departments (the proposal + the
   mandatory department).
3. **The mandate** — the devil's advocate head's mandate is to **evaluate the
   other departments' work** + **raise concerns** (lies, hallucinations,
   inappropriate work). The mandate is set on the head role (the
   `department_head` for the `devils_advocate` department).

### 12.2 `runtime/org.py` — the morality + ethics combination

The current org has **separate "morality" and "ethics" departments**. They are
**combined into one**:

1. **The combined department** — e.g. `ethics` (or `morality_ethics`). Define a
   constant (e.g. `ETHICS_DEPT = "ethics"`).
2. **The combination** — `org.bootstrap` creates **one** ethics department
   (not two). If the leader's `department_proposal` (Story 6) includes both
   "morality" and "ethics", they are **merged** into the single ethics
   department (the head is hired once).
3. **The mandate** — the combined ethics department's mandate is the union of
   the old morality + ethics mandates.

> **Note:** the exact slugs (`devils_advocate`, `ethics`) are up to the
> implementation — define them as constants in `org.py` (or a config) so they
> are consistent across the codebase.

### 12.3 `runtime/permissions.py` — the cross-department read access

The devil's advocate department (all its roles) + the leader are **one of the
only departments that can read other departments' directories**. Update the
read gate:

1. **`tiers.can_read`** (in `org/tiers.py`) — the current `can_read` allows:
   - the leader: only `MISSION.md`;
   - the head: only its own department policy;
   - the manager / IC: only within its own department.
   
   Add an **exception** for the devil's advocate (all its roles) + the leader:
   they can read **other departments' directories** (the `departments/<other>/`
   paths). E.g.:
   ```python
   def can_read(role, path: str) -> bool:
       # The devil's advocate (all its roles) + the leader can read other
       # departments' directories (the cross-department read access).
       if is_devils_advocate(role) or is_leader(role):
           return path == "MISSION.md" or path.startswith("departments/")
       if is_head(role):
           return path == policy_path(role.department)
       # manager / ic
       return path.startswith(f"departments/{role.department}/")
   ```
2. **`is_devils_advocate(role)`** — a helper (in `org/tiers.py`) that returns
   True if the role is in the devil's advocate department (e.g.
   `role.department == DEVILS_ADVOCATE_DEPT`).
3. **`permissions.read_reason`** — the read gate in `runtime/permissions.py`
   (the `READ_SCOPE` / the `cross_team_read` logic) is updated to allow the
   devil's advocate + the leader to read other departments' directories (the
   `can_read` change in `tiers.py` is the source of truth).

> **Note:** the devil's advocate's cross-department read is **visible** (it is
> logged in the audit trail, matching the existing "visible, never silent"
> philosophy). The devil's advocate's reads of other departments' directories
> are recorded in the audit (so the operator can see the cross-department
> reads).

### 12.4 The devil's advocate's evaluation

The devil's advocate department **evaluates the other departments' work** +
**raises concerns**. The evaluation happens in **Phase 7 (Evaluate)** (Story
1): the devil's advocate head reads the other departments' work (via the
cross-department read access) + raises concerns (lies, hallucinations,
inappropriate work). The concerns are surfaced to the leader (the evaluation)
+ the decision (Phase 8).

> **Ordering:** this story **depends on Story 6** (the department proposal) +
> Story 1 (the 8-phase Session). Do this after Stories 1 + 6.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on a new `tests/test_devils_advocate.py` (the
> mandatory department is always created; the cross-department read access is
> scoped to the devil's advocate + the leader) + the existing
> `tests/test_permissions.py` + `tests/test_tiers.py` + `tests/test_org.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
