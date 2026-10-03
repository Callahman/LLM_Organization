"""A real LLMBackend that talks to an OpenAI-compatible chat endpoint
(KoboldCpp, llama.cpp server, vLLM, LM Studio, ...).

This is the "later task" from ``SETUP.md``: it implements the ``LLMBackend``
interface so the org pipeline can run against a live model. ``make_backend()``
selects the backend from the environment (``.env``): ``LLM_BACKEND=stub``
(default) -> the offline ``StubBackend``; ``LLM_BACKEND=api`` -> ``OpenAIBackend``
built from ``LLM_MODEL`` / ``LLM_BASE_URL`` / ``LLM_API_KEY``.

Structured output uses **tool calls** by default (``LLM_STRUCTURED=tools``):
the role's output schema is offered as a single forced tool
(``submit_output``), so the model must return the shared envelope as the
tool's JSON arguments. This is the path that needs the server's tool-call
support (e.g. KoboldCpp's ``--jinja --jinjatools`` flags, as started by
``run_org.bat``). ``LLM_STRUCTURED=json`` keeps the legacy
``response_format: json_object`` request for servers without tool support.

``httpx`` is imported lazily inside ``invoke`` so the stub path (and the
offline test suite) needs no network dependency installed.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

from runtime.llm import LLMBackend, Reasoning, StubBackend

# The single tool the model must call to submit its structured output.
TOOL_NAME = "submit_output"
TOOL_DESCRIPTION = (
    "Submit your structured output for this task. Call this tool exactly "
    "once; its arguments are your complete output and must match your "
    "role's output schema."
)

# The known nested keys that must be JSON objects (dicts) — the Phase-2/3/4
# structured outputs the pipeline reads. A wrong type (e.g. a free-form string)
# is logged (not rejected) so future free-forms are visible in tool_calls.jsonl.
_NESTED_OBJECT_KEYS = ("mission_draft", "decomposition", "org_recommendation")


class OpenAIOutputError(RuntimeError):
    """The model's reply could not be parsed into the shared output envelope
    (no usable tool call and no JSON content) — a visible failure state,
    never silent."""


class OpenAIBackend(LLMBackend):
    """Calls ``{base_url}/chat/completions`` and parses the structured reply.

    The assembled ``context`` (role mandate + objective + memory + prior
    conversation) is sent as the user message. Structured output is requested
    via a **forced tool call** (``structured="tools"``, default): the role's
    ``output_schema`` is offered as the ``submit_output`` tool and the model
    must call it, so the envelope arrives as the tool's JSON arguments. With
    ``structured="json"`` it falls back to the legacy
    ``response_format: json_object`` request. If a server ignores the tool
    and returns plain content, a JSON content reply is still accepted (a
    visible fallback); anything else raises ``OpenAIOutputError``.
    """

    def __init__(self, model: str, base_url: str, api_key: str = "",
                 structured: str = "tools", max_tokens: int = 8192,
                 idle_timeout: float = 180.0):
        self.model = model
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or "not-needed"
        self.structured = (structured or "tools").strip().lower()
        # Generation budget for the model's reply. Must be large enough for
        # the model's chain-of-thought **plus** the submit_output tool call —
        # a too-small cap truncates the tool call's JSON mid-string (an
        # "Unterminated string" parse error). KoboldCpp's server-side default
        # is 2048, which is too small for a thinking model; 8192 is safe.
        self.max_tokens = int(max_tokens or 8192)
        # Progress-based idle timeout (seconds): the max time to wait for the
        # NEXT streamed chunk. A thinking model keeps emitting chunks
        # (progress), so a long think never trips this; a hung model emits no
        # chunks, so it trips after idle_timeout. This is the primary timeout
        # bound (replacing the old flat wall-clock, which false-timed-out
        # long-but-active thinks).
        self.idle_timeout = float(idle_timeout or 180.0)
        # Optional per-call stats callback (observability): called with
        # ``{ts, role, mode, outcome, error, latency}`` after every invoke.
        # The pipeline wires it to ``history/tool_calls.jsonl``; it must
        # never break a call (exceptions are swallowed).
        self.on_call: Optional[Callable[[Dict[str, Any]], None]] = None
        # Forward each streamed chunk (the dashboard's live "model stream"
        # window): (stream_id, role_id, model, kind, text).
        self.on_stream: Optional[Callable[[str, str, str, str, str], None]] = None

    # --- request building ---------------------------------------------------

    def _tool_for(self, role) -> Dict[str, Any]:
        """The role's output schema offered as a single function tool."""
        schema = getattr(role, "output_schema", None)
        if not isinstance(schema, dict):
            schema = {}
        if schema.get("type") != "object":
            schema = dict(schema, type="object")
        return {
            "type": "function",
            "function": {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "parameters": schema,
            },
        }

    def _payload(self, role, context: str) -> Dict[str, Any]:
        if self.structured == "json":
            return {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system",
                     "content": ("You are one agent in a simulated company. "
                                 "Always reply with a single JSON object that "
                                 "matches your role's output schema.")},
                    {"role": "user", "content": context},
                ],
            }
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "tools": [self._tool_for(role)],
            "tool_choice": {"type": "function",
                            "function": {"name": TOOL_NAME}},
            "messages": [
                {"role": "system",
                 "content": ("You are one agent in a simulated company. "
                             "Submit your structured output by calling the "
                             f"{TOOL_NAME} tool exactly once; its arguments "
                             "are your complete output and must match your "
                             "role's output schema.")},
                {"role": "user", "content": context},
            ],
        }

    # --- reply parsing ------------------------------------------------------

    @staticmethod
    def _parse(data: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        """Extract the shared output envelope from a chat completion reply.

        Returns ``(envelope, outcome)`` where outcome is ``"tool_call"`` or
        ``"content_fallback"``. Preferred: the ``submit_output`` tool call's
        JSON arguments. Fallback: plain JSON ``content`` (a server that
        ignored the tool), or a call the model wrote as **text** inside
        ``content`` (a fenced JSON block or an embedded JSON object, via
        ``_recover_tool_call``). Anything else raises ``OpenAIOutputError``
        (visible, never silent).
        """
        message = data["choices"][0]["message"]
        for tc in message.get("tool_calls") or []:
            fn = (tc or {}).get("function") or {}
            if fn.get("name", TOOL_NAME) != TOOL_NAME:
                continue
            raw = fn.get("arguments", "")
            if isinstance(raw, dict):
                return raw, "tool_call"
            if not (isinstance(raw, str) and raw.strip()):
                continue
            try:
                out = json.loads(raw)
            except json.JSONDecodeError as e:
                raise OpenAIOutputError(
                    f"{TOOL_NAME} arguments are not valid JSON: "
                    f"{raw[:300]!r} ({e})"
                ) from e
            if isinstance(out, dict):
                return out, "tool_call"
            raise OpenAIOutputError(
                f"{TOOL_NAME} arguments are not a JSON object: {raw[:300]!r}"
            )
        content = message.get("content") or ""
        if content.strip():
            try:
                out = json.loads(content)
                if isinstance(out, dict):
                    return out, "content_fallback"
            except json.JSONDecodeError:
                pass  # try the text-shape recovery below
            recovered = OpenAIBackend._recover_tool_call(content)
            if recovered is not None:
                return recovered, "content_fallback"
        raise OpenAIOutputError(
            f"reply has no {TOOL_NAME} tool call and no JSON object content: "
            f"{content[:300]!r}"
        )

    @staticmethod
    def _recover_tool_call(content: str) -> Optional[Dict[str, Any]]:
        """Recover a ``submit_output`` call the model wrote as **text** inside
        ``content``.

        A server without tool-call support (or a model that ignored the forced
        tool) can emit the call in the reply body as text. Handle the common
        text shapes:

        - a fenced JSON block containing the call's arguments (the whole
          block, or the call's ``arguments`` member if present);
        - a bare JSON object embedded in the text (the first brace-delimited
          span that parses as an object).

        Returns the parsed envelope dict, or ``None`` if no shape recovers.
        """
        candidates: list = []
        # Fenced blocks: ```json ... ``` (or any ``` ... ``` fence).
        for m in re.finditer(r"```[a-zA-Z0-9_-]*[ \t]*\n(.*?)```",
                             content, re.DOTALL):
            block = m.group(1).strip()
            if block:
                candidates.append(block)
        # First brace-delimited span in the raw text (covers a bare JSON
        # object surrounded by prose; the scanner is string-aware so braces
        # inside string values do not confuse it).
        start = content.find("{")
        if start != -1:
            depth = 0
            in_str = False
            esc = False
            for i in range(start, len(content)):
                ch = content[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidates.append(content[start:i + 1])
                            break
        for cand in candidates:
            try:
                out = json.loads(cand)
            except json.JSONDecodeError:
                continue
            if not isinstance(out, dict):
                continue
            # A tool-call wrapper: {"name": ..., "arguments": {...}}.
            if isinstance(out.get("arguments"), dict):
                return out["arguments"]
            return out
        return None

    def _report(self, role, outcome: str, t0: float, error: str = "") -> None:
        if self.on_call is None:
            return
        try:
            self.on_call({
                "ts": time.time(),
                "role": getattr(role, "id", ""),
                "mode": self.structured,
                "outcome": outcome,
                "error": error,
                "latency": round(time.time() - t0, 3),
            })
        except Exception:
            pass  # observability must never break the pipeline

    def _emit_stream(self, stream_id: str, role_id: str, kind: str,
                     text: str) -> None:
        """Forward one streamed chunk to the on_stream callback (the dashboard's
        live "model stream" window). Exceptions are swallowed: observability
        must never break the pipeline (same guarantee as on_call)."""
        if self.on_stream is None:
            return
        try:
            self.on_stream(stream_id, role_id, self.model, kind, text)
        except Exception:
            pass  # observability must never break the pipeline

    def _nested_type_warnings(self, out: Dict[str, Any]) -> str:
        """Return a warning string if any known nested key arrived as the wrong
        type (e.g. a free-form string instead of a JSON object). Empty if all
        known nested keys are well-typed. Observability only — it never rejects
        a call (the pipeline's tolerant extractors degrade gracefully), but it
        makes a future free-form visible in ``tool_calls.jsonl``."""
        problems = []
        for key in _NESTED_OBJECT_KEYS:
            if key in out and not isinstance(out[key], dict):
                problems.append(f"{key}={type(out[key]).__name__}")
        return ("nested-type: " + ", ".join(problems)) if problems else ""

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        import httpx  # lazy: only the api path needs it
        t0 = time.time()
        payload = self._payload(role, context)
        payload["stream"] = True
        # Progress-based idle timeout: the `read` timeout is the max time to
        # wait for the NEXT chunk. A thinking model keeps emitting chunks
        # (progress), so it never trips this even over a long think; a hung
        # model emits no chunks, so it trips after idle_timeout seconds. This
        # replaces the old flat wall-clock (which false-timed-out long-but-
        # active thinks). We accumulate three buffers from the stream:
        #   - reasoning_content: the model's chain-of-thought (streamed first);
        #   - content:           the plain reply (the content-fallback path);
        #   - tool_calls args:   the forced submit_output call (the tool path).
        import uuid
        stream_id = uuid.uuid4().hex[:8]
        role_id = getattr(role, "id", "")
        reasoning_buf = ""
        content_buf = ""
        tool_args_buf = ""
        tool_name = TOOL_NAME
        try:
            with httpx.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
                timeout=httpx.Timeout(connect=10.0, read=self.idle_timeout,
                                      write=10.0, pool=10.0),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue  # skip a malformed chunk
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    rc = delta.get("reasoning_content") or ""
                    if rc:
                        reasoning_buf += rc
                        self._emit_stream(stream_id, role_id, "thinking", rc)
                    cc = delta.get("content") or ""
                    if cc:
                        content_buf += cc
                        self._emit_stream(stream_id, role_id, "content", cc)
                    for tc in delta.get("tool_calls") or []:
                        fn = (tc or {}).get("function") or {}
                        if fn.get("name"):
                            tool_name = fn["name"]
                        ta = fn.get("arguments") or ""
                        if ta:
                            tool_args_buf += ta
                            self._emit_stream(stream_id, role_id, "tool_call", ta)
            # Reconstruct the non-streaming message shape and reuse _parse
            # (tool-call extraction, content fallback, text-shape recovery).
            message = {"role": "assistant", "content": content_buf}
            if tool_args_buf.strip():
                message["tool_calls"] = [{"function": {"name": tool_name,
                                                       "arguments": tool_args_buf}}]
            out, outcome = self._parse({"choices": [{"message": message}]})
        except httpx.TimeoutException as e:
            self._report(role, "error", t0,
                         f"LLM idle timeout: no response chunk for "
                         f"{self.idle_timeout}s — the model may be hung "
                         f"({type(e).__name__})")
            raise
        except OpenAIOutputError as e:
            self._report(role, "error", t0, str(e))
            raise
        except httpx.HTTPError as e:
            self._report(role, "error", t0, str(e))
            raise
        # Observability: log (not reject) a wrong-typed nested key (e.g. a
        # free-form string instead of a JSON object) so future free-forms are
        # visible in tool_calls.jsonl.
        self._report(role, outcome, t0, self._nested_type_warnings(out))
        return out


def make_backend() -> LLMBackend:
    """Build the backend selected by the environment (``.env``).

    ``LLM_BACKEND=stub`` (default) -> offline ``StubBackend``.
    ``LLM_BACKEND=api`` -> ``OpenAIBackend`` from ``LLM_MODEL`` /
    ``LLM_BASE_URL`` / ``LLM_API_KEY`` (structured-output mode from
    ``LLM_STRUCTURED``: ``tools`` (default) or ``json``; generation budget
    from ``LLM_MAX_TOKENS``: default ``8192``).
    """
    kind = os.getenv("LLM_BACKEND", "stub").strip().lower()
    if kind == "api":
        return OpenAIBackend(
            model=os.getenv("LLM_MODEL", ""),
            base_url=os.getenv("LLM_BASE_URL", ""),
            api_key=os.getenv("LLM_API_KEY", ""),
            structured=os.getenv("LLM_STRUCTURED", "tools"),
            max_tokens=os.getenv("LLM_MAX_TOKENS", "8192"),
            idle_timeout=os.getenv("LLM_IDLE_TIMEOUT_SECONDS", "180"),
        )
    return StubBackend()
