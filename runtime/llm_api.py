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
                 structured: str = "tools", max_tokens: int = 8192):
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
        # Optional per-call stats callback (observability): called with
        # ``{ts, role, mode, outcome, error, latency}`` after every invoke.
        # The pipeline wires it to ``history/tool_calls.jsonl``; it must
        # never break a call (exceptions are swallowed).
        self.on_call: Optional[Callable[[Dict[str, Any]], None]] = None

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
        ignored the tool). Anything else raises ``OpenAIOutputError``
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
            except json.JSONDecodeError as e:
                raise OpenAIOutputError(
                    f"reply has no {TOOL_NAME} tool call and content is not "
                    f"JSON: {content[:300]!r} ({e})"
                ) from e
            if isinstance(out, dict):
                return out, "content_fallback"
        raise OpenAIOutputError(
            f"reply has no {TOOL_NAME} tool call and no JSON object content: "
            f"{content[:300]!r}"
        )

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

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        import httpx  # lazy: only the api path needs it
        t0 = time.time()
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self._payload(role, context),
                timeout=300,
            )
            resp.raise_for_status()
            out, outcome = self._parse(resp.json())
        except OpenAIOutputError as e:
            self._report(role, "error", t0, str(e))
            raise
        except httpx.HTTPError as e:
            self._report(role, "error", t0, str(e))
            raise
        self._report(role, outcome, t0)
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
        )
    return StubBackend()
