"""Story 8 (Config consumption) — every .env knob is consumed or dropped.

(a) A plumb-ed knob (POD_MAX_ROUNDS) actually reaches its consumer (run_pod).
(b) A dropped knob (POD_MIN_ROLES) triggers the "unused .env key" warning
    (visible, not silently ignored).
"""

from __future__ import annotations

from roles.base import Role
from runtime.org import OrgState
from runtime.llm import StubBackend


def _role(rid, architype, department="", team="", reports_to=None):
    return Role(id=rid, architype=architype, department=department,
                team=team, reports_to=reports_to)


def _roles():
    head = _role("head", "department_head", "analytics")
    mgr = _role("mgr", "manager", "analytics", "pipelines", "head")
    ic = _role("ic", "ic", "analytics", "pipelines", "mgr")
    return head, mgr, ic


def test_pod_max_rounds_plumbed(monkeypatch, tmp_path):
    """Set POD_MAX_ROUNDS=5 in the env; assert the config dict has
    pod_max_rounds == 5 AND a run_pod call uses it (via a stub that records
    max_rounds)."""
    monkeypatch.setenv("POD_MAX_ROUNDS", "5")
    from runtime.config import load_config
    config = load_config()
    assert config["pod_max_rounds"] == 5
    # A run_pod call uses it (via a stub that records max_rounds).
    import runtime.dispatch as d
    head, mgr, ic = _roles()
    org = OrgState(history_dir=str(tmp_path))
    for r in (head, mgr, ic):
        org.add_role(r)
    backend = StubBackend()
    recorded = []
    def fake_run_pod(backend, pod, max_rounds=3, transcripts_dir=None, **kw):
        recorded.append(max_rounds)
        pod.decision = "ok"
        return pod
    monkeypatch.setattr(d, "run_pod", fake_run_pod)
    d._check_pod_triggers(
        backend, org, mgr, ["ic"],
        {"cross_team": True, "objective": "test"},
        [], [], [], [], None, str(tmp_path), str(tmp_path),
        config=config,
    )
    # The run_pod call uses max_rounds=5 (the config value, not the default 3).
    assert 5 in recorded


def test_dropped_knob_warns(monkeypatch, capsys):
    """Set a dropped knob in the env; assert the "unused .env key" warning is
    printed (capture stderr)."""
    import runtime.config as c
    # Mock _read_env_file_keys to return the dropped knob (POD_MIN_ROLES is no
    # longer in ENV_TO_CONFIG, so the "unused .env key" warning fires).
    monkeypatch.setattr(c, "_read_env_file_keys", lambda: {"POD_MIN_ROLES"})
    c.load_config()
    captured = capsys.readouterr()
    assert "unused .env key: POD_MIN_ROLES" in captured.err
