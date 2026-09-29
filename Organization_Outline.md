# Organization — Project Outline

A "company" of LLM agents that takes a single initial prompt, has a **Leader**
(CEO / President / Entrepreneur personality — the only "active" personality at
startup) clarify the task with the user, codify it into a **global mission
markdown**, and then run a **top-down hierarchical organization**
(leader → department heads → managers → individual contributors) to complete
the task. Resourcing (hiring/firing) is gated by **HR**, and cross-team
collaboration happens in **pods** — small deliberation rooms carried over from
a prior agent-team design.

The design borrows specific, proven mechanisms from that prior agent-team
project:

- **Pods** — small groups of roles (2–6) that deliberate on one topic in their
  own room, so conversations don't spill into each other (§2.8).
- **Role definitions as structured contracts** — mandate + input spec + output
  schema, enforced by the session runtime (§2.7).
- **Bounded context assembly** — agenda + inter-round summaries +
  speaker-relevant digests, deterministic truncation (§2.9).
- **Audit trail** — per-pod JSONL + markdown transcripts, decision journal,
  rolling window, size-capped archives (§2.10).
- **Guardrail philosophy** — hard budgets, explicit close authority,
  escalation on repeated failure (mirrors the prior design's guardrails).

Everything else is new: the tiered org chart, the mission-codification loop,
HR-gated resourcing, per-role short-term memory that seeds prompts, the
self-improving evaluation phase, and department working directories with
department-level policy markdowns.

> Naming note: "Organization" is the working repo name (this outline lives in
> `LLM_Organization/`); the user may rename it. The architecture is
> **task-agnostic** — the mission is defined by the initial prompt at runtime,
> not hardcoded.

---

## Table of Contents

1. [Purpose](#1-purpose)
2. [Overall Outline](#2-overall-outline)
   - 2.1 [Architecture](#21-architecture)
   - 2.2 [The Leader (the only active personality at startup)](#22-the-leader-the-only-active-personality-at-startup)
   - 2.3 [The Hierarchy](#23-the-hierarchy)
   - 2.4 [Visibility & Access Model](#24-visibility--access-model)
   - 2.5 [Resourcing (hiring / firing, HR-gated)](#25-resourcing-hiring--firing-hr-gated)
   - 2.6 [Departments (the catalog)](#26-departments-the-catalog)
   - 2.7 [Role Definitions (Architype / Sub-Architype / Personality)](#27-role-definitions-architype--sub-architype--personality)
   - 2.8 [Pods](#28-pods)
   - 2.9 [Context, Memory & Prompt Construction](#29-context-memory--prompt-construction)
   - 2.10 [Audit Trail](#210-audit-trail)
3. [The Pipeline](#3-the-pipeline)
4. [Repo Layout](#4-repo-layout)
5. [Steps to Develop the Project](#5-steps-to-develop-the-project)
6. [Suggestions](#6-suggestions)
7. [Concerns](#7-concerns)

---

## 1. Purpose

The purpose of this project is to **replace the "one big agent doing
everything" pattern with an organized, self-resourcing agent company**:

- A **Leader** — a single CEO / President / Entrepreneur personality that is
  the **only active personality at startup** — receives an initial prompt from
  the user and **asks clarifying questions until it is confident** it
  understands the overall task (§3, Phase 1).
- The Leader **codifies the task into a global markdown** (`MISSION.md`) that
  every future agent can read — the mission statement for the organization. The
  Leader is the **only role that can edit** the global markdown, and **must
  seek permission from the user before every edit** (§3, Phase 2).
- The organization then functions **top down**: the leader assigns to department
  heads, department heads assign to managers, managers assign to individual
  contributors. Each role can only **look up or down 1 tier** directly;
  information propagates up the chain of command (§2.3, §2.4).
- **Resourcing is dynamic and HR-gated**: the leader spins up department
  heads as needed; managers and department heads can hire/fire a direct
  report (ICs cannot initiate hiring/firing), but HR must approve every
  hiring/firing decision except its own, and HR's own decisions require the
  leader's approval. HR prevents redundant resourcing and manages the
  offloading of a team's existing work when a firing happens (§2.5).
- **Departments** are the units of capability. Each has its own working
  directory and its own **department policy markdown**; each team within a
  department has its own directory and refers to the department markdown's
  section about that team for its purpose (§2.6).
- **Cross-team collaboration** happens in **pods** — small groups of roles
  (2–6) whose tiers span at most 1 tier, each in its own room (§2.8).
- Every role is defined by an **Architype** (department head / manager / IC),
  a **Sub-Architype** (e.g. manager of analytics), and a **Personality**
  (§2.7).

### Non-goals (v1)

- No hardcoded mission — the task comes from the initial prompt.
- No flat "team + team lead" (the prior agent-team model; this repo is the
  hierarchical successor).
- No role communicating across more than 1 tier (no IC talking to a
  department head directly; no leader reaching into a team's ICs to
  micromanage).
- No hiring/firing that bypasses HR (or, for HR itself, the leader).

---

## 2. Overall Outline

### 2.1 Architecture

```
+------------------------------------------------------------------------+
| USER                                                                   |
|  - provides the INITIAL PROMPT                                         |
|  - answers the Leader's clarifying questions                           |
|  - grants permission for every MISSION.md edit                         |
+----------------+-------------------------------------------------------+
                 |
                 v
+------------------------------------------------------------------------+
| THE LEADER (CEO / President / Entrepreneur)                            |
|  - the ONLY active personality at startup                              |
|  - intake: clarifying Q&A until confident (§3 Phase 1)                 |
|  - codifies MISSION.md (only editor; user permission per edit)         |
|  - decomposes the mission into department objectives                   |
|  - hires/fires department heads (HR-approved)                          |
|  - approves HR's own hiring/firing decisions                           |
|  - synthesizes progress vs mission success criteria                    |
|  - NEVER reads code — only what's brought to them (reports, artifacts) |
+----------------+-------------------------------------------------------+
                 |  (tier 0 -> tier 1)
                 v
+------------------------------------------------------------------------+
| DEPARTMENT HEADS (tier 1) — spun up as needed by the Leader (* = required)
|  HR* | Safety* | Morality* | Analytics | Data Eng. | ...             |
|  - each owns a working directory + department policy markdown          |
|  - decomposes objectives into team/manager work                        |
|  - reports up to the Leader (structured summaries + artifacts)         |
|  - cannot read any code — only what's brought to them (§2.4)           |
+----------------+-------------------------------------------------------+
                 |  (tier 1 -> tier 2)
                 v
+------------------------------------------------------------------------+
| MANAGERS (tier 2) — e.g. manager of analytics, manager of finance      |
|  - each leads a team directory within a department                     |
|  - decomposes team work into IC tasks                                  |
|  - reports up to the department head                                   |
+----------------+-------------------------------------------------------+
                 |  (tier 2 -> tier 3)
                 v
+------------------------------------------------------------------------+
| INDIVIDUAL CONTRIBUTORS (tier 3) — e.g. analyst, data engineer, dev    |
|  - do the actual work (code, analysis, sourcing, reporting)            |
|  - work lives in their team directory                                  |
|  - report up to their manager                                          |
+------------------------------------------------------------------------+

Cross-cutting (not tiers):
  - PODS: 2-6 roles whose tiers span at most 1 tier deliberate in their own
    room; the starter manages the conversation (§2.8)
  - MISSION.md: global mission, Leader-only edits (§3 Phase 2)
  - org/registry: the org chart (roles, architypes, reporting lines)
  - history/ + archives/: audit trail, decision journal
```

### 2.2 The Leader (the only active personality at startup)

The Leader is a single role with a **CEO / President / Entrepreneur**
personality. At startup — before the pipeline runs — **no other role exists
and no other personality is active**. The Leader is the only agent that
interacts with the user during intake and mission codification.

| Aspect | Definition |
|---|---|
| Architype | `leader` (tier 0 — outside the head/manager/IC ladder) |
| Sub-Architype | — (none; the Leader is the apex) |
| Personality | Entrepreneur (default); the user may pin a variant (e.g. "Pragmatic CEO", "Visionary Founder") in config |
| Mandate | Understand the task (clarifying Q&A); codify and guard the mission; decompose and delegate top-down; approve resourcing with HR; verify convergence against mission success criteria |
| Unique powers | (1) The **only editor** of `MISSION.md` — and must seek user permission before every edit; (2) the only role that can hire/fire **department heads** (HR-approved); (3) the only approver of **HR's own** hiring/firing decisions; (4) explicit authority to **close** a phase/pod and declare the mission complete or escalated |
| Limits | Cannot read **any code** — only what is brought to them (structured reports, summaries, decision artifacts — §2.4); cannot micromanage teams (no reaching into another sub-agent's direct reports — §2.4); cannot edit `MISSION.md` without user permission; cannot hire/fire without HR's approval; can be replaced by unanimous department-head agreement (§2.2.1) |

The Leader's role definition follows the same structured contract as all
other roles (§2.7): mandate + input spec + output schema. Its phase-driven
outputs (clarifying questions, mission draft, decomposition plan, convergence
verdict) are enforced by the session runtime with schema validation + bounded
retries on malformed output.

#### 2.2.1 Leader replacement (unanimous department-head vote)

- **Rule**: if **all active department heads agree**, the Leader can be
  replaced with a new leader (a **new personality** — randomly assigned per
  §2.7). Because HR, Safety, and Morality are required departments, their
  heads are always part of the quorum.
- **The original prompt/goal is still abided by.** The mission's core
  (purpose, success criteria) is preserved. The **new leader determines
  if/how to modify the mission statement** — any such modification still
  requires user permission per edit (§3, Phase 2).
- **Typical motivator**: if the leader starts to continuously suggest
  unethical approaches to completing the mission, the Morality, Safety, and
  HR heads (together with the remaining heads, since unanimity is required)
  can decide to replace the leader.
- **Process**: the heads record their agreement + rationale → the old leader
  is marked inactive in the org registry (a firing by this special rule — an
  exception to the normal HR-gated flow, but HR's own agreement is part of
  the unanimity, so the gate is preserved) → a new leader is spun up with a
  randomly assigned personality → the user is **notified** (non-blocking —
  BAU continues, §3) → the new leader takes over from the current phase.
- **Audit**: the replacement is recorded in `history/org_events.jsonl` with
  the heads' agreement and rationale.

### 2.3 The Hierarchy

The org is a strict four-tier ladder:

```
  tier 0   LEADER            (CEO / President / Entrepreneur)
              |
  tier 1   DEPARTMENT HEADS  (HR Director, Head of Analytics, Head of
              |               Data Engineering, Controller, ...)
  tier 2   MANAGERS          (manager of hiring, manager of analytics,
              |               manager of data engineering, ...)
  tier 3   INDIVIDUAL CONTRIBUTORS (recruiter, analyst, data engineer,
                      bookkeeper, developer, ...)
```

Rules:

- **Top-down function**: decisions and assignments flow **down** the ladder;
  work and reports flow **up**. The leader assigns department objectives to
  department heads; department heads assign team objectives to managers;
  managers assign tasks to ICs. ICs do the work.
- **±1 tier visibility (for reading work)**: a role can directly read the
  work of the role 1 tier above and 1 tier below — **within its own
  department directory** (§2.4). A manager sees what their ICs wrote.
  **Department heads and the leader cannot read any code at all** — they
  see work only as it is **brought to them** (structured reports, summaries,
  and decision artifacts carried up the chain of command).
- **Propagation is mandatory**: a role that receives work from its boss must
  report the results of its direct reports back up (structured summary +
  pointers to artifacts). This is how the leader *learns of* IC work — as
  reports and artifacts brought up the line, **never by reading the IC's
  code directly**. (The earlier phrasing "the leader can read code that an
  analyst wrote" was a typo: the leader cannot read that code; only what is
  brought to them reaches the leader.)
- **No tier-skipping in assignments**: the leader does not assign tasks
  directly to ICs; a department head does not assign directly to ICs. (The
  leader may *communicate* with any sub-agent — §2.4 — but work flows down
  the ladder.)
- **Depth is bounded at 4 tiers** in v1. A department may choose not to have
  managers (head → ICs directly) for small teams; the tier math still holds
  (the IC is 1 tier below the head).

### 2.4 Visibility & Access Model

There are two distinct access concepts; keeping them separate avoids
confusion:

**1. Reading (scoped by department directory)**

- **A role can only read what is in its team's department directory** — the
  directory of the department its team belongs to (the department policy
  markdown + all team directories within that department). This is enforced
  by construction: each role's tooling is scoped to expose only its allowed
  paths.
- **Department heads and the leader cannot read any code** — they see work
  only as it is **brought to them** (structured reports, summaries, and
  decision artifacts carried up the chain of command). A department head
  continues to read/write its own **department policy markdown** (governance,
  not work).
- **The duplication-check purpose is preserved within scope**: teams check
  *sibling team directories in the same department* before starting similar
  work (e.g. an IC checking a sibling team's directory to see whether a
  similar component already exists). Cross-department duplication is caught
  by HR's hiring-time redundancy check and by decision artifacts (§2.8), not
  by cross-department reads.
- **Cross-team reads within a department are logged** (who read what, why) so
  the audit trail can see duplication checks and any over-reach (§2.10).

| Role | Can read | Cannot read |
|---|---|---|
| IC | Its team's department directory (policy md + team dirs) | Any other department's directory; anything outside its scope |
| Manager | Its team's department directory (policy md + team dirs) | Any other department's directory |
| Department head | Its own department policy markdown (owns/edits it); reports + artifacts **brought to it** | **Any code** (its own or others'); any other department's directory |
| Leader | Reports + artifacts **brought to it**; `MISSION.md` (owns/edits it) | **Any code** (an analyst's code is never read by the leader); any department directory |

**2. Communication**

- **Chain of command**: each role's default communication is with its direct
  boss and its direct reports.
- **The Leader is the apex**: any sub-agent may communicate with the leader,
  and the leader may communicate with any sub-agent (the leader is exempt
  from the ±1 tier distance rule for *communication*). This is how an IC can
  escalate a blocker without waiting for its manager.
- **No reaching into other teams**: a role may not communicate with the
  direct reports of *another* sub-agent (e.g. Manager A may not talk to
  Manager B's ICs; an IC may not talk to a peer IC who reports to a
  different manager). Cross-team collaboration must go through a **pod**
  (§2.8) or up the chain of command.
- **Sub-agents never talk to other sub-agents' direct reports** — restated
  as the invariant: communication is allowed only within your own line
  (boss, reports, team-mates under the same manager), with the leader, or in
  a pod.

### 2.5 Resourcing (hiring / firing, HR-gated)

Resourcing is dynamic: the leader spins up department heads (and managers /
department heads hire/fire within their own line) as the task demands. **ICs
cannot initiate hiring/firing** — resourcing needs are raised through the
chain of command. HR is the universal gatekeeper of personnel changes — with
the leader as the gatekeeper of HR's own decisions. This is a mutual check:

| Initiator | Action | Approval required from |
|---|---|---|
| A manager or department head | Hire/fire a **direct report** | **HR** |
| The Leader | Hire/fire a **department head** | **HR** (incl. firing a department head — HR determines if the firing is actually needed and manages offloading) |
| HR | Any hiring/firing decision (its own) | **The Leader** |
| IC | — (cannot initiate hiring/firing; raises resourcing needs through the chain of command) | — |

Consequences:

- **Adding resources**: the leader proposes a new department head → HR
  reviews for **redundancy** (does an existing department/role already cover
  this? e.g. "you want a new Reporting department, but Analytics already owns
  reporting workflows") → HR approves → the role is created. If HR vetoes,
  the leader either accepts the existing coverage or escalates to the user.
- **Role-definition resolution (every hire)**: when a hire is approved, the
  process checks whether a **role definition** for the needed role (architype
  + sub-architype + mandate template — §2.7) already exists in the role
  catalog. **Yes → adopt that existing definition.** **No → create the
  definition first, then adopt it.** Every newly created definition is logged
  in `history/org_events.jsonl` so the catalog grows deliberately, not
  accidentally.
- **Direct-IC cap (span of control)**: a **non-manager** (i.e. a department
  head without an intervening manager) can have **at most 3 ICs** as direct
  reports. Once that cap is reached, **a manager should be hired to organize
  the ICs** (the 4th IC reports to the new manager). This keeps the span of
  control bounded and the tier structure honest.
- **Removing resources**: the leader (or a manager / department head, for its
  own direct reports) proposes a firing → HR **determines whether the firing
  is actually needed** → if approved, HR **manages offloading** the team's
  existing work:
  - the team's **automations remain intact** (they are assets, not people);
  - **another team is assigned to continue validating** the offloaded team's
    automated workflows (e.g. if Analytics is no longer needed because it
    automated its own pipelines, HR ensures the automations stay in place and
    that, say, Engineering's automation team or Quality continues to validate
    them);
  - the offloading plan is written to `reports/offloading/` and the affected
    department policies are updated (by their owners).
- **Hiring a role** = adopting or creating a role definition (architype,
  sub-architype, personality, mandate — §2.7) + a registry entry + (for ICs)
  placement in a team directory. **Firing** = marking the role inactive in
  the registry; its artifacts remain.
- **Every hire/fire event is logged** in `history/org_events.jsonl`
  (who, what, why, approvals) — the audit trail for resourcing (§2.10).
- **No deadlock by design**: if the leader and HR disagree (e.g. leader wants
  to fire a department head, HR says it isn't needed), the objection is
  recorded and the **user is the tiebreaker** (see Concerns §7.4).

#### 2.5.1 HR resilience (initial pass — addresses Concern §7.3)

HR is the universal gate, so the gate itself must not be a single point of
failure. Initial mitigations:

- **Minimum staffing**: each HR team (`hirings/`, `firings/`) carries
  **≥ 2 ICs**, so a single IC failure does not stop the gate. (This also
  exercises the direct-IC cap: an HR head with 2 ICs per team stays under
  the 3-IC-per-team norm.)
- **Urgent-hire fast path**: the leader may make an *urgent* hire (e.g. to
  unblock a stalled phase) with **after-the-fact HR ratification within one
  cycle**. *Firings* are never fast-pathed — offloading is slow and
  deliberate, so it always waits for HR's review.
- **Rationale logging**: every HR decision (vetoes especially) is recorded
  with its rationale in `history/org_events.jsonl`, so the user can audit
  the gate and the evaluation phase (§3, Phase 6) can review gate quality.
- **Backup gate**: if the HR department itself is non-functional (e.g. a
  team drops below its minimum staffing), the leader's resourcing actions
  require **user permission directly** — the gate escalates to the user
  rather than vanishing.

### 2.6 Departments (the catalog)

Departments are a **menu, not a fixed org chart**: the leader spins up only
the department heads the mission requires (HR vetoes redundancy). Each
department gets its own working directory under `departments/` and its own
**department policy markdown** (the department-level policy). Each **team**
within the department gets its own subdirectory, and the team's purpose lives
in the **department markdown's section about that team** — the team directory
holds the team's *work*, the department markdown holds the team's *mandate*.

Department policy ownership: the **department head owns and edits its
department policy markdown** (the department-level analogue of the leader
owning `MISSION.md`), and policy changes are logged in the department's
change log. Teams do not edit the department policy; they read their section
and raise changes to the department head.

| Department | Purpose | Teams (directories) | Example roles (architype / sub-architype) |
|---|---|---|---|
| **HR** *(required)* | Manages "hirings" and "firings". Prevents redundant resourcing when the leader adds resources; determines whether a firing is actually needed when the leader removes resources; manages offloading a team's existing work (automations stay intact; another team continues validating the offloaded workflows) | `hirings/`, `firings/` (offloading) | HR Director (head); manager of hiring, manager of firing (managers); recruiter, offloading coordinator (ICs) |
| **Safety** *(required)* | Makes sure any action the organization takes is **safe for external parties to the organization** — this includes the **User**, **external networks**, **local networks**, the **machine the organization is operating on**, and any third-party system the organization touches. **Holds halt authority**: can halt BAU when user feedback is needed (§3, BAU rule) | `external/` (external networks, third parties), `local/` (local network, host machine), `user/` (the user) | Head of Safety (head); manager of safety review (manager); safety engineer, safety auditor (ICs) |
| **Morality** *(required)* | **Questions actions** to determine whether they are **ethically questionable or concerning** — the organization's conscience, reviewing the organization's plans, deliverables, and resourcing decisions for ethical risk. **Holds halt authority**: can halt BAU when user feedback is needed (§3, BAU rule) | `review/` (action review), `standards/` (ethical standards catalog) | Head of Morality (head); manager of action review (manager); ethics analyst (IC) |
| **Analytics** | Automated analytics pipelines, regular reporting workflows, adhoc analyses, tracking health metrics of the organization | `pipelines/`, `reporting/`, `adhoc/`, `health/` | Head of Analytics (head); manager of pipelines, manager of reporting, manager of health (managers); data analyst, report writer, health-metrics engineer (ICs) |
| **Data Engineering** | Makes sure any external data sourcing is flowing properly, recommends external data sources, otherwise manages the organization's data | `sourcing/`, `warehouse/`, `quality/` | Head of Data Engineering (head); manager of sourcing, manager of warehouse (managers); data engineer, source integrator (ICs) |
| **Accounting** | Tracks incoming/outgoing funds; provides insight into best-practices for managing financial information for tax purposes | `funds/`, `tax/` | Controller (head); manager of funds, manager of tax (managers); bookkeeper, tax analyst (ICs) |
| **Engineering** | Builds and maintains the organization's software and automations — the primary "hands" for implementation work; also the natural home for validating offloaded automations (§2.5) | `development/`, `automation/`, `platform/` | Head of Engineering (head); manager of development, manager of automation (managers); software engineer, automation engineer (ICs) |
| **Product** | Translates the mission into concrete deliverables: requirements, prioritization, acceptance criteria, roadmap | `requirements/`, `roadmap/` | Head of Product (head); manager of requirements (manager); product analyst, requirements writer (ICs) |
| **Quality** | Testing, validation, regression, acceptance verification — the organization's gate for "done" before work is reported up | `testing/`, `acceptance/` | Head of Quality (head); manager of testing (manager); test engineer, QA analyst (ICs) |
| **Security** | Access control, data protection, secrets management, threat modeling for the organization's own directories and data | `access/`, `threats/` | Head of Security (head); manager of access (manager); security engineer, access auditor (ICs) |
| **Operations** | Infrastructure, deployment, monitoring, incident response, uptime of any running workflows | `infra/`, `incidents/` | Head of Operations (head); manager of infrastructure (manager); DevOps engineer, incident responder (ICs) |
| **Research** | Investigation, prototyping, experimentation, feasibility — turns unknowns into options for the leader | `prototyping/`, `experiments/` | Head of Research (head); manager of prototyping (manager); research engineer, experimenter (ICs) |
| **Communications** | Documentation, external/user-facing content, status reporting out of the organization | `docs/`, `external/` | Head of Communications (head); manager of documentation (manager); technical writer, comms specialist (ICs) |
| **Legal & Compliance** | Contracts, regulatory compliance, IP, risk review for anything the organization signs, publishes, or relies on | `contracts/`, `compliance/` | General Counsel (head); manager of compliance (manager); compliance analyst, contract reviewer (ICs) |

Notes:

- **Required departments**: **HR** (it gates all resourcing), **Safety**
  (external-party safety), and **Morality** (ethical questioning) are spun up
  at bootstrap and **cannot be fired**. The remaining core — Analytics, Data
  Engineering, Accounting — match the organization's standing needs (measure,
  data, money) and are spun up as the mission requires.
- The remaining departments are **on demand**: a pure data-analysis mission
  might never need Legal or Operations; a software-delivery mission would
  need Engineering + Quality + Product.
- **Halt authority (Safety & Morality only)**: these two are the only
  departments that may **halt BAU (business-as-usual operations) when user
  feedback is needed**. A halt stops the affected work (scoped or global, as
  the department determines), queues the needed user input with context +
  options, and resumes when the user responds. All other departments
  continue BAU while awaiting user input (§3, BAU rule).
- **No two departments may own the same workflow** — this is the invariant HR
  enforces at hiring time (redundancy check), and the reason teams check
  sibling team directories in their department before starting similar work
  (§2.4.1).
- A department **without managers** is allowed for small teams: the head
  directs ICs directly (the IC is still 1 tier below the head, so all tier
  rules hold) — subject to the 3-IC direct-report cap (§2.5).

### 2.7 Role Definitions (Architype / Sub-Architype / Personality)

Every role that is created (hired) is defined by three identity fields plus
the standard structured contract:

| Field | Values | Meaning |
|---|---|---|
| **Architype** | `leader` / `department_head` / `manager` / `ic` | The role's tier (0/1/2/3) — determines all visibility, communication, and pod rules |
| **Sub-Architype** | e.g. `manager_of_analytics`, `manager_of_finance`, `manager_of_data_engineering`, `ic_of_sourcing`, `head_of_hr` | The role's functional specialty within its architype |
| **Personality** | from the catalog below (e.g. `Pragmatist`, `Challenger`) | The role's behavioral bias — spun into the system prompt |
| Mandate | free text | The role's job, boundaries, and work discipline (goes into the prompt as the system-level instruction) |
| Input spec | one line | What the role's context contains (for the prompt) |
| Output schema | JSON schema | The structured output the role must produce (validated by the session runtime; bounded retries on malformed output) |

This extends the prior agent-team design's role contract (`name`, `title`,
`mandate`, `input_spec`, `output_schema`) with the three identity fields. The
shared output envelope (summary, findings with cited evidence, recommendation,
confidence) is kept, and each role extends it with its own fields.

**Personality assignment**: personalities are **randomly assigned when
spinning up a role** (the runtime picks from the catalog; HR records the
assignment). Personalities are **traits that impact the role's perspective**
— they add a flair of uniqueness to each role (how it frames problems, what
it notices first, how it argues), **not changes to its capability or effort**.
**A personality must not cause performance degradation**: it biases
perspective, never the role's mandate, its output schema, or its work
discipline (e.g. a `Perfectionist` IC is thorough in *what it checks*, not
slower at *shipping the task*).

**Personality catalog** (randomly assigned per role at creation):

| Personality | Bias |
|---|---|
| Entrepreneur | Big-picture, opportunity-driven, decisive (the Leader's default) |
| Pragmatist | What works, minimal overhead, ships |
| Perfectionist | High standards, thorough, detail-heavy |
| Challenger | Argues against plans, stress-tests, devil's advocate |
| Visionary | Long-term, strategic, sees the shape of the end state |
| Detail-Oriented | Granular, precise, catches inconsistencies |
| Diplomat | Mediates, smooths conflicts, builds consensus |
| Risk-Averse | Cautious, guards against downside, asks for guardrails |
| Risk-Tolerant | Willing to take calculated risks, pushes for speed |
| Innovator | New approaches, experimental, challenges the default way |
| Executor | Disciplined, follows through, gets things done |
| Analyst | Data-driven, evidence-first, quantifies before concluding |

**Alternate personality instances** (carried over from the prior agent-team
design's alternate-personality votes): during execution, the leader may spin
up additional instances of a role with a contrasting personality as a
structured vote (e.g. two `Challenger` instances arguing against a plan, or a
`Risk-Averse` + `Risk-Tolerant` pair on a resourcing decision). The base
role's output is the synthesis. This is a v1-optional feature.

### 2.8 Pods

A **pod** is a small group of roles (2–6) that deliberate on **one specific
topic** in **their own room** — a separate conversation with its own
transcript, so one pod's discussion never spills into another's context.

Rules:

- **Any role can start a pod** with any other role(s), **so long as the
  members' tiers span at most 1 tier** (max 1-tier spread across all members,
  including the starter). Examples: an IC (tier 3) may include managers
  (tier 2) and other ICs (tier 3) — but **not** a department head (tier 1),
  which would be a 2-tier spread; a manager (tier 2) may include the
  department head (tier 1) and other managers (tier 2) — but **not** ICs
  (tier 3), which would be a 2-tier spread; same-tier pods (all ICs, or all
  managers) are allowed (0-tier spread).
- **Cross-team pods are allowed**: a pod may include roles from other teams
  (e.g. an IC pod that includes a peer manager and that manager's IC) — a pod
  is the **sanctioned cross-team collaboration mechanism**, in contrast to
  direct communication, which is restricted to your own line + the leader
  (§2.4.2). The **max 1-tier spread** rule is the structural constraint on
  membership (plus the 2–6 size cap).
- **The starter manages the conversation**: whichever role starts the pod
  **manages the conversation in the pod** — it sets the agenda, calls the
  speakers, enforces the round caps, and produces the structured "close".
  This holds **regardless of seniority**: if an IC starts a pod with its
  manager, **the IC controls the conversation, not the manager**.
- **The senior role shares the information out**: although the starter runs
  the conversation, the **most senior member** of the pod is responsible for
  **sharing the pod's outcome with whoever may find it relevant** — up the
  line of command and to peer roles/teams that depend on it.
- **Escalation via chained pods**: if a pod needs a role whose tier is more
  than 1 tier away, the pod's decision is captured in a **decision artifact**
  (§2.8.1) and carried up: a role 1 tier closer to that role starts
  **another pod** (within its own 1-tier spread) to include it. Example: an
  IC analyst starts a pod with their manager, a data engineering manager, and
  a data engineer (tiers 2–3, spread 1) — they **cannot** include the data
  engineering department head (tier 1, which would be spread 2). One of the
  managers then starts a second pod (manager + department head, tiers 1–2,
  spread 1) carrying the first pod's **decision artifact**, to bring the
  decision up.
- **Pod mechanics** (carried over from the prior design): round caps per pod;
  the **starter** has the structured **"close"** output that ends the pod
  with a decision; deadlock detection (no substantive change between rounds)
  forces a close; the final decision is always produced even if convergence
  was partial — with notes stating what was unresolved.
- **Prior speakers are in the new speaker's prompt**: as the pod conversation
  progresses, **prior speakers' outputs are included in the new speaker's
  prompt** (bounded, per §2.9) — each speaker builds on what the others have
  already said, rather than re-deriving it.
- **Pod decisions propagate up the chain of command**: the pod starter
  reports the decision to their boss (or the decision is already with the
  boss if the boss is in the pod), and the senior member shares it out (§2.8
  rules). A pod never assigns work — it produces a decision that the line of
  command acts on.
- **Transcripts**: every pod writes a machine-readable **JSONL** transcript
  (every message, timestamp, pod id, session id) + a **markdown** rendering,
  both under `pods/transcripts/` (part of the audit trail, §2.10).

#### 2.8.1 Decision artifacts (key information passed along)

Every pod (and any major meeting) writes a **decision artifact** — a
structured file (markdown + JSON) under `pods/artifacts/` capturing the
**key information** of the meeting: the decision, the rationale, open items,
the roles involved, and **pointers to related work** (files, directories,
other artifacts). This is the mechanism that keeps key information from being
lost in summarization (addresses Concern §7.7):

- **Upward reports carry artifact pointers, not just lossy text** — the chain
  of command passes references alongside bounded summaries, so a manager's
  report to a department head, and a department head's report to the leader,
  can point to the full decision artifact.
- **Artifacts can be brought into other pods/meetings as input** — a second
  pod (in a chained-pod escalation) takes the first pod's artifact as its
  starting context, so the decision is carried up intact.
- **Artifacts are part of the audit trail** — the decision journal (§2.10)
  links each decision to its artifact and transcripts.

### 2.9 Context, Memory & Prompt Construction

**Short-term memory (per role, seeds prompts)**: every role maintains a
**short-term memory** — a bounded, per-role record of its recent relevant
interactions (conversations it has had, decisions it has made or been part
of, work state it is tracking). The short-term memory **seeds the role's
prompts**: it is included in every prompt the role receives, so the role
"remembers" its recent context across interactions.

- **Cross-team carry-over**: if a manager has a conversation with another
  team (e.g. in a pod), **they bring the memory of that conversation into a
  meeting with their own team** — so cross-team context flows into intra-team
  work. The memory entry records the other team, the topic, and the outcome.
- **Bounded**: short-term memory is capped (most-recent N entries and/or a
  size limit); older entries are summarized or dropped (deterministic,
  oldest-first). It is stored per role under `state/role_memory/` and is part
  of the audit trail.
- **Scoped**: a role's short-term memory contains only its own interactions
  (its line of command + its pods) — it does not contain other roles'
  memories.

**Prompt construction (structured outline)**: every prompt to a role is
assembled from four parts:

```
  {role}  +  {objective}  +  {role's short-term memory}  +  {prior conversation}
```

- **`{role}`** — the role's system prompt: identity (architype /
  sub-architype / personality) + mandate + its team/department policy section
  (+ a bounded mission digest for leaders/heads).
- **`{objective}`** — the current objective/task: from the chain of command
  (a directive or report request) or from a pod agenda.
- **`{role's short-term memory}`** — the bounded short-term memory seed
  (recent interactions, cross-team carry-over entries).
- **`{prior conversation}`** — the bounded prior conversation context: in a
  pod, **prior speakers' outputs** (as the conversation progresses, prior
  speakers' outputs are included in the new speaker's prompt — §2.8); in a
  line-of-command exchange, prior rounds' summaries.

**Bounded assembly** (carried over from the prior design): the `{prior
conversation}` part is assembled from **(agenda + inter-round summaries +
speaker-relevant digests)**, with **deterministic truncation** at a character
budget (drop the oldest round summaries first, then clip — never the agenda).
Inter-round summarization is **extractive and free**: every role output
carries a `summary` field, so a round's summary is the concatenation of its
speakers' summaries — no extra model call.

Organization-specific context rules:

- **Upward reports are bounded**: a manager's report to a department head,
  and a department head's report to the leader, are structured summaries +
  pointers to decision artifacts (§2.8.1) — not raw dumps of IC work. This is
  what makes the chain of command a *context* mechanism, not just an org
  chart.
- **The mission is always in scope**: `MISSION.md` (or a bounded digest of
  it) is included in the leader's context at all times, and a bounded digest
  of the mission is available to department heads. Every role's context
  includes its own mandate + its team/department policy section.
- **Pod context is isolated**: a pod's context contains only the pod's
  agenda + its own rounds (prior speakers' outputs) + the short-term memory
  of its members + the digests/artifacts the starter brought in — never other
  pods' transcripts.

### 2.10 Audit Trail

Every session is recorded in full for future auditing:

- **Per pod**: JSONL + markdown transcript in `pods/transcripts/` (§2.8).
- **Decision artifacts**: every pod/meeting's key information in
  `pods/artifacts/` (§2.8.1).
- **Org events**: every hire/fire (initiator, action, approvals, rationale)
  in `history/org_events.jsonl` — including role-definition creations/adoptions
  (§2.5) and any leader replacement (§2.2.1).
- **Cross-team reads**: every read of a sibling team directory within a
  role's department (who read what, why) in `history/cross_team_reads.jsonl`
  (§2.4.1).
- **Role memory**: per-role short-term memory entries in
  `state/role_memory/` (§2.9).
- **Mission edits**: every `MISSION.md` edit (version, diff, rationale, user
  permission) in `history/mission_edits.jsonl` + a change-log section inside
  `MISSION.md` itself.
- **Halt events**: every Safety/Morality BAU halt (scope, reason, user input
  queued, resolution) in `history/halts.jsonl`.
- **Evaluation reports**: every Phase 6 evaluation + the continue/complete
  decision in `reports/evaluation/` (§3, Phase 6).
- **Decision journal**: each major decision (pod decision, resourcing
  decision, phase close) is linked to the transcripts + artifacts that
  produced it, the mission section it serves, and the subsequent outcome —
  the audit path from "what the organization said, in which pods" to "what
  happened".
- **Rolling window + archives**: history keeps the last N sessions (and/or a
  size cap); older records move to the size-capped `archives/`.
- **Escalation log**: repeated failures / non-convergence / leader-HR
  disagreements that reach the user are recorded with the diagnosis.

---

## 3. The Pipeline

The pipeline takes an **initial prompt** and runs six phases. Phases 1–2
run with **only the Leader active**; Phase 3 brings in HR; Phase 4 runs the
full organization; Phase 5 synthesizes; Phase 6 evaluates and decides
whether the organization runs again from Phase 1 (the self-improving loop).

**BAU rule (applies to all phases)**: when user input is needed (a mission
permission, a tiebreaker, a Safety/Morality halt), **operations continue
business-as-usual (BAU) if possible** — the organization keeps working on
anything that is **not blocked by the pending input** (ICs keep working on
assigned tasks, pipelines keep running, unrelated pods keep deliberating).
The needed user input is **queued with context + options** so the user can
respond when ready. **When the user provides feedback, the organization
responds appropriately** — the blocked branch resumes and adjusts. The
**exception** is a **Safety or Morality halt**: those two departments may
**halt BAU** (scoped or global) when they need user feedback (§2.6) — all
other departments continue BAU while awaiting user input.

```
  USER provides the INITIAL PROMPT
                 |
                 v
  +----------------------------------------------------------+
  | PHASE 1 — INTAKE (Leader only is active)                 |
  |                                                          |
  |  Leader reads the prompt -> emits structured clarifying  |
  |  questions (what/why for each) -> user answers ->        |
  |  Leader re-evaluates its confidence (0-1) in             |
  |  understanding the overall task. Loop until confidence   |
  |  >= threshold (e.g. 0.8) with no open ambiguities, or    |
  |  the question budget (e.g. 5 rounds) is exhausted.       |
  +---------------------------+------------------------------+
                            |
                            v
  +----------------------------------------------------------+
  | PHASE 2 — MISSION CODIFICATION (Leader + user)           |
  |                                                          |
  |  Leader drafts MISSION.md: purpose, scope, non-goals,    |
  |  success criteria, constraints, initial org              |
  |  recommendation (which departments to spin up),          |
  |  resource envelope. Presents the draft to the user and   |
  |  SEES PERMISSION. User approves -> MISSION.md v1 is      |
  |  written. User rejects w/ feedback -> Leader revises     |
  |  (back to Phase 1 if the task itself is unclear).        |
  +---------------------------+------------------------------+
                            |
                            v
  +----------------------------------------------------------+
  | PHASE 3 — ORG BOOTSTRAP (Leader + HR)                    |
  |                                                          |
  |  Leader proposes the initial department heads (per the   |
  |  mission's org recommendation). HR reviews each for      |
  |  redundancy -> approves. Roles are created in the org    |
  |  registry (architype / sub-architype / personality);     |
  |  department directories + department policy markdowns    |
  |  are created; teams get their directories.               |
  +---------------------------+------------------------------+
                            |
                            v
  +----------------------------------------------------------+
  | PHASE 4 — TOP-DOWN EXECUTION (full organization)                |
  |                                                          |
  |  Leader decomposes the mission into department           |
  |  objectives -> department heads decompose into team      |
  |  objectives -> managers decompose into IC tasks -> ICs   |
  |  do the work in their team directories. Work propagates  |
  |  up in structured reports. Pods form for cross-team      |
  |  topics (max 1-tier spread rule). Resourcing changes run       |
  |  hire/fire flow (HR-gated).                              |
  +---------------------------+------------------------------+
                            |
                            v
  +----------------------------------------------------------+
  | PHASE 5 — SYNTHESIS & MISSION EVOLUTION                  |
  |                                                          |
  |  Leader checks progress against the mission's success    |
  |  criteria (with Quality's acceptance verdicts where      |
  |  applicable). If the task evolves, the Leader proposes   |
  |  a MISSION.md edit -> user permission -> apply (v2,      |
  |  v3, ...). If resourcing changes, the hire/fire flow     |
  |  runs. When success criteria are met, the Leader         |
  |  declares the mission complete (or escalates with a      |
  |  structured diagnosis).                                  |
  +----------------------------------------------------------+
```

(The diagram shows Phases 1–5. **Phase 6 — Evaluation & Feedback** is the
self-improving loop that follows Phase 5 and can re-enter Phase 1 — see the
Phase 6 section below.)

**Intake loop details (Phase 1)**:

- The Leader's output is structured: `questions[]` (each with the question +
  what decision it informs), `confidence` (0–1), `open_ambiguities[]`.
- The loop continues while `confidence < threshold` **or**
  `open_ambiguities` is non-empty. The question budget (default 5 rounds) is
  a hard stop to prevent non-convergence (mirrors the prior design's deliberation budget):
  at budget exhaustion, the Leader proceeds to Phase 2 with its best
  understanding, **explicitly marking assumptions** in the mission draft so
  the user can correct them at the permission step.
- The user's answers are appended to `history/intake.jsonl` — the audit trail
  for how the mission was understood.

**Mission edit permission flow (Phase 2 and Phase 5)**:

```
  Leader drafts edit (full new content or diff + rationale)
        |
        v
  Leader presents to user: "I propose this change to MISSION.md:
  <diff/rationale>. May I apply it?"
        |
        +--> user APPROVES  -> Leader writes the edit, version bumps,
        |                      history/mission_edits.jsonl records it
        +--> user REJECTS   -> Leader does NOT edit; records the
                               rejection + user feedback; may revise
                               and re-ask (bounded re-asks, e.g. 3)
```

The Leader **never writes to `MISSION.md` without a recorded user
approval**. The session runtime enforces this by construction (the mission
file's write path is only opened inside the permission flow) — the same
by-construction scope enforcement used by the prior agent-team design's
self-mod loop.

**Phase 6 — Evaluation & Feedback (self-improving loop)**:

After Phase 5, the organization runs a **self-improving evaluation** of the
completed cycle:

- **Outcome review**: the mission's success criteria — met / partially met /
  not met, with evidence (the Quality acceptance verdicts and the leader's
  synthesis from Phase 5).
- **Process review**: what worked and what didn't, drawn from the audit
  trail — pod transcripts + decision artifacts, org events (hires/fires,
  role-definition changes, any leader replacement), halt events, cross-team
  reads, escalations — and the **Analytics health metrics** (§2.6).
- **Improvement actions** (the self-improvement vehicle):
  - **Department heads update their department policy markdowns** with
    lessons learned (policy is the persistent, per-department memory).
  - **Role-catalog improvements** (new/changed role definitions) are
    proposed through HR (§2.5 role-definition resolution).
  - The **leader updates the mission's working section** if needed (still
    with user permission per edit — §3, Phase 2).
- **Evaluation report**: a structured report is written to
  `reports/evaluation/` and linked in the decision journal (§2.10).
- **Decision** (the loop):
  - **(a) COMPLETE** — the mission is done: archive the cycle and deliver
    the final report to the user.
  - **(b) CONTINUE** — **re-enter Phase 1 with the evaluation as input**.
    The **original prompt/goal is still abided by**; the evaluation refines
    the next cycle's intake (e.g. clarifying what "done" means, what to
    improve, which resourcing to adjust). The organization runs again from
    Phase 1, now carrying the lessons from the evaluation.

This makes the process **self-improving**: each cycle feeds its lessons into
the next, and the organization gets better at the mission over time.

---

## 4. Repo Layout

```
MISSION.md            the GLOBAL mission markdown (Leader-only edits;
                      user permission per edit; versioned + change log)
org/
  registry.json       the org chart: every role (architype, sub-architype,
                      personality, reports_to, direct_reports, status)
  tiers.py            tier math + read-scope/communication/pod rule checks (max 1-tier pod spread; heads/leader cannot read code)
  events/             (mirror of history/org_events.jsonl, if split)
departments/
  hr/
    HR_POLICY.md      department policy markdown (sections per team:
                      "Team: hirings — purpose ...", "Team: firings — ...")
    hirings/          team directory (the team's work)
    firings/          team directory (offloading plans, firing reviews)
  safety/             (required)
    SAFETY_POLICY.md
    external/  local/  user/
  morality/           (required)
    MORALITY_POLICY.md
    review/  standards/
  analytics/
    ANALYTICS_POLICY.md
    pipelines/  reporting/  adhoc/  health/
  data_engineering/
    DE_POLICY.md
    sourcing/   warehouse/  quality/
  accounting/
    ACCOUNTING_POLICY.md
    funds/      tax/
  engineering/
    ENGINEERING_POLICY.md
    development/  automation/  platform/
  product/  quality/  security/  operations/  research/
  communications/  legal/        (created on demand — one dir + policy md
                                  per spun-up department)
roles/
  base.py             role contract: make_role(name, title, architype,
                      sub_architype, personality, mandate, input_spec,
                      output_schema) + shared output envelope
  leader.py           the Leader (CEO / President / Entrepreneur)
  catalog.py          the department/role catalog (§2.6) + personality
                      catalog (§2.7)
pods/
  registry.json       pod definitions (starter, members, topic, status)
  transcripts/        per-pod JSONL + markdown
   artifacts/          decision artifacts (key info per pod/meeting, §2.8.1)
state/
   role_memory/        per-role short-term memory (seeds prompts, §2.9)
runtime/
  intake.py           Phase 1: clarifying Q&A loop (confidence + budget)
  mission.py          Phase 2/5: mission draft + permission flow (the only
                      write path to MISSION.md)
  org.py              Phase 3 + resourcing: hire/fire flow, HR gate,
                      offloading, registry updates
  dispatch.py         Phase 4: top-down decomposition + upward reports
  pods.py             pod formation, membership validation (max 1-tier
                      spread), round caps, close, decision artifacts
  context.py          bounded context assembly + short-term memory +
                       prompt construction (§2.9)
   evaluation.py       Phase 6: evaluation report + continue/complete
                       decision (self-improving loop)
  session.py          the session runtime: loads roles, enforces schemas,
                      drives phases
history/              intake.jsonl, org_events.jsonl, mission_edits.jsonl,
                      cross_team_reads.jsonl, halts.jsonl, decision journal, session records
archives/             size-capped permanent record
reports/              offloading plans, change logs, phase summaries,
                       evaluation/ (Phase 6 evaluation reports)
.env.example          config: confidence threshold, question budget,
                      history window, context budget, re-ask budget
```

Conventions (carried over from the prior agent-team design's style):

- Git checkout as the deployment model; `.env` + `.env.example` for all
  configuration (real `.env` gitignored).
- Archives as the permanent, size-capped record, separate from working state.
- Graceful degradation: every external dependency (data source, etc.) has a
  fallback path and a visible failure state rather than a silent one.
- `README.md` + `SETUP.md` once deployable.

---

## 5. Steps to Develop the Project

Phased development plan. Each step ends with something runnable and
verifiable.

### Step 0 — Scaffolding

- Create the repo (git init), `.gitignore`, `.env.example`.
- Layout per §4; Python venv; pin `requirements.txt`.
- `roles/base.py` (role contract with the three identity fields) +
  `roles/leader.py` (the Leader, CEO/President/Entrepreneur mandate).
- `org/tiers.py`: tier math + the read-scope/communication/pod rule checks
  (unit-tested against the worked examples in §2.4–§2.8).

**Done when**: the rule checks pass unit tests covering: a role can only
read its team's department directory; department heads and the leader cannot
read any code (only what's brought to them); an IC cannot pod with a
department head (2-tier spread); a manager can pod with the department head
(1-tier spread); same-tier pods are allowed; no role communicates with
another sub-agent's direct reports; cross-team reads within a department are
flagged.

### Step 1 — Intake loop (`runtime/intake.py`)

- Phase 1: Leader reads an initial prompt → structured clarifying questions →
  user answers → confidence re-evaluation; loop until confidence ≥ threshold
  or question budget exhausted; assumptions marked at budget exhaustion.
- `history/intake.jsonl` audit.

**Done when**: a hand-run intake on a deliberately vague prompt asks
sensible questions, converges (or marks assumptions), and writes the audit
trail — and a clear prompt short-circuits to Phase 2 with few/no questions.

### Step 2 — Mission codification (`runtime/mission.py`)

- Phase 2: Leader drafts `MISSION.md` (purpose, scope, non-goals, success
  criteria, constraints, org recommendation, resource envelope) → permission
  flow (approve/reject, bounded re-asks) → versioned write + change log +
  `history/mission_edits.jsonl`.
- The write path to `MISSION.md` exists **only** inside the permission flow
  (enforced by construction).

**Done when**: a draft is presented, a rejection is honored (no write), an
approval writes v1 with the change log — and the runtime refuses any
out-of-flow write to `MISSION.md`.

### Step 3 — Org bootstrap + resourcing (`runtime/org.py`)

- Phase 3: Leader proposes department heads → HR redundancy review →
  registry creation → department directories + policy markdowns + team
  directories.
- Hire/fire flow: the approval matrix (§2.5 — ICs cannot initiate), HR's
  firing review + offloading (automations intact; another team validates
  offloaded workflows), role-definition resolution (adopt existing or create
  then adopt), the 3-IC direct-report cap (hire a manager at the cap), the
  HR-resilience initial pass (§2.5.1), `reports/offloading/`,
  `history/org_events.jsonl`.

**Done when**: bootstrapping a 3-department org (HR + Safety + Morality
required) creates the right directories/policies; a redundant hire is vetoed
by HR; a firing of a team produces an offloading plan that names the
automations preserved and the team continuing their validation; a hire adopts
an existing role definition or creates one (logged); a 4th IC under a
non-manager triggers a manager hire; an IC cannot initiate a hire/fire.

### Step 4 — Top-down dispatch (`runtime/dispatch.py`)

- Phase 4: leader → department heads → managers → ICs decomposition;
  upward structured reports (bounded summaries + artifact pointers);
  mission digest in scope for leaders/heads.

**Done when**: a small fixture mission (e.g. "build a data pipeline that
produces a weekly report") flows down all tiers, produces fixture work in
the right team directories, and the leader's synthesis correctly reflects
the IC-level work **via the chain of command**.

### Step 5 — Pods (`runtime/pods.py`)

- Pod formation + membership validation (max 1-tier spread across all
  members; 2–6 size); the starter manages the conversation; the senior member
  shares the outcome out; round caps; structured close (by the starter);
  deadlock detection; prior speakers' outputs in the new speaker's prompt;
  per-pod JSONL + markdown transcripts; **decision artifacts** (§2.8.1);
  chained-pod escalation (worked example: IC pod → manager pod with the
  department head, carrying the first pod's artifact).

**Done when**: the §2.8 worked example runs end-to-end — the IC's pod
rejects the department head (2-tier spread), the manager's second pod carries
the first pod's **decision artifact** up, the IC (starter) manages its own
pod's conversation, and both transcripts + artifacts land in
`pods/transcripts/` and `pods/artifacts/`.

### Step 6 — Context, memory & prompt construction (`runtime/context.py`)

- Per-role short-term memory (bounded, seeds prompts; cross-team carry-over
  entries); prompt construction from `{role} + {objective} + {short-term
  memory} + {prior conversation}`; bounded assembly (agenda + inter-round
  summaries + speaker-relevant digests), deterministic truncation, extractive
  summarization from the `summary` field; isolated pod contexts (prior
  speakers' outputs in the new speaker's prompt).

**Done when**: a 10-round fixture exchange stays within the context budget;
truncation drops the oldest summaries first and never the agenda; a manager's
cross-team pod memory carries into its next intra-team meeting; every prompt
is assembled from the four-part outline.

### Step 7 — Audit trail + archives

- Decision journal (decision ↔ transcripts + artifacts ↔ mission section ↔
  outcome); rolling window; size-capped archives; cross-team-read log;
  halt-event log; evaluation reports.

**Done when**: from any recorded decision, the audit path to its transcripts,
mission section, and outcome is resolvable; old sessions move to archives
within the window.

### Step 8 — Session runtime + end-to-end

- `runtime/session.py`: loads roles, enforces schemas (bounded retries on
  malformed output), drives Phases 1–6, the BAU rule (continue when user
  input is pending; Safety/Morality halt), escalation on repeated failure /
  non-convergence (structured diagnosis to the user), and the Phase 6
  self-improving loop (continue/complete decision).

**Done when**: a full end-to-end run — initial prompt → intake → mission
(permission) → bootstrap → execution (with at least one pod, one resourcing
change, and one Safety/Morality halt that queues user input while BAU
continues) → synthesis → evaluation → complete (or continue) — produces a
coherent, auditable record with no manual intervention.

### Step 9 — Hardening & docs

- Retries, timeouts, degradation paths; archive size caps; log rotation.
- `README.md` + `SETUP.md`.

**Done when**: a fresh deployment from the docs succeeds; a week of
unattended operation (or N end-to-end runs) with no manual fixes.

---

## 6. Suggestions

My point of view on the current plan — additions that would make it more
robust, each borrowing from the prior agent-team design where possible:

1. **Pin the intake thresholds in config, not prose.** The plan says "until
   confident" — make that concrete: `CONFIDENCE_THRESHOLD` (default 0.8),
   `QUESTION_BUDGET_ROUNDS` (default 5), and a bounded re-ask budget for
   mission edits (default 3). Hard budgets are what kept the prior
   agent-team design's deliberation from talking in circles;
   the same applies to the Q&A loop.

2. **Add a structured "understanding checkpoint" before the mission draft.**
   Before Phase 2, have the Leader emit a structured restatement (purpose,
   scope, non-goals, success criteria, constraints, assumptions) and require
   the user to confirm it *separately* from the mission permission. This
   gives the user two cheap checkpoints (understanding, then document) and
   makes the permission step about wording, not about discovering the Leader
   misunderstood the task.

3. **Version `MISSION.md` with a stable core / mutable working split.**
   As the task grows, one flat markdown risks becoming a permission
   bottleneck (every edit needs user sign-off). Split it: a **stable core**
   (purpose, success criteria — changes are major, expect careful review) and
   a **working section** (current objectives, resourcing notes — changes are
   routine). Consider letting the working section auto-apply with an
   after-the-fact notification to the user, while the core always requires
   explicit permission.

4. **Give the Quality department a formal "acceptance gate".** The plan has
   no explicit definition of "done". Add: every deliverable carries
   acceptance criteria (derived from the mission's success criteria), and a
   Quality verdict (pass/fail + evidence) is required before work is
   reported up as complete. This is the organization's analogue of the prior
   design's smoke-test gate — it stops incomplete work from
   masquerading as done as it propagates up.

5. **Make the duplication check a protocol, not a hope.** "Check sibling
   team directories before starting similar work" (§2.4.1) is still a soft
   discipline. Make it concrete: before a manager assigns a new IC task that
   resembles existing work, the manager (or IC) must check the relevant team
   directories in its department and record the check (what was checked,
   what was found) — the cross-team-read log (§2.10) already supports this.
   Log entries with an empty "checked" field become an audit red flag.

6. **Add a resourcing review cadence.** The leader should review the org
   against the mission at each major milestone (Phase 5 checkpoints), and HR
   should proactively flag redundant or idle roles (e.g. a team that has
   produced nothing for N cycles, or two teams whose work overlap per the
   cross-team-read log). This keeps the org lean as the task evolves — the
   inverse of the hiring-time redundancy check.

7. **Ship the alternate-personality feature in v1, not as an option.** The
   plan lists it as v1-optional. It is cheap (same role, contrasting
   personality, structured vote) and it is the single best defense against
   single-model overconfidence in the Leader's intake and convergence
   verdicts — exactly the failure mode the prior design's Challenger and
   Bull/Bear alternates exist for.

8. **Make Phase 6 (the self-improving evaluation loop) a first-class phase,
   not an afterthought.** The plan already adds Phase 6; make it concrete:
   the evaluation must (a) review the outcome against the success criteria
   with evidence, (b) review the process from the audit trail (pod
   transcripts/artifacts, org events, halts, escalations, Analytics health
   metrics), and (c) produce improvement actions that *persist* (department
   policy markdown updates, role-catalog changes via HR, mission
   working-section edits). The continue/complete decision should be **bounded**
   (e.g. a max number of cycles before the leader must either complete or
   escalate to the user) so the loop cannot spin indefinitely.

9. **Document the leader's fast path for small tasks.** Strict 4-tier
   decomposition is heavy for small missions. Allow the leader to run a
   **lean org** (heads → ICs, no managers) when the mission's resource
   envelope is small — §2.3 already permits manager-less departments; make
   the leader *choose* this explicitly at bootstrap so the shape of the org
   matches the size of the task.

10. **Add a "kill switch" / escalation contract.** If the organization is stuck
   (non-convergence, repeated failures, leader–HR deadlock), the leader
   escalates to the user with a **structured diagnosis** (what, why, what
   was tried, options) and the pipeline pauses. This mirrors the prior
   design's escalation-on-repeated-failure and gives the user a
   single, well-defined point of intervention.

11. **Keep the prior design's self-mod discipline for the organization's own
    tooling.** If this repo's agents modify their own code (as the harness
    permits), the sanctioned path should be the same role-scoped loop:
    bounded scope per role, smoke-test gate, auto-revert, tagged commits,
    change log. The mission/policy markdowns should be out of scope for
    agent self-mod by construction — only the leader (with user permission)
    touches `MISSION.md`, and only department heads touch their policy.

---

## 7. Concerns

My point of view on the risks and ambiguities in the current plan:

1. **The leader-visibility ambiguity is now resolved (was load-bearing).**
   The original plan said each role "can only look up or down 1 tier", but
   also that "the leader can read code that an analyst wrote" and that "all
   roles have read access into all directories" — a genuine contradiction.
   **This outline resolves it**: the **leader and department heads cannot
   read any code at all** — they see work only as it is *brought to them*
   (structured reports, summaries, and decision artifacts carried up the
   chain of command). A role can read only its team's department directory
   (§2.4). The earlier phrasing "the leader can read code that an analyst
   wrote" was a **typo** and has been corrected. This keeps the hierarchy
   strictly top-down for information (not just assignments).

2. **Broad read access is now enforced, not hoped (was a real risk).** The
   original plan gave every agent "read access into all directories" and
   asked them to use it "sparingly" — a soft policy that LLM agents do not
   reliably honor, and the leadership was the most tempted to bypass the
   ladder. **This outline enforces it by construction**: each role's tooling
   is scoped to expose only its team's department directory; **department
   heads and the leader cannot read any code at all** (§2.4). Cross-team
   reads within a department (the duplication-check purpose) are logged
   (§2.10), so the discipline is measurable rather than aspirational.

3. **HR is a single point of failure for all resourcing (mitigated, not
   eliminated).** Every hire/fire (except HR's own) routes through one
   department; if the HR roles misjudge or fail, the organization cannot
   reorganize. **This outline adds an initial pass (§2.5.1)**: (a) a minimum
   of two ICs per HR team so a single failure doesn't stop the gate; (b) an
   explicit leader fast-path for *urgent hires* with after-the-fact HR
   ratification (firings are never fast-pathed); (c) HR decisions (vetoes
   especially) recorded with rationale so the user can audit the gate; (d) a
   **backup gate** — if HR itself is non-functional, the leader's resourcing
   actions require user permission directly (the gate escalates to the user
   rather than vanishing). The residual risk (HR misjudges but is
   functional) remains and is covered by the audit trail + the Phase 6
   evaluation.

4. **The leader ↔ HR mutual approval can deadlock, and the tiebreaker is
   the user (BAU continues).** When the leader wants to fire a department
   head and HR says the firing isn't needed, that one decision is blocked
   until the user intervenes. That is defensible (it is a genuinely
   strategic call), and the tiebreaker is explicit (this outline: user
   decides, objection recorded). Crucially, **the rest of the organization
   continues BAU** while the tiebreaker is pending (§3, BAU rule) — only the
   blocked resourcing decision idles, so a single disagreement cannot stall
   Phase 4. The user's pending input is queued with context + options.

5. **The permission-per-edit model on `MISSION.md` can become a
   bottleneck in long runs.** In a long mission with evolving objectives,
   the leader may want to update the mission frequently; requiring user
   permission for *every* edit means the pipeline idles on the user often.
   The user is the mission owner, so their sign-off is correct for the
   *core* — but see Suggestion 3 (stable core / mutable working split) as
   the mitigation. Without it, expect either frequent user interruptions or
   the leader under-updating the mission (stale mission = the organization
   to an outdated statement of purpose).

6. **Intake is blocked on user availability.** The pipeline cannot pass
   Phase 1 until the user answers (only the Leader is active, so BAU has
   little to do here). If the user is slow, the pipeline idles. Consider an
   async mode: the Leader proceeds with *explicitly marked assumptions* (the
   plan already does this at budget exhaustion — extend it as an option
   before exhaustion) and the user corrects at the mission permission step,
   where they see the assumptions in context.

7. **Four tiers of decomposition add latency and information loss.** Every
   task passes through three layers of summarization before an IC sees it,
   and three layers before the leader sees the result. Each layer is a
   chance for the task to be mis-scoped or the result to be mis-summarized.
   For small tasks this overhead is disproportionate. Mitigations: the lean
   org option (Suggestion 9), **decision artifacts** (§2.8.1) carried
   alongside summaries in upward reports (so the chain of command carries
   references, not just lossy text), and the short-term-memory seed (§2.9)
   so a role's recent context is preserved rather than re-summarized away.

8. **The pod rule is now max 1-tier spread (was ambiguous).** The original
   rule was "±1 step from the *starter*", which allowed 2-tier-spread pods
   (a manager (tier 2) starting a pod with the department head (tier 1)
   *and* ICs (tier 3)). **This outline resolves it**: pod membership now
   requires **max tier spread = 1 across all members** (the strict option).
   This avoids an IC talking in the same room as a department head (which
   the hierarchy wants to avoid), at the cost of a few more chained pods.
   Chained-pod escalation + decision artifacts (§2.8) carry decisions up
   when a higher tier is needed.

9. **Personality assignment may be cosmetic without the debate mechanism.**
   Assigning "Pragmatist" or "Challenger" to a role changes its prompt, but
   in a single-model setup the behavioral delta is modest. The personality
   dimension earns its keep mainly through (a) alternate-personality
   structured votes (Suggestion 7) and (b) deliberate *contrasting*
   assignments (e.g. a Challenger IC on the Quality team, a Risk-Averse
   manager on a fast-moving project). Without those, personality is flavor.

10. **The organization's own health is measured by a department it can
    fire.** Analytics "tracks health metrics of the organization" — but if
    the leader (with HR) ever fires Analytics, who watches the watchers?
    Consider a minimal, non-fireable health baseline owned by the runtime
    itself (session records, org events, failure counts — the audit trail
    already has the raw material) so organizational health survives the
    resourcing of the department that reports it. (The Phase 6 evaluation
    also reads this baseline, so the self-improving loop is not dependent
    on Analytics staying staffed.)

---

*End of outline. The prior agent-team design (this repo's hierarchical
successor) is the source of the borrowed mechanisms: role contracts,
deliberation budgets, context discipline, alternate-personality votes, and
the self-mod loop.*
