# Story 12 — "Devil's advocate" role (a leader's direct report / red-team auditor)

> **Status: Done** — the role is always created in Org bootstrap (12.1); it
> "listens" to the leader's + heads' pods (12.2); its cross-department read
> access is scoped in `permissions.py` (12.3); and its Phase-7 gut check
> returns a verdict (`clean` / `flag`) that Phase 8 consumes (a flag forces a
> re-check / blocks a stop) (12.4).

## Goal

Add a **single "devil's advocate" role** — a red-team auditor reporting
**directly to the leader** — that institutes a formal **"gut check"** on the
org's outcomes. It is **not** a department: it is one role, created outside the
normal reporting chain so the people it checks cannot shape what it sees.

The role's charter:

1. **Always created** in Org bootstrap (mandatory — not optional).
2. **Cross-department read access** — one of the only roles that can read other
   departments' directories (scoped in `permissions.py`).
3. **"Listens" to any pod the leader is in AND any pod the heads are in** — it
   observes those deliberations, not just the final reports.
4. **Primed to doubt** — it does not accept information as true; it checks
   claims against what the pipeline has actually produced.
5. **Heavy emphasis on moral decision-making** — it flags immoral/improper
   actions, not just factual errors.
6. **Phase 7 hook** — in Evaluate it returns a verdict (`clean` /
   `flag: <findings>`); in **Phase 8 (Decide)** a `flag` is consumed by the
   leader to **force a re-check** or **block a stop** (don't ship
   low-quality/immoral outcomes).

> **Examples (the spec's intent):**
> - A head claiming **"We have generated $1k in revenue"** is **doubted** if
>   the pipeline hasn't even run yet (no execution artifacts to back the claim).
> - A head proposing **"generate more revenue by bypassing a website's
>   robots.txt"** is **flagged as immoral/improper** (an ethics violation,
>   independent of whether it would work).

## Files

- `runtime/org.py` — **modify** (the role is always created in bootstrap).
- `runtime/pods.py` — **modify** (the role "listens" to the leader's + heads'
  pods — it observes their deliberations).
- `runtime/session.py` — **modify** (the Phase-7 verdict + the Phase-8
  consequence — a `flag` forces a re-check / blocks a stop).
- `runtime/permissions.py` — **modify** (the cross-department read access).
- `org/tiers.py` — **modify** (the `can_read` / `cross_team_read` logic for the
  devil's advocate).
- `prompts/__init__.py` — **modify** (the `DEVILS_ADVOCATE_INSTRUCTION` prompt
  — the gut-check instruction, used by `_devils_advocate_verdict`).

## Detailed changes

### 12.1 `runtime/org.py` — the "devil's advocate" role is always created

In `org.bootstrap` (Phase 3), the **"devil's advocate" role** is **always
created** (even if the leader omits it from the `department_proposal`, Story
6):

1. **The role** — a single `Role` with a `devil's advocate` mandate. It reports
   **directly to the leader** (it is the leader's direct report — a red-team
   auditor, not a `department_head` of a working department). Define a constant
   (e.g. `DEVILS_ADVOCATE_ROLE = "devils_advocate"`).
2. **Always created** — `org.bootstrap` ensures the role is hired (the existing
   `org.hire` path, HR-approved). This is **in addition to** the leader's
   proposed departments (the proposal + the mandatory role).
3. **The mandate** — the role's mandate is to **institute a formal "gut check"**
   on the org's outcomes: **primed to doubt** (does not accept claims as true),
   **heavy on moral decision-making** (flags immoral/improper actions), and to
   **raise concerns** (fabrication, hallucination, low-quality outcomes). The
   mandate is set on the role.

> **Note:** the role is **not** a `department_head` and does **not** own a
> `departments/<slug>/` directory — it is a standalone role reporting to the
> leader. It does **not** change the architypes (`leader → department_head →
> manager → ic`) or add a new tier.

### 12.2 `runtime/pods.py` — the role "listens" to the leader's + heads' pods

The role **"listens" to any pod the leader is in AND any pod the heads are in**
(it observes those deliberations, not just the final reports):

1. **The listener** — when a pod the leader or a head is in is formed (e.g.
   Pod A — all `department_head`s + the leader; the leader+head clarification
   pods; the head+manager pods), the devil's advocate role is given **read
   access to the pod's deliberation** (it observes the pod's messages /
   clarifications).
2. **The scope** — the role listens to:
   - **any pod the leader is in** (e.g. Pod A, the leader-replacement vote, the
     leader+head clarification pods);
   - **any pod the heads are in** (e.g. Pod A, the leader+head clarification
     pods, the head+manager pods).
3. **The observation** — the role's listening is **visible** (it is logged in
   the audit trail, matching the existing "visible, never silent" philosophy).
   The role's reads of the pods' deliberations are recorded in the audit (so
   the operator can see the cross-pod reads).

> **Note:** "listening" means the role **observes** the pod's deliberation (it
> reads the pod's messages / clarifications) — it does **not** participate in
> the pod (it is not a pod member). It uses its cross-department read access to
> observe the pods.

### 12.3 `runtime/permissions.py` — the cross-department read access

The devil's advocate role + the leader are **one of the only roles that can
read other departments' directories**. Update the read gate:

1. **`tiers.can_read`** (in `org/tiers.py`) — the current `can_read` allows:
   - the leader: only `MISSION.md`;
   - the head: only its own department policy;
   - the manager / IC: only within its own department.

   Add an **exception** for the devil's advocate role + the leader: they can
   read **other departments' directories** (the `departments/<other>/` paths).
   E.g.:
   ```python
   def can_read(role, path: str) -> bool:
       # The devil's advocate role + the leader can read other departments'
       # directories (the cross-department read access).
       if is_devils_advocate(role) or is_leader(role):
           return path == "MISSION.md" or path.startswith("departments/")
       if is_head(role):
           return path == policy_path(role.department)
       # manager / ic
       return path.startswith(f"departments/{role.department}/")
   ```
2. **`is_devils_advocate(role)`** — a helper (in `org/tiers.py`) that returns
   True if the role **is** the devil's advocate role (e.g.
   `role.name == DEVILS_ADVOCATE_ROLE` or a dedicated field).
3. **`permissions.read_reason`** — the read gate in `runtime/permissions.py`
   (the `READ_SCOPE` / the `cross_team_read` logic) is updated to allow the
   devil's advocate role + the leader to read other departments' directories
   (the `can_read` change in `tiers.py` is the source of truth).

> **Note:** the devil's advocate's cross-department read is **visible** (it is
> logged in the audit trail, matching the existing "visible, never silent"
> philosophy). The devil's advocate's reads of other departments' directories
> are recorded in the audit (so the operator can see the cross-department
> reads).

### 12.4 `runtime/session.py` — the Phase-7 verdict + the Phase-8 consequence

The role **institutes a formal "gut check"** on the org's outcomes. The check
happens in **Phase 7 (Evaluate)** (Story 1) + the consequence in **Phase 8
(Decide)**:

1. **Phase 7 (Evaluate)** — the devil's advocate role:
   - reads the other departments' work (via the cross-department read access);
   - observes the pods it "listens" to (the leader's + heads' pods);
   - **doubts** the claims (does not accept them as true — checks them against
     what the pipeline has actually produced);
   - **flags** immoral/improper actions (heavy emphasis on moral
     decision-making);
   - returns a **verdict**: `clean` (no concerns) or `flag: <findings>`
     (concerns raised — fabrication, hallucination, low-quality outcomes,
     immoral/improper actions).
2. **Phase 8 (Decide)** — the leader consumes the verdict:
   - if `clean`, the decision proceeds normally (continue / complete /
     escalate);
   - if `flag`, the leader **forces a re-check** (re-evaluate the flagged
     outcomes) or **blocks a stop** (does not complete / ship the low-quality
     or immoral outcomes). The `flag` is surfaced to the leader (the decision)
     + the operator (the audit).

> **Note:** the verdict is **visible** (it is logged in the audit trail,
> matching the existing "visible, never silent" philosophy). The verdict + the
> Phase-8 consequence are recorded in the audit (so the operator can see the
> gut check + its consequence).

> **Implementation:** the gut check runs in `runtime/session.py`.
> `_evaluate_progress` (Phase 7) calls `_devils_advocate_verdict(leader_out,
> decisions)` **after** the leader's synthesis; it invokes the devil's advocate
> role (the `DEVILS_ADVOCATE_INSTRUCTION` prompt) with the leader's synthesis +
> the pods' deliberations + the department work (read via
> `_department_work_summary` through the cross-department read access), stores
> the verdict on `self.da_verdict`, and logs it to the audit. `_decide`
> (Phase 8) consumes `self.da_verdict` — a `flag` forces a re-check (the status
> is forced to `continue`) / blocks a stop, and is surfaced to the leader (the
> decision) + the operator (the audit). The check is **contained** (a missing
> role or an invoke failure is logged and never takes down Phase 7).

> **Ordering:** this story **depends on Story 6** (the department proposal —
> the role is always included in the proposal) + **Story 1** (the 8-phase
> Session — the Phase-7 verdict + the Phase-8 consequence) + **Story 4** (the
> pods — the role "listens" to the leader's + heads' pods). Do this after
> Stories 1 + 4 + 6.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on a new `tests/test_devils_advocate.py` (the
> role is always created; the cross-department read access is scoped to the
> devil's advocate role + the leader; the role "listens" to the leader's +
> heads' pods; the Phase-7 verdict is returned; the Phase-8 consequence — a
> `flag` forces a re-check / blocks a stop) + the existing
> `tests/test_permissions.py` + `tests/test_tiers.py` + `tests/test_org.py` +
> `tests/test_pods.py`.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.

## Repairs

> **Repair 1 (2026-07-10):** `tiers.can_read` — the leader's cross-department
> read access was not scoped (the `is_leader` branch was missing) — a head/IC
> read of another department could slip past the read gate. The leader (and
> the devil's advocate role) now explicitly get the cross-department read
> (`path == "MISSION.md" or path.startswith("departments/")`), while the head
> and manager/IC branches keep their own scope.
>
> **Repair 2 (2026-07-10):** `tiers.can_read_code` — the leader could read
> code (the `is_leader` check was missing from the code-read refusal) — a
> head/leader code read was not refused. The leader is now refused any code
> read (`if is_leader(role) or is_head(role): return False`); only the
> devil's advocate role reads code (its cross-department access).
>
> **Tests (2026-07-10):** 12 new tests in `tests/test_devils_advocate.py` —
> the role is always created in bootstrap; the cross-department read is
> scoped to the role + the leader; the role "listens" to the leader's +
> heads' pods (and not to IC pods); the Phase-7 verdict (`clean` / `flag` /
> missing-role); the Phase-8 consequence (a flag blocks a stop, a clean
> verdict does not); and the reporting-pod skip (no 3-tier-spread pod).
