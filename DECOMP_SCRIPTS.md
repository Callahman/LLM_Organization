# DECOMP_SCRIPTS — decomposition plan for `dispatch.py` + `llm_api.py`

> **What this is:** the step-by-step plan to decompose the two largest runtime
> modules (`runtime/dispatch.py`, 32.6 KB; `runtime/llm_api.py`, 37.1 KB) into
> focused submodules. This is the **plan + explanation** (STORY S24). The
> **actual execution is a later story** — do not run these steps until that
> story is approved.

## General cadence (the rule for every step)

Each step is small and **reversible**:

1. **Move** the code (create the target submodule, move the functions/methods).
2. **Update imports** in the source module (and anywhere else that referenced
   the moved symbols).
3. **Run the test suite** (`python -m pytest tests/ -q`) — it must be green.
4. **Commit** with a message naming the move (e.g. "dispatch: extract context
   builders to `dispatch_context.py`").

Only proceed to the next step once the current step is green. If a step breaks
tests, revert it (each move is isolated, so a revert is clean).

**Import-cycle rule:** a new submodule must **not** import the module it was
extracted from (e.g. `dispatch_context.py` must not `import dispatch`; `llm_parse.py`
must not `import llm_api`). If a moved function needs something from the parent,
pass it in as a parameter instead of importing the parent.

---

## Part A — `runtime/dispatch.py`

### Target structure

```
runtime/dispatch.py            main entry: dispatch() + role lifecycle + helpers
runtime/dispatch_context.py    context builders
runtime/dispatch_edits.py      IC self-edit logic
runtime/dispatch_pods.py       pod triggers
```

### Where each symbol goes (current top-level defs in `dispatch.py`)

| Symbol | Line | Moves to |
|---|---|---|
| `mission_digest` | 65 | `dispatch_context.py` |
| `_leader_ctx` | 78 | `dispatch_context.py` |
| `_head_ctx` | 91 | `dispatch_context.py` |
| `_manager_ctx` | 105 | `dispatch_context.py` |
| `_ic_ctx` | 115 | `dispatch_context.py` |
| `_self_edit_log` | 167 | `dispatch_edits.py` |
| `_repair_edit_paths` | 179 | `dispatch_edits.py` |
| `_run_self_edits` | 225 | `dispatch_edits.py` |
| `_retry_refused_edits` | 244 | `dispatch_edits.py` |
| `_apply_ic_self_edits` | 281 | `dispatch_edits.py` |
| `_task_types` | 379 | `dispatch_pods.py` |
| `_pod_topic` | 387 | `dispatch_pods.py` |
| `_check_pod_triggers` | 394 | `dispatch_pods.py` |
| `_work_path` | 147 | stays in `dispatch.py` |
| `_upward_report` | 153 | stays in `dispatch.py` |
| `_decomposition_list` | 517 | stays in `dispatch.py` |
| `_ensure_role` | 300 | stays in `dispatch.py` (role lifecycle) |
| `_fire_role` | 349 | stays in `dispatch.py` (role lifecycle) |
| `dispatch` | 539 | stays in `dispatch.py` (main entry) |

### Steps

- **A1 — extract context builders.** Create `runtime/dispatch_context.py`.
  Move `mission_digest`, `_leader_ctx`, `_head_ctx`, `_manager_ctx`, `_ic_ctx`
  into it. In `dispatch.py`, add
  `from runtime.dispatch_context import (mission_digest, _leader_ctx, _head_ctx,
  _manager_ctx, _ic_ctx)`. Run tests, confirm green, commit.
- **A2 — extract self-edit logic.** Create `runtime/dispatch_edits.py`. Move
  `_self_edit_log`, `_repair_edit_paths`, `_run_self_edits`,
  `_retry_refused_edits`, `_apply_ic_self_edits` into it. Update the `dispatch.py`
  imports. Run tests, confirm green, commit.
- **A3 — extract pod triggers.** Create `runtime/dispatch_pods.py`. Move
  `_task_types`, `_pod_topic`, `_check_pod_triggers` into it. Update the
  `dispatch.py` imports. Run tests, confirm green, commit.
- **A4 — slim `dispatch.py`.** `dispatch.py` now holds `dispatch` (main), the
  role lifecycle (`_ensure_role`, `_fire_role`), and the small helpers
  (`_work_path`, `_upward_report`, `_decomposition_list`). Verify there are no
  import cycles and that `dispatch()` is still the single entry point. Run
  tests, confirm green, commit.

---

## Part B — `runtime/llm_api.py`

### Target structure

```
runtime/llm_api.py             OpenAIBackend (the class) + make_backend (factory)
runtime/llm_parse.py           output parsing / validation / truncation / recovery
```

### Where each symbol goes

**Module-level in `llm_api.py`:**

| Symbol | Line | Moves to |
|---|---|---|
| `_tool_call_problem` | 48 | `llm_parse.py` |
| `validate_and_quarantine` | 67 | `llm_parse.py` |
| `OpenAIOutputError` | 105 | `llm_parse.py` |
| `make_backend` | 714 | stays in `llm_api.py` (factory) |

**`OpenAIBackend` methods (the parsing block — all `@staticmethod`/`@classmethod`,
so they become free functions cleanly):**

| Method | Line | Moves to |
|---|---|---|
| `_plausible_json_prefix` | 262 | `llm_parse.py` (free fn) |
| `_unbalanced_json` | 272 | `llm_parse.py` (free fn) |
| `_is_truncation` | 299 | `llm_parse.py` (free fn) |
| `_truncation_note` | 325 | `llm_parse.py` (free fn) |
| `_parse` | 340 | `llm_parse.py` (free fn) |
| `_recover_tool_call` | 402 | `llm_parse.py` (free fn) |

**`OpenAIBackend` methods that stay in the class** (they use `self` — payload,
reporting, streaming, and the main `invoke`):

`__init__` (137), `_tool_for` (187), `_thinking_directive` (203), `_payload`
(226), `_report` (464), `_error_type` (487), `_emit_stream` (507),
`_nested_type_warnings` (519), `invoke` (531).

### Steps

- **B1 — extract the parsing module.** Create `runtime/llm_parse.py`. Move the
  module-level `_tool_call_problem`, `validate_and_quarantine`,
  `OpenAIOutputError` into it. Move the six static/class parsing methods
  (`_plausible_json_prefix`, `_unbalanced_json`, `_is_truncation`,
  `_truncation_note`, `_parse`, `_recover_tool_call`) into it as **free
  functions** (drop the `@staticmethod`/`@classmethod` decorators). In
  `llm_api.py`, add `from runtime import llm_parse` and update the call sites
  inside `OpenAIBackend` (e.g. `OpenAIBackend._parse(...)` to
  `llm_parse._parse(...)`). Run tests, confirm green, commit.
- **B2 — verify no cycle.** Confirm `llm_parse.py` does **not** import
  `llm_api` (it must be self-contained — it only needs `json`/stdlib + the
  `LLMBackend`-independent types). Run tests, confirm green, commit.
- **B3 — (optional, only if `llm_api.py` is still too large.)** Extract the
  payload-building methods (`_tool_for`, `_thinking_directive`, `_payload`) into
  `runtime/llm_payload.py`. These use `self`, so refactor them to free functions
  that take the backend (or the needed fields) as a parameter, or keep them as a
  small mixin. Update `OpenAIBackend` to call them. Run tests, confirm green, commit.

---

## Final verification (after all steps)

- [ ] `python -m pytest tests/ -q` is green.
- [ ] No import cycles: `dispatch_context`/`dispatch_edits`/`dispatch_pods`
      do not import `dispatch`; `llm_parse` does not import `llm_api`.
- [ ] Entry points still work: `dispatch()` (from `dispatch.py`) and
      `make_backend()` (from `llm_api.py`) are unchanged as the public API.
- [ ] Module sizes reduced: `dispatch.py` and `llm_api.py` are each
      meaningfully smaller than 32.6 KB / 37.1 KB.
- [ ] `python run_session.py --dry-run` (offline) still runs end-to-end.

---

*End of DECOMP_SCRIPTS.md*
