"""The pipeline's prompts (Story 11).

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
    "- Your FIRST question to the user must be \"What is the organization's "
    "goal?\" — establish the goal before any other clarifying question "
    "(scope, size, ownership, success criteria). Do not jump into scope or "
    "org-size clarifications until you understand the goal.\n"
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

# Phase 2 (Mission) — the leader's department-proposal instruction (Story 6).
# Used by runtime/mission.py::_mission_context (the leader also proposes the
# departments the mission needs, in priority order).
MISSION_DEPARTMENT_PROPOSAL = (
    "Also set `department_proposal` to a JSON OBJECT with a `departments` "
    "array in PRIORITY order (highest first); each item is an OBJECT with "
    "`name` (string, the department), `priority` (integer), and `rationale` "
    "(string, why the mission needs it). Propose the OPERATIONAL departments "
    "that will do the mission's work (derived from the purpose/scope), in "
    "ADDITION to the governance departments (hr, safety, morality)."
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

# Phase 3 (Org bootstrap) — the bootstrap retry hint (Story 11 / B15). Used
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
# manager id + objective + policy are composed in by
# runtime/dispatch_common.py::_manager_ctx).
MANAGER_CTX_PREFIX = "PHASE 5 (manager "
MANAGER_CTX_OBJ = (
    "): decompose your team objective into IC tasks. Objective: "
)
MANAGER_CTX_POLICY = " | Policy so far: "
MANAGER_CTX_INSTRUCTION = (
    " Set `summary` to a JSON OBJECT with keys: `tasks` (a JSON array of "
    "objects, each exactly {\"ic_id\": <str>, \"task\": <str>}), `teams` "
    "(a JSON array of team names — the team work dirs the tasks live in, "
    "e.g. [\"pipelines\"]), and `policy` (a string — the department's "
    "operating policy that the ICs will follow). If you do NOT have any "
    "ICs yet (a fresh team), leave `tasks` as an empty array and set "
    "`teams` to the team names you expect to form."
)

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
# (Story 12). Used by runtime/session.py::_devils_advocate_verdict (the
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
