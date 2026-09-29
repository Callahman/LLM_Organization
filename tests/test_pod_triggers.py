"""Unit tests for the **pods A/B/C multi-trigger** (Step 4) — the trigger +
carry-over control path wired into the Phase 4 dispatch.

- **A (disagreement)**: conflicting recommendations across the IC work
  outputs (`detect_disagreement` reads the `recommendation` field — the
  dispatch keeps the full IC outputs, not just the upward reports).
- **B (cross-team)**: a `cross_team`-marked team objective (optionally
  naming the other teams' roles in `cross_team_with`).
- **C (routing rule)**: a task type matching the routing-rule config.

After the pod runs, the decision is carried **all three ways**:
(1) written to `pods/artifacts/` (+ the HistoryStore decision journal),
(2) carried up to the leader's Phase 5 synthesis prompt, and
(3) seeded into the members' memory as a cross-team `pod:<id>` entry.
"""

import os

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import OrgState
from runtime.dispatch import dispatch
from runtime.session import Session


def _role(rid, architype, department="", team="", reports_to=None):
    return Role(id=rid, architype=architype, department=department, team=team,
                reports_to=reports_to)


def _org():
    """leader -> head (analytics) -> manager (pipelines) -> 2 ICs."""
    org = OrgState(history_dir="history")
    leader = make_leader()
    head = _role("head_analytics", "department_head", "analytics")
    mgr = _role("mgr1", "manager", "analytics", "pipelines", "head_analytics")
    ic1 = _role("ic1", "ic", "analytics", "pipelines", "mgr1")
    ic2 = _role("ic2", "ic", "analytics", "pipelines", "mgr1")
    for r in (leader, head, mgr, ic1, ic2):
        org.add_role(r)
    return org, leader


def _scripts(conflicting=False, cross_team=False, task_type=None,
             cross_team_with=None):
    """The per-role scripts for a dispatch with one team (mgr1) and two ICs.

    The manager's script is [decomposition, pod agenda, pod close]; each IC's
    is [work output, pod speak]. `conflicting` gives the IC work outputs
    conflicting recommendations (trigger A); `cross_team` marks the team
    objective (trigger B); `task_type` drives trigger C (with the
    routing-rule config).
    """
    team_objectives = [{"manager_id": "mgr1", "objective": "build the ETL"}]
    if cross_team:
        team_objectives[0]["cross_team"] = True
        if cross_team_with:
            team_objectives[0]["cross_team_with"] = cross_team_with
    if task_type:
        team_objectives[0]["task_type"] = task_type
    ic1_work = {"summary": "extractor done",
                "work_path": "departments/analytics/pipelines/extractor.md"}
    ic2_work = {"summary": "loader done",
                "work_path": "departments/analytics/pipelines/loader.md"}
    if conflicting:
        ic1_work["recommendation"] = "approve the schema"
        ic2_work["recommendation"] = "concern: the schema breaks the loader"
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
    ])
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": team_objectives}},
    ])
    backend.set_script("mgr1", [
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"},
            {"ic_id": "ic2", "task": "write the loader"},
        ]}},
        {"summary": "agenda set", "agenda": "resolve the team's open question"},
        {"summary": "close", "decision": "approve schema v2",
         "rationale": "backwards compatible", "open_items": []},
    ])
    backend.set_script("ic1", [ic1_work, {"summary": "I support schema v2"}])
    backend.set_script("ic2", [ic2_work, {"summary": "I have migration concerns"}])
    return backend


def test_trigger_a_disagreement_forms_pod(tmp_path):
    org, leader = _org()
    backend = _scripts(conflicting=True)
    pods = []
    artifacts_dir = os.path.join(str(tmp_path), "pods", "artifacts")
    reports = dispatch(backend, org, leader, {"purpose": "a pipeline"},
                       pods_out=pods, artifacts_dir=artifacts_dir)
    # The dispatch still returns the department reports (behavior intact).
    assert len(reports) == 1
    # Trigger A fired: one pod, formed + run + written.
    assert len(pods) == 1
    pod = pods[0]
    assert "triggers: A" in pod.topic
    assert pod.starter.id == "mgr1"
    assert {m.id for m in pod.members} == {"mgr1", "ic1", "ic2"}
    assert pod.rounds >= 1
    assert pod.decision == "approve schema v2"
    # The decision artifact is written to pods/artifacts/.
    assert os.path.exists(os.path.join(artifacts_dir, pod.id + ".json"))
    assert os.path.exists(os.path.join(artifacts_dir, pod.id + ".md"))


def test_trigger_b_cross_team_forms_pod(tmp_path):
    org, leader = _org()
    backend = _scripts(cross_team=True)
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"},
             pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert len(pods) == 1
    assert "triggers: B" in pods[0].topic
    assert pods[0].decision == "approve schema v2"


def test_trigger_b_cross_team_with_includes_other_team_roles(tmp_path):
    # A cross-team objective naming another team's manager + IC: they join
    # the pod (still a 1-tier spread).
    org, leader = _org()
    mgr2 = _role("mgr2", "manager", "analytics", "reports", "head_analytics")
    ic3 = _role("ic3", "ic", "analytics", "reports", "mgr2")
    org.add_role(mgr2)
    org.add_role(ic3)
    backend = _scripts(cross_team=True, cross_team_with=["mgr2", "ic3"])
    # The other team's roles need scripts for the pod speaks.
    backend.set_script("mgr2", [{"summary": "we can validate the schema"}])
    backend.set_script("ic3", [{"summary": "our reports team is fine with it"}])
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"},
             pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert len(pods) == 1
    assert {m.id for m in pods[0].members} == {"mgr1", "ic1", "ic2", "mgr2", "ic3"}


def test_trigger_c_routing_rule_forms_pod(tmp_path):
    org, leader = _org()
    backend = _scripts(task_type="evaluation")
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"},
             pods_out=pods,
             routing_rules=["evaluation"],
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert len(pods) == 1
    assert "triggers: C" in pods[0].topic


def test_no_trigger_no_pod(tmp_path):
    org, leader = _org()
    backend = _scripts()
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"},
             pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert pods == []


def test_pod_carry_over_three_ways(tmp_path):
    # A full session (Phases 1-3 once, 4-5 iterate): trigger A forms a pod in
    # Phase 4, and the decision is carried all three ways.
    backend = _scripts(conflicting=True)
    # The leader's script: Phase 1, 2, 3, then Phase 4, 5, 6 (one iteration;
    # Phase 6 says 'complete' -> the loop stops).
    backend.set_script("leader", [
        {"confidence": 0.9, "questions": []},
        {"mission_draft": {"purpose": "a data pipeline",
                           "success_criteria": ["works"]}},
        {"org_recommendation": {"department_heads": [
            {"id": "head_analytics", "department": "analytics"}]}},
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
        {"verdict": "complete"},  # Phase 5
        {"verdict": "complete"},  # Phase 6 -> stop
    ])
    user_answer_fn = lambda qs: "a weekly report"
    user_permission_fn = lambda draft: {"decision": "approve", "feedback": ""}
    approver_fn = lambda approver, action, role: {"decision": "approve",
                                                  "rationale": "ok"}
    artifacts_dir = os.path.join(str(tmp_path), "pods", "artifacts")
    session = Session(
        backend, make_leader(),
        config={"pod_artifacts_dir": artifacts_dir},
        history_dir=str(tmp_path),
    )
    result = session.run(
        "build a data pipeline",
        user_answer_fn, user_permission_fn, approver_fn,
        max_iterations=3,
    )
    assert result.status == "complete"
    # (0) The pod was formed and filled `self.pods`.
    assert len(result.pods) == 1
    pod = result.pods[0]
    assert pod.decision == "approve schema v2"
    # (1) The decision artifact is in pods/artifacts/.
    assert os.path.exists(os.path.join(artifacts_dir, pod.id + ".json"))
    assert os.path.exists(os.path.join(artifacts_dir, pod.id + ".md"))
    # (2) The decision is in the leader's Phase 5 synthesis prompt.
    phase5 = [ctx for rid, ctx in backend.calls
              if rid == "leader" and "PHASE 5" in ctx][-1]
    assert "POD DECISIONS" in phase5
    assert "approve schema v2" in phase5
    # (3) The decision is seeded into the members' memory with a `pod:<id>`
    #     source (the cross-team carry-over).
    memories = session.backend.role_memories
    for rid in ("mgr1", "ic1", "ic2"):
        assert any(
            e.source == f"pod:{pod.id}" and e.summary == "approve schema v2"
            for e in memories[rid].entries
        ), rid