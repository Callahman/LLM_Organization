# Stories — per-story execution detail

One markdown per story from `EPIC.md` (§5), each going into **more detail on
what changes need to be made** (the files, the functions/classes, the logic).
Each story markdown ends with the **same testing instruction** (run the tests
once in the repo's venv; if it can't be run / fails for environmental reasons,
complete the work and raise the need for testing to the user).

## The 12 stories

| # | File | Story | Status |
|---|------|-------|--------|
| 1 | `story-01-session-restructure.md` | 8-Phase Session restructure (`runtime/session.py`) | **Done** |
| 2 | `story-02-split-dispatch.md` | Split `dispatch.py` into plan / staff / execute | **Done** |
| 3 | `story-03-headcount-caps.md` | Headcount caps + allotment | **Done** |
| 4 | `story-04-pods.md` | Pods (clarification / reporting / headcount / execution) | **Done** |
| 5 | `story-05-department-policy.md` | Department policy | **Done** |
| 6 | `story-06-department-proposal.md` | Department proposal in the Mission phase | **Done** |
| 7 | `story-07-config.md` | Config (new knobs) | Pending |
| 8 | `story-08-cli.md` | CLI (`run_session.py`, `reset_org.py`) | Pending |
| 9 | `story-09-tests.md` | Tests | Pending |
| 10 | `story-10-docs.md` | Docs (doc files to update) | Pending |
| 11 | `story-11-prompts.md` | Prompts directory (`prompts/`) | Pending |
| 12 | `story-12-devils-advocate.md` | "Devil's advocate" role (a leader's direct report / red-team auditor) | Pending |

> **Deployment status:** Stories 1–6 are deployed (the 8-phase Session
> restructure + the `dispatch.py` split, plus the Phase-1 informal draft and the
> 8-phase label cleanup; the headcount cap chain (Story 3), the pods incl. the
> collaboration pod (Story 4), the department policy-after-pod (Story 5), and
> the department proposal (Story 6)). **Step 3** (Stories 3 + 4 + 5 — headcount /
> pods / policy) is now complete; the next deployment is **Step 4** (Story 7 —
> config, and Story 8 — CLI; Story 6 already landed), per the order below.

## Deployment order (detailed, with reasoning)

**Principle:** deploy in **dependency order** — foundational code first,
dependent code after, and tests/docs last. Each step lists what it does and
**why it is in this position** (the dependencies it needs + the rationale).

### Step 1 — Story 2 (split `dispatch.py`)

- **What:** split the monolithic `runtime/dispatch.py` into
  `dispatch_common.py` (shared helpers) + `plan.py` (Phase 4) + `staff.py`
  (Phase 5) + `execute.py` (Phase 6).
- **Why first:** this is **foundational**. The three phase modules +
  `dispatch_common.py` are the **building blocks every later story imports**:
  Story 1 (Session) calls `run_plan` / `run_staff` / `run_execute`, and
  Stories 3/4/5 add the headcount / pods / policy **on top of** those modules.
  If Story 1 were done first, it would import modules that do not exist yet
  (a broken import). A **pure split (no logic change)** is also the safest
  first step — it refactors the existing working code without changing
  behavior, so the baseline stays green.

### Step 2 — Story 1 (8-Phase Session restructure)

- **What:** restructure `Session.run` to the 8 phases + the cycle loop
  (Phases 4–8 repeat on "continue", bounded by `max_iterations`).
- **Why now:** once the phase modules exist (Step 1), the Session can **wire
  the 8-phase sequence**. This is the **backbone** of the new process — after
  this step the pipeline runs end-to-end with the 8-phase structure (the old
  6-phase logic replaced), even though the new mechanisms (headcount / pods /
  policy) are not yet added. Doing the Session **before** the mechanisms keeps
  the phase structure stable while the mechanisms are built on top of it.

### Step 3 — Stories 3 + 4 + 5 (headcount / pods / policy)

- **What:** Story 3 (the headcount cap chain + allotment in Phase 3/4/5),
  Story 4 (the pod types — clarification / reporting / headcount / execution),
  Story 5 (the department policy, authored after the leader+head pod).
- **Why now, and why together:** these add the **new mechanisms on top of the
  phase modules** (Steps 1–2). They are **interdependent**, so they should be
  deployed **as a unit**:
  - the **headcount-finalization pods** (Pod A / Pod B) are Story 4 pods that
    **finalize the caps** Story 3 allots;
  - the **department policy** (Story 5) is authored **after the leader+head
    clarification pod** (Story 4);
  - the **clarification / reporting pods** (Story 4) carry the clarifications
    into the **headcount allotment** (Story 3) + the **policy** (Story 5).
  
  Splitting them one at a time would leave the process **half-wired** (e.g.
  the caps allotted but not finalized by the pods, or the policy authored
  before its clarification pod exists). They can be **worked in parallel**
  (they touch different files) but must **land together**.

### Step 4 — Stories 6 + 7 + 8 (proposal / config / CLI)

- **What:** Story 6 (the leader proposes the departments in Mission; Org
  bootstrap creates them), Story 7 (the new config knobs), Story 8 (the CLI's
  run-mode / phase logging).
- **Why now:** these are **lower-coupling** additions that build on the stable
  phase structure (Steps 1–3):
  - **Story 6 (proposal)** is **independent of the dispatch split** — it
    touches the leader schema + the mission + the bootstrap (not the phase
    modules). It can be worked in parallel with Step 3.
  - **Story 7 (config)** is **independent** — it only adds config knobs (the
    knobs are consumed by Stories 3 + 4, but adding the knobs does not depend
    on them). It can be worked in parallel.
  - **Story 8 (CLI)** **depends on Story 1** (the 8-phase Session) — the CLI's
    phase logging reflects the 8 phases + the `resume_from_phase` logic (a
    checkpoint at Phase 3+ resumes from Phase 4). It must come **after Step 2**.

### Step 5 — Story 11 (prompts) + Story 12 (devil's advocate)

- **What:** Story 11 (extract the prompts into `prompts/`), Story 12 (the
  "devil's advocate" role — a leader's direct report / red-team auditor that
  runs a formal "gut check" on the org's outcomes).
- **Why now:**
  - **Story 11 (prompts)** **depends on Story 2** (the dispatch split) — the
    dispatch / phase contexts live in the new modules (Step 1). Extracting
    them is a **pure move** (no behavior change), so it is safe to do once the
    split is stable.
  - **Story 12 (devil's advocate)** **depends on Story 6** (the department
    proposal) + **Story 1** (the 8-phase Session) + **Story 4** (the pods) —
    the role is always created in Org bootstrap (Phase 3), it "listens" to the
    leader's + heads' pods, and its cross-department read access is scoped in
    `permissions.py`. It must come **after Steps 2 + 4**.

### Step 6 — Story 9 (tests) + Story 10 (docs) — last

- **What:** Story 9 (the test coverage), Story 10 (the docs).
- **Why last:** these **verify / describe the final state** — they depend on
  **all the code stories** (1–8, 11, 12). The tests exercise the 8-phase
  process + the new mechanisms end-to-end (they would be meaningless before the
  code is in place), and the docs reflect the final file structure + the new
  mechanisms. Doing them last means they describe / verify the **completed**
  process, not a work-in-progress.

### Dependency diagram

```
Story 2 (split dispatch)
   │
   ▼
Story 1 (8-Phase Session)
   │
   ├──▶ Stories 3+4+5 (headcount / pods / policy)   [land together]
   │        │
   │        └──▶ Story 11 (prompts)
   │
   ├──▶ Story 8 (CLI)
   │
   └──▶ Story 6 (department proposal)
            │
            └──▶ Story 12 (devil's advocate)

Story 7 (config)          [independent — knobs consumed by 3+4]
Story 9 (tests) + 10 (docs)  [last — depend on all code stories]
```

### Parallelism notes

- **Steps 1 → 2 → 3** are **sequential** (each depends on the previous).
- **Within Step 3**, Stories 3/4/5 can be worked in parallel (different files)
  but **land together** (they are interdependent).
- **Step 4** (Stories 6/7/8) can be worked **in parallel with Step 3** (they
  touch different files), **except** Story 8 (which needs Story 1 / Step 2).
- **Step 5** (Stories 11/12) can be worked in parallel (different files).
- **Step 6** (Stories 9/10) is last (depends on all code stories).

## Shared testing instruction (in every story markdown)

> After you finish the code changes, **try to run the test suite once in the
> repo's virtual environment** (e.g. `python -m pytest tests/ -x` from the
> project root, using the repo's venv — see `SETUP.md`).
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
