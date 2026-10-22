# Findings & Recommendations — Organization Pipeline + Dashboard

> Generated from a code review of `D:\LLM\LLM_Organization`. Each item below lists the
> **current state** (with file references), the **recommendation** (specific code changes),
> and a **question** where the intent is ambiguous. Items are grouped into
> **A. Pipeline** (1–3), **B. Dashboard data/wiring** (4–5, 8–9), **C. Dashboard frontend**
> (6–7, 10), and **D. Bug** (11).

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

## Suggested ordering

1. **Item 11** (bug) — small, unblocks transcript writing.
2. **Items 3 + 5** — fix the headcount schema + wire transcripts for all pods (these are why the
   dashboard looks empty/confused).
3. **Items 1 + 2** — the intake + routing rework (bigger pipeline changes).
4. **Items 4, 7, 10** — frontend chart fixes (tooltips, combine, code volume).
5. **Items 8, 9** — investigate the org growth + headcount metric (may surface a pipeline bug).
6. **Item 6** — the new flowchart module (largest frontend addition).

---

## Open questions (summary)

| # | Item | Question |
|---|------|----------|
| 1 | Intake | Keep any Leader clarifying questions (not the goal, at a higher level), or go straight from the `INPUT` goal to Phase 2? |
| 2 | Routing | Task-based classifier (finer) or role-based with manager-chosen level (coarser)? Is IC code discussion/review MEDIUM? |
| 3 | `department_caps` | Confirm Phase 2 = *which* departments, Phase 3 = *how many* (two fields, not one)? |
| 4 | Agents chart | Combined activity per department, or current headcount per department as the primary series? |
| 8 | Roles by hierarchy | Should the org have grown past 8 heads + 1 IC (pipeline bug), or is the file stale (dashboard bug)? |
| 9 | Agents total | Current headcount (capped at 50) with churn separate, or a true cumulative-hires counter? |
| 10 | Code volume | Only `departments/` or the whole repo? Physical lines or non-blank lines? |
| 6 | Flowchart | Task text from the role's latest invoke context, or from the pod agenda / decomposition objective? |
