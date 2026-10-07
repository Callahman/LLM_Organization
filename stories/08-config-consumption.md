# Story 8 — Config consumption

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Findings:** B18 (8 dead knobs in `ENV_TO_CONFIG`, loader warning can't catch
them), C2 (8 `.env` knobs loaded but dead).

**Goal:** every `.env` knob is either **consumed** (plumbed to its consumer) or
**dropped** from the map (so the unused-key warning fires). No silently ignored
knob.

## Context (what exists today)
The 8 dead knobs are in `ENV_TO_CONFIG` (`runtime/config.py:25-43`) but never
consumed by the `Session`. Because they're in the `known` set, the "unused
`.env` key" warning (config.py:100-103) does **not** fire for them — an operator
setting e.g. `DIRECT_IC_CAP=5` gets a silently ignored value (the code uses the
`DIRECT_IC_CAP = 3` constant, org.py:38).

| `.env` key | config key | Intended consumer |
|------------|-----------|-------------------|
| `POD_MIN_ROLES` | `pod_min_roles` | `org/tiers.py` pod bounds (hardcoded 2) |
| `POD_MAX_ROLES` | `pod_max_roles` | `org/tiers.py` pod bounds (hardcoded 6) |
| `POD_MAX_ROUNDS` | `pod_max_rounds` | `run_pod(max_rounds=...)` (default 3) |
| `DIRECT_IC_CAP` | `direct_ic_cap` | `org.py` `_check_ic_cap` (`DIRECT_IC_CAP = 3`) |
| `CONTEXT_BUDGET_TOKENS` | `context_budget_tokens` | `bounded_assembly` / `_pod_ctx` |
| `ROLE_MEMORY_MAX_ENTRIES` | `role_memory_max_entries` | `MemoryBackend(max_entries_range=...)` |
| `HISTORY_WINDOW_SESSIONS` | `history_window_sessions` | `HistoryStore(window_sessions=...)` |
| `ARCHIVE_CAP_MB` | `archive_cap_mb` | `HistoryStore(archive_cap_mb=...)` |

## Tasks

- [ ] **Decide plumb-vs-drop for each knob** (default: plumb the 4 with a clear
  single consumer — `POD_MAX_ROUNDS`, `DIRECT_IC_CAP`, `HISTORY_WINDOW_SESSIONS`,
  `ARCHIVE_CAP_MB`; drop or plumb the rest). Record the decision in this file.
- [ ] **Plumb `POD_MAX_ROUNDS`:** pass `max_rounds` from the config into the
  `run_pod` calls in `runtime/dispatch.py:409,444` (e.g.
  `run_pod(backend, pod, max_rounds=self.config.get("pod_max_rounds", 3),
  transcripts_dir=...)`).
- [ ] **Plumb `DIRECT_IC_CAP`:** make `org.py` `_check_ic_cap` (org.py:181-193)
  read the cap from a param (default `DIRECT_IC_CAP = 3`) instead of the module
  constant; pass the config value where `hire`/`_check_ic_cap` is called.
- [ ] **Plumb `HISTORY_WINDOW_SESSIONS` + `ARCHIVE_CAP_MB`:** pass
  `window_sessions` and `archive_cap_mb` from the config into the `HistoryStore`
  constructor (find where `HistoryStore(...)` is instantiated in
  `runtime/session.py` and pass the config values).
- [ ] **Plumb `POD_MIN_ROLES` / `POD_MAX_ROLES`** (if plumb): make
  `org/tiers.py` `validate_pod` read the bounds from params (default 2/6)
  instead of the module constants; thread the config values through.
- [ ] **Plumb `CONTEXT_BUDGET_TOKENS` / `ROLE_MEMORY_MAX_ENTRIES`** (if plumb):
  pass `context_budget_tokens` to `bounded_assembly` (see Story 7) and
  `role_memory_max_entries` to `MemoryBackend(max_entries_range=(...))`.
- [ ] **Drop the rest:** for any knob not plumb-ed, **remove it from
  `ENV_TO_CONFIG`** (config.py:25-43) so the "unused `.env` key" warning fires
  (making the dead knob visible instead of silently ignored).
- [ ] **Tests** (`tests/test_config.py` or a new one):
  - (a) Set `POD_MAX_ROUNDS=5` in the env; assert the config dict has
    `pod_max_rounds == 5` AND a `run_pod` call uses it (via a stub that records
    `max_rounds`).
  - (b) Set a **dropped** knob in the env; assert the "unused `.env` key"
    warning is printed (capture stderr).

## Definition of done
- Every `.env` knob is consumed or dropped (no silently ignored knob).
- The plumb-ed knobs actually reach their consumers (verified by tests).