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

## Process diagram

The full process — entry points → configuration → the LLM backend chain → the
6-phase pipeline → state files → observability. Cylinder nodes `[(…)]` are
on-disk state files; the backend-chain subgraph shows the **call flow**
(outermost wrapper → innermost raw backend).

```mermaid
flowchart TD
    subgraph ENTRY["Entry points"]
        RS["run_session.py<br/>(--interactive / --revisit / --dry-run)"]
        RO["reset_org.py<br/>(--yes)"]
        BAT["run_org.bat<br/>(one-shot live run)"]
    end

    ENV[(".env")]
    CFG["runtime/config.py<br/>load_config()"]
    MKB["runtime/llm_api.py<br/>make_backend()"]

    subgraph BACKEND["LLM backend chain (built by session.build_backend)<br/>call flow: outermost → innermost"]
        MB["MemoryBackend<br/>(isolated per-role memory)"]
        RB["RoutingBackend<br/>(complexity routing + thinking budget)"]
        TB["TimeoutBackend<br/>(idle timeout + wall-clock backstop)"]
        RAW["raw backend<br/>OpenAIBackend (api) / StubBackend (stub)"]
    end

    subgraph PIPE["6-phase pipeline (runtime/session.py)"]
        P1["Phase 1 · Intake<br/>clarifying Q&A"]
        P2["Phase 2 · Mission<br/>draft + user approval"]
        P3["Phase 3 · Org bootstrap<br/>+ resourcing"]
        P4["Phase 4 · Dispatch<br/>top-down + upward reports"]
        P5["Phase 5 · Synthesis<br/>verdict"]
        P6["Phase 6 · Evaluation<br/>continue / complete"]
    end

    MISSION[("MISSION.md")]
    ORGCHART[("state/org_chart.json")]
    CKPT[("state/checkpoint.json")]
    MEM[("state/role_memory/*.json")]
    DEPT[("departments/*_POLICY.md")]
    HIST[("history/*.jsonl")]
    PODS[("pods/transcripts/*")]

    subgraph OBS["Observability (operator-owned, agent-write-locked)"]
        DASH["observability/dashboard.py<br/>(read-only, stdlib)"]
        WEB["web/ (index.html, app.js, style.css)"]
        BROWSE["browser<br/>http://127.0.0.1:8090"]
    end

    DONE["SessionResult"]

    BAT --> RS
    BAT --> DASH
    ENV --> CFG
    ENV --> MKB
    CFG --> RS
    MKB --> RAW
    RS --> MB
    MB --> RB
    RB --> TB
    TB --> RAW

    RS --> P1
    P1 --> P2 --> P3 --> P4
    P4 --> P5 --> P6
    P6 -->|continue (bounded by MAX_ITERATIONS)| P4
    P6 -->|complete| DONE

    P2 -->|approve (only write path)| MISSION
    P3 --> DEPT
    P3 --> ORGCHART
    P1 --> HIST
    P2 --> HIST
    P3 --> HIST
    P4 --> HIST
    P4 --> PODS
    MB --> MEM
    RS --> CKPT

    HIST --> DASH
    PODS --> DASH
    DASH --> WEB --> BROWSE

    RO -->|wipe| DEPT
    RO -->|wipe| ORGCHART
    RO -->|wipe| MISSION
```

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
observability/        read-only dashboard (operator-owned, agent-write-locked)
tests/                unit tests (offline, deterministic)
```

## Offline by design

The code ships with a deterministic `StubBackend` (scripted per role) so every
loop, budget, and schema check is testable **without a live model** — the same
offline-iteration idea as the prior design's `--feed-file`. A real backend is
wired behind the same `LLMBackend` interface (see `SETUP.md`).

## Observability

`observability/` is a **read-only** dashboard (stdlib-only, no dependencies)
that tails the audit trail and state in real time: it reads `history/*.jsonl`,
`state/`, and `pods/transcripts/`, and serves a local web UI. It is
**operator-owned and agent-write-locked** — the pipeline never writes to it.
Start it with:

```
python observability/dashboard.py --port 8090
```

then open http://127.0.0.1:8090.

## Quick start

See `SETUP.md` for the full deployment (git, venv, deps, tests) and for
wiring a real LLM backend.
