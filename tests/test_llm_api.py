"""Offline tests for the real backend (runtime/llm_api.py).

``httpx`` is imported lazily inside ``invoke``, so a fake ``httpx`` module is
injected into ``sys.modules`` — no network and no real dependency needed.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from runtime.llm import StubBackend
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
