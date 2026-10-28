# Addressing Issues

This document addresses three issues in the LLM Organization runtime, with a
detailed implementation plan for each.

## Root-cause summary

| # | Issue | Root cause |
|---|-------|-----------|
| 1 | Pods don't end on consensus | `run_pod` (runtime/pods.py) only stops on a capped round count, a wall-clock budget, or a deadlock (identical output). There is no consensus/`continue` signal from members, so a pod always burns its full round budget even when everyone agrees. |
| 2 | Managers created with no IC budget; leader proposes headcount | Phase 4 (runtime/plan.py) hires a manager whenever a head names a `manager_id`, with no check that it has an IC budget. The team cap (IC budget) is a "cap" that can be 0. Phase 3 (runtime/org.py `allot_department_caps`) has the leader propose the initial headcount, then Pod A finalizes it — the desired process is for the heads to *petition* the leader for headcount instead. |
| 3 | Headcount not updating in real-time | The headcount chart + chips render from `org_events.jsonl` (via `state.agents.events` / `agents_by_dept`), which is only flushed at checkpoints (after Phase 6) — so it's stale during Phase 4/5 when managers/ICs are hired. The dedicated real-time log `headcount.jsonl` (appended on every hire via `history.log_headcount`) *is* ingested in real-time into `state.headcount`, but the frontend never renders it. Also, the bootstrap uses `org.add_role()` directly (not `hire()`), so `headcount.jsonl` is missing the initial 10 roles. |

---

## Issue 1 — Pod early termination on consensus

### Root cause
`run_pod` (runtime/pods.py) runs a fixed agenda → deliberation → close flow. It
only stops early on:
- a capped round count (`max_rounds` / `max_deliberation_rounds`),
- a wall-clock budget (`pod_wall_clock_budget_seconds`), or
- a deadlock (a member returns identical output twice in a row).

There is no consensus signal, so a pod always burns its full round budget even
when every member (and the starter) agrees.

### Plan
**Files:** `roles/worker.py`, `prompts/__init__.py`, `runtime/pods.py`,
`runtime/session.py`.

1. **Add a `continue` field to the worker output schemas** (`roles/worker.py`).
   Add `"continue": {"type": "boolean"}` to the worker envelope (or to each of
   `HEAD_OUTPUT_SCHEMA` / `MANAGER_OUTPUT_SCHEMA` / `IC_OUTPUT_SCHEMA`) so pod
   members can emit it explicitly. Semantics:
   - `continue: true` = "I have more input / we should keep deliberating."
   - `continue: false` = "I agree / no more input needed."

   (Harmless in non-pod work — the model simply won't emit it.)

2. **Update the pod prompt** (`prompts/__init__.py` + the `_pod_ctx` builder in
   runtime/pods.py). In the speak phase, instruct members to also set `continue`
   per the semantics above.

3. **Consensus check in `run_pod`** (runtime/pods.py). After each deliberation
   round, collect `continue` from **every member AND the starter**. If **all of
   them** returned `continue: false`, break early → go straight to the close
   phase. Add a transcript entry noting the early stop (e.g.
   `kind: "consensus"`, "all members + starter agreed after N rounds").

4. **Config knob** (`runtime/session.py`): `pod_consensus_early_stop` (default
   `true`) so the behavior can be disabled.

### Behavior
A pod now ends as soon as **all members + the starter** agree, instead of always
burning its full round budget. The existing round cap / wall-clock / deadlock
stops remain as backstops.

---

## Issue 2 — Manager creation + headcount rework

### Root cause
- **Managers with no IC budget are created:** Phase 4 (runtime/plan.py) hires a
  manager whenever a head names a `manager_id` in its `team_objectives`, with no
  check that the manager has an IC budget. The team cap (the IC budget) is a
  "cap" that can be 0, so a manager with no ICs to manage is still created.
- **The leader proposes the initial headcount:** Phase 3 (runtime/org.py
  `allot_department_caps`) has the leader propose the department caps, then Pod A
  (all heads + leader) finalizes them. The desired process is for the heads to
  *petition* the leader for headcount (in a pod), with the leader synthesizing an
  overall org structure.
- **Headcount budgeting is implicit:** the team cap is a "cap" (a max), not an
  explicit per-manager IC count.

### 2a. Remove the leader's upfront headcount proposal (Phase 3)
- Stop calling `allot_department_caps()` as the leader-proposing step
  (runtime/session.py ~line 830). Keep `bootstrap()` (heads are still created).
- `org.department_caps` is now populated by the 2b headcount petition (not by
  the leader's upfront proposal).

### 2b. Headcount petition pod (Phase 4)
A new pod where **all heads petition the leader together** (not 1-by-1). New
function `run_headcount_petition(org, backend, leader, heads, total_cap,
max_petitions=3, config)` (in runtime/plan.py or pods.py):

- **Form a pod** (all heads + leader; leader = starter). The pod **may exceed
  the normal working-group size bound** (`cross_team=True`, with `max_roles` set
  high enough to fit all heads + leader). Log the devil's advocate listening.
  Write transcripts (like `run_pod`).
- **Loop (up to `max_petitions`, default 3):**
  1. **Each head petitions** with its desired structure. Output schema (a
     mapping with dynamic `manager_id` keys):
     ```
     petition: { "<manager_id>": { "ic_headcount": int, "purpose": str, "justification": str } }
     ```
     (Context: the head's department objective, the total cap, and the leader's
     previous structure if any.)
  2. **The leader synthesizes** the overall org structure, broken down by
     department. Output schema (a nested mapping with dynamic `department` →
     `manager_id` keys):
     ```
     org_structure: { "<department>": { "<manager_id>": { "ic_headcount": int, "purpose": str, "justification": str } } }
     ```
     (Context: all heads' petitions, the total cap. **The leader adjusts the
     structure to fit the total cap as it sees fit** — trimming/reshaping the
     requests so the combined `ic_headcount` + managers fits the cap.)
  3. **Each head votes** on whether it agrees with the leader's structure:
     `{ "agree": bool, "feedback": str }`.
  4. **If all heads `agree: true`** → stop (the leader's structure is the org
     structure).
- **After `max_petitions` rounds** (if not all agree) → **the leader's structure
  becomes de facto** (used by the org). A visible org event records that the
  leader's decision was adopted without full consensus.
- **Return** the final
  `{department: {manager_id: {ic_headcount, purpose, justification}}}`.

This petition **replaces** both the old Pod A (leader proposes dept caps) and
the old `_allot_team_caps` (head allots team caps) — the petition directly
produces the managers + their IC counts.

### 2c. Heads cannot do work
- Heads cannot do work directly, so the **head-directed branch is removed** (no
  more a head naming an `ic_id` to direct an IC with no manager). Every team
  that executes work must have a manager (from the petition).
- **If a head does not have a team that can execute a task** (because the
  headcount petition did not grant one, or the IC budget is too small), **the
  task is unfulfilled**. When the head reports up, it **explains in its report
  that the task cannot be fulfilled due to headcount restrictions**.
- **Files:**
  - `runtime/staff.py`: remove the head-directed branch (~line 258).
  - `runtime/plan.py`: the head's output no longer carries a head-directed
    `ic_id`.
  - `prompts/__init__.py`: heads can't do work; if they can't staff a team, the
    task is unfulfilled and they must explain it in their report (due to
    headcount restrictions).
  - `roles/worker.py`: drop the head-directed `ic_id` from the head schema.
  - The head's upward report (Phase 6/7) gains a section for **unfulfilled
    tasks** (with the reason: headcount restrictions).

### 2d. Don't create managers with no IC budget
- When hiring managers from the leader's de facto structure, only create a
  manager whose `ic_headcount` is a positive integer. Skip + log a visible org
  event when `ic_headcount` is 0/missing (the manager is not created).

### 2e. Bound ICs by the explicit IC count
- `runtime/staff.py` `_team_cap_ok` enforces the manager's explicit
  `ic_headcount` (stored on the org, e.g. `org.manager_ic_counts[(department,
  team)]`). A hire that would exceed it is blocked (visible note).

### Schemas + prompts (2b–2c)
- `roles/worker.py`: add the head's `petition` (mapping → `{ic_headcount,
  purpose, justification}`) + `agree`/`feedback` (vote); drop the head-directed
  `ic_id`.
- `roles/leader.py`: add `org_structure` (nested mapping → `{ic_headcount,
  purpose, justification}`) for the synthesis.
- `prompts/__init__.py`: the head's petition prompt, the leader's synthesis
  prompt, the head's vote prompt, and the "heads can't do work / unfulfilled
  due to headcount restrictions" fallback.

### Behavior
The leader no longer proposes headcount up front. After heads author policies,
all heads petition the leader in one pod; the leader synthesizes an overall org
structure (by department), adjusting it to fit the total cap as it sees fit;
heads vote; it repeats until all agree or N rounds, after which the leader's
structure is de facto. Each manager gets a specific `ic_headcount`, managers
with no IC budget are never created, and heads (which can't do work) either have
a team that executes the task or report the task as unfulfilled due to headcount
restrictions.

---

## Issue 3 — Dashboard real-time headcount

### Root cause
- The headcount chart + chips render from `org_events.jsonl` (via
  `state.agents.events` / `agents_by_dept`), which is only flushed at
  checkpoints (after Phase 6) — so it's stale during Phase 4/5 when
  managers/ICs are hired. The chart shows the bootstrap events all at the same
  timestamp ("data at 0s, no other X-axis elements").
- The dedicated real-time log `headcount.jsonl` (appended on every hire via
  `history.log_headcount`) *is* ingested in real-time into `state.headcount`
  (the dashboard tails the file by offset, so it picks up each new hire), but
  the frontend never renders `state.headcount`.
- The bootstrap uses `org.add_role()` directly (not `hire()`), so it never
  calls `history.log_headcount` — that's why `headcount.jsonl` starts at 11
  (missing the initial 10 roles).

### Plan
**Files:** `observability/web/app.js`, `observability/dashboard.py`,
`runtime/org.py`.

1. **Frontend — headcount chart from `headcount.jsonl`**
   (`observability/web/app.js`). Change `renderAgentsChart` to build its series
   from `state.headcount` (the real-time log) instead of `state.agents.events`
   (the stale `org_events.jsonl`). Add a `buildHeadcountSeries(entries)` that
   accumulates per-department net headcount from each entry's `{ts, event,
   department}` (`event === "fire" ? -1 : 1`, clamped at 0) — same shape as the
   existing `buildNetHeadcountSeries`, just consuming the right source. This
   directly fixes the "data at 0s, no other X-axis elements" symptom (the 30
   Phase 4/5 hires are now spread over time).

2. **Frontend — chips from the real source** (`observability/web/app.js`).
   Change `renderHeadcountChips` to compute `total` + `by_department` from
   `headcount.jsonl` (the latest accumulation) — `headcount.jsonl` is the
   desired source.

3. **Backend — make `headcount.jsonl` complete** (`runtime/org.py`). Pass a
   `history` to `bootstrap()` and call
   `history.log_headcount(len(org.active_roles()), "hire", head.id,
   head.department)` for each created head (operational + required +
   devil's advocate), so `headcount.jsonl` has the full history from 0.

4. **Backend (optional, for other org-event views)** (`runtime/org.py`): flush
   `org.write_events()` on every hire/fire so `org_events.jsonl` is also
   real-time (helps any other view that reads org events). Lower priority than
   (1)–(3).

### Behavior
The headcount chart + chips update in real-time as managers/ICs are hired,
driven by `headcount.jsonl` (appended on every hire, now including the
bootstrap), instead of only at checkpoints.

---

## Resolved decisions
- **Issue 1:** consensus requires **all members + the starter** to return
  `continue: false`.
- **Issue 2b:** the heads petition the leader **in the same pod** (not 1-by-1);
  the **leader adjusts the structure to fit the total cap as it sees fit**; the
  pod **may exceed the normal working-group size bound**; after N petitions
  (default 3) the leader's structure is **de facto**.
- **Issue 2c:** heads can't do work; if a head has no team that can execute a
  task, the task is **unfulfilled** and the head **explains in its report that
  it cannot be fulfilled due to headcount restrictions**.
- **Issue 3:** `headcount.jsonl` is the source for the headcount chart + chips.

## Dependencies / ordering
- **Issue 3** first (small, self-contained; and it's the source Issue 2's hires
  will flow into).
- **Issue 1** second (independent, small).
- **Issue 2** last (largest; the petition pod + "heads can't do work"
  restructure).