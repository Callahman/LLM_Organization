# Organization

A **company of LLM agents** that takes an initial prompt and, through a
bounded pipeline of intake → mission → org bootstrap → execution → synthesis
→ evaluation, produces a coherent, **auditable** record of work — with
strict visibility/communication/pod invariants enforced by construction.

The design is specified in `Organization_Outline.md`; the build is tracked in
`EXECUTION_CHECKLIST.md`; the initial setup and deployment steps (on your
machine) are in `SETUP.md`.

## The pipeline (Phases 1–6)

1. **Intake** — the Leader asks clarifying questions until it is confident
   (or marks assumptions at the question budget).
2. **Mission codification** — the Leader drafts `MISSION.md`; the user
   approves (the only write path to the mission).
3. **Org bootstrap + resourcing** — department heads are proposed, HR
   reviews, directories/policies are created; required departments
   (HR, Safety, Morality) are always present.
4. **Top-down dispatch** — leader → heads → managers → ICs; work propagates
   up in structured reports (the leader never reads code).
5. **Synthesis** — the Leader checks progress against the mission's success
   criteria.
6. **Evaluation** — a bounded **continue/complete** decision (the
   self-improving loop).

## Revisiting the mission (`--revisit`)

Roles remember their past: each role's isolated memory is loaded from / saved
to `state/role_memory/` around every run, so a later run starts with the
context of what already happened. `python run_session.py --revisit` goes
further — it **revisits the current mission**:

1. **Intake** re-clarifies the goal against the existing `MISSION.md` (the
   goal may have changed).
2. **Mission codification** continues the version number (v1 → v2 → …) and
   revises the existing mission.
3. **Org bootstrap** runs additively — it only adds roles, never drops or
   overwrites one that already exists.
4. **Dispatch + synthesis** run as usual, then the org chart is re-saved to
   `state/org_chart.json` for the next revisit.

To start from a clean slate, run `python reset_org.py --yes` (it wipes
`departments/`, `state/`, `MISSION.md`, and the `history/*.jsonl` audit
trails).

## The invariants (enforced by construction)

- **A role can only read its team's department directory.**
- **Department heads and the Leader cannot read any code** — they see work
  only as it is brought to them (reports, summaries, decision artifacts).
- **Communication** is chain-of-command + team-mates + the Leader (apex); no
  reaching into another sub-agent's direct reports.
- **Pods** require max 1-tier spread across all members (2–6 size); the
  starter manages the conversation; the senior member shares the outcome out;
  chained pods carry decision artifacts up.

## Layout

```
MISSION.md            the global mission markdown (Leader-owned)
org/                  tier math + the rule checks
roles/                role contracts (base, leader)
departments/          one directory per department (policy + team dirs)
runtime/              the session runtime (llm, intake, mission, org,
                      dispatch, pods, context, history, session)
pods/                 transcripts + decision artifacts
state/role_memory/    per-role memory (persistent across runs)
state/org_chart.json  the saved org chart (loaded on a --revisit run)
history/              audit trail (intake, mission edits, org events, ...)
archives/             rolled-over sessions (size-capped)
reports/              offloading plans + evaluation reports
tests/                unit tests (offline, deterministic)
```

## Offline by design

The code ships with a deterministic `StubBackend` (scripted per role) so every
loop, budget, and schema check is testable **without a live model** — the same
offline-iteration idea as the prior design's `--feed-file`. A real backend is
wired behind the same `LLMBackend` interface (see `SETUP.md`).

## Quick start

See `SETUP.md` for the full deployment (git, venv, deps, tests) and for
wiring a real LLM backend.
