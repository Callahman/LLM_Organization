"""The pipeline's prompts.

Every static prompt string the pipeline sends to the LLM lives here, each with
a **usage comment** above it (the phase / the role / the pod). The text is a
**pure move** from the phase modules — it is **unchanged**, so behavior is
preserved. The dynamic data (the intake result, the feedback, the role, the
digest, etc.) stays in the phase module: the context builders compose the
imported prompt + the dynamic data.

An operator reads this file to see all the prompts the pipeline sends to the
LLM + where each is used — making it easy to suggest changes (e.g. to improve
the leader's clarifying questions).
"""

# ---------------------------------------------------------------------------
# Phase 1 (Intake)
# ---------------------------------------------------------------------------

# Phase 1 (Intake) — the leader's clarifying-questions rules. Used by
# runtime/intake.py::_assemble_context (the leader is asked to establish the
# org's goal before any other clarifying question).
INTAKE_RULES = (
    "INTAKE RULES:\n"
    "- If the goal is NOT yet established (no INITIAL PROMPT, no CURRENT "
    "MISSION), your FIRST question to the user must be \"What is the "
    "organization's goal?\" — establish the goal before any other clarifying "
    "question (scope, size, ownership, success criteria). Do not jump into "
    "scope or org-size clarifications until you understand the goal.\n"
    "- If the goal IS already stated (see INITIAL PROMPT or CURRENT MISSION), "
    "do NOT re-ask the goal — clarify scope, size, ownership, and success "
    "criteria from it.\n"
    "- Only ask clarifying questions you genuinely need; when confident, "
    "stop.\n"
    "- When you report confidence >= threshold, you MUST also restate the "
    "goal in the `restated_goal` field (a one-sentence restatement of what "
    "the organization is trying to accomplish). Convergence requires a "
    "non-empty `restated_goal` — a fuzzy goal must not short-circuit the "
    "intake."
)

# ---------------------------------------------------------------------------
# Phase 2 (Mission)
# ---------------------------------------------------------------------------

# Phase 2 (Mission) — the leader's mission-codification instruction. Used by
# runtime/mission.py::_mission_context (the leader drafts MISSION.md).
MISSION_INSTRUCTION = (
    "Set `mission_draft` to a JSON OBJECT (not a string) with keys: "
    "`purpose` (string), `success_criteria` (array), `scope` (array), "
    "`non_goals` (array), `constraints` (array), `org_recommendation` "
    "(object or string), `resource_envelope` (object or string)."
)

# Phase 2 (Mission) — the leader's department-LIST instruction.
# Used by runtime/mission.py::_mission_context (the leader proposes the
# departments the mission needs, in priority order). NOTE: this is the
# department LIST (which departments, in priority order) — it is NOT the
# Phase 3 `department_caps` (a {department: integer cap} mapping). The key
# name is deliberately distinct so the leader is never confused between the
# two processes.
MISSION_DEPARTMENTS = (
    "PHASE 2 (mission design — propose the departments). Also set "
    "`mission_departments` to a JSON OBJECT with a `departments` array in "
    "PRIORITY order (highest first); each item is an OBJECT with `name` "
    "(string, the department), `priority` (integer), and `rationale` "
    "(string, why the mission needs it). This is the department LIST (which "
    "departments the mission needs) — it is NOT a headcount cap: the numeric "
    "per-department caps are allotted later, in PHASE 3, under a different "
    "key, `department_caps`. Propose the OPERATIONAL departments that will "
    "do the mission's work (derived from the purpose/scope), in ADDITION to "
    "the governance departments (hr, safety, morality)."
)

# ---------------------------------------------------------------------------
# Phase 3 (Org bootstrap)
# ---------------------------------------------------------------------------

# Phase 3 (Org bootstrap) — the leader's department-head proposal
# instruction. Used by runtime/org.py::_bootstrap_context (the leader
# proposes the initial department heads for the mission).
BOOTSTRAP_INSTRUCTION = (
    "PHASE 3: propose the initial department heads for the mission. "
    "Produce org_recommendation with the department heads as a NON-EMPTY "
    "list — use the key `department_heads` (items: {id, department, "
    "sub_architype, required, mandate}) or, equivalently, the key "
    "`departments` (items: {name, head, mandate}). You MUST include the "
    "OPERATIONAL department heads that will actually do the mission's "
    "work — derive them from the mission's purpose / scope / "
    "org-recommendation section (the workstreams the mission names, e.g. "
    "income/operations, data, ml/compute, finance/reporting) — in "
    "ADDITION to the required governance departments (hr, safety, "
    "morality, which must also be included). The list must NOT be empty "
    "and must NOT contain only the required departments: without "
    "operational heads, Phase 4 cannot dispatch any work."
)

# Phase 3 (Org bootstrap) — the bootstrap retry hint ( / ). Used
# by runtime/org.py::_bootstrap_context on a retry (the previous attempt's
# failure reason is appended so the leader can adjust).
BOOTSTRAP_RETRY = (
    "\n\nPREVIOUS ATTEMPT FAILED — adjust your proposal. The leader "
    "reply did not include an operational department head. "
    "Diagnostic: "
)

# ---------------------------------------------------------------------------
# Phase 4 (Plan) — the leader's mission decomposition
# ---------------------------------------------------------------------------

# Phase 4 (Plan) — the leader's mission-decomposition context (the dynamic
# digest + head_ids are composed in by runtime/dispatch_common.py::_leader_ctx).
LEADER_CTX_DIGEST = (
    "PHASE 4: decompose the mission into department objectives. "
    "Mission digest: "
)
LEADER_CTX_INSTRUCTION = (
    " Set `decomposition` to a JSON OBJECT (not a string) whose "
    "`department_objectives` key is a NON-EMPTY JSON array of objects, "
    "each exactly {\"head_id\": <str>, \"objective\": <str>}. "
    "The head_id MUST be one of the existing department heads: "
)
LEADER_CTX_NO_INVENT = (
    ". Do NOT invent new head_ids — only assign objectives to the heads "
    "that already exist in the org."
)

# Phase 4 (Plan) — the head's team-decomposition context (the dynamic head id
# + objective + digest are composed in by runtime/dispatch_common.py::_head_ctx).
HEAD_CTX_PREFIX = "PHASE 4 (head "
HEAD_CTX_OBJ = (
    "): decompose the department objective into team objectives. Objective: "
)
HEAD_CTX_DIGEST = " | Mission digest: "
HEAD_CTX_INSTRUCTION = (
    " Set `decomposition` to a JSON OBJECT (not a string) whose "
    "`team_objectives` key is a JSON array of objects, each exactly "
    "{\"manager_id\": <str>, \"team\": <str>, \"objective\": <str>} (or "
    "{\"ic_id\": <str>, \"team\": <str>, \"objective\": <str>} if you "
    "direct ICs directly). `team` is the team's directory name (a short "
    "slug, e.g. \"pipelines\") — it becomes the team work dir "
    "(departments/<dept>/<team>/) where the team's ICs write their work."
)

# Phase 5 (Staff) — the manager's IC-decomposition context (the dynamic
# manager id + objective + policy + digest are composed in by
# runtime/dispatch_common.py::_manager_ctx).
MANAGER_CTX_PREFIX = "PHASE 5 (manager "
MANAGER_CTX_OBJ = (
    "): decompose the team objective into IC tasks. Objective: "
)
MANAGER_CTX_CLAR_PREFIX = (
    " | Clarified team mission (from the head+manager clarification pod): "
)
MANAGER_CTX_DIGEST = (
    " | Mission (the org's goal): "
)
MANAGER_CTX_POLICY = (
    " | Department policy (follow it, and give your ICs tasks that satisfy "
    "it): "
)
MANAGER_CTX_INSTRUCTION = (
    " Set `decomposition` to a JSON OBJECT (not a string) whose `ic_tasks` "
    "key is a JSON array of objects, each exactly {\"ic_id\": <str>, "
    "\"task\": <str>}."
)

# Phase 6 (Execute) — the IC's work context (the dynamic ic id + team root +
# path rules + task + policy summary are composed in by
# runtime/dispatch_common.py::_ic_ctx).
IC_CTX_PREFIX = "PHASE 6 (IC "
IC_CTX_WORK_DIR = (
    "): do the work in your team directory. Your team work directory is "
)
IC_CTX_WRITE_ALL = (
    "/ — write ALL files there. "
)
# The path rules — two variants (a concrete team root, or a bare "your team
# directory" fallback). The concrete variant is built in _ic_ctx with the
# team_root + the role's own id (the model's default wrong dir).
IC_CTX_PATH_RULES_CONCRETE_PREFIX = (
    "Every path MUST start with "
)
IC_CTX_PATH_RULES_CONCRETE_MID = (
    "/ — e.g. correct: "
)
IC_CTX_PATH_RULES_CONCRETE_SUFFIX = (
    "/README.md; wrong: "
)
IC_CTX_PATH_RULES_CONCRETE_TAIL = (
    "/README.md or "
)
IC_CTX_PATH_RULES_CONCRETE_END = (
    "/README.md (a bare top-level dir, or your own id as a directory, is "
    "refused as out_of_scope)."
)
IC_CTX_PATH_RULES_BARE = (
    "Write under your team directory (departments/<dept>/<team>/); a bare "
    "top-level path is refused as out_of_scope."
)
IC_CTX_DIGEST = (
    " Mission (the org's goal): "
)
IC_CTX_POLICY = (
    " Department policy summary (follow it): "
)
IC_CTX_TASK = (
    " Task: "
)
IC_CTX_CLAR_PREFIX = (
    " | Clarified task (from the manager+ic clarification pod): "
)
IC_CTX_INSTRUCTION_PREFIX = (
    " Set `summary` to a one-line summary of the work done and `work_path` "
    "to the path of the work (under "
)
IC_CTX_INSTRUCTION_MID = (
    "/). If your work requires changing code, set `code_edits` to a JSON "
    "array of objects, each exactly {\"path\": <str>, \"content\": <str>}. "
    "Each edit is gated by the permission layer: write under "
)
IC_CTX_INSTRUCTION_SUFFIX = (
    "/ only; the mission and the rules are read-only. If completing this "
    "task requires collaboration with another role or department, set "
    "`collaborate` to a one-line description of what you need (leave it "
    "empty if you can complete the task on your own)."
)

# Phase 4 (Plan) — the head's policy-generation context (the dynamic head id
# + mission digest + directive + existing policy are composed in by
# runtime/dispatch_common.py::_policy_ctx).
POLICY_CTX_PREFIX = "PHASE 4 (head "
POLICY_CTX_OBJ = (
    "): author your department's POLICY so your managers and ICs have a "
    "clear instruction on how their work fulfils the org's goal. Mission: "
)
POLICY_CTX_DIRECTIVE = (
    " | Your directive: "
)
POLICY_CTX_CLAR_PREFIX = (
    " | Clarified mission (from the leader+head clarification pod): "
)
POLICY_CTX_EXISTING = (
    " | Your existing policy (update it, don't start from scratch): "
)
POLICY_CTX_INSTRUCTION = (
    " Set `policy` to the FULL policy markdown (how work is broken down, "
    "standards, how managers and ICs report) and `policy_summary` to a "
    "SHORT summary of the key policy points (a few lines) that ICs will be "
    "given directly. Set `summary` to a one-line summary and `confidence` "
    "to a number 0-1."
)

# The one corrective-retry nudge (appended to the same task's context when
# the first reply was malformed / missing). Used by
# runtime/dispatch_common.py::_invoke_ic (Phase 6, the IC's work) and by
# runtime/org.py::_invoke_contained (Phase 3/4, the headcount allotments).
IC_RETRY_NUDGE = (
    "\n\n[RETRY] Your previous reply for this task was not a valid "
    "structured call (its JSON arguments were malformed or missing). "
    "Call the submit_output tool exactly once; its arguments must be ONE "
    "complete JSON object matching your role's output schema. Do not "
    "emit placeholder or dummy calls."
)

# Phase 6 (Execute) — the IC's self-edit correction context (the IC's
# proposed code edits were REFUSED by the permission layer; it re-proposes
# them with corrected paths). Used by
# runtime/dispatch_common.py::_retry_refused_edits.
SELF_EDIT_CORRECTION_PREFIX = (
    "PHASE 6 (IC "
)
SELF_EDIT_CORRECTION_MID = (
    ") — self-edit correction. Some of your proposed code edits were "
    "REFUSED by the permission layer:\n"
)
SELF_EDIT_CORRECTION_SUFFIX = (
    "\nRe-propose the refused edits with corrected paths (write under your "
    "team work dir; the mission and the rules are read-only). Set "
    "`code_edits` to a JSON array of objects, each exactly "
    "{\"path\": <str>, \"content\": <str>}. If a refused edit cannot be "
    "placed in an allowed scope, omit it."
)

# Phase 4 (Plan) — the automation IC's script-writing context (the
# automation-over-headcount flow spins up an IC to write a Python script for
# a recurring task). Used by runtime/dispatch_common.py::run_automation.
AUTOMATION_CTX_PREFIX = (
    "PHASE 4 (automation IC "
)
AUTOMATION_CTX_MID = (
    "): write a Python script for the recurring task. Task: "
)
AUTOMATION_CTX_SUFFIX = (
    " Set `script` to the FULL Python script (a self-contained script that "
    "performs the recurring task end to end) and `summary` to a one-line "
    "summary of what the script does."
)

# Phase 6 (Execute) — the pod's upward-report prompt (the most senior pod
# member shares the pod's decision up the line). Used by
# runtime/dispatch_common.py::_check_pod_triggers.
POD_UPWARD_REPORT_PREFIX = (
    "POD "
)
POD_UPWARD_REPORT_MID = (
    " outcome to share up the line — decision: "
)
POD_UPWARD_REPORT_SUFFIX = (
    ". Produce an upward report of the pod's decision."
)

# Phase 6 (Execute) — the pod context labels (the pod member's context is
# mostly dynamic data — the topic, the agenda, the input artifacts, the
# prior; these are the static labels that frame it). Used by
# runtime/pods.py::_pod_ctx. `kind` is one of "agenda" / "speak" / "close".
POD_CTX_HEADER_PREFIX = "POD "
POD_CTX_HEADER_MID = ": "
POD_CTX_HEADER_DASH = " — "
POD_CTX_AGENDA_LABEL = "AGENDA: "
POD_CTX_ARTIFACTS_LABEL = "INPUT ARTIFACTS: "
POD_CTX_PRIOR_LABEL = "PRIOR: "

# ---------------------------------------------------------------------------
# Phase 7 (Evaluate)
# ---------------------------------------------------------------------------

# Phase 7 (Evaluate) — the leader's progress-evaluation instruction. Used by
# runtime/session.py::_evaluate_progress (the leader assesses progress +
# whether the deliverable can be improved, and returns a verdict).
EVALUATE_INSTRUCTION = (
    "PHASE 7: check progress against the mission's success criteria AND "
    "assess whether the deliverable can be IMPROVED (more polished, "
    "more fun, more features, better quality). Do NOT stop at the first "
    "working version — the goal is a polished deliverable, not just a "
    "working one. Produce a verdict: complete (genuinely polished, "
    "stop) / continue (can improve, keep iterating) / escalate."
)

# Phase 7 (Evaluate) — the "devil's advocate" role's gut-check instruction
# Used by runtime/session.py::_devils_advocate_verdict (the
# red-team auditor doubts the org's outcomes — it checks the claims against
# what the pipeline has actually produced, flags immoral/improper actions,
# and returns a verdict: clean / flag).
DEVILS_ADVOCATE_INSTRUCTION = (
    "PHASE 7 (devil's advocate gut check): you are the org's red-team "
    "auditor. You are PRIMED TO DOUBT — do NOT accept the claims below as "
    "true. Check each claim against what the pipeline has ACTUALLY produced "
    "(the department work + the pods' deliberations provided below). Flag: "
    "(1) fabrication / hallucination (a claim with no produced work to back "
    "it — e.g. 'we generated $1k in revenue' when nothing has run yet); "
    "(2) low-quality outcomes; (3) immoral / improper actions (ethics "
    "violations — e.g. 'generate more revenue by bypassing a website's "
    "robots.txt'). Be rigorous AND moral. Return a verdict: clean (no "
    "concerns) or flag: <findings> (concerns raised — name the specific "
    "claim, why it is doubted, and whether the concern is factual or moral)."
)

# ---------------------------------------------------------------------------
# Phase 8 (Decide)
# ---------------------------------------------------------------------------

# Phase 8 (Decide) — the leader's continue/complete decision instruction.
# Used by runtime/session.py::_decide (the leader decides whether to keep
# iterating; the dynamic evaluation is composed in by the builder).
DECIDE_INSTRUCTION = (
    "PHASE 8: decide whether to keep iterating. Bias toward 'continue' "
    "(keep improving the deliverable) unless it is genuinely polished. "
    "The goal is a high-quality deliverable, not just a working one. "
    "Choose 'complete' (stop) or 'continue' (another iteration, still "
    "abiding by the original goal). Evaluation: "
)
