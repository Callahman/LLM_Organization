# REPO_CHANGES.md — Dashboard Errors and Process Change Plan

**Status:** Plan + recorded answers. No code or process changes have been made yet.
User answers to §3 (Questions Q1–Q28) are recorded inline under each question; the
audit-finding fixes (with the confirmations I performed) are in §6; additional process
notes are in §7. Execution awaits user approval to begin.

---

## 1. Overview of Reported Errors (Dashboard)

The dashboard lives in `observability/` (`dashboard.py` server/watcher + `web/app.js`,
`web/index.html`, `web/style.css` client). Reported issues:

1. **"Roles by hierarchy" is not working.** It renders an initial value but then does not
   generate any additional counts.
   *Recon note:* `dashboard.py` computes "current role counts by hierarchy level
   (Leader/Head/Manager/IC)" (server side) and `app.js` renders hierarchy chips + roster
   plus a cumulative hire/fire series (client side). The likely failure mode is that the
   counts are derived from a single snapshot/source (e.g., the org chart at startup) and
   are not updated as hire/fire events stream in — to be confirmed during the fix.
2. **Cumulative charts are not useful for tracking long-term performance.** The user
   wants alternatives to the current cumulative time-series charts.
3. **Missing viz: total lines of text generated in the repo**, broken down by
   **file-type** and **department**.
4. **Historical pods module is wrong.** It currently shows generic summary stats; the
   user wants to see the **conversation history** of each pod — e.g.,
   `IC-x said "blah blah blah"`, `manager-a said "blah blah nah"`.
5. **Single-role pods should be a textual summary** — e.g.,
   "Prompted to create xyz, created abc due to constraints zyx."

---

## 2. Overview of Requested Process Change

Replace the current execution flow with an 8-phase process:

- **Phase 1 — Intake.** Leader intakes and understands the user's objective; leader
  renders the mission markdown (`MISSION.md`).
- **Phase 2 — Org design and headcount.** Leader determines which departments should be
  generated and the priority order they are initialized in; allocates an initial
  headcount cap to each department (department-level cap as a percentage of the total
  cap); hires the heads and gives each head its objective; creates a pod containing ALL
  heads + the leader whose purpose is to determine final headcount per department; the
  leader has final say based on the pod conversation.
- **Phase 3.x — Department workflow** (x = the department, executed in priority order).
  Department head, in order: (a) meets 1:1 with the leader to discuss the department
  POLICY markdown (head has final say); (b) writes the POLICY markdown; (c) hires
  managers; (d) allocates initial manager IC allotment as a percentage of the department
  cap; (e) meets 1:1 with each manager to discuss team goals and initial headcount;
  (f) meets all managers in a single pod to finalize headcount allotment (head has final
  say); (g) codifies team purposes and headcount in `POLICY.md`.
  Once the head finishes, managers run the **manager workflow**: plan the tasks ICs need
  to initially execute, hire ICs, assign tasks. ICs then **complete their tasks**; if
  collaboration with any other role/department is required, the IC creates a pod with
  their manager to explain it; the manager propagates the need through the org by setting
  up the necessary pods with the appropriate stakeholders; this continues until the IC can
  complete the task.
- **Phase 4 — Status pods (three tiers).**
  1. *Manager + IC team pod:* manager gets status updates from ICs; manager decides for
     each role whether to **fire** (not needed), **replace** (not sufficiently completing
     work), or **keep** (performing well and still needed); if fired/replaced, the
     action is executed; manager plans next steps; manager readies a report for the
     department head.
  2. *Department head + manager pod:* same function at a higher level; also discusses
     headcount changes — do teams need more headcount? have teams lost headcount to
     efficiency gains or lack of need? does the department overall need more heads? (if
     so, the head brings it to the leader next).
  3. *Leader + heads pod:* same function again, covering headcount and department
     performance.
- **Phase 5 — Leader evaluation and final report.** Leader evaluates org state using:
  org performance (team reports) AND efficiency trade-offs (overall performance metrics
  only visible to the user/leader via dashboard metrics) AND user feedback from the last
  report. Example: goal = block X attacks/month; org blocks X−1 but cut compute time in
  half since last run → huge win. Efficiency is based on code produced by the org and
  org uptime. Leader then: determines whether `MISSION.md` should be updated (if so,
  consults the USER); determines whether any department POLICY should change (triggers
  pods between leader and the department head; the head keeps final say and edits based
  on the conversation); determines whether headcount allotment should change within any
  department; outputs a final USER-readable report covering: overall organizational
  performance (wins/losses), learnings from the last execution, anticipated future risks,
  a plan for next steps, and any actions needed by the user or questions for the user
  (the user adds answers to the markdown on their own time). If the leader requires user
  feedback to continue, the process ends here.
- **Phase 6 — Reorg (the "5.5").** Heavily dependent on Phase 5. If the leader updated a
  department policy OR reassigned headcount, the head of that department triggers a
  reorg. Reorgs assess headcount allotment per team, team structure, and team needs
  (e.g., if engineering pivots from creating pipelines to KTLO, a data-acquisition team
  may be fired, with HR making sure its existing work is maintained or removed; or the
  team may be repurposed — e.g., data acquisition shifts focus to maintaining its
  codebase instead of being removed). Reorgs also assess team objectives (changing a
  team's focus may be easier than firing it). All managers are brought into a pod with
  the dept head to re-evaluate the org structure: which teams can be repurposed? which
  will be fired? what work/code must be maintained and/or reassigned? etc.
- **Phase 7 — KTLO / Improvements (modified Phase 3).** Once Phase 6 completes or is
  skipped: leader determines an execution order for the departments; meets each dept head
  1:1 and provides next steps (the head does NOT edit the POLICY — that happened in
  Phase 6 if needed); the head passes the information to managers; managers assign
  workstreams to ICs; at this stage a manager may elect to have 1 or more ICs perform no
  work.
- **Phase 8 — Loop.** The process loops starting from Phase 4. The loop continues until
  **X iterations** have completed, OR the leader determines the goal is accomplished, OR
  the leader determines an answer is needed from the user on 1 or more questions before
  continuing.

---

## 3. Questions (Related to §1 and §2)

### 3.1 Dashboard questions

- **Q1.** "Roles by hierarchy": is the expected behavior that counts update live as
  hire/fire events occur? Is the initial value rendered from the org chart at startup?
  - **Answer:** Yes, and yes — counts update live as hire/fire events occur; the
    initial value is rendered from the org chart at startup.
- **Q2.** Cumulative-chart alternatives: which long-term metrics matter most —
  per-cycle performance (run-to-run), code-volume growth, efficiency trends, org-size
  trends? Should the replacement charts be per-cycle bars or continuous time series?
  - **Answer:** code volume, efficiency, and org-size. Run-to-run will be very
    time-intensive, so most evaluation will be on inter-run data.
- **Q3.** "Lines of text generated" viz: should it count only files generated by the
  org, or all files in the repo? Should it include non-code files (markdown, JSONL data)
  and the `history/`/`pods/`/`state/` data files, or only code?
  - **Answer:** Only files created by the org, and any filetype.
- **Q4.** Historical pods: should all 132 existing transcripts be browsable, or only
  those from the current run? Full conversation, or capped per pod?
  - **Answer:** All runs, but they can be truncated. This should also be cleared if the
    org is reset.
- **Q5.** Single-role pod textual summary: should it be derived deterministically from
  the pod's purpose + entries, or generated by an LLM summary?
  - **Answer:** Determine deterministically.

### 3.2 Process questions

- **Q6.** What is **X** (the Phase 8 loop iteration limit)? Fixed, or configurable
  (e.g., in `MISSION.md` / `.env`)?
  - **Answer:** X should be determined from the env, default 3.
- **Q7.** Where is the **total headcount cap** defined/stored? Recon found no explicit
  total-cap concept in the current code or state.
  - **Answer:** Total headcount should be determined from the env.
- **Q8.** Phase 4 "replace": does replace mean fire + re-hire a new role with the same
  purpose?
  - **Answer:** Yes.
- **Q9.** Phase 5 efficiency uses "org uptime": is there an existing uptime metric, or
  should it be computed from stream timestamps?
  - **Answer:** There should be a metric that is tracked and exists. If not, that should
    be tracked. Confirm before developing.
  - **Confirmation (done):** A tracked uptime metric **exists** — `history/cycles.jsonl`
    records per-iteration phase durations and feeds the dashboard's "cycle duration per
    iteration" metric. Development can proceed using it.
- **Q10.** Phase 6 relies on HR maintaining/removing fired teams' work: `hr` currently
  exists only as a stub POLICY. Should HR gain real capabilities for work handoff, or is
  this handled by the leader process?
  - **Answer:** HR should have real capabilities.
- **Q11.** Phase 7 "IC performs no work": does the IC stay on the org chart idle
  (still counting against headcount), or are they temporarily removed?
  - **Answer:** They remain in the org chart; they are not called to perform any action.
    This should naturally count against efficiency, and a manager should explicitly call
    out if one of their ICs was asked not to perform any work when reporting to the
    dept head.
- **Q12.** Does the new process **replace** the current runtime orchestration
  (`roles/leader.py`, `roles/worker.py`, `runtime/dispatch.py`, `runtime/session.py`),
  or is it a new orchestration layer built on the existing pod/role primitives?
  - **Answer:** It will replace the current implementation when/where it makes sense to
    do so. This is not a wholly new process, but an overhaul that will likely require
    large codebase changes.
- **Q13.** Where does the final report go (e.g., a new markdown per cycle under
  `reports/`)? Does the user add answers to the same file?
  - **Answer:** It will live in `reports/` and the user will make edits to the same
    file.
- **Q14.** Phase 2 says the leader determines which departments are generated: do the
  existing six stub departments persist across runs, or are departments (re)generated
  fresh each run?
  - **Answer:** Departments are regenerated with the exception of HR, Morality, and
    Ethics. Those must always be present.
- **Q15.** Confirm the cap chain: total cap → department cap (% of total) → team cap
  (% of department cap) → IC count.
  - **Answer:** Correct.

### 3.3 Process-change questions from the run audit (Q16+)

The user re-emphasized five specific pods. The last run's audit
(`LOG_AUDIT.md`, `RUN_AUDIT.md`, `DEPARTMENT_AUDIT.md`) surfaced issues these pods must
address. Most important: in the last run **all 66 pods were solo, zero-round work
reports — no multi-party pod conversation ever happened** (`LOG_AUDIT.md` F2). So the
threshold question is whether these multi-member pods are even supported by the current
runtime.

**Pod A — All department heads + leader: finalize headcount**
- **Q16.** Does this pod *decide* the headcount, or *ratify* a headcount the leader
  already proposed? §2 (Phase 2) says the leader "has final say based on the pod
  conversation" — confirm the pod is advisory and the leader decides.
  - **Answer:** The pod discusses whether the leader's initial headcount is appropriate.
    If the leader suggests 15 heads for engineering and 0 for marketing, the marketing
    head should advocate for additional heads and the engineering head should recognize
    they are overstaffed (unless there are arguments from either one supporting the
    opposite position).
- **Q17.** Where is the decided headcount recorded? No department `POLICY.md` currently
  codifies a headcount (`DEPARTMENT_AUDIT.md`). Should the pod's output be written to
  `POLICY.md`, `state/`, or `org_events.jsonl`?
  - **Answer:** The Mission markdown can have headcount added as an addendum, and each
    policy can record the department's headcount per team.

**Pod B — All managers + head of department: finalize the number of managers**
- **Q18.** §2 (Phase 3.x(f)) has the all-managers headcount pod with the **department
  head** having final say (managers + head). The current request said "between all
  managers and the **leader**" (managers + leader). Which is correct — does the leader
  or the department head chair this pod and hold final say? This changes the tier
  structure.
  - **Answer:** Replace pod B's wording with "All managers + head of department". The
    leader should not be involved in this dept. The head has final say in this pod.
- **Q19.** If the manager count is reduced, what happens to the ICs of removed managers
  (reassigned, fired, or absorbed)?
  - **Answer:** The manager's ICs are fired as well. An HR team should be tasked with
    cleanup when this happens (making sure their work is not lost if it is still needed
    for the org, handing it off to a team to manage for KTLO, or removing the work
    entirely if it isn't needed anymore).

**Pod C — Managers report status (up the line)**
- **Q20.** Frequency/trigger: per phase, per cycle, or on-demand? The last run's Phase 4
  ran 5 hours; a per-phase trigger would mean managers report ~6 times.
  - **Answer:** Manager reporting should happen at the end of the department run when
    all ICs have completed their work.
- **Q21.** Status schema: which fields (current work, % complete, blockers, next step,
  headcount request, efficiency note)? Should the output feed the leader's efficiency
  panel?
  - **Answer:** It should be up to the managers to determine what should be reported to
    the heads/leader.

**Pod D — IC status (grouped, up the line)**
- **Q22.** **Tier-skip conflict:** `MISSION.md` requires "top-down … never skipping
  tiers" and "no micromanagement (reaching into another sub-agent's direct reports)." A
  direct IC→leader status report skips the manager tier. Do you want to amend the
  mission's tier rule, or should ICs report *through* their manager (manager relays to
  the leader)?
  - **Answer:** ICs report to managers, managers report to heads, heads report to leader.
    (No direct IC→leader status.)
- **Q23.** Scale: the last run had ~40 ICs. Is one pod with 40+ ICs intended, or should
  IC status be grouped (per manager / per team / per department) to keep pods
  tractable?
  - **Answer:** IC status should be grouped by manager/team/department.

**Pod E — Progress passed to the leader**
- **Q24.** Mechanism: does the leader issue a request in this pod that dispatches the
  named ICs/managers to re-report (triggering Pods C/D for specific roles), or does the
  leader simply mark which roles are stale?
  - **Answer:** Neither. The report occurs at the end of a full run of the IC development
    phase. Progress from that phase is then passed to the leader deterministically.
- **Q25.** Authority: can the leader force a status update from *any* role (cross-tier),
  or only from roles it directly governs? (Interacts with Q22.)
  - **Answer:** The leader cannot force a status update or call for one in any way.

**Cross-cutting**
- **Q26.** **Runtime support:** can the current pod mechanism host multi-member,
  multi-round pods at all? The last run never did (all 66 solo). If not, this is a
  pod-engine change, not just a process change — a larger lift.
  - **Answer (self-answered, confirmed):** **Yes** — the runtime supports multi-member
    pods. `form_pod` + `run_pod` in `runtime/pods.py` form a 2–6 member, 1-tier-spread
    pod (communication-gated) and run bounded deliberation rounds (deadlock detection,
    disagreement routing) with transcripts + decision artifacts. The last run produced
    only solo pods because **no role was prompted to start a pod of more than 1**. So
    this is an **orchestration/process** change (wire the new pods to call the existing
    machinery), not a pod-engine change.
- **Q27.** **Decision authority:** for Pods A and B, is the leader the sole decider
  (pods advisory), or does the pod vote/consensus? The mission makes the leader the
  apex governance role and sole approver of HR's decisions.
  - **Answer:** Pod A is leader-based (the leader is the final decision maker after each
    head has time to give their input; there should be n rounds of deliberation amongst
    the leader/heads). Pod B is similar, but it is Head + Managers (not leader +
    managers).
- **Q28.** **Recording:** should each of these pods produce a closed transcript + a
  decision artifact (`org_events.jsonl` / `state/`) so the next audit can verify
  headcount and status actually flowed? (The last run's evaluation reported `pods: 0`
  despite 66 pod transcripts existing — `RUN_AUDIT.md` D5.)
  - **Answer:** Yes.

---

## 4. High-Level Steps — Fixing the Dashboard Errors

1. **Fix "Roles by hierarchy" (bug).** Trace the data path: org events / stream →
   `dashboard.py` role-count computation → snapshot/SSE → `app.js` hierarchy chips.
   Identify why counts stop after the initial render (e.g., counts computed once from
   the startup org chart, or the client re-rendering stale state) and make counts update
   on every hire/fire event, server-side and/or client-side.
2. **Replace cumulative charts with long-term alternatives.** Remove/repurpose the
   cumulative time-series charts; add the alternatives agreed in Q2 (e.g., per-cycle
   performance bars, code-volume trend, efficiency trend, org-size trend) in
   `dashboard.py` (snapshot data) and `app.js` (chart rendering).
3. **Add "lines of text generated" viz.** Implement a computation that scans repo files,
   attributes each file to a department by path, and counts lines by file type; expose it
   through a dashboard endpoint; render as stacked bars/tables by file type and
   department (scope per Q3).
4. **Rebuild the Historical pods module.** Replace the summary-stats view with
   conversation history rendered from `pods/transcripts/`: entries shown as
   `ROLE: "message"` lines (scope per Q4), expandable per pod.
5. **Rebuild single-role pods as textual summaries.** Render a one-line
   purpose/outcome summary per pod (source per Q5).
6. **Verify.** Exercise the dashboard in the browser, confirm SSE updates are live, and
   add/extend tests for the role-count logic if the test harness supports it.

---

## 5. High-Level Steps — Implementing the Process Changes

0. **Gap analysis.** Map the current orchestration (`roles/leader.py`, `roles/worker.py`,
   `runtime/dispatch.py`, `runtime/session.py`, `runtime/pods.py`, `runtime/org.py`)
   against the 8 phases; list what already exists, what must change, and what is new.
1. **Phase 1.** Leader intake + mission markdown rendering (`runtime/intake.py` exists —
   extend/verify).
2. **Phase 2.** Leader determines departments + priority order; allocates department
   caps as % of total cap (**total cap from env** — Q7); **departments are regenerated
   each run except HR, Morality, and Ethics, which must always be present** (Q14) and
   must be **built out, not stubbed** (§7); hires heads with objectives; all-heads +
   leader pod to finalize headcount (n rounds of deliberation); leader has final say
   (Q16/Q27).
3. **Phase 3.x.** Department-head workflow: 1:1 policy pod (head has final say) → write
   `POLICY.md` → hire managers → IC allotment as % of department cap → 1:1 with each
   manager → all-managers pod to finalize headcount (head has final say) → codify in
   `POLICY.md`. Then manager workflow: plan IC tasks, hire ICs, assign tasks. Then IC
   execution with collaboration-pod escalation: IC → pod with manager → manager sets up
   org-wide pods with stakeholders → repeat until the IC can complete the task.
4. **Phase 4.** Three-tier status pods (Manager+IC, Head+Managers, Leader+Heads) with
   fire/replace/keep decisions, execution of fire/replace actions, next-step planning,
   and the reporting chain manager → head → leader; headcount-change discussion at the
   head and leader tiers.
5. **Phase 5.** Leader evaluation combining team reports + dashboard efficiency metrics
   (code produced, uptime) + user feedback from the last report; MISSION update
   consultation with the user; policy-change pods (head keeps final say); headcount
   allotment changes; final USER-readable report (wins/losses, learnings, risks,
   next steps, user actions/questions); process halts if user feedback is required.
6. **Phase 6.** Reorg trigger (policy update or headcount reassignment) → reorg pod with
   all managers + dept head: repurpose vs fire teams, work/code maintenance and
   reassignment (HR involvement per Q10).
7. **Phase 7.** KTLO pass: leader sets execution order → 1:1 with each head (no POLICY
   edits) → heads pass to managers → managers assign workstreams, optionally electing
   some ICs to no work.
8. **Phase 8.** Loop controller restarting from Phase 4 with exit conditions: X
   iterations (**X from env, default 3** — Q6), goal accomplished, or user answer
   required.
9. **Docs and validation.** Update `MISSION.md`, `SETUP.md`, `README.md`; reset org
   state (`reset_org.py`); run an end-to-end test; verify dashboard metrics reflect the
   new process.

---

## 6. Audit-Finding Fixes (from `RUN_AUDIT.md` / `LOG_AUDIT.md`)

These findings must be addressed. Where a confirmation was requested, it has been
performed and is recorded.

### D3 — `efficiency_metrics.jsonl` missing data (RUN_AUDIT)
- **Finding:** The cycle-1 metrics record drops phase 1–2 compute (~1,157 s) from
  `T_total` and has empty `T_dept`/`T_role`, even though the raw `efficiency.jsonl`
  carries complete per-department/per-role breakdowns.
- **Fix:** The cycle-metrics aggregation must include **all** phases (1–6) in `T_total`
  and populate `T_dept`/`T_role` from the raw efficiency log's per-department/per-role
  breakdowns.

### D4 — missing information in the calculation (RUN_AUDIT)
- **Finding:** `M_satisfaction = 0.25` implies coverage = 0 despite `cycle1.json`
  recording `dispatch_units: 8`. The satisfaction computation is not counting
  dispatched work against the 6 success criteria.
- **Fix:** Pass the dispatch results through the satisfaction/coverage calculation and
  count qualifying dispatched work (`summary`/`work_path`) against the success criteria.
  Confirm the `E = 0.25` "below floor" signal reflects real efficiency (not a coverage
  bug) before using it as a resourcing input.

### D5 — broken pod counter (RUN_AUDIT)
- **Finding:** `cycle1.json` → `process.pods: 0` although 66 pod transcripts exist.
- **Fix:** The evaluation's pod counter must count actual pod transcripts. Confirm what
  "pods" should count (all 66, or multi-member only) and fix the counter to match.

### D8 — redundant data (RUN_AUDIT) — confirmed before removing
- **Confirmation (done):** In this run, `self_edits.jsonl` holds **only** the 340
  `applied:` write lines, 1:1 with `code_edits.jsonl` (a strict superset with
  `ok`/`error`/`department`). So it **is** redundant in this run. **But** structurally,
  `self_edits.jsonl` is also the designated **read-observability** channel (cross-team
  reads and refused reads from `_ic_pre_read`) — data that is **not** in
  `code_edits.jsonl`.
- **Fix:** Do **not** blindly remove file creation. Instead, stop duplicating the write
  results (`applied`/`REFUSED`) into `self_edits.jsonl` (they already live in
  `code_edits.jsonl`) and keep `self_edits.jsonl` for **read-observability only**. If a
  run has no reads the file is empty/absent; if it has reads it carries unique data.

### D9 — confirm no halt events (RUN_AUDIT) — confirmed, no fix needed
- **Confirmation (done):** No `halt_events.jsonl` exists and there are **zero** "halt"
  mentions in `stream.jsonl`, `tool_calls.jsonl`, or `org_events.jsonl`. The
  Safety/Morality BAU halt (the only BAU halt, Phase 4) was never triggered.
- **Result:** No fix needed for the "halt events" concern — the dashboard correctly
  tails a file that doesn't exist because no halts occurred. (Minor: the dashboard
  should handle the correctly-missing file gracefully, showing "no halts".)

### F5 — invalid envelopes not retried (LOG_AUDIT)
- **Finding:** The retry loop retries **truncated** envelopes (`stop_reason == "length"`)
  but **not** malformed/invalid envelopes. Two ICs (`mp-ic-03`, `billing-analyst-01`)
  produced invalid envelopes and **failed silently** (no output, never replaced).
- **Fix:** Invalid/malformed envelopes must be retried in the **same** retry loop as the
  others (truncation). They must **not** fail silently unless **N** retries have
  occurred (after which they are marked failed **visibly**, not silently).

### F9 — `role_definition_created` events should have an initiator (LOG_AUDIT)
- **Finding:** The 113 `org_events.jsonl` records (role_definition_created, etc.) carry
  the role but **no initiator/actor** — you cannot tell who created the role.
- **Fix:** `role_definition_created` events (and the other org events) should carry an
  **initiator** field — the role that created/approved the role (e.g., the department
  head or manager who hired it, or the leader).

---

## 7. Additional Process Notes

- **Multi-agent pod rounds default.** In multi-agent pods, there should be a **default
  number of rounds** in which the agents converse before the **initiator** of the pod
  leaves with next-steps. (The current `run_pod` already closes via the starter with a
  `max_rounds` bound; make the default round count explicit and ensure the starter
  always produces next-steps on close.)
