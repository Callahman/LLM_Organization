"""runtime — the session runtime that drives the pipeline.

This package is the Organization's engine. The two largest concerns are split
into a **parent facade + focused submodules**: the parent keeps the core class
+ a slim orchestrator and re-exports the submodule functions, so importing from
the parent still works unchanged. The README's "Module organization" section
has the full "where to find what" map; this docstring is the quick reference.

LLM backend
- `llm`            — the LLM backend interface + a deterministic offline stub.
- `llm_api`        — a real OpenAI-compatible backend (the facade: core loop +
                     `make_backend`); reply parsing and streaming live in the
                     submodules below.
- `llm_api_parse`  — the real backend: reply parsing + truncation detection.
- `llm_api_stream` — the real backend: streaming + the bounded retry loop.
- `complexity`     — complexity routing (does a task use the model's "thinking"?).
- `efficiency`     — the S22 efficiency trade-off in the Phase 3-6 loop.
- `timing`         — invoke timing (per-role / per-department wall-clock time).

The 6-phase pipeline (one module per phase; the big ones are split)
- `intake`         — Phase 1 (clarifying Q&A loop).
- `mission`        — Phase 2 (mission codification + permission flow).
- `org`            — Phase 3 (the core registry + bootstrap/resourcing facade).
- `org_bootstrap`  — Phase 3: the Leader's department-head proposal.
- `org_resourcing` — Phase 3: hire / fire resourcing actions.
- `org_approvals`  — Phase 3: the approval matrix for resourcing actions.
- `org_leader`     — Phase 3: Leader replacement (unanimous head vote).
- `dispatch`       — Phase 4 (the core context assembly + dispatch facade).
- `dispatch_main`  — Phase 4: the top-down dispatch runner.
- `dispatch_role_work` — Phase 4: role lifecycle + IC work invokes.
- `dispatch_pod_triggers` — Phase 4: the Pods A/B/C multi-trigger.
- `dispatch_self_edits` — Phase 4: IC self-edits (gated by permissions).
- `dispatch_efficiency` — Phase 4: the Leader's S22 efficiency actions.
- `dispatch_automation` — Phase 4: automation over headcount (S22).
- `session`        — the session runtime that drives Phases 1-6 + the BAU rule
                     + escalation + the Phase 6 self-improving loop (facade).
- `session_phases123` — run setup + Phases 1-3 (intake, mission, bootstrap).
- `session_loop`      — the Phases 4-6 bounded self-improving loop.
- `session_phases`    — Phase 5 `synthesis` + Phase 6 `evaluate`.
- `session_efficiency`— the S22 per-iteration efficiency metrics + floor trigger.
- `session_escalation`— `escalate` (a structured diagnosis to the user).
- `session_finalize`  — the run finalization (rolling window + persist).

Pods
- `pods`          — bounded, 1-tier-spread working groups (the facade).
- `pod_artifacts` — transcript + decision-artifact files.
- `solo_pods`     — solo (single-role) leader pods.

Supporting infrastructure
- `context`      — per-role short-term memory + bounded prompt construction.
- `history`      — audit trail, decision journal, rolling window, archives.
- `permissions`  — the permission layer for agent self-modification.
- `config`       — the central config loader (reads the ``.env`` tuning knobs).
- `coerce`       — tolerant coercion of LLM structured outputs.
- `guard`        — bounded-retry guard for user-approval callbacks.
"""
