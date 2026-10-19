"""Unit tests for `runtime/dispatch.py` — Phase 4 top-down dispatch (Epic 4).

The leader decomposes the mission into department objectives -> department
heads into team objectives -> managers into IC tasks -> ICs do the work in
their team directories. Work propagates **up** in structured reports (bounded
summaries + artifact pointers); no tier is skipped.
"""

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.llm_api import OpenAIOutputError
from runtime.org import OrgState
from runtime.dispatch import dispatch, mission_digest


def _role(rid, architype, department="", team="", reports_to=None):
    return Role(id=rid, architype=architype, department=department, team=team,
                reports_to=reports_to)


def _org():
    """A full chain: leader -> head (analytics) -> manager (pipelines) -> IC."""
    org = OrgState(history_dir="history")
    leader = make_leader()
    head = _role("head_analytics", "department_head", "analytics")
    mgr = _role("mgr1", "manager", "analytics", "pipelines", "head_analytics")
    ic = _role("ic1", "ic", "analytics", "pipelines", "mgr1")
    for r in (leader, head, mgr, ic):
        org.add_role(r)
    return org, leader, head, mgr, ic


def test_dispatch_propagates_up(tmp_path):
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"},
        ]}},
    ])
    backend.set_script("head_analytics", [
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"},
        ]}},
    ])
    backend.set_script("mgr1", [
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"},
        ]}},
    ])
    backend.set_script("ic1", [
        {"summary": "extractor done",
         "work_path": "departments/analytics/pipelines/extractor.md"},
    ])

    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    reports = dispatch(backend, org, leader, mission)

    # The leader's view: one department report, carrying a **bounded** chain up
    # (each level reports a bounded summary of the level below; the leader
    # never sees the full work, only summaries + pointers).
    assert len(reports) == 1
    assert reports[0]["head"] == "head_analytics"
    dept = reports[0]["report"]
    assert dept["from"] == "head_analytics"
    # The department report carries the team report (from the manager) as a
    # bounded {from, summary}.
    team = dept["children"][0]
    assert team["from"] == "mgr1"
    # The manager's report carries a bounded summary of the IC work below it.
    assert "unit(s) reported up" in team["summary"]


def test_head_generates_policy_before_managers(tmp_path, monkeypatch):
    # Change 2: before a head decomposes into managers, it is invoked to
    # author its department POLICY (full markdown, written to disk) and a
    # POLICY_SUMMARY (for ICs). Managers get the full policy in their context;
    # ICs get the policy_summary (not the full policy).
    monkeypatch.chdir(tmp_path)  # isolate the policy file write
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
        # leader+head pod (leader is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify the department's mission"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    # The head's script: [pod speak, pod speak, policy, decomposition, pod
    # agenda, pod close] — the leader+head pod (head is a member: 2 speaks)
    # runs BEFORE the policy (its main call), then the head+manager pod (head
    # is the starter: agenda + close) runs after the decomposition.
    backend.set_script("head_analytics", [
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        {"policy": "ALWAYS use schema v2.", "policy_summary": "use schema v2",
         "summary": "policy set", "confidence": 0.9},
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"}]}},
        {"summary": "agenda set", "agenda": "clarify the team's mission"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    backend.set_script("mgr1", [
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"}]}},
        # manager+ic pod (mgr1 is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify ic1's task"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    backend.set_script("ic1", [
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        {"summary": "extractor done",
         "work_path": "departments/analytics/pipelines/extractor.md"},
    ])

    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    dispatch(backend, org, leader, mission)

    # The head was invoked for the policy (context mentions "POLICY").
    head_calls = [ctx for (rid, ctx) in backend.calls
                  if rid == "head_analytics"]
    assert any("author your department's POLICY" in ctx
               for ctx in head_calls)
    # The manager's context carries the FULL policy.
    mgr_calls = [ctx for (rid, ctx) in backend.calls if rid == "mgr1"]
    assert any("ALWAYS use schema v2." in ctx for ctx in mgr_calls)
    # The IC's context carries the policy_summary (NOT the full policy).
    ic_calls = [ctx for (rid, ctx) in backend.calls if rid == "ic1"]
    assert any("use schema v2" in ctx for ctx in ic_calls)
    assert not any("ALWAYS use schema v2." in ctx for ctx in ic_calls)
    # The policy was written to disk (isolated under tmp_path).
    policy_file = tmp_path / "departments" / "analytics" / "ANALYTICS_POLICY.md"
    assert policy_file.exists()
    assert "ALWAYS use schema v2." in policy_file.read_text(encoding="utf-8")


def test_dispatch_skips_missing_roles(tmp_path):
    # A department objective that references a head not in the org is skipped
    # (no tier is fabricated).
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "ghost_head", "objective": "nobody owns this"},
        ]}},
    ])
    reports = dispatch(backend, org, leader, {"purpose": "x"})
    assert reports == []


def test_dispatch_tolerates_head_string_decomposition(tmp_path):
    """The head's `decomposition` came back as a **string** (the exact Phase-4
    crash: `head_out['decomposition'].get(...)` -> AttributeError) — the
    dispatch must degrade to 'no team work' for that department, not crash."""
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"},
        ]}},
    ])
    # The head's decomposition is a string (the model ignored the forced
    # schema) — this is the exact shape that crashed dispatch.
    backend.set_script("head_analytics", [
        {"summary": "decompose",
         "decomposition": "Have the pipelines manager build the ETL."},
    ])
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    # Must NOT raise AttributeError — the department reports up with zero team
    # work (the head produced no team_objectives).
    reports = dispatch(backend, org, leader, mission)
    assert len(reports) == 1
    assert reports[0]["head"] == "head_analytics"


def test_dispatch_tolerates_leader_string_decomposition(tmp_path):
    """The leader's `decomposition` is a **string** (the model ignored the
    forced schema) — the dispatch degrades to 'no work to dispatch' (zero
    reports), not an AttributeError crash."""
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"summary": "decompose",
         "decomposition": "Assign the pipeline build to the analytics head."},
    ])
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    reports = dispatch(backend, org, leader, mission)
    assert reports == []


def test_decomposition_list_tolerates_shapes():
    """_decomposition_list() handles the shapes the real LLM free-forms: a dict
    (canonical), a bare list (collapsed), and a string/None (ignored)."""
    from runtime.dispatch import _decomposition_list
    # Canonical: a dict with the key.
    assert _decomposition_list(
        {"decomposition": {"team_objectives": [{"objective": "x"}]}},
        "team_objectives") == [{"objective": "x"}]
    # Collapsed: the object is a bare list.
    assert _decomposition_list(
        {"decomposition": [{"objective": "x"}]}, "team_objectives") == [{"objective": "x"}]
    # String: the model ignored the schema.
    assert _decomposition_list(
        {"decomposition": "have the manager build it"}, "team_objectives") == []
    # Missing: no decomposition key.
    assert _decomposition_list({}, "team_objectives") == []
    # Non-dict items are filtered out.
    assert _decomposition_list(
        {"decomposition": {"team_objectives": [{"objective": "x"}, "str", 5]}},
        "team_objectives") == [{"objective": "x"}]


def test_mission_digest_is_bounded():
    mission = {"purpose": "a pipeline", "success_criteria": ["works", "fast"],
               "scope": ["ETL"], "constraints": ["no new deps"]}
    digest = mission_digest(mission)
    # The digest includes purpose + success criteria + scope (bounded), not the
    # full markdown.
    assert "a pipeline" in digest
    assert "works" in digest
    assert "ETL" in digest


def test_dispatch_self_edit_gated(monkeypatch):
    # An IC proposes code_edits during the dispatch: the scoped one is applied,
    # the meta-rule one is refused (gated by the permission layer).
    import os
    import shutil
    from runtime import permissions as P
    tmp = os.path.join(P.ROOT, "dispatch_test_tmp")
    os.makedirs(tmp, exist_ok=True)
    monkeypatch.setattr(P, "ROOT", tmp)
    try:
        org, leader, head, mgr, ic = _org()
        backend = StubBackend()
        backend.set_script("leader", [
            {"decomposition": {"department_objectives": [
                {"head_id": "head_analytics", "objective": "build the pipeline"},
            ]}},
        ])
        backend.set_script("head_analytics", [
            {"decomposition": {"team_objectives": [
                {"manager_id": "mgr1", "objective": "build the ETL"},
            ]}},
        ])
        backend.set_script("mgr1", [
            {"decomposition": {"ic_tasks": [
                {"ic_id": "ic1", "task": "write the extractor"},
            ]}},
        ])
        # The IC proposes code_edits: a scoped one (applied) + a meta one (refused).
        backend.set_script("ic1", [
            {"summary": "extractor done",
             "work_path": "departments/analytics/pipelines/extractor.md",
             "code_edits": [
                 {"path": "departments/analytics/pipelines/extractor.py",
                  "content": "print('extractor')\n"},
                 {"path": "runtime/permissions.py", "content": "x"},
             ]},
        ])

        mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
                   "scope": ["ETL"]}
        reports = dispatch(backend, org, leader, mission)
        assert len(reports) == 1

        # The scoped edit was applied (the file exists in the sandbox).
        applied = os.path.join(tmp, "departments", "analytics", "pipelines", "extractor.py")
        assert os.path.exists(applied)
        # The meta edit was refused (the permission module is not created/changed).
        meta_path = os.path.join(tmp, "runtime", "permissions.py")
        assert not os.path.exists(meta_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- error containment (an IC hiccup must not kill the run) ----------------------

class _FlakyBackend:
    """A backend that fails the first `fail_times` invokes of the roles in
    `fail_roles` (raising OpenAIOutputError) and then delegates to `inner`.
    Records every (role_id, context) it sees (to assert the corrective
    retry's nudge was sent)."""

    def __init__(self, inner, fail_roles=(), fail_times=1):
        self.inner = inner
        self.fail_roles = set(fail_roles)
        self.fail_times = fail_times
        self.fails = {}
        self.contexts = []

    def invoke(self, role, context, reasoning=None, timeout=None, phase=None):
        self.contexts.append((role.id, context))
        if role.id in self.fail_roles:
            n = self.fails.get(role.id, 0)
            if n < self.fail_times:
                self.fails[role.id] = n + 1
                raise OpenAIOutputError("malformed reply (simulated)")
        return self.inner.invoke(
            role, context, reasoning=reasoning, timeout=timeout, phase=phase)


def _decomposition_scripts(backend):
    """The leader -> head -> manager decomposition scripts (a single IC task).

    The clarification pods (leader+head, head+manager, manager+ic) run BEFORE
    each main call, so each role's script prepends its pod participation (the
    starter does agenda + close; the member does 2 speaks) before its main-call
    entry.
    """
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"},
        ]}},
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
        {"policy": "ALWAYS use schema v2.", "policy_summary": "use schema v2",
         "summary": "policy set", "confidence": 0.9},
        # The head's decomposition (Phase 4).
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"},
        ]}},
        # head+manager pod (head is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify the team's mission"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])
    backend.set_script("mgr1", [
        # head+manager pod (manager is a member): 2 speaks.
        {"summary": "pod speak 1"},
        {"summary": "pod speak 2"},
        # The manager's decomposition (its main call, Phase 5).
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"},
        ]}},
        # manager+ic pod (mgr1 is the starter): agenda + close.
        {"summary": "agenda set", "agenda": "clarify ic1's task"},
        {"summary": "close", "decision": "clarified", "rationale": "ok",
         "open_items": []},
    ])


def test_dispatch_contains_persistent_ic_failure():
    """Error containment: an IC whose invoke fails (even after the corrective
    retry) is contained — the dispatch does NOT raise; it records the failure
    and continues (one IC hiccup must not kill the run)."""
    org, leader, head, mgr, ic = _org()
    inner = StubBackend()
    _decomposition_scripts(inner)
    # ic1 ALWAYS fails (the corrective retry fails too).
    backend = _FlakyBackend(inner, fail_roles={"ic1"}, fail_times=99)
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    # Must NOT raise — the run completes with the IC's failure contained.
    reports = dispatch(backend, org, leader, mission)
    assert len(reports) == 1
    dept = reports[0]["report"]
    assert dept["from"] == "head_analytics"
    # The manager's team report is present — the dispatch continued past the
    # failing IC (it did not abort the whole department).
    assert dept["children"][0]["from"] == "mgr1"
    # The corrective retry was attempted (the nudge context was sent).
    assert any(rid == "ic1" and "[RETRY]" in c
               for (rid, c) in backend.contexts)


def test_dispatch_ic_corrective_retry_recovers():
    """Error containment: an IC whose FIRST invoke fails but whose corrective
    retry succeeds is recovered — the dispatch completes and the IC's work is
    recorded (the nudge recovered it)."""
    org, leader, head, mgr, ic = _org()
    inner = StubBackend()
    _decomposition_scripts(inner)
    # Option A (pod ABORTS): the manager+ic pod's member speak is a bare call
    # that propagates out of run_pod and is contained by _run_contained_pod.
    # ic1's first failure is that pod speak (aborting the pod); its second
    # failure is the work invoke (first try). The corrective retry (nudge)
    # then succeeds, consuming work_output at index 0 — the script is just
    # [work_output] (the failed invokes consume no entries).
    inner.set_script("ic1", [
        {"summary": "extractor done",
         "work_path": "departments/analytics/pipelines/extractor.md"},
    ])
    # ic1 fails TWICE: its first invoke (the pod speak, aborting the pod) and
    # its second invoke (the work, first try) — the corrective retry (nudge)
    # then succeeds.
    backend = _FlakyBackend(inner, fail_roles={"ic1"}, fail_times=2)
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    reports = dispatch(backend, org, leader, mission)
    assert len(reports) == 1
    dept = reports[0]["report"]
    assert dept["from"] == "head_analytics"
    # The manager's team report reflects 1 unit reported up (the IC's work).
    assert "unit(s) reported up" in dept["children"][0]["summary"]
    # The first attempt failed, then the corrective retry (nudge) succeeded.
    assert any(rid == "ic1" and "[RETRY]" in c
               for (rid, c) in backend.contexts)


# --- _invoke_ic (the containment helper) ----------------------------------------

def test_invoke_ic_returns_error_on_persistent_failure():
    """_invoke_ic returns (None, error) when BOTH the initial invoke and the
    corrective retry fail — the error is a visible description (the caller
    records it in the upward report and continues)."""
    from runtime.dispatch import _invoke_ic
    org, leader, head, mgr, ic = _org()
    inner = StubBackend()
    backend = _FlakyBackend(inner, fail_roles={"ic1"}, fail_times=99)
    out, err = _invoke_ic(backend, ic, "ctx", reasoning=None,
                          timeout=None, phase=4)
    assert out is None
    assert err is not None
    assert "OpenAIOutputError" in err


def test_invoke_ic_recovers_on_corrective_retry():
    """_invoke_ic returns (output, None) when the corrective retry succeeds —
    the first failure is transparent to the caller."""
    from runtime.dispatch import _invoke_ic
    org, leader, head, mgr, ic = _org()
    inner = StubBackend()
    inner.set_script("ic1", [{"summary": "done", "confidence": 0.9}])
    backend = _FlakyBackend(inner, fail_roles={"ic1"}, fail_times=1)
    out, err = _invoke_ic(backend, ic, "ctx", reasoning=None,
                          timeout=None, phase=4)
    assert err is None
    assert out == {"summary": "done", "confidence": 0.9}


# --- [content] / policy / mission wiring (the audit fixes) -------------------

def test_head_output_schema_carries_policy_fields():
    # Root-cause fix: the head's forced submit_output schema must carry the
    # `policy` + `policy_summary` fields — otherwise the department policy the
    # head authors is silently dropped at submit time (the "says it will, but
    # doesn't" symptom).
    from roles.worker import HEAD_OUTPUT_SCHEMA
    props = HEAD_OUTPUT_SCHEMA.get("properties", {})
    assert "policy" in props
    assert "policy_summary" in props


def test_policy_missing_event_logged(tmp_path, monkeypatch):
    # A visible failure state (never silent): when a head returns NO policy
    # (the model ignored the forced schema), a `policy_missing` org event is
    # logged and the head proceeds to decomposition.
    monkeypatch.chdir(tmp_path)  # isolate the policy file write
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
    ])
    # The head's first invoke (the policy generation) returns NO policy field.
    backend.set_script("head_analytics", [
        {"summary": "no policy field", "confidence": 0.9},
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"}]}},
    ])
    backend.set_script("mgr1", [
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"}]}},
    ])
    backend.set_script("ic1", [
        {"summary": "extractor done"}])
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    dispatch(backend, org, leader, mission)
    # The `policy_missing` org event was logged (visible, never silent). The
    # head id is the event's `initiator` (the `target` is None — the head
    # reports against itself).
    assert any(
        e.get("kind") == "policy_missing"
        and e.get("initiator") == "head_analytics"
        for e in org.events
    )


def test_manager_ic_context_carries_mission(tmp_path, monkeypatch):
    # The mission digest (the org's goal) is passed DOWN to managers and ICs
    # (not only the heads): the manager's and the IC's context carry the
    # mission.
    monkeypatch.chdir(tmp_path)  # isolate the policy file write
    org, leader, head, mgr, ic = _org()
    backend = StubBackend()
    backend.set_script("leader", [
        {"decomposition": {"department_objectives": [
            {"head_id": "head_analytics", "objective": "build the pipeline"}]}},
    ])
    backend.set_script("head_analytics", [
        {"policy": "ALWAYS use schema v2.", "policy_summary": "use schema v2",
         "summary": "policy set", "confidence": 0.9},
        {"decomposition": {"team_objectives": [
            {"manager_id": "mgr1", "objective": "build the ETL"}]}},
    ])
    backend.set_script("mgr1", [
        {"decomposition": {"ic_tasks": [
            {"ic_id": "ic1", "task": "write the extractor"}]}},
    ])
    backend.set_script("ic1", [
        {"summary": "extractor done"}])
    mission = {"purpose": "a data pipeline", "success_criteria": ["works"],
               "scope": ["ETL"]}
    dispatch(backend, org, leader, mission)
    # The manager's context carries the mission (its digest: purpose).
    mgr_calls = [ctx for (rid, ctx) in backend.calls if rid == "mgr1"]
    assert any("a data pipeline" in ctx for ctx in mgr_calls)
    # The IC's context carries the mission (its digest: purpose).
    ic_calls = [ctx for (rid, ctx) in backend.calls if rid == "ic1"]
    assert any("a data pipeline" in ctx for ctx in ic_calls)
