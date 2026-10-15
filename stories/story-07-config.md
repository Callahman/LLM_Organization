# Story 7 — Config (new knobs)

## Goal

Add the **new config knobs** the 8-phase process needs (the headcount caps +
the pod round counts + the execution-pod routing rules), and document them in
`.env.example`. The knobs are read by `runtime/config.py` (the `ENV_TO_CONFIG`
mapping) and handed to `Session` (which passes them to the org / the phase
modules / the pods).

## Files

- `runtime/config.py` — **modify** (add the new knobs to `ENV_TO_CONFIG`).
- `.env.example` — **modify** (document the new knobs).

## Detailed changes

### 7.1 `runtime/config.py` — the new knobs

Add to `ENV_TO_CONFIG` (the `.env` key → (Session config key, cast) mapping):

**Headcount knobs** (Story 3):
```python
"HEAD_COUNT_TOTAL": ("head_count_total", int),
"DEPARTMENT_CAP_DEFAULT": ("department_cap_default", float),  # % of total
"TEAM_CAP_DEFAULT": ("team_cap_default", float),              # % of the department cap
```

**Pod round-count knobs** (Story 4) — the default iteration cap per pod kind:
```python
"CLARIFICATION_POD_ROUNDS": ("clarification_pod_rounds", int),
"REPORTING_POD_ROUNDS": ("reporting_pod_rounds", int),
"HEADCOUNT_POD_ROUNDS": ("headcount_pod_rounds", int),
"EXECUTION_POD_ROUNDS": ("execution_pod_rounds", int),
```

**Execution-pod routing-rule knob** (Story 4, Trigger C):
```python
"ROUTING_RULES": ("routing_rules", str),  # a JSON list, or a path to a rules file
```

> **Note:** the existing `POD_MAX_ROUNDS` knob (the global pod round cap)
> stays — the new per-kind round counts are the **defaults** per kind, and
> `POD_MAX_ROUNDS` is the **global cap** (a pod never exceeds it).

### 7.2 `.env.example` — document the new knobs

Add the new knobs to `.env.example` (with a comment for each), grouped by
purpose:

```bash
# --- Headcount caps (Story 3) ---
# The total headcount cap (the max number of roles the org may have).
HEAD_COUNT_TOTAL=50
# The default department cap (as a % of the total, 0.0-1.0).
DEPARTMENT_CAP_DEFAULT=0.25
# The default team cap (as a % of the department cap, 0.0-1.0).
TEAM_CAP_DEFAULT=0.5

# --- Pod round counts (Story 4) — the default iteration cap per pod kind ---
CLARIFICATION_POD_ROUNDS=3
REPORTING_POD_ROUNDS=2
HEADCOUNT_POD_ROUNDS=3
EXECUTION_POD_ROUNDS=3

# --- Execution-pod routing rules (Story 4, Trigger C) ---
# A JSON list of routing rules, or a path to a rules file.
ROUTING_RULES=[]
```

> **Ordering:** this story is **independent** — it only adds config knobs. It
> can be done in parallel with the other stories (the knobs are consumed by
> Stories 3 + 4).

### 7.3 The config consumers

The new knobs are consumed by:
- **`head_count_total`** — `org.bootstrap` + the phase modules (Story 3).
- **`department_cap_default`** / **`team_cap_default`** — the cap allotment
  (Story 3).
- **`clarification_pod_rounds`** / **`reporting_pod_rounds`** /
  **`headcount_pod_rounds`** / **`execution_pod_rounds`** — the pod round
  counts (Story 4).
- **`routing_rules`** — the Trigger C execution-pod routing rules (Story 4).

The `Session` config dict (from `load_config`) carries these knobs, and
`Session.run` passes them to the org / the phase modules / the pods.

## Testing

> **Instruction to the LLM implementing this story:** after you finish the code
> changes, **try to run the test suite once in the repo's virtual environment**
> (e.g. `python -m pytest tests/ -x` from the project root, using the repo's
> venv — see `SETUP.md`). Focus on the existing `tests/test_config.py`
> (`test_pod_max_rounds_plumbed`, `test_unknown_knob_warns`) — the new knobs
> must be plumbed (not dead) + an unknown knob must still warn.
>
> - **If the tests pass**, you are done.
> - **If you cannot run the tests** (no venv, missing dependencies, a test
>   harness error) **or the tests fail for reasons outside your changes**,
>   **still complete the code work** and then **explicitly raise the need for
>   testing to the user** — state clearly that you could not verify the changes
>   by running the tests, why (the specific error / missing venv), and that the
>   user should run the test suite to confirm. Do not silently skip this step.
