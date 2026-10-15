# Story 11 — Prompts directory (`prompts/`)

## Goal

Extract the **pipeline's prompts** (and parts of prompts) into a dedicated
`prompts/` location, each with a **comment above it indicating how/where it is
used** (the phase / the role / the pod). The prompts are **auditable** — the
text is **unchanged** (a pure move), so behavior is preserved.

## Files

- `prompts/` — **create** (the dedicated prompts location).
- `runtime/llm_api.py` — **modify** (the `_context` builder imports the prompt
  from `prompts/`).
- `runtime/intake.py` — **modify** (`_assemble_context` imports the prompt).
- `runtime/mission.py` — **modify** (`_mission_context` imports the prompt).
- `runtime/org.py` — **modify** (`_bootstrap_context` imports the prompt).
- `runtime/pods.py` — **modify** (the pod context imports the prompt).
- `runtime/dispatch_common.py` / `plan.py` / `staff.py` / `execute.py` —
  **modify** (the dispatch / phase contexts import the prompts).
- `runtime/evaluate.py` — **modify** (the evaluation context imports the
  prompt).

## Detailed changes

### 11.1 Create the `prompts/` location

Create a dedicated `prompts/` location (a package, e.g. `prompts/__init__.py`,
or a single `prompts.py` module). The prompts live here, each with a **usage
comment** above it.

### 11.2 Extract the prompts (a pure move)

Extract the **prompt text** (the strings the pipeline sends to the LLM) from
the phase modules into `prompts/`. The prompts to extract:

- **The 4-part prompt** (`runtime/llm_api.py::_context`) — the role mandate +
  the input spec + the context (the 4-part prompt the backend assembles).
- **The intake context** (`runtime/intake.py::_assemble_context`) — the
  Phase-1 clarifying-questions context.
- **The mission context** (`runtime/mission.py::_mission_context`) — the
  Phase-2 mission-codification context.
- **The bootstrap context** (`runtime/org.py::_bootstrap_context`) — the
  Phase-3 org-bootstrap context.
- **The pod context** (`runtime/pods.py`) — the pod-agenda / pod-context
  builder (the per-kind context from Story 4).
- **The dispatch / phase contexts** (`runtime/dispatch_common.py` /
  `plan.py` / `staff.py` / `execute.py`) — the per-phase contexts (the
  leader-decomposition context, the head-workflow context, the
  manager-workflow context, the IC-execution context).
- **The evaluation context** (`runtime/evaluate.py`) — the Phase-7 / Phase-8
  evaluation / decision context.

Each extracted prompt has a **comment above it** indicating **how/where it is
used** (the phase / the role / the pod). E.g.:

```python
# Phase 2 (Mission) — the leader's mission-codification context. Used by
# runtime/mission.py::_mission_context (the leader is asked to draft
# MISSION.md + fill department_proposal).
MISSION_CONTEXT = (
    "PHASE 2: codify the global mission (MISSION.md). "
    "Set `mission_draft` to a JSON OBJECT (not a string) with keys: ..."
)
```

### 11.3 The phase modules import the prompts

The phase modules **import** the prompts from `prompts/` (instead of building
them inline). The context builders (`_assemble_context`, `_mission_context`,
etc.) **compose** the imported prompt + the dynamic data (the intake result,
the feedback, etc.). The **prompt text is unchanged** (a pure move) — only the
location changes.

> **Rule:** the prompt text is **unchanged** (a pure move). The dynamic data
> (the intake result, the feedback, the role, etc.) stays in the phase module
> (the context builder composes the prompt + the data). Only the **static
> prompt text** moves to `prompts/`.

### 11.4 The prompts are auditable

The prompts are **auditable** — they are in a dedicated `prompts/` location,
each with a usage comment. An operator can read `prompts/` to see all the
prompts the pipeline sends to the LLM + where each is used (the phase / the
role / the pod). This makes it easy to **suggest changes** to the prompts
(e.g. to improve the leader's clarifying questions).

> **Ordering:** this story **depends on Story 2** (the dispatch split) — the
> dispatch / phase contexts are in the new modules. Do this after Story 2.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the prompts test (a new
> `tests/test_prompts.py` — see Story 9) + the existing `tests/test_context.py`
> (the 4-part prompt) — the prompt text must be unchanged (a pure move), so the
> context tests must still pass.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
