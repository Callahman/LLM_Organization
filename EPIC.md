# Epic — Address the audit findings

This Epic groups the findings from the audit (Sections 2–9 of
`AUDIT_FINDINGS.md`) into stories. Each story has a markdown under `stories/`
with a task checklist detailed enough to start the work with little-to-no extra
context (files to touch with line refs, the specific change, and the test to
add).

## Findings covered
- **Section 8 (re-audit):** A1–A11.
- **Section 9 (deep-dive audits):** B1–B18.
- **Relevant earlier items:** C1, C2, R1, R7, R10.

## Stories (in suggested order)

| # | Story | Findings | Priority |
|---|-------|----------|----------|
| 1 | [Persistence & crash recovery](stories/01-persistence-crash-recovery.md) | B1, B2, B3, B4, B7, R1 | HIGH |
| 2 | [Complexity routing & thinking budget](stories/02-complexity-routing-thinking-budget.md) | A7, B17, A6 | HIGH |
| 3 | [Safety halt enforcement](stories/03-safety-halt-enforcement.md) | A4, A10, B12, C1 | MED |
| 4 | [Output validation & tool_call quarantine](stories/04-output-validation-toolcall-quarantine.md) | A8, A9, R10 | MED |
| 5 | [Leader replacement](stories/05-leader-replacement.md) | A1 | HIGH |
| 6 | [Firing](stories/06-firing.md) | A3, R7 | MED |
| 7 | [Pod context & lifecycle bounding](stories/07-pod-context-lifecycle-bounding.md) | A2, B13, B14 | MED |
| 8 | [Config consumption](stories/08-config-consumption.md) | B18, C2 | MED |
| 9 | [Concurrency safety](stories/09-concurrency-safety.md) | B5, B6 | MED |
| 10 | [Tiers.py safety invariants](stories/10-tiers-safety-invariants.md) | A11 | MED |
| 11 | [Minor robustness](stories/11-minor-robustness.md) | B8, B9, B10, B11, B15, B16 | LOW |
| 12 | [Dead-code cleanup](stories/12-dead-code-cleanup.md) | A5 | LOW |

## Suggested order
1, 2, 5 (HIGH) → 3, 4, 6, 7, 8, 9, 10 (MED) → 11, 12 (LOW).

## Why this order
- **Story 1** restores the failure that actually happened (§7.8 — a lost run):
  a Phase 4 crash should lose at most the current iteration's hires.
- **Story 2** restores a dead core feature (complexity routing) and makes its
  tuning knob operator-settable.
- **Story 5** wires the only resourcing operation that was fully dead
  (`replace_leader`) to the design in the outline.
- **Stories 3 & 4** both touch the live-invoke path; do them together if
  possible (the halt check and the envelope check land in the same place).
- **Story 8** (config) and **Story 2** (thinking budget) both touch
  `config.py`: `THINKING_BUDGET` is added in Story 2, the 8 dead knobs in
  Story 8.