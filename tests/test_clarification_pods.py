"""Story 4 + Story 5 — the pod types, capped iterations, the reporting /
clarification pods, and the clarification -> policy ordering.

Story 4: a pod has a **type** (``kind``: clarification / reporting / headcount /
execution / collaboration) that drives the **default capped round count** (the
pod runs for a bounded number of iterations, then the initiator returns a
result). The **reporting pods** (Phase 7: ic->manager, manager->head,
head->leader) and the **clarification pods** (leader+head, head+manager,
manager+ic) are 2-member parent+child pods.

Story 5: the department policy is authored **after** the leader+head
clarification pod (the policy reflects the clarified mission; the pod -> policy
sequencing is strict).

This file tests the pod kind, the capped iterations, the kind recording in the
transcript / artifact, the config knobs, the clarification -> policy context,
and the parent+child pod formation (using the production code's exact call).
"""

from __future__ import annotations

import json

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import OrgState
from runtime.pods import (
    POD_KIND_DEFAULT_ROUNDS,
    Pod,
    form_pod,
    run_pod,
    write_decision_artifact,
    write_transcripts,
)
from runtime.dispatch_common import _policy_ctx, generate_head_policies


def _ic(rid, team, reports_to):
    return Role(id=rid, architype="ic", department="analytics",
                team=team, reports_to=reports_to)


def _mgr(rid, team, reports_to):
    return Role(id=rid, architype="manager", department="analytics",
                team=team, reports_to=reports_to)


def _head(rid, department):
    return Role(id=rid, architype="department_head", department=department)


# --- The pod kind (type) -----------------------------------------------------

def test_pod_kind_defaults_to_execution():
    # A pod's `kind` defaults to "execution" (the existing A/B/C pods).
    leader = make_leader()
    head = _head("head", "analytics")
    pod = Pod(id="pod_test", starter=leader, members=[head], topic="test")
    assert pod.kind == "execution"


def test_form_pod_kind_passthrough():
    # form_pod passes the `kind` through to the Pod.
    leader = make_leader()
    head1 = Role(id="head1", architype="department_head", department="analytics", team="pipelines")
    head2 = Role(id="head2", architype="department_head", department="analytics", team="pipelines")  # same team -> gate passes
    roles = {"leader": leader, "head1": head1, "head2": head2}
    pod = form_pod(roles, "leader", ["head1", "head2"], "test",
                   kind="clarification")
    assert pod.kind == "clarification"


def test_pod_kind_default_rounds():
    # The default capped round count per pod kind.
    assert POD_KIND_DEFAULT_ROUNDS["clarification"] == 2
    assert POD_KIND_DEFAULT_ROUNDS["reporting"] == 2
    assert POD_KIND_DEFAULT_ROUNDS["headcount"] == 3
    assert POD_KIND_DEFAULT_ROUNDS["execution"] == 3
    assert POD_KIND_DEFAULT_ROUNDS["collaboration"] == 3


# --- Capped iterations -------------------------------------------------------

def _two_member_pod_roles():
    # ic1 reports to mgr1 (one reporting line) -> a valid 2-member pod.
    ic1 = _ic("ic1", "pipelines", "mgr1")
    mgr1 = _mgr("mgr1", "pipelines", "head")
    return {"ic1": ic1, "mgr1": mgr1}


def test_run_pod_capped_by_kind(tmp_path):
    # Story 4 (capped iterations): a pod with no explicit max_rounds runs for
    # the pod's **kind** default (the clarification pod is capped at 2 rounds).
    roles = _two_member_pod_roles()
    backend = StubBackend()
    pod = form_pod(roles, "ic1", ["ic1", "mgr1"], "test", kind="clarification")
    backend.set_script("ic1", [
        {"agenda": "a", "summary": "agenda"},
        {"summary": "s1"},
        {"summary": "s2"},
        {"decision": "d", "rationale": "r", "open_items": []},
    ])
    backend.set_script("mgr1", [
        {"summary": "m1"},
        {"summary": "m2"},
    ])
    run_pod(backend, pod, max_rounds=None)
    # The clarification pod is capped at 2 rounds (the kind default).
    assert pod.rounds == 2


def test_run_pod_explicit_max_rounds_override(tmp_path):
    # An explicit max_rounds overrides the per-kind default.
    roles = _two_member_pod_roles()
    backend = StubBackend()
    pod = form_pod(roles, "ic1", ["ic1", "mgr1"], "test", kind="clarification")
    backend.set_script("ic1", [
        {"agenda": "a", "summary": "agenda"},
        {"summary": "s1"},
        {"summary": "s2"},
        {"decision": "d", "rationale": "r", "open_items": []},
    ])
    backend.set_script("mgr1", [
        {"summary": "m1"},
        {"summary": "m2"},
    ])
    run_pod(backend, pod, max_rounds=1)
    # The explicit max_rounds=1 overrides the kind default (2).
    assert pod.rounds == 1


# --- The kind is recorded in the transcript / artifact -----------------------

def test_write_transcripts_records_kind(tmp_path):
    # The pod's kind is recorded in the transcript markdown.
    roles = _two_member_pod_roles()
    pod = form_pod(roles, "ic1", ["ic1", "mgr1"], "test", kind="reporting")
    base = write_transcripts(pod, transcripts_dir=str(tmp_path))
    md = open(base + ".md", encoding="utf-8").read()
    assert "- kind: reporting" in md


def test_write_decision_artifact_records_kind(tmp_path):
    # The pod's kind is recorded in the decision artifact.
    roles = _two_member_pod_roles()
    pod = form_pod(roles, "ic1", ["ic1", "mgr1"], "test", kind="headcount")
    pod.decision = "some decision"
    base = write_decision_artifact(pod, artifacts_dir=str(tmp_path))
    artifact = json.load(open(base + ".json", encoding="utf-8"))
    assert artifact["kind"] == "headcount"


# --- Config -------------------------------------------------------------------

def test_clarification_pod_rounds_config(monkeypatch):
    monkeypatch.setenv("CLARIFICATION_POD_ROUNDS", "4")
    from runtime.config import load_config
    config = load_config()
    assert config["clarification_pod_rounds"] == 4


def test_reporting_pod_rounds_config(monkeypatch):
    monkeypatch.setenv("REPORTING_POD_ROUNDS", "3")
    from runtime.config import load_config
    config = load_config()
    assert config["reporting_pod_rounds"] == 3


def test_headcount_pod_rounds_config(monkeypatch):
    monkeypatch.setenv("HEADCOUNT_POD_ROUNDS", "5")
    from runtime.config import load_config
    config = load_config()
    assert config["headcount_pod_rounds"] == 5


# --- Story 5: the clarification -> policy ordering ----------------------------

def test_policy_ctx_includes_clarification():
    # The head's policy context includes the clarification pod's outcome.
    head = _head("head", "analytics")
    ctx = _policy_ctx(head, "mission digest", "existing policy", "directive",
                      clarification="the clarified mission")
    assert "Clarified mission" in ctx
    assert "the clarified mission" in ctx


def test_policy_ctx_no_clarification():
    # Without a clarification, the policy context has no clarification line.
    head = _head("head", "analytics")
    ctx = _policy_ctx(head, "mission digest", "existing policy", "directive")
    assert "Clarified mission" not in ctx


def test_generate_head_policies_passes_clarifications(tmp_path):
    # Story 5: the policy is authored AFTER the clarification pod -- the head's
    # context includes the clarification (the pod -> policy sequencing is strict).
    head = _head("head", "analytics")
    head.mandate = "do analytics"
    org = OrgState(history_dir=str(tmp_path))
    org.add_role(head)
    backend = StubBackend()
    backend.set_script("head", [
        {"policy": "# POLICY", "policy_summary": "summary",
         "summary": "s", "confidence": 0.9},
    ])
    clarifications = {"head": "the clarified mission"}
    policies = generate_head_policies(
        backend, org, [{"head_id": "head", "objective": "build the pipeline"}],
        "mission digest", departments_dir=str(tmp_path / "departments"),
        clarifications=clarifications,
    )
    # The head's context included the clarification.
    head_ctx = [ctx for (rid, ctx) in backend.calls if rid == "head"][0]
    assert "the clarified mission" in head_ctx
    assert policies["head"]["policy"] == "# POLICY"


# --- The parent+child pod formation (Story 4) --------------------------------
#
# The clarification pods (leader+head, head+manager, manager+ic) and the
# reporting pods (ic->manager, manager->head, head->leader) are 2-member
# parent+child pods. These tests use the **production code's exact call** so
# the formation is verified end-to-end: the parent is the starter and the child
# in the member list (a 2-member parent+child pod).

def test_leader_head_clarification_pod_forms():
    # Production code (run_plan) forms the leader+head clarification pod as:
    #   form_pod(roles_with_leader, leader.id, [leader.id, head.id], ..., kind="clarification")
    leader = make_leader()
    head = _head("head_analytics", "analytics")
    roles = {"leader": leader, "head_analytics": head}
    pod = form_pod(roles, "leader", ["leader", "head_analytics"],
                   "Clarify the department's mission (department analytics)",
                   kind="clarification")
    assert pod.kind == "clarification"
    assert pod.starter.id == "leader"


def test_head_manager_clarification_pod_forms():
    # Production code (run_plan) forms the head+manager clarification pod as:
    #   form_pod(org.roles, head.id, [head.id, manager.id], ..., kind="clarification")
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "pipelines", "head_analytics")
    roles = {"head_analytics": head, "mgr1": mgr}
    pod = form_pod(roles, "head_analytics", ["head_analytics", "mgr1"],
                   "Clarify the team's mission (team pipelines)",
                   kind="clarification")
    assert pod.kind == "clarification"
    assert pod.starter.id == "head_analytics"


def test_manager_ic_clarification_pod_forms():
    # Production code (run_staff) forms the manager+ic clarification pod as:
    #   form_pod(org.roles, manager.id, [manager.id, ic.id], ..., kind="clarification")
    mgr = _mgr("mgr1", "pipelines", "head_analytics")
    ic = _ic("ic1", "pipelines", "mgr1")
    roles = {"mgr1": mgr, "ic1": ic}
    pod = form_pod(roles, "mgr1", ["mgr1", "ic1"],
                   "Clarify the IC's task (task write the extractor)",
                   kind="clarification")
    assert pod.kind == "clarification"
    assert pod.starter.id == "mgr1"


def test_reporting_pod_forms():
    # Production code (session._run_reporting_pods) forms the reporting pod as:
    #   form_pod(roles, parent.id, [parent.id, role.id], ..., kind="reporting")
    mgr = _mgr("mgr1", "pipelines", "head_analytics")
    ic = _ic("ic1", "pipelines", "mgr1")
    roles = {"mgr1": mgr, "ic1": ic}
    pod = form_pod(roles, "mgr1", ["mgr1", "ic1"],
                   "ic1 reports to mgr1 (status / results / headcount)",
                   kind="reporting")
    assert pod.kind == "reporting"
    assert pod.starter.id == "mgr1"
