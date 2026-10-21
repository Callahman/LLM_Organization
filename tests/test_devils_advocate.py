"""Unit tests for the "devil's advocate" role — a leader's direct
report / red-team auditor that institutes a formal "gut check" on the org's
outcomes.

The role:
- is **always created** in Org bootstrap (mandatory — even if the leader
  omits it from the proposal);
- has **cross-department read access** (one of the only roles that can read
  other departments' directories — the leader included, but the leader still
  cannot read code);
- **"listens" to any pod the leader is in AND any pod the heads are in**
  (it observes the deliberation — it is not a pod member);
- returns a **Phase-7 verdict** (`clean` / `flag: <findings>`) that Phase 8
  consumes (a `flag` forces a re-check / blocks a stop);
- is **skipped by the reporting pods** (an ic→leader reporting pod would span
  3 tiers and violate the <=1 tier-spread bound — it is invoked directly in
  Phase 7 instead).
"""

from org import tiers
from org.tiers import DEVILS_ADVOCATE_ROLE
from roles.base import Role
from roles.leader import make_leader
from runtime.llm import StubBackend
from runtime.org import OrgState, bootstrap
from runtime.mission import MissionResult
from runtime.intake import IntakeResult
from runtime.pods import (
    form_pod,
    devils_advocate_listens,
    log_devils_advocate_listening,
    PodMembershipError,
)
from runtime.session import Session


# --- Helpers ----------------------------------------------------------------

def _da_role(leader_id="leader"):
    """The devil's advocate role (a red-team auditor reporting to the leader)."""
    return Role(id=DEVILS_ADVOCATE_ROLE, architype="ic",
                sub_architype="red_team_auditor", personality="Guardian",
                reports_to=leader_id)


def _head(rid, dept):
    return Role(id=rid, architype="department_head", department=dept)


def _mgr(rid, dept, team, reports_to):
    return Role(id=rid, architype="manager", department=dept, team=team,
                sub_architype=team, reports_to=reports_to)


def _ic(rid, dept, team, reports_to):
    return Role(id=rid, architype="ic", department=dept, team=team,
                sub_architype=team, reports_to=reports_to)


def _approve_all(approver_type, action, target):
    return {"decision": "approve", "rationale": "ok"}


def _mission():
    return MissionResult(approved=True, attempts=1, version=1,
                         mission_path="MISSION.md")


def _intake():
    return IntakeResult(confident=True, converged=True, rounds=1,
                        confidence=0.9)


def _session_with_da(tmp_path, da_verdict, leader_decision, include_da=True):
    """A Session with a scripted devil's advocate verdict (Phase 7) + leader
    decision (Phase 8). The DA role + a department head are added to the org
    (``include_da=False`` builds the org without the role — the missing-role
    case)."""
    backend = StubBackend()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    backend.set_script(DEVILS_ADVOCATE_ROLE,
                       [{"verdict": da_verdict, "findings": "..."}])
    backend.set_script("leader", [{"verdict": leader_decision}])
    if include_da:
        session.org.add_role(_da_role())
    session.org.add_role(_head("head_analytics", "analytics"))
    return session


# --- A1: the role is always created in bootstrap ----------------------------

def test_bootstrap_always_creates_devils_advocate(tmp_path):
    """The role is **always created** in Org bootstrap — even when the leader
    proposes only a single operational department and omits the role
    entirely."""
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    backend = StubBackend()
    # The Leader proposes a single operational department (the DA role is NOT
    # in the proposal — the bootstrap must still create it).
    backend.set_script("leader", [
        {"summary": "propose",
         "org_recommendation": {"department_heads": [
             {"id": "head_analytics", "department": "analytics",
              "sub_architype": "head_of_analytics", "required": False,
              "mandate": "Head of analytics."},
         ]}},
    ])
    bootstrap(org, backend, leader, _mission(), _approve_all,
              departments_dir=str(tmp_path))
    da = org.get(DEVILS_ADVOCATE_ROLE)
    # The role is present (an ic — a red-team auditor, not a department head).
    assert da is not None
    assert da.architype == "ic"
    # It reports **directly** to the leader.
    assert da.reports_to == leader.id
    # Its creation is logged (visible, never silent).
    assert any(e["kind"] == "devils_advocate_bootstrapped"
               for e in org.events)


# --- A2: cross-department reads scoped to the role + the leader -------------

def test_devils_advocate_cross_department_read():
    """The role + the leader can read **other departments'** directories
    (policies + code for the role; policies only for the leader). A normal IC
    cannot read another department at all."""
    da = _da_role()
    leader = make_leader()
    # The role reads other departments' policy markdowns (the governance
    # record of the work).
    assert tiers.can_read(da, "departments/analytics/ANALYTICS_POLICY.md")
    # The role reads other departments' code (it checks the claims against
    # what the pipeline has actually produced).
    assert tiers.can_read_code(da, "departments/analytics/pipelines/a.py")
    # The leader reads other departments' policies...
    assert tiers.can_read(leader, "departments/analytics/ANALYTICS_POLICY.md")
    # but the leader still cannot read any code (it sees work only as it is
    # brought to it).
    assert not tiers.can_read_code(leader, "departments/analytics/pipelines/a.py")
    # A normal IC cannot read another department (policy or code).
    ic = _ic("ic1", "analytics", "pipelines", "mgr1")
    assert not tiers.can_read(ic, "departments/engineering/ENGINEERING_POLICY.md")
    assert not tiers.can_read_code(ic, "departments/engineering/core/b.py")


# --- A3: the role "listens" to the leader's + heads' pods -------------------

def test_devils_advocate_listens_to_leader_pod():
    """The role "listens" to any pod the **leader** is in (it observes the
    deliberation — it is not a pod member)."""
    leader = make_leader()
    da = _da_role()
    head = _head("head_analytics", "analytics")
    roles = {"leader": leader, "head_analytics": head,
             DEVILS_ADVOCATE_ROLE: da}
    pod = form_pod(roles, "leader", ["leader", "head_analytics"],
                   "Pod A: all heads + the leader")
    assert devils_advocate_listens(pod, roles) is da


def test_devils_advocate_listens_to_head_pod():
    """The role "listens" to any pod the **heads** are in (a head+manager pod
    the leader is not a member)."""
    da = _da_role()
    head = _head("head_analytics", "analytics")
    mgr = _mgr("mgr1", "analytics", "pipelines", "head_analytics")
    roles = {"head_analytics": head, "mgr1": mgr, DEVILS_ADVOCATE_ROLE: da}
    pod = form_pod(roles, "head_analytics", ["head_analytics", "mgr1"],
                   "head+manager pod")
    assert devils_advocate_listens(pod, roles) is da


def test_devils_advocate_does_not_listen_to_ic_pod():
    """The role does NOT "listen" to a pod with neither the leader nor a head
    (a manager+IC pod) — it listens only to the leader's + heads' pods."""
    da = _da_role()
    mgr = _mgr("mgr1", "analytics", "pipelines", "head_analytics")
    ic = _ic("ic1", "analytics", "pipelines", "mgr1")
    roles = {"mgr1": mgr, "ic1": ic, DEVILS_ADVOCATE_ROLE: da}
    pod = form_pod(roles, "mgr1", ["mgr1", "ic1"], "manager+IC pod")
    assert devils_advocate_listens(pod, roles) is None


def test_log_devils_advocate_listening_records_event(tmp_path):
    """The role's "listening" is **visible** — it is logged in the audit
    (never silent)."""
    org = OrgState(history_dir=str(tmp_path))
    leader = make_leader()
    da = _da_role()
    head = _head("head_analytics", "analytics")
    roles = {"leader": leader, "head_analytics": head,
             DEVILS_ADVOCATE_ROLE: da}
    pod = form_pod(roles, "leader", ["leader", "head_analytics"],
                   "Pod A: all heads + the leader")
    log_devils_advocate_listening(org, pod, roles)
    events = [e for e in org.events if e["kind"] == "devils_advocate_listening"]
    assert events
    assert events[0]["initiator"] == DEVILS_ADVOCATE_ROLE
    assert events[0]["target"] == pod.id


# --- A4: the Phase-7 verdict ------------------------------------------------

def test_phase7_verdict_returned(tmp_path):
    """Phase 7: the role's gut check returns a `clean` verdict — it is stored
    on `session.da_verdict` and logged to the audit."""
    session = _session_with_da(tmp_path, "clean", "complete")
    verdict = session._devils_advocate_verdict({"verdict": "complete"}, [])
    assert verdict == "clean"
    assert session.da_verdict == "clean"
    assert any(e["kind"] == "devils_advocate_verdict"
               for e in session.org.events)


def test_phase7_flag_verdict_returned(tmp_path):
    """Phase 7: the role raises concerns — the verdict starts with `flag`
    (fabrication / hallucination / low-quality outcomes / immoral actions)."""
    flag = "flag: fabrication in the ETL output"
    session = _session_with_da(tmp_path, flag, "complete")
    verdict = session._devils_advocate_verdict({"verdict": "complete"}, [])
    assert verdict.startswith("flag")
    assert session.da_verdict == flag


def test_phase7_missing_role_returns_none(tmp_path):
    """Phase 7: the role is missing from the org — the gut check is skipped
    (contained), `session.da_verdict` is None, and the miss is logged
    (visible, never silent)."""
    session = _session_with_da(tmp_path, "clean", "complete", include_da=False)
    verdict = session._devils_advocate_verdict({"verdict": "complete"}, [])
    assert verdict is None
    assert session.da_verdict is None
    assert any(e["kind"] == "devils_advocate_missing"
               for e in session.org.events)


# --- A5: the Phase-8 consequence --------------------------------------------

def test_phase8_flag_blocks_stop(tmp_path):
    """Phase 8: a `flag` **blocks a stop** — even when the leader decides
    `complete`, the status is forced to `continue` (re-check the flagged
    outcomes). The flag is surfaced to the evaluation + the audit."""
    session = _session_with_da(tmp_path, "flag: low-quality ETL", "complete")
    session.da_verdict = "flag: low-quality ETL"
    evaluation, status = session._decide(
        _intake(), _mission(),
        [{"department": "analytics"}],  # dispatch_results (non-empty)
        "complete", max_iterations=3,
    )
    # The flag blocks the stop: the status is forced to `continue`.
    assert status == "continue"
    # The flag is surfaced to the evaluation...
    assert evaluation["devils_advocate_flag"] == "flag: low-quality ETL"
    # and the audit (visible, never silent).
    assert any(e["kind"] == "devils_advocate_flag_consumed"
               for e in session.org.events)


def test_phase8_clean_verdict_does_not_block_stop(tmp_path):
    """Phase 8: a `clean` verdict does not block the stop — the leader's
    `complete` decision proceeds (the status is `complete`, no flag in the
    evaluation)."""
    session = _session_with_da(tmp_path, "clean", "complete")
    session.da_verdict = "clean"
    evaluation, status = session._decide(
        _intake(), _mission(),
        [{"department": "analytics"}],
        "complete", max_iterations=3,
    )
    assert status == "complete"
    assert "devils_advocate_flag" not in evaluation


# --- A6: the reporting pods skip the role -----------------------------------

def test_reporting_pod_skip_devils_advocate(tmp_path):
    """The **reporting pods** (Phase 7) skip the role — it is a special
    red-team auditor (an ic reporting to the leader), not a normal ic/manager
    direct report. Had it not been skipped, its ic→leader reporting pod would
    span 3 tiers (leader=0, ic=3) and violate the <=1 tier-spread bound (a
    `PodMembershipError`)."""
    backend = StubBackend()
    session = Session(backend, make_leader(), history_dir=str(tmp_path))
    session.org.add_role(_da_role())
    session.org.add_role(_head("head_analytics", "analytics"))
    # The leader + head are invoked by the head→leader reporting pod (agenda /
    # speak / close).
    backend.set_script("leader", [
        {"agenda": "status / results / fire-replace-keep",
         "summary": "agenda set"},
        {"summary": "leader speaks"},
        {"decision": "ok", "rationale": "ok"},
    ])
    backend.set_script("head_analytics", [
        {"summary": "head report"},
    ])
    # The reporting pods run: the role is skipped, so the only pod formed is
    # the head→leader one (1-tier spread) — the method completes without
    # raising a `PodMembershipError`.
    try:
        session._run_reporting_pods()
    except PodMembershipError as e:
        raise AssertionError(
            f"the devil's advocate role was not skipped by the reporting "
            f"pods: {e}"
        )
