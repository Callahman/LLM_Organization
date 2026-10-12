# CODE UPDATE REQUEST

Four changes to the live "model stream" window, the Phase 4 dispatch workflow,
and the Phase 3–6 efficiency loop.
Each section states **why** the change is needed, **where** it occurs, and the
**details** of the edit.

---

## Change 1 — Stream window: unlimit the *previous* segment, keep the *current* segment limited

### Why
The live "model stream" window shows the two most recent model calls (a 2-slot
ring: the *current* call still being streamed, and the *previous* call that has
finished). Today **both** are truncated to the last 4,000 characters, so a
finished call's output is cut off — the user can never see the whole thing.
The fix: the **previous** segment (a completed call) is shown in full; the
**current** segment (still growing every tick) stays capped, which keeps the
per-second SSE payload small while a call is actively streaming.

### Where
`observability/dashboard.py` → `Watcher.snapshot()` → the `stream` list
comprehension (currently lines 288–297).

### Details
- The ring is `self.stream_segments = [current, previous]` (index 0 = current).
  `snapshot()` emits it `reversed` → `[previous, current]`.
- Replace the uniform truncation:
  ```python
  "kinds": {k: v[-4000:] for k, v in s["kinds"].items()},
  ```
  with a per-segment rule: the **current** segment (`s is self.stream_segments[0]`)
  keeps `[-4000:]`; every other segment (the **previous** one) is emitted in full.
- The server-side accumulation (`ingest_stream`, line 168) and the client render
  (`app.js`) already handle full text — no change needed there.

---

## Change 2 — Heads generate a policy **and** a `policy_summary` before any managers exist

### Why
Today a department head's policy markdown is only a **stub** (a header, no
content — `org.py::_create_department_dirs`), and the head goes straight into
its Phase 4 decomposition (creating managers). So managers/ICs have no clear
instruction on how their work fulfils the org's goal. The fix: before a head
decomposes into managers, it is invoked to produce (a) the full department
**policy** markdown and (b) a **`policy_summary`** that distils the key policy
points. **Managers** get the full policy in their context; **ICs** get the
`policy_summary`. Policies are generated for **all** heads, including the
required governance departments (HR, Safety, Morality).

The head's context follows the standing formula: **Mission.md + the head's
existing policy (Department Instructions) + the boss's directive (the leader's
department objective, or the head's mandate for a required dept) + the role's
memory** (already auto-folded by `MemoryBackend`).

### Where
All in `runtime/dispatch.py`.

### Details
1. **New context builder** `_policy_ctx(head, mission_digest, existing_policy, directive)`
   (next to `_head_ctx`/`_manager_ctx`/`_ic_ctx`, ~line 196–250). Instructs the
   head to emit `policy` (full markdown) + `policy_summary` (key points for ICs),
   feeding it the mission digest, its existing policy, and its directive.
2. **New helpers** to read/write the policy file
   (`departments/<dept>/<DEPT>_POLICY.md`, the path from `org/tiers.py::policy_path`):
   - `_read_policy(dept, departments_dir)` → existing content ("" if missing).
   - `_write_policy(dept, policy_text, departments_dir)` → writes/overwrites the file.
3. **New function** `generate_head_policies(backend, org, dept_objectives,
   mission_digest, departments_dir)` — iterates over **every** head in
   `org.department_heads()` (operational **and** required), builds the directive
   (the head's department objective if the leader assigned one, else the head's
   `mandate`), invokes the head, writes the full policy to disk, and returns
   `{head_id: {"policy": <full text>, "policy_summary": <summary>}}`.
4. **Call it in `dispatch()`** after the leader's decomposition
   (`dept_objectives = ...`, line 806) and **before** the head-decomposition loop
   (line 818), so no manager is created before its department's policy exists.
5. **Thread the policy down:**
   - `_manager_ctx(manager, objective, policy="")` — add the **full policy** to the
     manager's context.
   - `_ic_ctx(ic, task, policy_summary="")` — add the **`policy_summary`** to the
     IC's context.
   - At the call sites (manager invoke ~line 864, IC invoke ~line 892), pass
     `policies[head.id]["policy"]` / `policies[head.id]["policy_summary"]`.
- The head's policy output (`{policy, policy_summary, summary, confidence}`) is a
  valid envelope (it carries the required `summary` + `confidence`), so it passes
  the backend's envelope validation. The head is invoked **twice** in Phase 4:
  once for the policy, once for the decomposition.
- A head reading/writing its **own** policy is consistent with the tier rules
  (`org/tiers.py`: a head reads its own policy markdown; it cannot read code) —
  no permission change is required.

---

## Change 3 — Role label = id + sub_architype + personality + department + reasoning level (drop the model name)

### Why
The stream window currently labels each segment `role · model` (e.g.
`ic1 · Qwen3.8`). Because every role shares the same backbone, the model name
carries no useful information, while the **reasoning level** (whether the model
is "thinking") does. The label should instead identify the role fully — its
**id**, its **sub_architype + personality**, its **department** — plus the
**reasoning level** (HIGH / MEDIUM / LOW).

### Where
The label is built once at stream-emit time, so it flows into **both** the live
feed and the `stream.jsonl` recording.

| File | Location | Change |
|------|----------|--------|
| `runtime/llm_api.py` | `OpenAIBackend._emit_stream` (line 584) + its three call sites in `invoke()` (lines 707, 711, 728) | Accept the `role` object + `reasoning` level; build the label; pass `label` + `reasoning` to `on_stream`. |
| `runtime/history.py` | `HistoryStore.log_stream` (line 134) | Record the new `label` + `reasoning` fields. |
| `observability/dashboard.py` | `Watcher.ingest_stream` (line 140) + `snapshot` (line 288) | Carry `label` + `reasoning` into the segment and the snapshot. |
| `observability/web/app.js` | `renderModelStream` (line 473) | Render `label · reasoning` instead of `role · model`. |

### Details
- **Label composition** (skip empty parts, join with ` · `):
  `id` (always) → `sub_architype` (if set) → `(personality)` (if set) →
  `department` (if set). E.g. `head_analytics · head_of_analytics · (Pragmatist) · analytics`.
- **Reasoning level** = the routed level actually used (the `reasoning` param on
  `OpenAIBackend.invoke()`, after the `RoutingBackend` budget), upper-cased
  (`HIGH` / `MEDIUM` / `LOW`).
- The `model` field is **still recorded** in `stream.jsonl` (harmless) but is no
  longer **rendered** in the window.

---

## Change 4 — Complete Wave 4's rollout (S22 — efficiency trade-off in the Phase 3–6 loop), per `STORIES.md`

### Why
`STORIES.md` (the approved audit follow-up story set) is at **Waves 1–3 code
complete; Wave 4 (S22) pending**. This request requires that **Wave 4's
rollout gets completed**: S22 — the efficiency trade-off in the Phase 3–6
loop (Implement, High priority, fully specified) — is implemented end to end,
with every acceptance criterion in `STORIES.md` met.

### Where
`STORIES.md` → "Wave 4 — Efficiency trade-off (fully specified)" →
"S22 — Efficiency trade-off in the Phase 3–6 loop" — the authoritative spec
(context, the two levers, firing rules, efficiency score & threshold,
`M_satisfaction`, acceptance criteria, affected files).

### Details
Implement S22 exactly as specified in `STORIES.md`:
- **Instrument the Phase 3–6 loop** with wall-clock timing (`T_total`,
  `T_p3…T_p6`, `T_dept`, `T_role`, `H_peak`, `C`, `N_created`) and surface the
  full breakdown (auditable + a new dashboard **Efficiency** panel).
- **Compute `M_satisfaction`** (0–1) for both terminal and recurring goals, per
  the S22 definition (terminal: fraction of terminal success criteria met;
  recurring: attainment of the cycle target, e.g.
  `min(1, actual_return / target_return)`).
- **Compute `E` per iteration**:
  `E = M_satisfaction / (0.5 · (T_total / T_ref) + 0.5 · (C / C_ref))`, with
  `T_ref` / `C_ref` = running averages over the last 3 iterations (fixed
  0.5/0.5 weights).
- **Mandate in the Leader's Phase 5/6 prompt**: the full per-phase /
  per-department / per-role breakdown + `H_peak` + `C` + `N_created` + `E`,
  and a mandate to keep `E` high (minimize headcount/compute subject to
  mission satisfaction).
- **`EFFICIENCY_FLOOR` (default ~0.4)**: when `E < EFFICIENCY_FLOOR`, the
  Leader takes a visible efficiency action (reduce headcount / automate a
  recurring task / stop if the mission is satisfied).
- **Dynamic headcount control**: the Leader/heads can offload/fire/replace
  roles per the firing rules — fire **direct reports only**, firing
  **cascades** to the whole subtree, the **cascade size is included in the
  HR-approval request**, and leader replacement is the special case — building
  on the existing `fire()` / `required_approver()` / `replace_leader()` in
  `runtime/org.py`.
- **Automation flow**: a recurring task → an IC writes a Python script → the
  IC is fired if not needed for other work → the recurring task is then done by
  **executing the script** (subprocess / tool call) instead of an IC each time.
- **No regression**: mission quality, the existing invariants, the
  user-approval gate, and auditability are preserved.
- **Tests added**: efficiency measurement, `E` computation, the
  `EFFICIENCY_FLOOR` trigger, the firing cascade + HR request, and the
  automation flow.

Affected files (per S22): `runtime/session.py` (instrument the loop, Phase 5/6
prompt + mandate), `runtime/org.py` (dynamic headcount, firing cascade + HR
request), `runtime/dispatch.py` (per-phase/dept/role timing, automation flow),
`runtime/context.py` (efficiency metrics into the prompt),
`observability/dashboard.py` (Efficiency panel), `tests/`.

---

## Verification
- `pytest tests/` — the full suite must stay green (209+ tests).
- Existing stream/dashboard tests (`tests/test_dashboard.py`,
  `tests/test_observability_hooks.py`) cover `ingest_stream`/`snapshot`; they
  should still pass with the new fields (they read `role`/`model`, which remain).
- Manual: run a session and watch the model-stream window — the previous call
  shows in full, the current call is capped, and each segment is labelled
  `id · sub_architype · (personality) · department · LEVEL` (no model name).
- Wave 4 complete (Change 4): every S22 acceptance criterion in `STORIES.md`
  is met — the Phase 3–6 loop is instrumented, `M_satisfaction` + `E` are
  computed and surfaced (Leader's Phase 5/6 prompt + dashboard Efficiency
  panel), the `EFFICIENCY_FLOOR` trigger fires a visible efficiency action,
  the firing cascade + HR request works, the automation flow works, and the
  new S22 tests pass.

---

## Final instruction — Testing responsibility

- **The user performs all testing.** In every change in this document, the
  user — not the implementing agent — runs the tests.
- **The rollout of the changes must NOT include testing.** Implementing a
  change does not mean running `pytest` (or any other test command) as part of
  the rollout; the agent does not execute tests while rolling out the changes.
- **The rollout ends with a final prompt for the user to test.** After all the
  changes are implemented, the agent stops and hands the user a clear, explicit
  prompt to run the tests — what to run and what to confirm — and then awaits
  the user's results.
