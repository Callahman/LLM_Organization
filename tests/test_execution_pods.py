"""the **execution pods (A/B/C)** + the **collaboration pod**
(IC + manager), verified end-to-end through the Phase 4-6 dispatch.

- **Execution pods (A/B/C)** (``kind="execution"``): the existing
  ``_check_pod_triggers`` logic — Trigger A (disagreement), Trigger B
  (cross-team), Trigger C (routing rule). (The trigger *firing* is covered in
  ``test_pod_triggers.py``; here we assert the pod's ``kind`` is
  ``"execution"`` + the capped-iterations behaviour.)

- **Collaboration pod** (IC + manager, ``kind="collaboration"``): when an IC's
  work flags a collaboration need (its output sets ``collaborate``), the
  **manager** sets up a 2-member pod (IC + manager), capped at
  ``collaboration_pod_rounds``; the IC then **retries** its work with the
  pod's outcome. A no-``collaborate`` IC forms no collaboration pod.

These tests drive the production ``dispatch`` (``runtime.dispatch``) with a
``StubBackend`` so the pod formation is verified exactly as the code runs it.
"""

from __future__ import annotations

import os

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import OrgState
from runtime.dispatch import dispatch
from runtime.pods import POD_KIND_DEFAULT_ROUNDS


def _role(rid, architype, department="", team="", reports_to=None):
    return Role(id=rid, architype=architype, department=department, team=team,
                reports_to=reports_to)


def _org():
    """leader -> head (analytics) -> manager (pipelines) -> 1 IC (ic1)."""
    org = OrgState(history_dir="history")
    leader = make_leader()
    head = _role("head_analytics", "department_head", "analytics")
    mgr = _role("mgr1", "manager", "analytics", "pipelines", "head_analytics")
    ic1 = _role("ic1", "ic", "analytics", "pipelines", "mgr1")
    for r in (leader, head, mgr, ic1):
        org.add_role(r)
    return org, leader


def _scripts(collaborate=False, cross_team=False):
    """The per-role scripts for a dispatch with one team (mgr1) and one IC.

    The IC's work output sets ``collaborate`` when ``collaborate`` is True
    (triggering the collaboration pod). ``cross_team`` marks the team objective
    (trigger B -> an execution pod).

    Script order per role (each entry is consumed in order by the StubBackend;
    the last entry is reused once the script is exhausted):

    - leader: [decomposition, leader+head pod (starter: agenda + close)]
    - head: [leader+head pod (member: 2 speaks), policy,
               decomposition (team_objectives),
               head+manager pod (starter: agenda + close)]
    - mgr1: [head+manager pod (member: 2 speaks),
               decomposition (ic_tasks),
               manager+ic pod (starter AND member: agenda + 2 speaks + close),
               collaboration pod (starter: agenda + 3 speaks + close)
                (only when `collaborate`),
               execution pod (starter: agenda + 3 speaks + close)]
    - ic1: [manager+ic pod (member: 2 speaks), work output,
               collaboration pod (member: 3 speaks) + retry work output
                (only when `collaborate`),
                execution pod (member: speak, reused for later rounds)]
    """
    team_objectives = [{"manager_id": "mgr1", "objective": "build the ETL"}]
    if cross_team:
        team_objectives[0]["cross_team"] = True

    ic_work = {"summary": "extractor done",
               "work_path": "departments/analytics/pipelines/extractor.md"}
    if collaborate:
        ic_work["collaborate"] = "need the schema team to validate the output"
    ic_retry = {"summary": "extractor done (with collaboration)",
                "work_path": "departments/analytics/pipelines/extractor.md"}

    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
        # leader+head pod (leader is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify the department's mission"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    backend.set_script("head_analytics", [
        # leader+head pod (head is a member): 2 speaks.
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        # The head's policy (its main call, Phase 4).
        {"policy": "ALWAYS use schema v2.", "policy_summary": "schema v2"},
        # The head's decomposition (Phase 4).
        {"decomposition": {"team_objectives": team_objectives}},
        # head+manager pod (head is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify the team's mission"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    # mgr1: the manager+ic clarification pod consumes FOUR manager invokes —
    # the manager is both the starter AND a member (agenda + one speak per
    # round, 2 rounds = the clarification kind default, + close). The
    # collaboration-pod entries are scripted only when the IC's work flags a
    # collaboration need (otherwise the execution pod's entries would be
    # misaligned).
    mgr_script = [
        # head+manager pod (manager is a member): 2 speaks.
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        # The manager's decomposition (its main call, Phase 5).
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"}]}},
        # manager+ic pod (manager is the starter AND a member):
        # agenda + 2 round speaks + close.
        {"summary": "agenda set", "agenda": "clarify ic1's task"},
        {"summary": "mgr ic r1"},
        {"summary": "mgr ic r2"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ]
    if collaborate:
        # collaboration pod (manager is the starter): agenda + speaks + close.
        # (Distinct summaries so the deadlock detector does not cut the pod
        # short; the last entry is reused if the pod runs more rounds.)
        mgr_script += [
            {"summary": "collab agenda", "agenda": "plan the collaboration"},
            {"summary": "collab m1"},
            {"summary": "collab m2"},
            {"summary": "collab m3"},
            {"summary": "collab close", "decision": "validate with schema team",
             "rationale": "agreed", "open_items": []},
        ]
    # execution pod (manager is the starter): agenda + speaks + close.
    mgr_script += [
        {"summary": "exec agenda", "agenda": "resolve the cross-team question"},
        {"summary": "exec m1"},
        {"summary": "exec m2"},
        {"summary": "exec m3"},
        {"summary": "exec close", "decision": "approve schema v2",
         "rationale": "backwards compatible", "open_items": []},
    ]
    backend.set_script("mgr1", mgr_script)
    ic_script = [
        # manager+ic pod (ic1 is a member): 2 speaks.
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        # The IC's work (its main call, Phase 6) -- sets `collaborate` when
        # requested.
        ic_work,
    ]
    if collaborate:
        # collaboration pod (ic1 is a member): speaks (distinct so the
        # deadlock detector does not cut the pod short; the last entry is
        # reused if the pod runs more rounds).
        ic_script += [
            {"summary": "collab i1"},
            {"summary": "collab i2"},
            {"summary": "collab i3"},
        ]
        # The IC's retry work (after the collaboration pod).
        ic_script.append(ic_retry)
    # execution pod (ic1 is a member): speak (reused for later rounds).
    ic_script.append({"summary": "I support schema v2"})
    backend.set_script("ic1", ic_script)
    return backend


def _collab_pods(pods):
    return [p for p in pods if p.kind == "collaboration"]


def _exec_pods(pods):
    return [p for p in pods if p.kind == "execution"]


# --- The collaboration pod (IC + manager) -----------------------------------

def test_collaboration_pod_forms_when_ic_needs_help(tmp_path):
    org, leader = _org()
    backend = _scripts(collaborate=True)
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"}, pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    # The collaboration pod formed: IC + manager, kind="collaboration".
    collab = _collab_pods(pods)
    assert len(collab) == 1
    pod = collab[0]
    assert pod.kind == "collaboration"
    assert pod.starter.id == "mgr1"
    assert {m.id for m in pod.members} == {"mgr1", "ic1"}
    assert pod.rounds >= 1
    assert pod.decision == "validate with schema team"


def test_collaboration_pod_capped_iterations():
    # The collaboration pod's default capped round count is 3 (the kind
    # default), and the config knob overrides it.
    assert POD_KIND_DEFAULT_ROUNDS["collaboration"] == 3


def test_collaboration_pod_retry_feeds_ic_work(tmp_path):
    # After the collaboration pod, the IC retries its work with the pod's
    # outcome (the retry context includes the pod's decision).
    org, leader = _org()
    backend = _scripts(collaborate=True)
    dispatch(backend, org, leader, {"purpose": "a pipeline"},
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    # The IC's retry work context includes the collaboration pod's decision.
    ic_ctxs = [ctx for rid, ctx in backend.calls if rid == "ic1"]
    # The first IC context is the manager+ic clarification pod speak; the work
    # contexts are the ones that name the task. The retry work context includes
    # the collaboration pod's decision ("validate with schema team").
    assert any("validate with schema team" in ctx for ctx in ic_ctxs)


def test_no_collaborate_no_collaboration_pod(tmp_path):
    # When the IC's work does not flag a collaboration need, no collaboration
    # pod forms.
    org, leader = _org()
    backend = _scripts(collaborate=False)
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"}, pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert _collab_pods(pods) == []


# --- The execution pods (A/B/C) ---------------------------------------------

def test_execution_pod_kind_is_execution(tmp_path):
    # A cross-team objective (trigger B) forms an execution pod with
    # kind="execution" (the default).
    org, leader = _org()
    backend = _scripts(cross_team=True)
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"}, pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    exec_pods = _exec_pods(pods)
    assert len(exec_pods) == 1
    pod = exec_pods[0]
    assert pod.kind == "execution"
    assert "triggers: B" in pod.topic
    assert pod.starter.id == "mgr1"
    assert {m.id for m in pod.members} == {"mgr1", "ic1"}
    assert pod.decision == "approve schema v2"


def test_execution_pod_capped_iterations():
    # The execution pod's default capped round count is 3 (the kind default).
    assert POD_KIND_DEFAULT_ROUNDS["execution"] == 3


def test_collaboration_and_execution_pods_coexist(tmp_path):
    # A cross-team objective where the IC also needs collaboration: BOTH a
    # collaboration pod (IC + manager) and an execution pod (trigger B) form.
    org, leader = _org()
    backend = _scripts(collaborate=True, cross_team=True)
    pods = []
    dispatch(backend, org, leader, {"purpose": "a pipeline"}, pods_out=pods,
             artifacts_dir=os.path.join(str(tmp_path), "pods", "artifacts"))
    assert len(_collab_pods(pods)) == 1
    assert len(_exec_pods(pods)) == 1
    # The collaboration pod (IC + manager) is distinct from the execution pod.
    assert _collab_pods(pods)[0].decision == "validate with schema team"
    assert _exec_pods(pods)[0].decision == "approve schema v2"
