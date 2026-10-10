"""The permission layer for agent self-modification.

This module is the single source of truth for what any role may write, and it
is itself a protected meta-rule: no role may edit this module, the mission, or
the workspace boundary. That is what stops an agent from rewriting the rules to
grant itself more access (e.g. mission-edit) or to escape the workspace.

Invariants (enforced by construction, not by prompt):

- SANDBOX  : every path a role writes must resolve inside ``ROOT``
             (LLM_Organization). A path that escapes (``..`` or a symlink) is
             refused. This is the "keep them in LLM_Org" rule, now in code.
- MISSION  : ``MISSION.md`` is read-only for every role except the leader, and
             the leader may only write it through the existing user-approval
             path. No role may edit this rule.
- META     : this module (plus the org invariants and the role contract) is
             read-only. No role may edit the rules that keep it confined.

Only ``write_file`` is the sanctioned write path for agent self-mod. The
trusted harness's own bookkeeping writes do not go through here.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

# The sandbox boundary: the LLM_Organization root. Computed from this file's
# location (runtime/permissions.py -> parent = LLM_Organization).
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Meta-rules / read-only paths, relative to ROOT. These encode the permission
# system itself and are NOT editable by any role (including the leader).
PROTECTED = (
    os.path.join("runtime", "permissions.py"),  # this module (the rules)
    os.path.join("org", "tiers.py"),            # org invariants
    os.path.join("roles", "base.py"),           # the role contract
)

# Top-level code the org's active roles may self-modify via the gated loop.
TOOLING = ("runtime", "org", "roles", "pods")


def resolve(path: str) -> str:
    """Resolve *path* and enforce the sandbox.

    Raises ``PermissionError`` if the resolved path escapes ``ROOT`` (via
    ``..`` or a symlink). This is the "confined to LLM_Organization" rule.
    """
    candidate = path if os.path.isabs(path) else os.path.join(ROOT, path)
    real = os.path.realpath(candidate)
    root_real = os.path.realpath(ROOT)
    if real != root_real and not real.startswith(root_real + os.sep):
        raise PermissionError(f"path escapes the workspace: {path!r}")
    return real


def _rel(path: str) -> str:
    """Return *path* relative to ``ROOT`` (for matching PROTECTED / scoping).

    A relative *path* is resolved against ``ROOT`` (not the CWD), so the
    result uses the platform separator and the scoping checks in
    ``can_edit`` can split it reliably.
    """
    candidate = path if os.path.isabs(path) else os.path.join(ROOT, path)
    real = os.path.realpath(candidate)
    root_real = os.path.realpath(ROOT)
    if real == root_real:
        return ""
    if real.startswith(root_real + os.sep):
        return os.path.relpath(real, root_real)
    return os.path.normpath(path)


def edit_reason(role, path: str) -> tuple:
    """Return ``(allowed, reason)`` for a role's write to *path*.

    `reason` is a short, human-readable explanation of the decision — which
    invariant was satisfied (when allowed) or violated (when refused). This is
    what the audit records on a refusal, so the operator can see *why* an edit
    was denied without re-deriving it from the code.

    Enforces, in order: the sandbox, the observability lock (operator-owned,
    read-only for every role), the mission lock, the meta-rule lock,
    department-policy ownership, department/team scoping, and org-tooling
    self-mod.
    """
    try:
        resolve(path)
    except PermissionError as e:
        return False, f"sandbox: {e}"
    rel = _rel(path)
    parts = rel.split(os.sep)
    # 1. Observability: operator-owned analytics — read-only for every role.
    #    Agents can never write into observability/; the dashboard process
    #    is an operator tool, not an agent.
    if parts and parts[0] == "observability":
        return False, ("observability: operator-owned analytics is read-only "
                       "for every role")
    # 2. Mission: only the leader may write it (and only via the user-approval
    #    path, a separate check). No role may edit this rule.
    if rel == "MISSION.md":
        if role.architype == "leader":
            return True, "mission: the leader may edit MISSION.md"
        return False, "mission: only the leader may edit MISSION.md"
    # 3. Meta-rules: read-only for every role (the rules themselves).
    if rel in PROTECTED:
        return False, f"meta_rule: {rel} is a protected invariant"
    # 4. Department policy: only the owning department head.
    #    e.g. departments/engineering/ENGINEERING_POLICY.md
    if parts and parts[0] == "departments" and len(parts) >= 3:
        dept = parts[1]
        if parts[2].endswith("_POLICY.md"):
            if role.architype == "department_head" and role.department == dept:
                return True, f"department_policy: {role.id} owns {dept}"
            return False, (f"department_policy: only the {dept} department "
                           f"head may edit its policy")
        # 5. Team dirs / work files: only roles in that department.
        if role.department == dept:
            return True, f"team_work: {role.id} is in {dept}"
        return False, (f"team_work: {role.id} (dept "
                       f"{role.department or '-'}) is not in {dept}")
    # 6. Org tooling: self-mod via the gated loop (any active role).
    if parts and parts[0] in TOOLING:
        if role.status == "active":
            return True, f"org_tooling: {role.id} is active"
        return False, f"org_tooling: {role.id} is not active"
    # 7. Out of scope: a top-level dir that is not a recognized write scope.
    top = parts[0] if parts else rel
    # Name the role's concrete team dir so the refusal is actionable — the
    # dispatch feeds this reason back for a corrective retry, so the model
    # sees exactly where to write.
    if role.department and role.team:
        hint = (f" your team work dir is "
                f"'departments/{role.department}/{role.team}/' — write there")
    else:
        hint = ""
    return False, (f"out_of_scope: '{top}' is not a writable scope for this "
                   f"role{hint}; the allowed scopes are the team work dir "
                   f"(departments/<dept>/<team>/), org tooling "
                   f"(runtime/org/roles/pods), MISSION.md, or a department "
                   f"policy")


def can_edit(role, path: str) -> bool:
    """True if *role* may write *path* (see `edit_reason` for the why)."""
    return edit_reason(role, path)[0]


def read_reason(role, path: str) -> tuple:
    """Return ``(allowed, reason)`` for a role's READ of *path*.

    This is the read gate (the mirror of `edit_reason` for writes). It
    enforces the org's read invariants (audit §2.4) — the ones that were
    previously advisory (documented but not enforced):

    - CODE_READ  : department heads and the leader cannot read any code
                   (work products) — only what is brought up as a bounded
                   summary + pointer.
    - READ_SCOPE : a role may only read its own team's department directory
                   (another department is refused).
    - CROSS_TEAM : a role reading a sibling team directory in the same
                   department is the duplication-check read — it is ALLOWED
                   but flagged (the dashboard shows it).

    `reason` is a short, human-readable explanation of the decision — which
    invariant was satisfied (when allowed) or violated (when refused) — so a
    refusal is self-explanatory in the audit (visible, never silent).
    """
    from org import tiers
    # 0. SANDBOX: a read that escapes the workspace is refused (the "keep them
    #    in LLM_Org" rule) — the same boundary the write gate enforces.
    try:
        resolve(path)
    except PermissionError as e:
        return False, f"sandbox: {e}"
    rel = _rel(path).replace(os.sep, "/")
    if not rel:
        return False, "read: the workspace root is not a readable path"
    # 1. MISSION: MISSION.md is read-only for every role (the mission lock —
    #    the same lock the write gate enforces).
    if rel == "MISSION.md":
        return False, "mission: MISSION.md is read-only for every role " \
                      "(the mission lock)"
    # 2. META: the meta-rule files are read-only for every role (the rules
    #    themselves — the same lock the write gate enforces).
    if rel.replace("/", os.sep) in PROTECTED:
        return False, f"meta_rule: {rel} is a protected invariant " \
                      f"(read-only)"
    # 3. CODE_READ: department heads and the leader cannot read code.
    if (tiers.is_head(role) or tiers.is_leader(role)) and tiers.is_code_path(rel):
        return False, ("code_read: department heads and the leader cannot "
                       "read code (work products) — only what is brought "
                       "up as a bounded summary + pointer")
    # 4. READ_SCOPE: a role may only read its own team's department directory.
    if not tiers.can_read(role, rel):
        return False, (f"read_scope: {role.id} may only read its own team's "
                       f"department directory")
    # 5. CROSS_TEAM: a sibling-team read is allowed but flagged (the
    #    duplication-check read).
    if tiers.cross_team_read(role, rel):
        return True, ("cross_team: allowed (the duplication-check read) — "
                      "flagged for the dashboard")
    return True, f"read: {role.id} may read {rel}"


def can_read_path(role, path: str) -> bool:
    """True if *role* may read *path* (see `read_reason` for the why)."""
    return read_reason(role, path)[0]


def write_file(role, path: str, content: str) -> str:
    """Write *content* to *path* if *role* may edit it.

    The only sanctioned write path for agent self-mod. Raises
    ``PermissionError`` if the role may not edit the path — the message
    carries the specific reason (which invariant was violated), so a refusal
    is self-explanatory in the audit.
    """
    allowed, reason = edit_reason(role, path)
    if not allowed:
        raise PermissionError(f"role {role.id!r} may not edit {path!r}: {reason}")
    real = resolve(path)
    parent = os.path.dirname(real)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(real, "w", encoding="utf-8") as f:
        f.write(content)
    return real


def read_file(
    role,
    path,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """Read a file on behalf of ``role``, gated by the read invariants (the
    sandbox, the mission lock, the meta-rule lock, the department scope, and
    the code-read invariants — heads/leaders cannot read code).

    This is the **read gate** that wires the invariants into the pipeline
    (the write counterpart is ``write_file``). A refused read raises
    ``PermissionError`` (visible, never silent); the rest proceed.

    A **cross-team read** (a sibling team directory in the same department —
    the duplication-check read) is **logged** (visible, not silent): when
    ``log`` is supplied it is called with a human-readable line, so the audit
    shows the role read across teams.

    Returns the file's content (an empty string when the file does not yet
    exist — a read of a new file is not an error).
    """
    from org import tiers
    allowed, reason = read_reason(role, path)
    if not allowed:
        raise PermissionError(
            f"role {role.id!r} may not read {path!r}: {reason}"
        )
    # A cross-team read (a sibling team dir in the same department) is the
    # duplication-check read that must be logged (visible, not silent).
    rel = _rel(path).replace(os.sep, "/")
    if tiers.cross_team_read(role, rel):
        if log:
            log(f"cross-team read: {role.id!r} -> {path!r}")
    real = resolve(path)
    if not os.path.isfile(real):
        return ""
    with open(real, "r", encoding="utf-8") as f:
        return f.read()


def apply_code_edits(
    role,
    edits,
    log: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """Apply a role's self-edit requests (a list of {path, content}), each
    gated by ``write_file`` (the sandbox, the mission lock, and the meta-rule
    lock). A refused write is recorded visibly (never silent) and the rest
    proceed. Returns one result per edit:

    - applied: ``{"path": ..., "ok": True, "real": ...}``
    - refused: ``{"path": ..., "ok": False, "error": ...}``

    `log` (optional) is called with a human-readable line for each result, so
    a refusal is visible in the audit, not swallowed.
    """
    results: List[Dict[str, Any]] = []
    for edit in edits or []:
        # Tolerate a free-form (non-dict) edit — the model occasionally
        # collapses `code_edits` to a string; skip it (visible, never a crash).
        if not isinstance(edit, dict):
            continue
        path = edit.get("path", "")
        content = edit.get("content", "")
        try:
            real = write_file(role, path, content)
            results.append({"path": path, "ok": True, "real": real})
            if log:
                log(f"applied: {role.id} -> {path}")
        except PermissionError as e:
            results.append({"path": path, "ok": False, "error": str(e)})
            if log:
                log(f"REFUSED: {role.id} -> {path}: {e}")
    return results
