"""Tests for the observability data hooks (OBSERVABILITY_CHECKLIST.md Phase 1).

- ``OrgState.log_event`` timestamps + department details (in-memory, no files).
- ``OpenAIBackend`` per-call outcome reporting via ``on_call`` (fake httpx,
  no network).
- ``HistoryStore`` observability log methods (temp dir).
"""

import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from roles.base import Role
from runtime.history import HistoryStore
from runtime.org import OrgState
from runtime.llm_api import TOOL_NAME, OpenAIBackend, OpenAIOutputError


def _role():
    return Role(id="leader", architype="leader", status="active")


def _reply_to_sse_lines(reply):
    """Convert a non-streaming reply to SSE lines (one data chunk + [DONE]).

    The backend now reads a *streaming* response, so the fake reply (in the
    non-streaming ``message`` shape) is re-shaped into a single ``delta`` chunk
    — enough to exercise the accumulation + _parse path without a real server.
    """
    choices = reply.get("choices") or []
    if choices:
        choice = dict(choices[0])
        if "message" in choice:
            choice["delta"] = choice.pop("message")
        reply = dict(reply, choices=[choice])
    return ["data: " + json.dumps(reply), "data: [DONE]"]


def _install_fake_httpx(monkeypatch, reply):
    sse_lines = _reply_to_sse_lines(reply)

    def stream(method, url, headers=None, json=None, timeout=None):
        resp = types.SimpleNamespace(
            raise_for_status=lambda: None,
            iter_lines=lambda: iter(sse_lines),
        )

        class _Ctx:
            def __enter__(self):
                return resp
            def __exit__(self, *a):
                return False
        return _Ctx()

    mod = types.ModuleType("httpx")
    mod.stream = stream
    mod.Timeout = lambda **kw: kw  # fake httpx.Timeout (invoke passes connect/read/...)
    mod.TimeoutException = type("TimeoutException", (Exception,), {})
    mod.HTTPError = type("HTTPError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "httpx", mod)


def _tool_reply(args):
    return {"choices": [{"message": {
        "content": None,
        "tool_calls": [{"function": {
            "name": TOOL_NAME, "arguments": json.dumps(args)}}],
    }}]}


def _content_reply(content):
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}


# --- OrgState.log_event -------------------------------------------------------

def test_org_event_has_timestamp_and_department():
    org = OrgState()
    org.log_event("hired", "leader", "sales-ops",
                  {"department": "sales", "ts_extra": 1})
    e = org.events[-1]
    assert e["kind"] == "hired"
    assert e["detail"]["department"] == "sales"
    assert isinstance(e["ts"], float) and e["ts"] > 0


# --- OpenAIBackend.on_call ----------------------------------------------------

def test_backend_reports_tool_call_outcome(monkeypatch):
    _install_fake_httpx(monkeypatch, _tool_reply({"summary": "s"}))
    stats = []
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    backend.on_call = stats.append
    backend.invoke(_role(), "ctx")
    assert len(stats) == 1
    s = stats[0]
    assert s["outcome"] == "tool_call"
    assert s["role"] == "leader"
    assert s["mode"] == "tools"
    assert s["latency"] >= 0
    assert s["error"] == ""


def test_backend_reports_content_fallback_outcome(monkeypatch):
    _install_fake_httpx(
        monkeypatch, _content_reply('{"summary": "s"}'))
    stats = []
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    backend.on_call = stats.append
    backend.invoke(_role(), "ctx")
    assert stats[0]["outcome"] == "content_fallback"


def test_backend_reports_error_outcome_and_raises(monkeypatch):
    _install_fake_httpx(monkeypatch, _content_reply("I cannot comply."))
    stats = []
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    backend.on_call = stats.append
    with pytest.raises(OpenAIOutputError):
        backend.invoke(_role(), "ctx")
    assert stats[0]["outcome"] == "error"
    assert stats[0]["error"]  # the offending text is visible


def test_backend_on_call_exception_never_breaks_invoke(monkeypatch):
    _install_fake_httpx(monkeypatch, _tool_reply({"summary": "s"}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    def broken(stat):
        raise RuntimeError("observability must not break the pipeline")
    backend.on_call = broken
    out = backend.invoke(_role(), "ctx")  # must not raise
    assert out == {"summary": "s"}


# --- HistoryStore observability logs ------------------------------------------

def test_history_store_observability_logs(tmp_path):
    h = HistoryStore(history_dir=str(tmp_path))
    h.log_code_edit("ic_x", "departments/engineering/foo.py", True)
    h.log_code_edit("ic_x", "observability/evil.py", False,
                    error="role may not edit")
    h.log_tool_call({"ts": 1.0, "role": "leader", "mode": "tools",
                     "outcome": "tool_call", "error": "", "latency": 0.5})
    h.log_cycle(4, 1, 1000.0, 1002.5)
    h.log_stream("s1", "leader", "qwen", "thinking", "let me think")
    h.log_stream("s1", "leader", "qwen", "content", "reply")

    edits = [json.loads(l) for l in open(
        str(tmp_path / "code_edits.jsonl"), encoding="utf-8")]
    assert edits[0]["ok"] is True and edits[0]["role"] == "ic_x"
    assert edits[1]["ok"] is False and edits[1]["error"]
    assert "ts" in edits[0]

    calls = [json.loads(l) for l in open(
        str(tmp_path / "tool_calls.jsonl"), encoding="utf-8")]
    assert calls[0]["outcome"] == "tool_call"

    cycles = [json.loads(l) for l in open(
        str(tmp_path / "cycles.jsonl"), encoding="utf-8")]
    assert cycles[0]["phase"] == 4
    assert cycles[0]["duration"] == pytest.approx(2.5)

    stream = [json.loads(l) for l in open(
        str(tmp_path / "stream.jsonl"), encoding="utf-8")]
    assert stream[0]["stream_id"] == "s1"
    assert stream[0]["kind"] == "thinking"
    assert stream[0]["text"] == "let me think"
    assert stream[1]["kind"] == "content"
    assert stream[1]["text"] == "reply"
