"""Unit tests for `runtime/pods.py` — the §2.8 worked example end-to-end
(Epic 5 Definition of Done).

The IC's pod rejects the department head (2-tier spread); the manager's second
pod carries the first pod's **decision artifact** up; the IC (starter) manages
its own pod's conversation; both transcripts + artifacts land in
`pods/transcripts/` and `pods/artifacts/`.
"""

import os

from roles.base import Role
from runtime.llm import StubBackend
from runtime import pods
from runtime.org import OrgState


def _role(rid, architype, department="", team="", reports_to=None, personality=""):
    return Role(id=rid, architype=architype, department=department, team=team,
                reports_to=reports_to, personality=personality)


def _roles():
    head = _role("head_analytics", "department_head", "analytics", personality="Strategist")
    mgr = _role("mgr1", "manager", "analytics", "pipelines", "head_analytics", "Pragmatist")
    ic = _role("ic1", "ic", "analytics", "pipelines", "mgr1", "Pragmatist")
    return {"head_analytics": head, "mgr1": mgr, "ic1": ic}


def test_ic_pod_rejects_department_head():
    roles = _roles()
    try:
        pods.form_pod(roles, "ic1", ["ic1", "head_analytics"], "schema change")
        raise AssertionError("expected PodMembershipError")
    except pods.PodMembershipError as e:
        assert "spread" in str(e)


def test_worked_example_end_to_end(tmp_path):
    roles = _roles()
    backend = StubBackend()

    # The IC's pod: IC (starter) + manager. The IC manages the conversation.
    pod1 = pods.form_pod(roles, "ic1", ["ic1", "mgr1"], "schema change")
    # Script the starter (IC): agenda + close.
    backend.set_script("ic1", [
        {"summary": "agenda set", "agenda": "decide the schema change"},
        {"summary": "close", "decision": "approve schema v2",
         "rationale": "backwards compatible", "open_items": []},
    ])
    # Script the manager: one speak (repeats).
    backend.set_script("mgr1", [
        {"summary": "concerns about migration cost"},
    ])
    pods.run_pod(backend, pod1, max_rounds=2)
    assert pod1.decision == "approve schema v2"
    assert pod1.starter.id == "ic1"  # the IC (starter) managed it

    # Write pod1's transcripts + decision artifact.
    transcripts_dir = os.path.join(str(tmp_path), "transcripts")
    artifacts_dir = os.path.join(str(tmp_path), "artifacts")
    base = pods.write_transcripts(pod1, transcripts_dir=transcripts_dir)
    assert os.path.exists(base + ".jsonl")
    assert os.path.exists(base + ".md")
    artifact_base = pods.write_decision_artifact(pod1, artifacts_dir=artifacts_dir)
    assert os.path.exists(artifact_base + ".json")
    assert os.path.exists(artifact_base + ".md")

    # The manager's second pod (chained escalation): manager (starter) +
    # department head, carrying pod1's decision artifact.
    pod2 = pods.chained_pod(
        pod1,
        roles,
        "mgr1",
        ["mgr1", "head_analytics"],
        "approve schema v2 at the department level",
        first_artifact_path=artifact_base + ".md",
    )
    assert pod2.input_artifacts == [artifact_base + ".md"]
    # pod2 membership is valid (manager + head = 1-tier spread).
    from org import tiers
    assert tiers.validate_pod(pod2.members)[0]

    # Script pod2's starter (manager) + the head's speak.
    backend.set_script("mgr1", [
        {"summary": "agenda", "agenda": "approve schema v2"},
        {"summary": "close", "decision": "approved", "rationale": "ok", "open_items": []},
    ])
    backend.set_script("head_analytics", [
        {"summary": "no objections"},
    ])
    pods.run_pod(backend, pod2, max_rounds=2)
    assert pod2.decision == "approved"
    # The senior member (the head) shares the outcome out (up the line).
    assert pods.senior_member(pod2).id == "head_analytics"


def test_deadlock_detection(tmp_path):
    roles = _roles()
    backend = StubBackend()
    pod = pods.form_pod(roles, "ic1", ["ic1", "mgr1"], "topic")
    # The starter and the member produce IDENTICAL output every round ->
    # deadlock after round 1.
    backend.set_script("ic1", [
        {"summary": "same", "agenda": "a"},
        {"summary": "same", "decision": "d", "rationale": "r", "open_items": []},
    ])
    backend.set_script("mgr1", [
        {"summary": "same"},
    ])
    pods.run_pod(backend, pod, max_rounds=5)
    assert pod.rounds <= 2
    assert "deadlock" in pod.closed_reason


# --- Story 7 (A2/B13/B14): pod context & lifecycle bounding ----------------


def test_pod_ctx_token_bounded():
    # (a) Token bounding: a pod with many long speak entries (total well over
    # the budget) -> _pod_ctx output is <= the budget tokens (the transcript
    # is truncated) and the header is intact.
    roles = _roles()
    pod = pods.form_pod(roles, "ic1", ["ic1", "mgr1"], "topic")
    # Add many long speak entries (total well over the 4000-token budget).
    for i in range(40):
        pod.transcript.append(
            {"kind": "speak", "role": f"r{i}", "summary": "x" * 300})
    ctx = pods._pod_ctx(pod, "speak", budget_tokens=4000)
    from runtime.context import estimate_tokens
    # The output is <= the budget tokens (the agenda + the summaries that fit).
    assert estimate_tokens(ctx) <= 4000
    # The header is intact (it must survive).
    assert "POD" in ctx and pod.id in ctx


def test_chained_pod_skipped_on_empty_decision(tmp_path, monkeypatch):
    # (b) Chained pod skipped on empty decision: a first pod with an empty
    # decision -> the chained pod is not formed (assert via a stub that the
    # chained run_pod is not called).
    import runtime.dispatch as d
    roles = _roles()
    org = OrgState(history_dir=str(tmp_path))
    for r in roles.values():
        org.add_role(r)
    backend = StubBackend()
    calls = []

    def fake_run_pod(backend, pod, max_rounds=3, transcripts_dir=None, **kw):
        calls.append(pod.id)
        pod.decision = ""  # the first pod's decision is empty
        return pod

    monkeypatch.setattr(d, "run_pod", fake_run_pod)
    # The starter is the manager (reports_to = the head, the boss).
    d._check_pod_triggers(
        backend, org, roles["mgr1"], ["ic1"],
        {"cross_team": True, "objective": "test"},
        [], [], [],
        [], None,
        str(tmp_path), str(tmp_path),
    )
    # The chained pod is not formed (run_pod is called only once, for the
    # first pod).
    assert len(calls) == 1


def test_pod_wall_clock_budget(monkeypatch):
    # (c) Wall-clock budget: a pod that exceeds the budget closes early with
    # the budget-exceeded reason.
    import time
    roles = _roles()
    pod = pods.form_pod(roles, "ic1", ["ic1", "mgr1"], "topic")
    backend = StubBackend()
    backend.set_script("ic1", [
        {"summary": "agenda", "agenda": "a"},
        {"summary": "speak"},
        {"summary": "close", "decision": "d", "rationale": "r", "open_items": []},
    ])
    backend.set_script("mgr1", [{"summary": "speak"}])
    # Stub time.monotonic to simulate elapsed time (each call returns a larger
    # value, so the elapsed time quickly exceeds the budget).
    times = iter([0.0, 100.0, 200.0, 300.0, 400.0, 500.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(times))
    pods.run_pod(backend, pod, max_rounds=3, pod_wall_clock_seconds=50.0)
    # The pod is closed early with the budget-exceeded reason.
    assert pod.closed_reason == "pod wall-clock budget exceeded"
