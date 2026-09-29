"""runtime — the session runtime that drives the pipeline.

Modules:
- `llm`       — the LLM backend interface + a deterministic offline stub.
- `intake`    — Phase 1 (clarifying Q&A loop).
- `mission`   — Phase 2 (mission codification + permission flow).
- `org`       — Phase 3 (org bootstrap + resourcing).
- `dispatch`  — Phase 4 (top-down decomposition + upward reports).
- `pods`      — pod formation, conversation mechanics, artifacts, transcripts.
- `context`   — per-role short-term memory + bounded prompt construction.
- `history`   — audit trail, decision journal, rolling window, archives.
- `session`   — the session runtime that drives Phases 1–6 + the BAU rule +
  escalation + the Phase 6 self-improving loop.
"""
