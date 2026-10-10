"""Unit tests for `org/tiers.py` — the visibility/communication/pod invariants
(Epic 0 Definition of Done).

Worked examples (Organization_Outline.md §2.4, §2.8):
- a role can only read its team's department directory;
- department heads and the leader cannot read any code;
- an IC cannot pod with a department head (2-tier spread);
- a manager can pod with the department head (1-tier spread);
- same-tier pods are allowed;
- no role communicates with another sub-agent's direct reports;
- cross-team reads within a department are flagged.
"""

from org import tiers
from roles.base import Role


def _role(rid, architype, department="", team="", reports_to=None):
    return Role(
        id=rid,
        architype=architype,
        department=department,
        team=team,
        reports_to=reports_to,
    )


# --- Tier math -------------------------------------------------------------

def test_tier_math():
    assert tiers.architype_to_tier("leader") == 0
    assert tiers.architype_to_tier("department_head") == 1
    assert tiers.architype_to_tier("manager") == 2
    assert tiers.architype_to_tier("ic") == 3


# --- Read scope ------------------------------------------------------------

def test_ic_reads_only_its_department():
    ic = _role("ic1", "ic", department="analytics", team="pipelines")
    assert tiers.can_read(ic, "departments/analytics/pipelines/a.py")
    assert tiers.can_read_code(ic, "departments/analytics/pipelines/a.py")
    # Not another department.
    assert not tiers.can_read(ic, "departments/engineering/core/b.py")
    assert not tiers.can_read_code(ic, "departments/engineering/core/b.py")


def test_head_cannot_read_any_code():
    head = _role("head_analytics", "department_head", department="analytics")
    # A head owns/reads only its own department policy markdown (governance).
    assert tiers.can_read(head, "departments/analytics/ANALYTICS_POLICY.md")
    # But it cannot read any code (work products) — only what is brought up.
    assert not tiers.can_read_code(head, "departments/analytics/pipelines/a.py")
    assert not tiers.can_read(head, "departments/analytics/pipelines/a.py")


def test_leader_cannot_read_any_code():
    leader = _role("leader", "leader")
    assert tiers.can_read(leader, "MISSION.md")
    assert not tiers.can_read_code(leader, "departments/analytics/pipelines/a.py")
    assert not tiers.can_read(leader, "departments/analytics/ANALYTICS_POLICY.md")


def test_cross_team_read_flagged():
    ic = _role("ic1", "ic", department="analytics", team="pipelines")
    # Reading a sibling team directory in the same department is the
    # duplication-check read that must be logged.
    assert tiers.cross_team_read(ic, "departments/analytics/etl/x.py")
    # Reading its own team is not cross-team.
    assert not tiers.cross_team_read(ic, "departments/analytics/pipelines/a.py")


# --- Communication ---------------------------------------------------------

def test_leader_is_apex():
    leader = _role("leader", "leader")
    ic = _role("ic1", "ic", department="analytics", team="pipelines", reports_to="mgr1")
    assert tiers.can_communicate(leader, ic)
    assert tiers.can_communicate(ic, leader)


def test_chain_of_command():
    head = _role("head_analytics", "department_head", department="analytics")
    mgr = _role("mgr1", "manager", department="analytics", team="pipelines", reports_to="head_analytics")
    ic = _role("ic1", "ic", department="analytics", team="pipelines", reports_to="mgr1")
    # Boss / reports.
    assert tiers.can_communicate(ic, mgr)
    assert tiers.can_communicate(mgr, ic)
    assert tiers.can_communicate(mgr, head)
    assert tiers.can_communicate(head, mgr)
    # Team-mates (same team).
    ic2 = _role("ic2", "ic", department="analytics", team="pipelines", reports_to="mgr1")
    assert tiers.can_communicate(ic, ic2)


def test_no_reaching_into_another_subagents_reports():
    # Manager A must not talk to Manager B's IC (a different sub-agent's
    # direct report).
    head = _role("head_analytics", "department_head", department="analytics")
    mgr_a = _role("mgrA", "manager", department="analytics", team="etl", reports_to="head_analytics")
    mgr_b = _role("mgrB", "manager", department="analytics", team="pipelines", reports_to="head_analytics")
    ic_b = _role("icB", "ic", department="analytics", team="pipelines", reports_to="mgrB")
    assert not tiers.can_communicate(mgr_a, ic_b)
    assert not tiers.can_communicate(ic_b, mgr_a)


# --- Pod membership --------------------------------------------------------

def test_ic_cannot_pod_with_head():
    ic = _role("ic1", "ic", department="analytics", team="pipelines")
    head = _role("head_analytics", "department_head", department="analytics")
    ok, reason = tiers.validate_pod([ic, head])
    assert not ok  # 2-tier spread
    assert "spread" in reason


def test_manager_can_pod_with_head():
    mgr = _role("mgr1", "manager", department="analytics", team="pipelines")
    head = _role("head_analytics", "department_head", department="analytics")
    ok, reason = tiers.validate_pod([mgr, head])
    assert ok  # 1-tier spread


def test_same_tier_pods_allowed():
    ic1 = _role("ic1", "ic", department="analytics", team="pipelines")
    ic2 = _role("ic2", "ic", department="analytics", team="pipelines")
    ok, reason = tiers.validate_pod([ic1, ic2])
    assert ok  # 0-tier spread


def test_pod_size_bounds():
    ic1 = _role("ic1", "ic", department="analytics", team="pipelines")
    ic2 = _role("ic2", "ic", department="analytics", team="pipelines")
    # Too small.
    ok, reason = tiers.validate_pod([ic1])
    assert not ok
    assert "size" in reason
    # Two is fine.
    assert tiers.validate_pod([ic1, ic2])[0]


# --- Story 10 (A11): safety invariants enforced / documented ---------------

def test_can_communicate_enforced_in_form_pod():
    """Story 10 (A11): a pod with a member pair that may not communicate is
    rejected (the communication gate is wired into form_pod)."""
    from runtime.pods import form_pod, PodMembershipError
    # Two ICs on different teams that cannot communicate (no boss/report
    # relationship, not same team).
    mgr_a = _role("mgrA", "manager", department="analytics", team="etl", reports_to="head")
    mgr_b = _role("mgrB", "manager", department="analytics", team="pipelines", reports_to="head")
    ic_a = _role("icA", "ic", department="analytics", team="etl", reports_to="mgrA")
    ic_b = _role("icB", "ic", department="analytics", team="pipelines", reports_to="mgrB")
    # ic_a and ic_b cannot communicate (different teams, no boss/report link).
    assert not tiers.can_communicate(ic_a, ic_b)
    roles = {"mgrA": mgr_a, "icA": ic_a, "icB": ic_b}
    try:
        form_pod(roles, "mgrA", ["icA", "icB"], "topic")
        raise AssertionError("expected PodMembershipError")
    except PodMembershipError as e:
        assert "communicate" in str(e)


def test_can_read_code_enforced_note_present():
    """Story 14: can_read_code is documented as **enforced** (the gap is filled
    — the read gate wires the invariant into the live path), no longer
    advisory."""
    import inspect
    doc = inspect.getdoc(tiers.can_read_code) or ""
    assert "Enforced" in doc
    assert "Advisory" not in doc
    assert "not yet enforced" not in doc


def test_cross_team_read_enforced_note_present():
    """Story 14: cross_team_read is documented as **enforced** (the gap is
    filled — the read gate logs cross-team reads, visible not silent), no
    longer advisory."""
    import inspect
    doc = inspect.getdoc(tiers.cross_team_read) or ""
    assert "Enforced" in doc
    assert "Advisory" not in doc
    assert "not yet enforced" not in doc
