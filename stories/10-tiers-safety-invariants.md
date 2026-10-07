# Story 10 — Tiers.py safety invariants

**Rule:** Tests may not be run by the agent — only the user may run tests.

**Finding:** A11 (`tiers.py` `can_read_code` / `cross_team_read` /
`can_communicate` dead).

**Goal:** the tiers.py safety invariants are either enforced (wired into the
live path) or explicitly documented as advisory (with a note that the gap is
known). No silently dead safety invariant.

## Context (what exists today)
`org/tiers.py` defines safety invariants that are never called:
- `can_read_code(role)` — whether a role may read code (ICs/heads may; the
  leader may not).
- `cross_team_read(role, other)` — whether a role may read another team's
  output (the duplication-check reads).
- `can_communicate(role, other)` — whether two roles may communicate (a
  communication gate).

None are called in the pipeline. The communication path (pods, upward reports)
does not check `can_communicate`; the code-read path does not check
`can_read_code`.

## Tasks

- [ ] **Wire `can_communicate` into the pod/communication path.** In the pod
  formation (`runtime/pods.py` `form_pod` / `validate_pod`) or the upward-report
  path, call `tiers.can_communicate(role, other)` for each member pair; if a
  pair may not communicate, reject the pod (raise `PodMembershipError` with the
  reason) or log a visible note. (Grep `def can_communicate` in `org/tiers.py`
  for the signature.)
- [ ] **Gate or document `can_read_code`.** In the code-read path (where a role
  is given code to read — find the tool-call / code-read logic in
  `runtime/dispatch.py` or `runtime/llm_api.py`), call
  `tiers.can_read_code(role)` before granting code access; if it returns False,
  refuse (with a visible note). **If** the code-read path does not exist yet,
  document `can_read_code` as advisory in `org/tiers.py` (a docstring note that
  it is not yet enforced) so the gap is explicit.
- [ ] **Document `cross_team_read`.** Add a docstring note in `org/tiers.py`
  that `cross_team_read` is advisory (the duplication-check reads are not yet
  gated by it), OR wire it into the cross-team read path if one exists.
- [ ] **Tests** (`tests/test_tiers.py` or a new one):
  - (a) **`can_communicate` enforced:** a pod with a pair that may not
    communicate is rejected (or the note is logged).
  - (b) **`can_read_code`:** a role that may not read code is refused code
    access (or the advisory note is present in the docstring).

## Definition of done
- `can_communicate` is enforced in the pod/communication path.
- `can_read_code` / `cross_team_read` are either enforced or explicitly
  documented as advisory (the gap is visible).