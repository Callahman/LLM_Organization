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
