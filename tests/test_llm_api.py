"""Offline tests for the real backend (runtime/llm_api.py).

``httpx`` is imported lazily inside ``invoke``, so a fake ``httpx`` module is
injected into ``sys.modules`` — no network and no real dependency needed.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from runtime.llm import Reasoning, StubBackend
from runtime.llm_api import (
    TOOL_NAME,
    OpenAIBackend,
    OpenAIOutputError,
    make_backend,
)


# --- fakes ------------------------------------------------------------------

def _role():
    return types.SimpleNamespace(
        id="leader",
        output_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["summary", "confidence"],
        },
    )


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
    """Inject a fake httpx module whose stream() records the request and yields
    the reply as a single SSE chunk. Returns the recorded request."""
    seen = {}
    sse_lines = _reply_to_sse_lines(reply)

    def stream(method, url, headers=None, json=None, timeout=None):
        seen["method"] = method
        seen["url"] = url
        seen["headers"] = headers
        seen["payload"] = json
        seen["timeout"] = timeout
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
    return seen


def _tool_reply(args: dict) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "function": {
                                "name": TOOL_NAME,
                                "arguments": json.dumps(args),
                            }
                        }
                    ],
                }
            }
        ]
    }


def _content_reply(content: str) -> dict:
    return {"choices": [{"message": {"content": content, "tool_calls": None}}]}


# --- request shape (tools mode, the default) --------------------------------

def test_tools_mode_sends_forced_tool(monkeypatch):
    seen = _install_fake_httpx(
        monkeypatch, _tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://localhost:5001/v1")
    out = backend.invoke(_role(), "ctx")
    payload = seen["payload"]
    assert "response_format" not in payload
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == TOOL_NAME
    # the role's output schema is offered as the tool's parameters
    assert payload["tools"][0]["function"]["parameters"]["required"] == [
        "summary", "confidence"]
    assert payload["tool_choice"] == {
        "type": "function", "function": {"name": TOOL_NAME}}
    assert seen["url"] == "http://localhost:5001/v1/chat/completions"
    assert out == {"summary": "s", "confidence": 0.9}


def test_tools_mode_missing_schema_degrades_to_empty_object(monkeypatch):
    seen = _install_fake_httpx(monkeypatch, _tool_reply({}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    role = types.SimpleNamespace(id="leader")  # no output_schema attribute
    backend.invoke(role, "ctx")
    params = seen["payload"]["tools"][0]["function"]["parameters"]
    assert params == {"type": "object"}


# --- streaming (the rewrite) ---------------------------------------------------

def test_streaming_request_sends_stream_true(monkeypatch):
    seen = _install_fake_httpx(
        monkeypatch, _tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://localhost:5001/v1")
    backend.invoke(_role(), "ctx")
    assert seen["payload"]["stream"] is True


def test_reasoning_streamed_before_tool_call_is_handled(monkeypatch):
    # The model streams reasoning_content (its chain-of-thought) first, then
    # the forced tool call. The rewrite must read the reasoning (to advance the
    # stream) and still assemble the tool call's arguments into the envelope.
    reply = {"choices": [{"message": {
        "content": None,
        "reasoning_content": "The user wants a summary; let me produce one.",
        "tool_calls": [
            {"function": {"name": TOOL_NAME,
                          "arguments": '{"summary": "s", "confidence": 0.7}'}}
        ],
    }}]}
    _install_fake_httpx(monkeypatch, reply)
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out == {"summary": "s", "confidence": 0.7}


def test_on_stream_fires_per_chunk_for_each_kind(monkeypatch):
    # The model streams reasoning_content (thinking), content (reply), and
    # tool_calls (tool call). The on_stream callback must fire for each kind,
    # with (stream_id, role_id, model, kind, text) — the source for the
    # dashboard's live "model stream" window.
    reply = {"choices": [{"message": {
        "content": "plain reply",
        "reasoning_content": "The user wants a summary; let me produce one.",
        "tool_calls": [
            {"function": {"name": TOOL_NAME,
                          "arguments": '{"summary": "s", "confidence": 0.7}'}}
        ],
    }}]}
    _install_fake_httpx(monkeypatch, reply)
    backend = OpenAIBackend(model="qwen", base_url="http://x/v1")
    calls = []
    backend.on_stream = lambda sid, rid, model, kind, text: calls.append(
        (sid, rid, model, kind, text))
    backend.invoke(_role(), "ctx")
    kinds = [c[3] for c in calls]
    assert "thinking" in kinds
    assert "content" in kinds
    assert "tool_call" in kinds
    # each call has (stream_id, role_id, model, kind, text)
    for sid, rid, model, kind, text in calls:
        assert sid  # non-empty stream_id
        assert rid == "leader"  # the role's id
        assert model == "qwen"  # the model
        assert text  # non-empty text


# --- bounded timeout retries ---------------------------------------------------

def _install_failing_httpx(monkeypatch, fail_times, reply):
    """Inject a fake httpx whose stream() raises a ReadTimeout for the first
    `fail_times` attempts, then yields `reply` as a single SSE chunk. Returns a
    dict with the attempt count and the ReadTimeout class (for assertions)."""
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)  # no real backoff
    sse_lines = _reply_to_sse_lines(reply)
    mod = types.ModuleType("httpx")
    mod.Timeout = lambda **kw: kw
    mod.TimeoutException = type("TimeoutException", (Exception,), {})
    ReadTimeout = type("ReadTimeout", (mod.TimeoutException,), {})
    mod.HTTPError = type("HTTPError", (Exception,), {})
    calls = {"n": 0}

    def stream(method, url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise ReadTimeout("simulated idle timeout")
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

    mod.stream = stream
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return {"calls": calls, "ReadTimeout": ReadTimeout}


def test_timeout_is_retried_then_succeeds(monkeypatch):
    # The first attempt times out (a ReadTimeout), the second succeeds. The
    # backend must retry the whole request (bounded) and return the reply.
    fake = _install_failing_httpx(
        monkeypatch, fail_times=1,
        reply=_tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out == {"summary": "s", "confidence": 0.9}
    assert fake["calls"]["n"] == 2  # one timeout + one success


def test_timeout_exhausts_retries_then_raises(monkeypatch):
    # Every attempt times out. After max_retries retries (default 3 -> 4 total
    # attempts), the timeout is re-raised (a visible failure, never silent).
    fake = _install_failing_httpx(
        monkeypatch, fail_times=99,
        reply=_tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(fake["ReadTimeout"]):
        backend.invoke(_role(), "ctx")
    assert fake["calls"]["n"] == 4  # 1 + 3 retries


def test_timeout_retry_respects_max_retries_zero(monkeypatch):
    # max_retries=0 disables retries: a single timeout is raised immediately.
    fake = _install_failing_httpx(
        monkeypatch, fail_times=99,
        reply=_tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1", max_retries=0)
    with pytest.raises(fake["ReadTimeout"]):
        backend.invoke(_role(), "ctx")
    assert fake["calls"]["n"] == 1  # no retries


# --- truncated output (the rewrite) --------------------------------------------

def _install_truncating_httpx(monkeypatch, trunc_times, good_reply,
                              finish_reason="length"):
    """Inject a fake httpx whose stream() returns a TRUNCATED submit_output
    call (the JSON cut off mid-string, an unterminated string) for the first
    `trunc_times` attempts, then `good_reply`. The truncated reply's final
    chunk carries `finish_reason` (default "length"; pass "" to exercise the
    heuristic path where the server reports no finish_reason). Returns the
    attempt count."""
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda s: None)  # no real backoff
    mod = types.ModuleType("httpx")
    mod.Timeout = lambda **kw: kw
    mod.TimeoutException = type("TimeoutException", (Exception,), {})
    mod.HTTPError = type("HTTPError", (Exception,), {})
    calls = {"n": 0}

    def _sse_truncated():
        # A truncated submit_output call: the JSON is cut off mid-string
        # (unterminated), and the final chunk reports finish_reason.
        truncated_args = '{"summary": "Stood up the fleet'  # no closing quote
        chunks = [
            {"choices": [{"delta": {
                "tool_calls": [{"function": {"name": TOOL_NAME,
                                             "arguments": truncated_args}}]}}]},
        ]
        if finish_reason:
            chunks.append({"choices": [{"delta": {},
                                        "finish_reason": finish_reason}]})
        else:
            chunks.append({"choices": [{"delta": {}}]})
        lines = ["data: " + json.dumps(c) for c in chunks]
        lines.append("data: [DONE]")
        return lines

    def stream(method, url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        lines = (_sse_truncated() if calls["n"] <= trunc_times
                 else _reply_to_sse_lines(good_reply))
        resp = types.SimpleNamespace(
            raise_for_status=lambda: None,
            iter_lines=lambda: iter(lines),
        )

        class _Ctx:
            def __enter__(self):
                return resp
            def __exit__(self, *a):
                return False
        return _Ctx()

    mod.stream = stream
    monkeypatch.setitem(sys.modules, "httpx", mod)
    return {"calls": calls}


def test_truncated_output_is_retried_then_succeeds(monkeypatch):
    # The first attempt returns a truncated submit_output call (the generation
    # budget was exhausted mid-JSON, finish_reason="length"); the second
    # succeeds. The backend must retry the whole request (bounded) and return
    # the good reply — a truncation is transient, unlike a malformed shape.
    fake = _install_truncating_httpx(
        monkeypatch, trunc_times=1,
        good_reply=_tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out == {"summary": "s", "confidence": 0.9}
    assert fake["calls"]["n"] == 2  # one truncation + one success


def test_truncation_exhausts_retries_then_raises(monkeypatch):
    # Every attempt returns a truncated output. After max_retries retries
    # (default 3 -> 4 total attempts), the OpenAIOutputError is re-raised
    # (a visible failure, never silent) — and it is flagged truncated.
    fake = _install_truncating_httpx(
        monkeypatch, trunc_times=99,
        good_reply=_tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(OpenAIOutputError) as exc:
        backend.invoke(_role(), "ctx")
    assert fake["calls"]["n"] == 4  # 1 + 3 retries
    assert exc.value.truncated is True


def test_truncation_heuristic_without_finish_reason(monkeypatch):
    # A server that does NOT report finish_reason: a truncation is still
    # detected by the heuristic (a truncation-shaped parse failure on a
    # plausible, unbalanced JSON prefix) and retried.
    fake = _install_truncating_httpx(
        monkeypatch, trunc_times=1,
        good_reply=_tool_reply({"summary": "s", "confidence": 0.9}),
        finish_reason="")
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out == {"summary": "s", "confidence": 0.9}
    assert fake["calls"]["n"] == 2


def test_malformed_shape_is_not_retried(monkeypatch):
    # A parse failure that is a *malformed shape* the model chose (garbage that
    # is not a plausible JSON prefix) is NOT a truncation and is NOT retried —
    # it is raised immediately and flagged truncated=False.
    reply = {"choices": [{"message": {
        "content": None,
        "tool_calls": [
            {"function": {"name": TOOL_NAME, "arguments": "{not json"}}],
    }}]}
    _install_fake_httpx(monkeypatch, reply)
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(OpenAIOutputError) as exc:
        backend.invoke(_role(), "ctx")
    assert exc.value.truncated is False


# --- reasoning level (thinking steering) ----------------------------------------

def test_low_reasoning_directs_no_thinking(monkeypatch):
    # LOW (routine work) steers the model to answer directly with no extended
    # chain-of-thought: the system message carries the directive and the user
    # message carries the Qwen3 /no_think marker (the thinking is what eats
    # the generation budget and truncates the submit_output JSON).
    seen = _install_fake_httpx(
        monkeypatch, _tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    backend.invoke(_role(), "ctx", reasoning=Reasoning.LOW)
    messages = seen["payload"]["messages"]
    system = next(m for m in messages if m["role"] == "system")
    user = next(m for m in messages if m["role"] == "user")
    assert "chain-of-thought" in system["content"]  # the no-thinking directive
    assert "/no_think" in user["content"]  # the Qwen3 native toggle


def test_high_reasoning_thinks_fully(monkeypatch):
    # HIGH (complex work) thinks fully: no no-thinking directive and no
    # /no_think marker (the model's chain-of-thought is wanted).
    seen = _install_fake_httpx(
        monkeypatch, _tool_reply({"summary": "s", "confidence": 0.9}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    backend.invoke(_role(), "ctx", reasoning=Reasoning.HIGH)
    messages = seen["payload"]["messages"]
    system = next(m for m in messages if m["role"] == "system")
    user = next(m for m in messages if m["role"] == "user")
    assert "chain-of-thought" not in system["content"]
    assert "/no_think" not in user["content"]


# --- legacy json mode ---------------------------------------------------------

def test_json_mode_keeps_legacy_request(monkeypatch):
    seen = _install_fake_httpx(
        monkeypatch,
        _content_reply('{"summary": "s", "confidence": 0.5}'))
    backend = OpenAIBackend(model="m", base_url="http://x/v1",
                            structured="json")
    out = backend.invoke(_role(), "ctx")
    payload = seen["payload"]
    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert out["summary"] == "s"


# --- reply parsing -------------------------------------------------------------

def test_tool_arguments_parsed(monkeypatch):
    _install_fake_httpx(
        monkeypatch,
        _tool_reply({"summary": "s", "findings": [], "confidence": 1.0}))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out["findings"] == []
    assert out["confidence"] == 1.0


def test_fallback_to_json_content_when_tool_ignored(monkeypatch):
    _install_fake_httpx(
        monkeypatch, _content_reply('{"summary": "s", "confidence": 0.2}'))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    out = backend.invoke(_role(), "ctx")
    assert out["confidence"] == 0.2


def test_non_json_content_raises_visible(monkeypatch):
    _install_fake_httpx(monkeypatch, _content_reply("I cannot comply."))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(OpenAIOutputError):
        backend.invoke(_role(), "ctx")


def test_malformed_tool_arguments_raise_visible(monkeypatch):
    reply = {"choices": [{"message": {
        "content": None,
        "tool_calls": [
            {"function": {"name": TOOL_NAME, "arguments": "{not json"}}],
    }}]}
    _install_fake_httpx(monkeypatch, reply)
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(OpenAIOutputError):
        backend.invoke(_role(), "ctx")


def test_no_tool_call_and_no_content_raises_visible(monkeypatch):
    _install_fake_httpx(monkeypatch, _content_reply(""))
    backend = OpenAIBackend(model="m", base_url="http://x/v1")
    with pytest.raises(OpenAIOutputError):
        backend.invoke(_role(), "ctx")


# --- make_backend env selection -------------------------------------------------

def test_make_backend_selects_api(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_MODEL", "qwen")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:5001/v1/")
    monkeypatch.setenv("LLM_STRUCTURED", "json")
    backend = make_backend()
    assert isinstance(backend, OpenAIBackend)
    assert backend.model == "qwen"
    assert backend.base_url == "http://localhost:5001/v1"  # trailing / stripped
    assert backend.structured == "json"


def test_make_backend_defaults_to_tools(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_MODEL", "qwen")
    monkeypatch.delenv("LLM_STRUCTURED", raising=False)
    assert make_backend().structured == "tools"


def test_make_backend_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    assert isinstance(make_backend(), StubBackend)
