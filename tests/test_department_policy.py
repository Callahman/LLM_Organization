"""Story 9 — the **department policy** is authored by the **department head**
(NOT the IC), **after** the leader+head clarification pod.

The department policy is a **department-level artifact** owned by the
``department_head``: in Phase 4 (pre-decomposition) every department head is
invoked to author its department POLICY (full markdown, written to
``departments/<dept>/<DEPT>_POLICY.md``) and a POLICY_SUMMARY (the key points
ICs are given directly). The IC does **not** author the policy — it receives
the policy summary as context for its work. The policy is authored **after**
the leader+head clarification pod (the pod's clarification is passed to the
policy context; the pod → policy sequencing is strict).

Driven with a ``StubBackend`` (offline).
"""

from __future__ import annotations

import os

from roles.base import Role
from runtime.llm import StubBackend
from runtime.org import OrgState
from runtime.dispatch_common import generate_head_policies


def _head(rid, department):
    return Role(id=rid, architype="department_head", department=department)


def _mgr(rid, team, reports_to):
    return Role(id=rid, architype="manager", department="analytics",
                team=team, reports_to=reports_to)


def _ic(rid, team, reports_to):
    return Role(id=rid, architype="ic", department="analytics", team=team,
                reports_to=reports_to)


def _org_with_head_and_ic(tmp_path):
    """An org with one department head (analytics) + a manager + an IC (the
    IC is the role that must NOT author the policy)."""
    org = OrgState(history_dir=str(tmp_path))
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "pipelines", "head_analytics")
    ic1 = _ic("ic1", "pipelines", "mgr1")
    for r in (head, mgr, ic1):
        org.add_role(r)
    return org, head, ic1


def _policy_script():
    return [{"policy": "# ANALYTICS POLICY", "policy_summary": "weekly reports",
             "summary": "s", "confidence": 0.9}]


# --- The head (NOT the IC) authors the policy --------------------------------

def test_head_authors_policy_not_ic(tmp_path):
    # The department head is invoked to author the policy; the IC is NOT
    # invoked (the IC receives the policy summary, it does not author the
    # policy).
    org, head, ic1 = _org_with_head_and_ic(tmp_path)
    backend = StubBackend()
    backend.set_script(head.id, _policy_script())
    policies = generate_head_policies(
        backend, org,
        [{"head_id": head.id, "objective": "build the pipeline"}],
        "mission digest",
        departments_dir=os.path.join(str(tmp_path), "departments"),
    )
    # The head was invoked (its output is the policy).
    invoked = {rid for (rid, _) in backend.calls}
    assert head.id in invoked
    # The IC was NOT invoked (it does not author the policy).
    assert ic1.id not in invoked
    # The returned policy is the head's.
    assert policies[head.id]["policy"] == "# ANALYTICS POLICY"
    assert policies[head.id]["policy_summary"] == "weekly reports"


def test_manager_not_invoked_for_policy(tmp_path):
    # The manager is also not the policy author — only the department head is
    # invoked by generate_head_policies.
    org = OrgState(history_dir=str(tmp_path))
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "pipelines", "head_analytics")
    for r in (head, mgr):
        org.add_role(r)
    backend = StubBackend()
    backend.set_script(head.id, _policy_script())
    generate_head_policies(
        backend, org,
        [{"head_id": head.id, "objective": "build the pipeline"}],
        "mission digest",
        departments_dir=os.path.join(str(tmp_path), "departments"),
    )
    invoked = {rid for (rid, _) in backend.calls}
    assert head.id in invoked
    assert mgr.id not in invoked


# --- The policy is department-scoped -----------------------------------------

def test_policy_written_to_department_dir(tmp_path):
    # The policy is a department-level artifact: it is written to
    # departments/<dept>/<DEPT>_POLICY.md (the department's directory).
    org, head, _ = _org_with_head_and_ic(tmp_path)
    backend = StubBackend()
    backend.set_script(head.id, _policy_script())
    departments_dir = os.path.join(str(tmp_path), "departments")
    generate_head_policies(
        backend, org,
        [{"head_id": head.id, "objective": "build the pipeline"}],
        "mission digest",
        departments_dir=departments_dir,
    )
    policy_path = os.path.join(departments_dir, "analytics", "ANALYTICS_POLICY.md")
    assert os.path.exists(policy_path)
    content = open(policy_path, encoding="utf-8").read()
    assert "# ANALYTICS POLICY" in content


def test_policy_missing_is_visible(tmp_path):
    # A head that returns no policy is a visible failure state (the org logs a
    # "policy_missing" event; the policy file stays a stub) — never silent.
    org, head, _ = _org_with_head_and_ic(tmp_path)
    backend = StubBackend()
    backend.set_script(head.id, [{"summary": "no policy", "confidence": 0.5}])
    departments_dir = os.path.join(str(tmp_path), "departments")
    policies = generate_head_policies(
        backend, org,
        [{"head_id": head.id, "objective": "build the pipeline"}],
        "mission digest",
        departments_dir=departments_dir,
    )
    assert policies[head.id]["policy"] == ""
    # The org logged the visible "policy_missing" event.
    assert any(ev.get("kind") == "policy_missing" for ev in org.events)


# --- The policy is authored AFTER the leader+head pod ------------------------

def test_policy_authored_after_leader_head_pod(tmp_path):
    # Story 5: the policy is authored AFTER the leader+head clarification pod —
    # the pod's clarification is passed to the policy context (the pod → policy
    # sequencing is strict). When the caller passes the pod's clarification,
    # the head's policy context includes it.
    org, head, _ = _org_with_head_and_ic(tmp_path)
    backend = StubBackend()
    backend.set_script(head.id, _policy_script())
    # The leader+head pod's clarification (the caller formed the pod and passes
    # its outcome here).
    clarifications = {head.id: "the clarified mission from the leader+head pod"}
    generate_head_policies(
        backend, org,
        [{"head_id": head.id, "objective": "build the pipeline"}],
        "mission digest",
        departments_dir=os.path.join(str(tmp_path), "departments"),
        clarifications=clarifications,
    )
    # The head's policy context included the pod's clarification.
    head_ctx = [ctx for (rid, ctx) in backend.calls if rid == head.id][0]
    assert "the clarified mission from the leader+head pod" in head_ctx


def test_no_clarification_for_required_depts(tmp_path):
    # A required governance dept gets no clarification (no leader+head
    # clarification pod) — its policy context has no clarification line.
    org = OrgState(history_dir=str(tmp_path))
    head = _head("head_safety", "safety")
    org.add_role(head)
    backend = StubBackend()
    backend.set_script(head.id, _policy_script())
    # No clarification passed (a required dept gets none).
    generate_head_policies(
        backend, org, [],
        "mission digest",
        departments_dir=os.path.join(str(tmp_path), "departments"),
        clarifications={},
    )
    head_ctx = [ctx for (rid, ctx) in backend.calls if rid == head.id][0]
    assert "Clarified mission" not in head_ctx
