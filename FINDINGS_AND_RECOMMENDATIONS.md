# Findings & Recommendations — Organization Pipeline + Dashboard

> Generated from a code review of `D:\LLM\LLM_Organization`. Each item below lists the
> **current state** (with file references), the **recommendation** (specific code changes),
> and a **question** where the intent is ambiguous. Items are grouped into
> **A. Pipeline** (1–3), **B. Dashboard data/wiring** (4–5, 8–9), **C. Dashboard frontend**
> (6–7, 10), and **D. Bug** (11).

---

## User Answers (from user)

1. **Intake** — Keep clarification, but the leader must **NOT re-prompt the user for a goal** once one is supplied. Thread the supplied goal into Phase 2.
2. **Routing** — Make it **task-based**. Move **code development into MEDIUM** (not HIGH).
3. **`department_caps`** — Correct. Make the naming **distinct**, change both **code AND prompts**, and convey a **clear indication of which step/phase the leader is on** so the two similar processes don't confuse the leader.
4. **Agents chart** — **Option b: current active headcount per department.** The metric should answer: how large is the org, and which departments make up a majority of the headcount?
5. **Transcripts** — Implement the rec as-is.
6. **Flowchart** — Use the **pod agenda / decomposition objective** for the task text.
7. **Tooltips** — Implement the rec as-is; make sure it's included in the flow-chart from item 6.
8. **Roles by hierarchy** — Check the conversation logs: were managers engaging in conversations/thinking? If so, the org is broken. (Active managers were seen in the dashboard, so some are expected.)
9. **Agents total** — Likely cumulative, but given item 8 this may be a **data-collection issue letting the org exceed the headcount cap.** Update the chart to show **total headcount** (not net events). Confirm the cap is enforced.
10. **Code volume** — **Option a** (file-write log). Total all role code (includes policies), focus on code generated in `departments/`. **Physical lines** are fine (all lines OK).
11. **Bug** — Add a **sanitization step for reading/writing** transcripts.

---

## To-Do List

| # | Item | Status |
|---|------|--------|
| 11 | Bug: sanitize pod id for transcript read/write | ✅ done |
| 5 | Transcripts: pass `transcripts_dir` to the 4 `run_pod` sites | ✅ done |
| 3 | `department_caps`: rename Phase 2 key → `mission_departments` + distinct naming + phase indicator (code + prompts) | ✅ done |
| 1 | Intake: keep clarification, never re-ask goal; thread goal to Phase 2 | ✅ done |
| 2 | Routing: task-based classifier (task signal drives; code development = MEDIUM) | ✅ done |
| F1 | Frontend: sub-renderer per panel + memoization per data change + data-bound Event/Efficiency panels | ✅ done |
| F2 | History: `invocations.jsonl` records `role` + `department` | ✅ done |
| 4 | Agents chart: current active headcount per department | 🔄 partial — headcount chips in; chart series still cumulative |
| 7 | Tooltips: generic hover tooltip on `drawTimeSeries` (+ flowchart) | ⬜ pending |
| 10 | Code volume: file-write log, all role code incl. policies, `departments/` | ⬜ pending |
| 8 | Roles by hierarchy: investigate manager activity in logs + dashboard-side fix | 🔄 partial — investigation done (no managers in logs); dashboard-side fix pending |
| 9 | Agents total: show total headcount (not net events) + confirm cap enforced | ✅ done |
| 6 | Flowchart module: org flow panel (stepper + current phase + roles + task from pod agenda) | ⬜ pending |

> Status legend: ⬜ pending · 🔄 in progress / partial · ✅ done
>
> **Verified this pass:** item 2 is now fully rolled out (code development = MEDIUM, tested in
> `tests/test_complexity.py`); item 9 is done (total headcount net of fires + cap confirmed
> enforced); item 8's investigation is done (no managers in any run's logs — the org is stuck at
> bootstrap); item 4 is partial (current headcount per department renders as headcount chips; the
> chart series is still the cumulative hire/activity series).
>
> **Rolled out earlier:** items 1, 3 (pipeline), 11 + 5 (transcripts, prior pass), and the two
> new items **F1** (frontend sub-renderers/memoization/data-binding) and **F2** (invocations log
> `role`+`department`).

---

## A. Pipeline

### 1. Intake — remove the LOW-reasoning leader loop; keep the `INPUT("what's the org goal")` prompt

**Current state.** `runtime/intake.py::run_intake` does two things:

- If there is no `initial_prompt`, it asks the hardcoded, schema-less `INPUT` question
  `"What is the organization's goal?"` and records the free-text answer as the intake `target`.
- Then it runs a `while rounds < question_budget` loop that invokes the **Leader at LOW**
  (`classify_complexity(1, leader, {})` → `Reasoning.LOW` in `runtime/complexity.py`).
  The Leader's prompt carries `INTAKE_RULES` (`prompts/__init__.py`), which says
  *"Your FIRST question to the user must be 'What is the organization's goal?'"*.

Because the goal was already supplied (via `--prompt` / the interactive input in
`run_session.py`), the LOW Leader asking for it again is redundant. The LOW model can
re-ask the user, emit a fuzzy `restated_goal`, or push a wrong goal into Phase 2 — which then
feeds the (higher-level) clarification/mission development and causes further confusion.

**Recommendation.**

- In `run_intake`, when a goal is already present (`initial_prompt` non-empty, or the `INPUT`
  answer was captured), **skip the LOW Leader clarifying loop** (or, at minimum, never let it
  re-ask the goal). The intake result should be the goal itself (plus any non-goal assumptions),
  handed straight to Phase 2.
- Drop the "first question must be the goal" line from `INTAKE_RULES` — it only made sense
  when the goal was unknown. If any clarifying questions are kept, they run at a higher level
  and are seeded with the known goal.
- Thread the captured goal into `run_mission` as the `informal_draft` / `current_goal` so
  Phase 2 develops `MISSION.md` from the user's actual goal.

**Question.** Do you want to keep *any* Leader clarifying questions in intake (just not the
redundant goal question, and at a higher reasoning level), or go fully straight from the
`INPUT` goal to Phase 2 mission development?

**Rolled out (per your answer 1 — keep clarification, never re-ask the goal, thread it to Phase 2).**
The goal question is now **conditional**, not hard-coded:

- `INTAKE_RULES` (`prompts/__init__.py`) and `LEADER_MANDATE` (`roles/leader.py`): the goal
  question is asked **only when there is no INITIAL PROMPT and no CURRENT MISSION** (i.e. no goal
  has been supplied yet). When a goal IS supplied, the Leader clarifies scope/success-criteria
  from it without re-asking the goal.
- `runtime/intake.py`: the hard-coded goal round fires only when `mission_path` is absent **and**
  `initial_prompt` is blank; `_assemble_context` tells the Leader the goal is already stated (see
  INITIAL PROMPT) when one was supplied; and `_informal_draft` **seeds the Goal with the supplied
  goal** when the Leader never restated it — so Phase 2 (`run_mission`) is threaded with the
  actual goal (the `informal_draft` / `current_goal` path from the recommendation).

---

### 2. Complexity / thinking routing — make it task-based (or role-based, but the level chosen by the hiring manager)

**Current state.** `runtime/complexity.py::classify_complexity` routes by **role + phase**:

- Phase 1 → LOW (HIGH only on disagreement / last budget round).
- Phase 2 → LOW (MEDIUM only on `is_decision`).
- Phases 3/4/5/6 → by `role.architype`: leader/head/manager → MEDIUM, IC → LOW.

This is role-based, not task-based, so a code-writing IC runs at LOW while a conversational
head runs at MEDIUM — the inverse of the desired behavior.

**Recommendation (task-based).** Rework `classify_complexity` to classify by the **task type**
of the invoke (threaded in via the `signal` dict or a new `task_kind` argument), using these tiers:

- **HIGH** — code development, `MISSION.md` authoring, `POLICY.md` authoring.
- **MEDIUM** — headcount allotment, planning/decomposition, task assignment, code discussion/review.
- **LOW** — conversational, Q&A, reporting, status.

This means each call site (`run_mission`, `allot_department_caps`, `_allot_team_caps`, the
Phase 4/5 decomposition invokes, `_invoke_ic`, the policy authoring, the upward reports, etc.)
tags its invoke with the task kind. The `RoutingBackend` / `MemoryBackend` already forward
`reasoning` + `phase`, so the plumbing exists.

**Alternative (role-based, manager-chosen).** Keep role-based routing but let the **hiring
manager pick the level per role at hire time** (store a `reasoning_level` on the `Role`, set by
the leader/head when it hires). Simpler, but coarser.

**Question.** Which do you want — the task-based classifier (finer, more call-site changes) or
the role-based-with-manager-chosen-level (coarser, fewer changes)? And should code
*discussion/review* be MEDIUM (per your list) even when done by an IC?

**Rolled out (per your answer 2: task-based; code development = MEDIUM).** The classifier is now
**task-first**: `classify_complexity` reads the **task signal** (what the task IS) before the
phase number — a decision task (`is_decision`) or a devil's-advocate `gut_check` is always HIGH
regardless of phase, and the phase number is a fallback for tasks that carry no signal. The
dispatch sites and the Phase 8 decide / efficiency-floor sites pass the same `(task, phase,
role)` shape (the decide / efficiency sites pass `{"is_decision": True}`).

The **tier rework is done** (your answer 2: "Move code development into MEDIUM (not HIGH)"):

- **Code development = MEDIUM (not HIGH)**: Phases 4/5/6 (plan / staff / execute) route to
  MEDIUM — the leader/head/manager structuring **and** the IC executing/planning its task (a
  code-writing IC in Phase 6 runs at MEDIUM, raised from LOW). Disagreement / deadlock in a pod
  round is the only path to HIGH there.
- **`MISSION.md` authoring = HIGH**: Phase 2 (mission) routes to HIGH (Phases 7/8 evaluate /
  decide likewise — heavy leader tasks).
- **Conversational / Q&A = LOW**: Phase 1 (intake) routes to LOW (HIGH only on the last budget
  round when not converging).

Tested in `tests/test_complexity.py` (`test_ic_executing_planning_routes_medium`: "raised from
LOW"; `test_structuring_routes_medium`; `test_complex_phases_route_high`;
`test_decisions_route_high`).

---

### 3. `department_caps` — reconcile the prompt with the expected schema

**Current state.** The same key `department_caps` is asked for in **two different shapes**:

- **Phase 2 (Mission)** — `MISSION_DEPARTMENT_CAPS` (`prompts/__init__.py`):
  *"set `department_caps` to a JSON OBJECT with a `departments` array in PRIORITY order; each
  item is an OBJECT with `name`, `priority`, `rationale`."*
  Parsed by `runtime/mission.py::_department_caps` → a list of `{name, priority, rationale}`
  (note: **no numeric cap** despite the key name).
- **Phase 3 (Org bootstrap)** — `_allot_caps_ctx` (`runtime/org.py`):
  *"Return `department_caps` as a `{department: cap}` mapping."*
  Parsed by `_parse_and_clamp_caps` → a `{department: int}` mapping.

So the Leader is told to emit `{"departments": [{name, priority, rationale}]}` in Phase 2 and
`{dept: cap}` in Phase 3. Because the Leader's memory carries its Phase 2 shape into Phase 3
(MemoryBackend folds memory into the prompt), it can emit the Phase 2 shape in Phase 3, and
`_parse_and_clamp_caps` returns `{}` (no numeric values) — the headcount allotment silently
degrades to the per-manager IC cap. This is the confusion visible in the Leader's runlog.

**Recommendation.**

- **Rename** the Phase 2 key (it is not a cap) — e.g. `mission_departments` (a list of
  `{name, priority, rationale}`) — so it does not collide with the Phase 3 `department_caps`
  (a `{dept: cap}` mapping).
- Update `MISSION_DEPARTMENT_CAPS` (`prompts/__init__.py`), `runtime/mission.py`
  (`_department_caps` + `MissionResult.department_caps`), and the Phase 3 consumers
  (`_department_caps_to_heads` in `runtime/org.py`) to the new key.
- Keep the Phase 3 `department_caps` shape as `{dept: cap}` (it is the one that actually carries
  caps), and make its prompt explicit that it is a **mapping of department name → integer cap**,
  distinct from the Phase 2 department list.

**Question.** Confirm: Phase 2 should propose *which* departments (name/priority/rationale) and
Phase 3 should allot *how many* (dept→cap) — i.e. two different fields, not one? If so, the
rename above is the fix.

**Rolled out (per your answer 3 — distinct naming, code AND prompts, clear phase indicator).**
Confirmed: Phase 2 = *which* departments, Phase 3 = *how many* — two different fields.

- The Phase 2 key is renamed **`mission_departments`** (a list of `{name, priority, rationale}`):
  `MissionResult.mission_departments` + `_mission_departments()` in `runtime/mission.py`,
  `_mission_departments_to_heads()` in `runtime/org.py`, the `LEADER_OUTPUT_SCHEMA` key
  (`roles/leader.py`), and `MISSION_DEPARTMENTS` (`prompts/__init__.py`).
- `_mission_departments` reads the **new key first, with a fallback to the legacy
  `department_caps` key** — so a model that still emits the old key is not silently dropped.
- The prompts now carry a **clear phase indicator**: `MISSION_DEPARTMENTS` says it is the
  **Phase 2** department LIST (not a numeric cap), and the Phase 3 `_allot_caps_ctx` says it is
  the **Phase 3** `{department: integer cap}` mapping, explicitly distinct from `mission_departments`.
- The Phase 3 `department_caps` (the numeric caps) is unchanged.

---

## B. Dashboard data / wiring

### 4. "Agents over time (by department)" — departments duplicated instead of combined

**Current state.** In `observability/web/app.js::render()`, the agents chart is:

```js
buildCumulativeSeries(state.agents.events, (e) => e.department, (e) => e.ts)
  .concat(buildCumulativeSeries(state.tool_calls, (e) => e.department || 'unknown', (e) => e.ts))
```

Two series sets are concatenated, and **both are keyed by the department name**. So each
department appears as **two** stacked series (one from hire/fire events, one from tool calls)
with the same label — the "duplicated" look. (Also, `buildCumulativeSeries` counts *records*,
so the hire side counts hire events, not net headcount.)

**Recommendation.** Merge the two sources **per department** into a single series per department
(sum the hire events + tool-call activity under one key), or, if they should be visually
distinct, give them distinct labels (e.g. `data · hires` and `data · activity`). Combining into
one series per department is what was requested.

**Question.** Do you want the agents chart to show (a) combined activity per department (hires +
calls in one series), or (b) current headcount per department (from the org chart) as the
primary series? These are different metrics.

**Status (verified — partial).** Answered — option b (current active headcount per department).
The current headcount per department now renders as **headcount chips** in the Agents card
(`renderHeadcountChips` in `observability/web/app.js`, from `state.agents.by_department`), which
answers the metric question (how large is the org, and which departments make up a majority of
the headcount). The **chart series itself is still the cumulative hire + tool-call activity
series** (the "duplicated" look from the original finding is not fixed) — so item 4 is partial.

---

### 5. Historical/active pods only show the Leader (solo) pods

**Current state.** The dashboard ingests every `pods/transcripts/*.jsonl`. Solo (Leader) pods
always write transcripts (`SoloTracker`, `runtime/session.py:188`). Execution pods (A/B/C) also
write them (`runtime/dispatch_common.py:937`). **But several `run_pod` call sites do NOT pass
`transcripts_dir`**, so those pods never write a transcript file and never appear:

- Clarification pods — `runtime/dispatch_common.py:132` (`_run_contained_pod`).
- Pod A (headcount) — `runtime/org.py:734`.
- Pod B (team caps) — `runtime/plan.py:171`.
- Phase 7 (evaluate) pods — `runtime/session.py:266` and `:284`.

**Recommendation.** Pass `transcripts_dir` (from `config["pod_transcripts_dir"]`, default
`"pods/transcripts"`) to each of those `run_pod` calls. The config is already available at each
site (the session has `self.config`; `allot_department_caps` / `_allot_team_caps` take `config`;
`_run_contained_pod` needs the dir threaded in from its caller). After this,
clarification/headcount/evaluate pods write transcripts and show in the active + historical panes.

---

### 8. "Roles by hierarchy" not updating (Head=8, but no managers/ICs recognized)

**Current state.** The level chips + roster are driven by `state/org_chart.json`'s `architype`
field (`observability/dashboard.py::poll_org_chart` + `_by_level`, with
`ARCHITYPE_LEVEL = {department_head: Head, manager: Manager, ic: IC}`). The **current** org
chart contains exactly 9 roles: 8× `department_head` + 1× `ic` (0 managers). So the dashboard is
correctly showing Head=8, Manager=0, IC=1 — it is not a rendering bug.

**Likely causes.**

- (a) **The org isn't growing** — it is stuck at bootstrap (8 heads + 1 IC) and is not hiring
  managers/ICs (a pipeline issue, possibly related to item 3's headcount degradation or the IC cap).
- (b) **The org chart file is stale** — `poll_org_chart` only re-reads when the file *size*
  changes; if `OrgState.save()` is not called as roles are hired (or is saving a same-size
  file), the dashboard will not see the growth.

**Recommendation / investigation.**

- Confirm `OrgState.save()` (which writes `state/org_chart.json`) is called after each hire/fire
  in the run; if not, wire it in.
- Make `poll_org_chart` re-read on a content hash (or mtime) rather than size-only, so
  same-size updates are not missed.
- Separately, check why the org is stuck at 8 heads + 1 IC (likely item 3 / the team-cap path).

**Question.** Is the org *supposed* to have grown beyond 8 heads + 1 IC by the point you looked
(i.e. a pipeline bug), or did you expect the dashboard to reflect a larger org that you know
exists (i.e. a stale-file bug)?

**Status (verified — investigation done).** Checked the logs (per your answer 8): **no managers
exist in any run** — `state/org_chart.json` carries 9× `department_head` + 1× `ic` (no
managers), `history/org_events.jsonl` shows only bootstrap events, `history/invocations.jsonl`
shows only leader + head invokes, and the pod transcripts show the heads conversing (Pod A
headcount) but no managers. So the dashboard is **not** broken — it correctly shows Manager=0.
The pipeline *does* support manager hiring (Phase 4 Plan hires the managers the team objectives
name; Phase 5 Staff runs the manager branch) — the runs simply never named a manager, so the org
is stuck at bootstrap (not growing): **likely cause (a) confirmed**, not a stale-file bug. The
dashboard-side fix (`poll_org_chart` re-read on a content hash / mtime rather than size-only) is
**still pending**.

---

### 9. "Agents over time" total >100 but the policy cap is 50

**Current state.** `agents.total` = `sum(agents_by_dept.values())`, where
`agents_by_dept[dept] = max(0, … + delta)` (delta = +1 per hire event, −1 per fire event, from
`history/org_events.jsonl`). The cap is `HEAD_COUNT_TOTAL` (`.env`, → `head_count_total`,
default 50 per your note). The current org chart has only 9 roles, yet the chart shows >100 —
so the chart is showing a **cumulative hire count over the whole run**, not the current headcount.

**Likely causes.**

- (a) The org hires and replaces many roles over the run (lots of hire events), and **fires are
  not being subtracted** (the `fired` event is not logged in `org_events.jsonl`, or is logged
  under a different `kind`), so the count only grows.
- (b) The org is genuinely exceeding the cap (a policy violation).

**Recommendation.**

- Make the chart show the **current headcount** (from the org chart, net of fires) rather than a
  cumulative hire count — that is the number the cap applies to. Keep a separate "hires over
  time" series if the churn should be visible.
- Verify `fired` events are logged (so the net is correct).
- Confirm the cap is actually enforced at hire time (it is, in `runtime/org.py` /
  `runtime/staff.py` via `MAX_ORG_ROLES` / team caps) — if the org is exceeding it, that is a
  separate bug.

**Question.** Do you want the "agents over time" total to be the **current headcount** (capped at
50) — with churn shown separately — or a true cumulative-hires counter (which can exceed 50 by
design)?

**Status (verified — done).** The "agents over time" total is now the **current headcount**:
`agents.total` = the sum of per-department counts, **net of fires** (`FIRE_KINDS = {"fired"}`,
delta −1 in `observability/dashboard.py`), and `fired` events **are** logged (`runtime/org.py`
`fire()` → `org.log_event("fired", ...)` with the department detail), so the net is correct. The
total headcount renders as headcount chips in the Agents card; the cumulative hire/fire event
series remains as the separate churn view. The cap is **confirmed enforced**: the
`HEAD_COUNT_TOTAL=50` department-cap chain (Phase 3 leader allots department caps summing ≤ 50 →
Pod A finalizes → Phase 4 team caps → Phase 5 IC bounded by the team cap) plus the hard
`MAX_ORG_ROLES=60` backstop at bootstrap/hire time.

---

## C. Dashboard frontend

### 6. New module — org flowchart (phases, current phase, active roles + their tasks)

**Current state.** No such module. The dashboard has charts + the conversation monitor + the
model stream, but no phase-flow view.

**Recommendation.** Add a new panel (e.g. "Org flow") that renders:

- The 8-phase flow (Intake → Mission → Bootstrap → Plan → Staff → Execute → Evaluate → Decide)
  as a horizontal stepper.
- The **current phase** highlighted (driven by the latest `cycles.jsonl` /
  `efficiency_metrics.jsonl` `cycle` + phase, or a new `current_phase` field in the snapshot).
- The **active roles in that phase** (from the org chart + the latest tool-call/efficiency data)
  and **their current task** (from the latest `stream` segment label + the pod agenda / the
  role's last invoke context).

This needs a small backend addition: the `Watcher` tracks the current phase (from the
cycles/efficiency-metrics logs) and exposes it + the active roles in the snapshot. The frontend
renders the stepper + the role/task list.

**Question.** For "their current task," do you want the task text from the role's latest invoke
context (the prompt), or from the pod agenda / the decomposition objective? The invoke context
is more granular but noisier.

**Status (verified — pending).** No org-flow panel exists yet (no stepper in
`observability/web/index.html`, and the snapshot carries no `current_phase` field). Answered per
your answer 6: the tasks come from the pod agenda / decomposition objective.

---

### 7. Tooltips on the graphs

**Current state.** Only the code-edits chart has a hover tooltip (`drawTimeSeries`'s
`hoverRecords` path, `app.js:113`). The other time-series charts (agents, levels, tools, errors)
and the bars have no per-point tooltip.

**Recommendation.** Add a generic hover tooltip to `drawTimeSeries` (and keep the one on
`drawBars`): on mousemove, find the nearest time point, and show a tooltip listing **each
series' value at that point with its legend label + color** (so the operator can see which
shaded band is which, and the value at any x). Reuse the existing tooltip DOM pattern
(`bar-tooltip` / `edit-tooltip`).

**Status (verified — pending).** `drawTimeSeries` still only has the `hoverRecords` path (the
per-edit detail tooltip on the code-edits chart); there is **no generic per-point hover tooltip**
yet. (Your answer 7: implement the rec as-is; make sure it's included in the flow-chart from
item 6.)

---

### 10. "Code edits over time" → "Code volume over time" (total LOC by file type, cumulative)

**Current state.** The `chart-edits` shows applied vs refused **edit attempts** (from
`history/code_edits.jsonl`), segmented by department. That is edit *attempts*, not code *volume*.

**Recommendation.** Replace it with "code volume over time": the **total lines of code in the
repo over time, broken down by file type (cumulative)**. Two ways to get the data:

- **(a) A file-write log (recommended).** When an IC's work is applied (`apply_code_edits` in
  `runtime/permissions.py`, and the IC's `work_path` file write in `runtime/dispatch_common.py`),
  log a `history/code_volume.jsonl` record: `{ts, path, file_type, lines_added, lines_total}`.
  The dashboard accumulates `lines_total` per file type over time. File type = the extension
  (`.md`, `.py`, `.json`, …).
- **(b) A repo scan.** The `Watcher` periodically walks `departments/` (and the repo) and
  computes total lines per file type. Simpler to wire but does a disk scan each poll.

Option (a) is recommended — it is incremental, requires no scan, and ties volume to the run's
timeline. The frontend chart becomes a cumulative stacked series by file type (reusing
`drawTimeSeries`).

**Question.** Should "code volume" count only the IC work files under `departments/`, or the
whole repo (including `runtime/`, `prompts/`, etc.)? And is "lines of code" = physical lines
(including blank) or non-blank lines?

**Status (verified — pending).** No `code_volume` logging exists in the runtime yet (no
`history/code_volume.jsonl` writer), and the chart is still "Code edits over time" (edit
attempts, applied vs refused). Answered per your answer 10 (option a): a file-write log of all
role code (including policies) under `departments/`, physical lines.

---

## D. Bug

### 11. `FileNotFoundError` in `write_transcripts` (pod id with a `/`)

**Current state.** The traceback:

```
File "...\runtime\pods.py", line 335, in write_transcripts
    base = os.path.join(transcripts_dir, pod.id)
FileNotFoundError: [WinError 3] ... 'pods\transcripts\solo_IC 2 — data product / bundle engineer_p6.jsonl'
```

`pod.id` is `"solo_IC 2 — data product / bundle engineer_p6"` — it contains a **space**, an
**em-dash**, and a **`/`**. `os.path.join` treats the `/` as a path separator, so it tries to
write into a subdirectory `pods/transcripts/solo_IC 2 — data product/` that does not exist →
`FileNotFoundError`. (The space and em-dash are also unsafe on some filesystems.)

**Root cause.** The solo pod id is built from the role's **full label** (id · sub_architype ·
department), which can contain a `/` (e.g. a sub_architype like `data product / bundle
engineer`). `write_transcripts` uses `pod.id` directly as the file name.

**Recommendation.** In `write_transcripts` (`runtime/pods.py:331`), **sanitize the file name**:
replace path-unsafe characters (`/`, `\`, spaces, and optionally non-ASCII like the em-dash)
with a safe separator (e.g. `-`), or derive a slug/hash. Apply the same sanitization wherever
`pod.id` is used to build a transcript path (the `.jsonl` / `.md` writes). Keep `pod.id` itself
unchanged (it is the display id); only the **file name** is sanitized. This also fixes the same
latent issue for multi-role pod ids that contain a `/`.

---

## E. Rolled out this pass (new items F1 + F2)

> These two items came from the follow-up finding list (not the original A–D review) and are
> recorded here so the file reflects everything that has shipped.

### F1. Frontend — sub-renderer per panel, memoization per data change, data-bound panels

**Rolled out.** `observability/web/app.js` was refactored from a single monolithic `render()`
into a **sub-renderer per panel**, each **memoized per data change**:

- A `renderPanel(name, data, renderFn)` helper serializes the panel's input data and **skips the
  render when the data is unchanged** since the last render — so the 1-second SSE tick only
  redraws the panels whose data actually changed (no redundant re-render of every panel).
- Each chart (agents / levels / edits / tools / cycles / errors) is now its own sub-renderer
  (`renderAgentsChart`, …) rather than inline `drawTimeSeries` calls in `render()`.
- The **EventPanel** (halt events) and **EfficiencyPanel** (per-role / per-department invoke
  time) are **data-bound**: `render()` passes each the exact snapshot slice it renders from
  (`state.halt_events`, `state.efficiency`), so a panel re-renders exactly when the data it
  displays changes.

> Note: this is a **structure** refactor (sub-renderers + memoization + data binding). It does
> **not** change the metrics — the agents-chart "current active headcount per department" (item 4),
> the generic hover tooltips (item 7), and the code-volume chart (item 10) are still pending.

### F2. History — `invocations.jsonl` records `role` + `department`

**Rolled out.** `runtime/history.py::log_invocation` now records a **`department`** field (the
`role` field — the role id — was already present). `runtime/complexity.py::RoutingBackend.invoke`
passes the role's department through, so the dashboard can segment invocations by team without
re-deriving it.

---

## Suggested ordering

1. **Item 11** (bug) — small, unblocks transcript writing. ✅ done
2. **Items 3 + 5** — fix the headcount schema + wire transcripts for all pods (these are why the
   dashboard looks empty/confused). ✅ done
3. **Items 1 + 2** — the intake + routing rework (bigger pipeline changes). ✅ both done (item 2's
   tier rework — code development = MEDIUM — is rolled out + tested).
4. **Items 4, 7, 10** — frontend chart fixes (tooltips, combine, code volume). 🔄 item 4 partial
   (current headcount per department renders as chips; the chart series is still the cumulative
   hire/activity series); ⬜ items 7 + 10 pending (the F1 structure refactor —
   sub-renderers/memoization/data-binding — is ✅ done, so these chart fixes now slot into the
   sub-renderers).
5. **Items 8, 9** — investigate the org growth + headcount metric (may surface a pipeline bug).
   ✅ item 9 done (total headcount net of fires + cap confirmed enforced); 🔄 item 8 partial
   (investigation done: no managers in any run's logs — the org is stuck at bootstrap; the
   dashboard-side content-hash fix is pending).
6. **Item 6** — the new flowchart module (largest frontend addition). ⬜ pending

---

## Open questions (summary)

| # | Item | Question | Status |
|---|------|----------|--------|
| 1 | Intake | Keep any Leader clarifying questions (not the goal, at a higher level), or go straight from the `INPUT` goal to Phase 2? | ✅ answered — keep clarification, never re-ask the goal; rolled out |
| 2 | Routing | Task-based classifier (finer) or role-based with manager-chosen level (coarser)? Is IC code discussion/review MEDIUM? | ✅ answered — task-based; rolled out (code development = MEDIUM, tested) |
| 3 | `department_caps` | Confirm Phase 2 = *which* departments, Phase 3 = *how many* (two fields, not one)? | ✅ answered — two fields; renamed to `mission_departments`; rolled out |
| 4 | Agents chart | Combined activity per department, or current headcount per department as the primary series? | ✅ answered — current headcount per dept (your answer 4, option b); 🔄 partial (renders as headcount chips; the chart series is still the cumulative hire/activity series) |
| 8 | Roles by hierarchy | Should the org have grown past 8 heads + 1 IC (pipeline bug), or is the file stale (dashboard bug)? | ✅ answered — check the logs (your answer 8); 🔄 investigation done: no managers in any run's logs (the org is stuck at bootstrap — the pipeline hires managers only when the plan names them); the dashboard-side content-hash fix is pending |
| 9 | Agents total | Current headcount (capped at 50) with churn separate, or a true cumulative-hires counter? | ✅ answered — total headcount + confirm cap (your answer 9); done (total headcount net of fires; cap confirmed enforced: dept-cap chain ≤ 50 + `MAX_ORG_ROLES=60` backstop) |
| 10 | Code volume | Only `departments/` or the whole repo? Physical lines or non-blank lines? | ✅ answered — file-write log, `departments/`, physical lines (your answer 10, option a); ⬜ pending |
| 6 | Flowchart | Task text from the role's latest invoke context, or from the pod agenda / decomposition objective? | ✅ answered — pod agenda / decomposition objective (your answer 6); ⬜ pending |
