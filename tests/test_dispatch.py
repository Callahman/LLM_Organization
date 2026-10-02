"""Unit tests for `runtime/dispatch.py` — Phase 4 top-down dispatch (Epic 4).

The leader decomposes the mission into department objectives -> department
heads into team objectives -> managers into IC tasks -> ICs do the work in
their team directories. Work propagates **up** in structured reports (bounded
summaries + artifact pointers); no tier is skipped.
"""

from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
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
