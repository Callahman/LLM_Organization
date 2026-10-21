"""runtime — the session runtime that drives the pipeline.

Modules:
- `llm` — the LLM backend interface + a deterministic offline stub.
- `intake` — Phase 1 (clarifying Q&A loop).
- `mission` — Phase 2 (mission codification + permission flow).
- `org` — Phase 3 (org bootstrap + resourcing).
- `plan` — Phase 4 (leader decomposition + the per-department head workflow).
- `staff` — Phase 5 (the per-team manager workflow: IC decomposition + hiring).
- `execute` — Phase 6 (the per-IC work + self-edits + pod triggers + upward report).
- `pods` — pod formation, conversation mechanics, artifacts, transcripts.
- `context` — per-role short-term memory + bounded prompt construction.
- `history` — audit trail, decision journal, rolling window, archives.
- `session` — the session runtime that drives Phases 1–8 + the BAU rule +
  escalation + the Phase 8 self-improving loop.
"""
