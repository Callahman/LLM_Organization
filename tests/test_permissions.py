"""Tests for the permission layer (runtime/permissions.py).

Covers the invariants the user cares about:
- SANDBOX : a path that escapes the workspace is refused.
- MISSION : only the leader may write MISSION.md.
- META    : the permission module (and the org invariants / role contract) is
            read-only for every role, including the leader.
Plus the normal scoping (department policy, team dirs) and the write path.
"""

import os
import shutil

import pytest

from roles.base import Role
from runtime import permissions as P


def make_role(architype, department="", team="", status="active"):
    return Role(
        id=f"r_{architype}_{department or 'x'}",
        architype=architype,
        department=department,
        team=team,
        status=status,
    )


# --- OBSERVABILITY -----------------------------------------------------------

def test_observability_locked_for_every_role():
    assert not P.can_edit(make_role("leader"), "observability/metrics.json")
    assert not P.can_edit(
        make_role("department_head", "hr"), "observability/dashboard.py")
    assert not P.can_edit(
        make_role("ic", "engineering", "development"), "observability/web/app.js")


def test_observability_write_refused_before_any_write():
    with pytest.raises(PermissionError):
        P.write_file(make_role("leader"), "observability/evil.py", "x")


# --- SANDBOX ---------------------------------------------------------------

def test_sandbox_blocks_escape_via_dotdot():
    with pytest.raises(PermissionError):
        P.resolve(os.path.join("..", "..", "outside.txt"))


def test_sandbox_allows_inside():
    real = P.resolve("departments/engineering/development/foo.py")
    assert real.startswith(os.path.realpath(P.ROOT))


# --- MISSION ---------------------------------------------------------------

def test_mission_locked_for_non_leaders():
    assert not P.can_edit(make_role("ic", "engineering", "development"), "MISSION.md")
    assert not P.can_edit(make_role("department_head", "engineering"), "MISSION.md")
    assert not P.can_edit(make_role("manager", "engineering"), "MISSION.md")


def test_mission_allowed_for_leader():
    assert P.can_edit(make_role("leader"), "MISSION.md")


# --- META (the rules themselves) ------------------------------------------

def test_permission_module_read_only_for_everyone():
    module = os.path.join("runtime", "permissions.py")
    assert not P.can_edit(make_role("leader"), module)
    assert not P.can_edit(make_role("department_head", "engineering"), module)
    assert not P.can_edit(make_role("ic", "engineering", "development"), module)


def test_org_invariants_and_contract_read_only():
    leader = make_role("leader")
    assert not P.can_edit(leader, os.path.join("org", "tiers.py"))
    assert not P.can_edit(leader, os.path.join("roles", "base.py"))


# --- READ GATE (Story 14) ----------------------------------------------------

def test_read_gate_blocks_sandbox_escape():
    # A read that escapes the workspace is refused (the sandbox invariant) —
    # a visible PermissionError, never a silent read.
    with pytest.raises(PermissionError):
        P.read_file(make_role("ic", "engineering", "development"),
                    os.path.join("..", "..", "outside.txt"))


def test_read_gate_blocks_mission_and_meta():
    # The mission lock and the meta-rule lock refuse reads for every role,
    # including the leader (the rules themselves are read-only).
    for role in (make_role("leader"),
                 make_role("ic", "engineering", "development")):
        with pytest.raises(PermissionError):
            P.read_file(role, "MISSION.md")
        with pytest.raises(PermissionError):
            P.read_file(role, os.path.join("runtime", "permissions.py"))


def test_read_gate_blocks_other_department():
    # A role may not read another department's files (the department scope).
    with pytest.raises(PermissionError):
        P.read_file(make_role("ic", "engineering", "development"),
                    os.path.join("departments", "hr", "hirings", "note.md"))


def test_read_gate_blocks_code_for_head_and_leader():
    # Department heads and the leader cannot read any code (the code-read
    # invariant) — a visible PermissionError, never a silent read.
    code = os.path.join("departments", "engineering", "development", "a.py")
    with pytest.raises(PermissionError):
        P.read_file(make_role("department_head", "engineering"), code)
    with pytest.raises(PermissionError):
        P.read_file(make_role("leader"), code)


def test_read_gate_allows_in_scope_read(monkeypatch):
    # An in-scope read (a manager/IC reading code in its own department) is
    # allowed and returns the file's content.
    tmp = os.path.join(P.ROOT, "read_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        code = os.path.join("departments", "engineering", "development", "a.py")
        P.write_file(make_role("ic", "engineering", "development"),
                     code, "print('hi')\n")
        assert P.read_file(
            make_role("manager", "engineering", "development"), code
        ) == "print('hi')\n"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_read_gate_logs_cross_team_read(monkeypatch):
    # A cross-team read (a sibling team dir in the same department — the
    # duplication-check read) is **logged** (visible, not silent): the log
    # callable is called with a cross-team line, and the read still returns
    # the content.
    tmp = os.path.join(P.ROOT, "read_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        sib = os.path.join("departments", "engineering", "etl", "x.py")
        P.write_file(make_role("ic", "engineering", "etl"), sib, "print('x')\n")
        lines = []
        content = P.read_file(make_role("ic", "engineering", "development"),
                              sib, log=lines.append)
        assert content == "print('x')\n"
        assert any("cross-team" in ln for ln in lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Department policy -----------------------------------------------------

def test_dept_policy_only_own_head():
    policy = os.path.join("departments", "engineering", "ENGINEERING_POLICY.md")
    assert P.can_edit(make_role("department_head", "engineering"), policy)
    assert not P.can_edit(make_role("department_head", "hr"), policy)
    assert not P.can_edit(make_role("ic", "engineering", "development"), policy)


# --- Team dirs -------------------------------------------------------------

def test_team_file_only_own_dept():
    f = os.path.join("departments", "engineering", "development", "work.py")
    assert P.can_edit(make_role("ic", "engineering", "development"), f)
    assert not P.can_edit(make_role("ic", "hr", "hirings"), f)


# --- write_file respects permissions --------------------------------------

def test_write_file_respects_permissions(monkeypatch):
    # Use a repo-local temp dir (the system temp dir is locked in this env).
    tmp = os.path.join(P.ROOT, "perm_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        eng = make_role("ic", "engineering", "development")
        hr = make_role("ic", "hr", "hirings")
        path = os.path.join("departments", "engineering", "development", "work.py")
        real = P.write_file(eng, path, "print('hi')\n")
        assert os.path.exists(real)
        with pytest.raises(PermissionError):
            P.write_file(hr, path, "x")
        with pytest.raises(PermissionError):
            P.write_file(eng, os.path.join("..", "escape.py"), "x")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- apply_code_edits (the self-edit action) --------------------------------

def test_apply_code_edits_applies_scoped(monkeypatch):
    tmp = os.path.join(P.ROOT, "perm_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        ic = make_role("ic", "engineering", "development")
        edits = [
            {"path": os.path.join("departments", "engineering", "development", "fix.py"),
             "content": "print('fix')\n"},
        ]
        results = P.apply_code_edits(ic, edits)
        assert len(results) == 1
        assert results[0]["ok"] is True
        assert os.path.exists(results[0]["real"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_code_edits_refuses_meta_and_escape(monkeypatch):
    tmp = os.path.join(P.ROOT, "perm_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        ic = make_role("ic", "engineering", "development")
        edits = [
            {"path": os.path.join("runtime", "permissions.py"), "content": "x"},
            {"path": "MISSION.md", "content": "x"},
            {"path": os.path.join("..", "escape.py"), "content": "x"},
        ]
        results = P.apply_code_edits(ic, edits)
        assert len(results) == 3
        assert all(r["ok"] is False for r in results)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_apply_code_edits_logs_refusals(monkeypatch):
    tmp = os.path.join(P.ROOT, "perm_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        ic = make_role("ic", "engineering", "development")
        log_lines = []
        edits = [
            {"path": os.path.join("departments", "engineering", "development", "ok.py"),
             "content": "print('ok')\n"},
            {"path": os.path.join("runtime", "permissions.py"), "content": "x"},
        ]
        results = P.apply_code_edits(ic, edits, log=log_lines.append)
        assert results[0]["ok"] is True
        assert results[1]["ok"] is False
        assert any("applied" in line for line in log_lines)
        assert any("REFUSED" in line for line in log_lines)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
