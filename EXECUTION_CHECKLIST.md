# Remaining Work

The Organization codebase is complete and verified offline - every loop,
budget, and schema check is covered by the offline test suite (the build epics
and Steps 1-4 in `Organization_Outline.md` are done). This checklist tracks
only what still needs to be done.

> Initial setup (venv, deps, running the offline tests) is in `SETUP.md`.
> The design is specified in `Organization_Outline.md`.

---

## 1. A real LLM backend

Drive the Organization with a live model instead of the offline `StubBackend`.
The interface + a worked example are in `SETUP.md` ("The LLM backend").

- [ ] Implement `LLMBackend.invoke` (call your model, return the shared output
      envelope) and select it where the `Session` is constructed.
- [ ] Set `LLM_BACKEND=api` in `.env` (plus the model's `base_url` / `api_key`).
- [ ] Hand-run a deliberately vague intake against the real model and confirm
      the clarifying Q&A loop resolves it - confidence climbs across rounds,
      the mission is approved, the org bootstraps, and the work flows up.

**Definition of Done:** a full pipeline run against the real model - intake ->
mission -> org -> dispatch -> Phase 5 synthesis -> verdict - completes with the
leader's verdict "complete" (or a clean "escalated"), and the clarifying Q&A
loop demonstrably resolves a vague intake.

---

## 2. Unattended operation (the final DoD)

A fresh deployment from the docs, then a week of unattended operation (or N
end-to-end runs) with no manual fixes.

- [ ] Deploy from `SETUP.md` on a clean machine (venv + deps + offline tests
      green).
- [ ] Run the pipeline unattended for a week (or N end-to-end runs) and confirm
      no manual intervention is needed - the bounded loops hold, the schema
      retries are visible (not silent), the thinking budget is respected, and
      the state/history/archive directories stay within their caps.

**Definition of Done:** a week of unattended operation (or N end-to-end runs)
with no manual fixes - the bounded loops hold, the schema retries are visible
(not silent), the thinking budget is respected, and the state/history/archive
directories stay within their caps.