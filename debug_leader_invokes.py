"""Throwaway debug script - counts the leader invocations per phase."""
import sys, os, shutil
sys.path.insert(0, ".")
from runtime.llm import StubBackend, Reasoning
from runtime.session import Session
from roles.leader import make_leader

class DebugStubBackend(StubBackend):
    def invoke(self, role, context, reasoning=Reasoning.LOW, timeout=None, phase=None):
        if role.id == "leader":
            print(f"  leader invoke  phase={phase}")
        return super().invoke(role, context, reasoning, timeout, phase)

def _phase123():
    rec = {"org_recommendation": {"departments": [
        {"slug": "analytics", "head_title": "Head of Analytics", "headcount": 3}]}}
    return [
        {"summary": "clear", "questions": [], "confidence": 0.9,
         "formal_mission": "Build a data pipeline.", **rec},
        {"summary": "done", "questions": [], "confidence": 0.9,
         "formal_mission": "Build a data pipeline.", **rec},
        {"summary": "ok", "questions": [], "confidence": 0.9,
         "formal_mission": "Build a data pipeline.", **rec},
    ]

def _plan_verdict(verdict):
    return [{"decomposition": {"team_objectives": []}},
            {"verdict": "complete"},
            {"verdict": verdict}]

tmp = os.path.join(".", "_debug_tmp")
if os.path.exists(tmp):
    shutil.rmtree(tmp)
os.makedirs(tmp)
leader_script = (_phase123() + _plan_verdict("continue") + _plan_verdict("complete"))
backend = DebugStubBackend()
backend.set_script("leader", leader_script)
backend.set_script("head_analytics", [{"decomposition": {"team_objectives": []}}])
state_dir = os.path.join(tmp, "state")
config = {
    "mission_path": os.path.join(tmp, "MISSION.md"),
    "state_dir": state_dir,
    "org_chart_path": os.path.join(state_dir, "org_chart.json"),
    "memory_dir": os.path.join(state_dir, "role_memory"),
    "checkpoint_path": os.path.join(state_dir, "checkpoint.json"),
    "pod_transcripts_dir": os.path.join(tmp, "pods", "transcripts"),
}
session = Session(backend, make_leader(), config=config, history_dir=tmp)
print("=== Running test_cycle_repeats_on_continue scenario ===")
result = session.run(
    "build a data pipeline",
    lambda qs: "a weekly report",
    lambda draft: {"decision": "approve", "feedback": ""},
    lambda approver, action, role: {"decision": "approve", "rationale": "ok"},
    max_iterations=3,
)
print(f"=== Result: status={result.status}, cycles={result.cycles}, phases={result.phases} ===")
shutil.rmtree(tmp, ignore_errors=True)
