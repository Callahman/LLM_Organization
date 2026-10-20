# AUDIT_FINDINGS.md — LLM_Organization (final wiring + dead-code audit)

**Date:** 2026-07-10
**Method:** Read all 32 production modules (`runtime/` 24, `roles/` 3, `org/` 2,
`prompts/` 1, entry points 2) + grep-verified wiring (config-knob consumption,
backend chain, invariant call sites, state-file writers, dashboard inputs).
Cross-referenced against the 6 audit docs (RUN/LOG/EPIC/ORG/AUDIT/README) and
the EPIC acceptance criteria.

---

## 1. ✅ Confirmed working (wiring concerns resolved)

Every open wiring question from the prior audits is now **verified wired**,
with the evidence:

| Concern (from prior audits) | Status | Evidence |
|---|---|---|
| Backend chain (EPIC Story 2; ORG §1.9) | **Wired** | `session.py::build_backend` (D5): `raw → TimeoutBackend → RoutingBackend → MemoryBackend`, then `session.py:171` wraps outermost with `TimingBackend`. Full chain: `TimingBackend(MemoryBackend(RoutingBackend(TimeoutBackend(raw))))`. `on_call`/`on_stream` observability wired to `tool_calls.jsonl`/`stream.jsonl`. |
| Mission `approved=False` handling (RUN D1) | **Wired** | `session.py:786-787`: after the reask budget, `if not mission.approved: return self._escalate(...)` — visible escalation, never silent. |
| Efficiency data "dropped" (RUN D2) | **Wired** | `EfficiencyMeter` instantiated (`session.py:180`), `start_iteration` (830), `record_phase` (648, 837), `finish_iteration` (522, Phase 8) → appends `history/efficiency_metrics.jsonl`. |
| Timing / efficiency panel (RUN D2) | **Wired** | `TimingTracker` + `TimingBackend` (outermost wrapper) → appends `history/efficiency.jsonl`. |
| Complexity routing (EPIC Story 2) | **Wired** | `RoutingBackend` in the chain; `classify_complexity` pure router; `ThinkingBudget` with visible LOW fallback; D2 fix (explicit phase at call sites, since `MemoryBackend` re-wraps the context). |
| `dispatch.py` monolith (EPIC Story 2) | **Thin shim** | Re-exports 30 helpers from `dispatch_common.py` + the 3 phase modules; `dispatch()` is the 3-phase sequence (same return shape). No duplicated logic. |
| Config knobs (ORG D1; EPIC S20) | **Wired** | `runtime/config.py` maps all 24 org-tuning knobs + warns on unknown/unused `.env` keys; invalid values fall back to code defaults **with a warning**. Grep-verified consumption of 21/22 knobs (see Finding F1 for the exception). |
| Worker output schemas (LOG F2/F3) | **Wired** | `worker_output_schema` attached at every creation site: `org.py:380/417/524` (heads/ICs), `dispatch_common.py:666` (`_ensure_role`). |
| Invariants (read scope, pod spread, communication) | **Enforced** | `can_read`/`can_read_code` enforced in `permissions.edit_reason` (write path); `validate_pod` + `can_communicate` (all member pairs) enforced in `pods.form_pod`; `POD_MIN/MAX_ROLES` knobs override the constants (S20). |
| Permission layer (sandbox/mission/meta) | **Enforced** | `permissions.py`: ROOT sandbox (realpath, `..`/symlink refused), MISSION lock, META lock (`permissions.py`/`tiers.py`/`base.py`), observability lock, department-policy lock; rejections carry human-readable reasons and are logged (`REFUSED: ...`), never swallowed. |
| Checkpointing (EPIC Story 1) | **Wired** | `session.py::_checkpoint` (atomic tmp + `os.replace`) after Phase 3 (811) and each iteration (932); `run_session.py::_decide_run_mode` resumes from it. |
| State files | **All wired** | `org_chart.json` (`OrgState.save/load`), `mission_draft.md` (intake), `role_memory/` (`MemoryBackend.save_state/load_state`), `checkpoint.json` (above). |
| User-callback guard (EPIC Story 11) | **Wired** | `guard.py::guarded_call`: bounded retry (default 2), visible stderr note per failure, raises `UserApprovalError` on final failure. |
| IC invoke containment (LOG F5) | **Wired** | `dispatch_common.py::_invoke_ic`: first failure → one corrective retry (`IC_RETRY_NUDGE`); second failure → `(None, visible_error)` — the error propagates as a report. |
| Prompts (EPIC Story 11) | **Complete** | `prompts/__init__.py`: all static prompts for all 8 phases, each with a usage comment (pure move, text unchanged). |
| Dashboard inputs | **All real files** | `org_events/code_edits/tool_calls/cycles/stream/efficiency/efficiency_metrics.jsonl` + `state/org_chart.json` + `pods/transcripts/`. All are produced (see §3 note on `halt_events.jsonl`). |
| CLI (EPIC S15/S16, D6/D7) | **Wired** | `run_session.py`: `--interactive/--revisit/--fresh/--dry-run/--prompt`; default mode **revisit** (S15); fresh runs wipe state first (S16, reuses `reset_org.wipe_state`); `max_iterations` config-driven (D6); dry-run redirects to a temp dir (D7). |
| `reset_org.py` | **Clean** | Dry-run by default, `--yes` to delete; wipes `departments/ state/ MISSION.md history/*.jsonl pods/ reports/ archives/`; every deletion printed. |

**Code-hygiene scan (production):** no `TODO/FIXME/XXX/HACK`; no bare
`except:`; the single `NotImplementedError` (`llm.py:47`) is the base-class
contract (legitimate); 12 `except Exception` sites — 9 are visible (org events,
corrective retries, documented observability guards), 3 are silent (Findings
F3, F4, F6).

---

## 2. 🔴 Findings

### F1 — `EXECUTION_POD_ROUNDS` is a dead config knob (moderate)

`config.py:92` maps `EXECUTION_POD_ROUNDS → execution_pod_rounds` and
`.env.example` documents it (`EXECUTION_POD_ROUNDS=3`), but **no code consumes
`execution_pod_rounds`** (grep-verified: the only hit project-wide is the
config mapping itself). The A/B/C execution pods are actually bounded by
`pod_max_rounds` (`dispatch_common.py:867/915`, default 3). An operator who
sets `EXECUTION_POD_ROUNDS` gets a **silent no-op**.

**Fix (1 line):** in the execution-pod trigger sites, use
`(config or {}).get("execution_pod_rounds", (config or {}).get("pod_max_rounds", 3))`
— or remove the knob from `config.py` + `.env.example`.

### F2 — `--dry-run` does not isolate agent self-modification writes (moderate)

`--dry-run` redirects the pipeline's own state writes by `chdir`-ing to a temp
dir (`run_session.py:201-206`) — those writes are CWD-relative. But the gated
self-mod path resolves relative paths against the **project root**, not the
CWD: `permissions.resolve()` uses `ROOT` (computed from `permissions.py`'s
location, `permissions.py:30/50`). So in a dry run, IC `code_edits` and
`run_automation` scripts (`automations/<slug>.py`) are applied to the **real
project**, not the throwaway dir. The dry-run promise ("the real org is left
untouched") does not cover the self-mod gate.

**Fix:** make the self-mod root CWD-relative in dry-run (e.g. an overridable
root in `permissions`, or chdir + a CWD-based `ROOT`), or document the
limitation in the `--dry-run` help text.

### F3 — Hire failure is silent (moderate)

`dispatch_common.py:671` (`_ensure_role`): `except Exception: return None`.
This is the RUN_AUDIT D6 case ("could not hire the automation IC — the run
proceeded without it"). The role simply doesn't exist and the run continues,
but the **failure is not logged or escalated** — an operator sees a missing
role with no reason.

**Fix (2 lines):** log an org event (`hire_failed`, with the error) before
returning `None`.

### F4 — `permissions.can_read_path` is dead code (minor)

Defined at `permissions.py:210`, **never called** anywhere (grep-verified,
including tests). The read-scope invariant is enforced by context-builder
scoping (the phase modules assemble only what a role may see), not by a
runtime read gate. The dead helper creates the false impression that a read
gate exists.

**Fix:** wire it into the read helpers (`_read_policy`, `_ic_pre_read`) as
defense-in-depth — or delete it.

### F5 — IC self-edit invoke failure is silent (minor)

`dispatch_common.py:598`: `except Exception: return` — if the IC's self-edit
invoke fails, the edits are skipped with **no log**. (The IC's work itself is
reported; only the secondary self-edit action is lost silently.)

**Fix:** log a visible note (org event or `code_edits.jsonl` entry with
`ok=False`).

### F6 — Corrupted checkpoint silently ignored (minor)

`run_session.py::_decide_run_mode`: `except (OSError, ValueError): pass` — a
corrupt `checkpoint.json` silently falls back to the default phase (3).
`session.py:691-704` handles the same file with a **visible** note on the
session path — the CLI path is the inconsistent one.

**Fix:** print a visible warning when the checkpoint fails to parse.

### F7 — Devil's-advocate policy read failure is silent (minor)

`session.py:405`: `except Exception: content = ""` — a failed department-policy
read in the DA's context assembly is silently treated as empty.

**Fix:** log a note (the DA's doubt is weakened by missing policies; at minimum
record it in `org_events.jsonl`).

### F8 — `EFFICIENCY_FLOOR` is not tunable (minor, note)

`efficiency.py:46`: `EFFICIENCY_FLOOR = 0.4` — a hardcoded constant, **not** an
env knob (it is *not* a dead knob — it is consumed; it is simply not
configurable). If an operator wants to tune the floor, there is no `.env`
path.

**Fix (optional):** add an `EFFICIENCY_FLOOR` mapping in `config.py` (it is
already a constructor arg of `EfficiencyMeter`).

### F9 — `_debug_tmp/` leftover debug data (cleanup target, not code)

`_debug_tmp/` contains stale session artifacts (`cycles/efficiency/intake/
invocations/mission_edits.jsonl`, `pods/transcripts/solo_leader_p1/p2`,
`state/mission_draft.md`) from a prior run. It is not produced by the current
pipeline (the pipeline writes to `history/`, `pods/`, `state/`).

**Fix:** delete the directory (or move it under gitignore if it is a scratch
area).

---

## 3. Notes / non-issues

- **`automations/`** is the live target dir for `run_automation` scripts
  (`dispatch_common.py:716`, default `script_dir="automations"`); it is empty
  until the first automation fires. Not dead weight.
- **`halt_events.jsonl`** is created on demand (first Safety/Morality halt).
  The dashboard tails it; a missing file is the normal state before the first
  halt. The RUN_AUDIT D9 "nonexistent log" concern is resolved (the log is
  produced; the dashboard must tolerate the not-yet-created file).
- **`llm_api.py:581/621`** `except Exception: pass` are intentional, documented
  observability guards ("observability must never break the pipeline") — the
  audit-trail write failing is not a control-flow failure.
- **`devils_advocate_failed`** (session.py:371) is visible (org event); a
  failed DA gut-check degrades to "no flag" (the stop decision is not blocked
  by a failure — only by an actual `flag`). Per spec.
- **`EFFICIENCY_FLOOR` in ORG_AUDIT §4.3** was listed as a knob to verify —
  it is a constant, not a knob (see F8).

---

## 4. Prioritized recommendations

| # | Action | Effort |
|---|---|---|
| 1 | Wire `EXECUTION_POD_ROUNDS` into the execution-pod trigger (or drop the knob) — **F1** | 1 line |
| 2 | Log hire failures as an org event — **F3** | 2 lines |
| 3 | Close the `--dry-run` self-mod isolation gap (or document it) — **F2** | small |
| 4 | Delete or wire `permissions.can_read_path` — **F4** | 1 line / small |
| 5 | Add visible logging to the three silent `except`s — **F5, F6, F7** | 3 lines |
| 6 | Optional: make `EFFICIENCY_FLOOR` an env knob — **F8** | 1 line |
| 7 | Clean up `_debug_tmp/` — **F9** | delete dir |

**Overall assessment:** the pipeline is in strong shape. Every prior wiring
concern is resolved and verified; the codebase is self-documenting (fix
history is recorded inline), error handling is overwhelmingly visible, and the
invariants are enforced by construction. The findings are 3 moderate
(gap in a documented guarantee, one dead knob, one silent failure) and 6 minor
(dead helper, three silent minor failures, one untunable constant, one cleanup
target) — none of which affect the core run path's correctness.
