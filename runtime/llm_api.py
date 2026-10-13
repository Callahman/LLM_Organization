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

``httpx`` is imported lazily inside the invoke loop so the stub path (and
the offline test suite) needs no network dependency installed.

**Decomposition (Phase 4):** this file keeps the backend class (``__init__``,
the payload builders, the reporting hooks, the nested-type warnings) + the
module-level helpers (``_role_label``, ``validate_and_quarantine``,
``OpenAIOutputError``, ``make_backend``). The reply parsing + truncation
detection moved to ``runtime/llm_api_parse.py`` (module functions;
``OpenAIBackend`` keeps staticmethod delegations, so
``OpenAIBackend._parse_tool_args(...)`` etc. keep working); the streaming +
bounded retry loop moved to ``runtime/llm_api_stream.py``
(``run_invoke_loop``; ``OpenAIBackend.invoke`` delegates to it). This file
re-exports the full public API (backward-compatible facade).
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from roles.base import validate_envelope
from runtime.llm import LLMBackend, Reasoning, StubBackend
from runtime.llm_api_parse import (
    TOOL_NAME,
    TOOL_DESCRIPTION,
    plausible_json_prefix,
    unbalanced_json,
    is_truncation,
    truncation_note,
    parse_json_documents,
    parse_tool_args,
    parse_reply,
    recover_tool_call,
)


def _role_label(role) -> str:
    """The role's full label for the live feed / recordings: id (always),
    sub_architype (if set), (personality) (if set), department (if set) —
    empty parts are skipped, joined with ' · '. The model name is
    deliberately NOT part of the label (every role shares the same backbone,
    so it carries no useful info)."""
    parts = [role.id]
    if getattr(role, "sub_architype", ""):
        parts.append(role.sub_architype)
    if getattr(role, "personality", ""):
        parts.append(f"({role.personality})")
    if getattr(role, "department", ""):
        parts.append(role.department)
    return " · ".join(parts)


# The known nested keys that must be JSON objects (dicts) — the Phase-2/3/4
# structured outputs the pipeline reads. A wrong type (e.g. a free-form string)
# is logged (not rejected) so future free-forms are visible in tool_calls.jsonl.
_NESTED_OBJECT_KEYS = ("mission_draft", "decomposition", "org_recommendation")


def _tool_call_problem(tc: Any) -> str:
    """Story 4 (A9/R10): return a reason if a `tool_call` is malformed (not a
    dict, missing `name`, or `args` not parseable), else '' (well-formed)."""
    if not isinstance(tc, dict):
        return f"tool_call is not a dict ({type(tc).__name__})"
    if not tc.get("name"):
        return "tool_call is missing `name`"
    args = tc.get("args")
    if args is None or isinstance(args, dict):
        return ""  # no args, or a structured dict — well-formed
    if isinstance(args, str):
        try:
            json.loads(args)
            return ""  # a JSON string — parseable
        except json.JSONDecodeError:
            return f"tool_call `args` not parseable: {args[:100]!r}"
    return f"tool_call `args` not parseable ({type(args).__name__})"


def validate_and_quarantine(role, out: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Story 4 (A8/A9/R10): envelope-validate an LLM output and quarantine a
    malformed `tool_call`. Returns ``(output, events)`` where ``output`` is the
    (possibly safe-fallback) envelope and ``events`` is a list of visible log
    lines (the caller prints them + records them in the history log). Never
    raises on a malformed shape — a visible note + a safe fallback, not a crash.
    """
    events: List[str] = []
    role_id = getattr(role, "id", "")
    # `validate_envelope` validates the required keys (`summary` + `confidence`)
    # + type-checks present keys; a missing optional key is not a problem.
    problems = validate_envelope(out)
    if problems:
        events.append(f"[llm] invalid envelope from {role_id}: "
                      f"{'; '.join(problems)}")
        # A safe fallback (a valid envelope + an `error` marker) — never a crash.
        return {"summary": "", "findings": [], "recommendation": "",
                "confidence": 0.0, "error": "invalid_envelope"}, events
    if isinstance(out, dict) and "tool_call" in out:
        reason = _tool_call_problem(out["tool_call"])
        if reason:
            events.append(f"[llm] quarantined malformed tool_call from "
                          f"{role_id}: {reason}")
            out["tool_call"] = None  # drop it — never propagate the bad call
    return out, events


class OpenAIOutputError(RuntimeError):
    """The model's reply could not be parsed into the shared output envelope
    (no usable tool call and no JSON content) — a visible failure state,
    never silent.

    ``truncated`` is True when the failure is a *truncation* (the stream ended
    mid-JSON: the generation budget was exhausted, or the parse failure is
    truncation-shaped on unbalanced JSON) rather than a malformed shape the
    model chose. Truncations are transient — the bounded retry loop in
    ``invoke`` retries them (a fresh attempt may think shorter and fit);
    malformed shapes are not (the envelope-validation layer above handles
    those)."""

    def __init__(self, message: str, truncated: bool = False):
        super().__init__(message)
        self.truncated = truncated


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
                 idle_timeout: float = 180.0, max_retries: int = 3):
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
        # Bounded retries on a timeout (a Read/Connect/Pool timeout) AND on a
        # truncated output (the stream ended mid-JSON: the generation budget
        # was exhausted): the whole streaming request is retried from the
        # start — the model's partial generation is lost (a stateless HTTP
        # request), so a resume is impossible. `max_retries` is the number of
        # retries AFTER the first attempt (default 3 -> up to 4 total
        # attempts), with a short backoff between attempts; timeouts and
        # truncations share the attempt budget. A parse error that is a
        # malformed shape the model chose (not a truncation), or a non-timeout
        # transport error, is never retried.
        try:
            self.max_retries = int(max_retries)
        except (TypeError, ValueError):
            self.max_retries = 3
        self.max_retries = max(0, self.max_retries)
        # Optional per-call stats callback (observability): called with
        # ``{ts, role, mode, outcome, error, latency}`` after every invoke.
        # The pipeline wires it to ``history/tool_calls.jsonl``; it must
        # never break a call (exceptions are swallowed).
        self.on_call: Optional[Callable[[Dict[str, Any]], None]] = None
        # Forward each streamed chunk (the dashboard's live "model stream"
        # window): (stream_id, role_id, model, kind, text, label, reasoning).
        # `label` is the role's full label (id · sub_architype · (personality)
        # · department); `reasoning` is the level actually used (HIGH/MEDIUM/
        # LOW). The model name is recorded but not rendered (all roles share
        # the same backbone).
        self.on_stream: Optional[Callable[[str, str, str, str, str, str, str], None]] = None
        # The phase of the in-flight invoke (set by invoke, read by _report):
        # the backend is driven sequentially, so this is safe. Carried to the
        # tool_calls row so the dashboard can segment calls by phase (A0).
        self._current_phase: Optional[int] = None

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

    def _thinking_directive(self, reasoning: Reasoning) -> Tuple[str, str]:
        """The (system-directive, user-marker) that steers the model's
        thinking level for a call. Complex work (HIGH) thinks fully (no
        directive); routine work (LOW) is told to answer directly with no
        extended chain-of-thought — the model's thinking is what consumes the
        generation budget and truncates the submit_output JSON, so capping it
        on the bulk of dispatch work shrinks truncation risk at the source.

        - system-directive: appended to the system message (a natural-language
          instruction that works across models).
        - user-marker: appended to the user message; the Qwen3 ``/no_think``
          token natively disables thinking on the target model (LOW only).
        """
        if reasoning is Reasoning.HIGH:
            return "", ""
        if reasoning is Reasoning.MEDIUM:
            return (" Keep your reasoning brief and focused; do not over-think "
                    "routine details."), ""
        # LOW: answer directly, no extended chain-of-thought.
        return (" Answer directly and concisily. Do NOT produce an extended "
                "chain-of-thought or reasoning preamble — go straight to the "
                "structured output."), "\n/no_think"

    def _payload(self, role, context: str,
                 reasoning: Reasoning = Reasoning.LOW) -> Dict[str, Any]:
        directive, marker = self._thinking_directive(reasoning)
        if self.structured == "json":
            system = ("You are one agent in a simulated company. "
                      "Always reply with a single JSON object that "
                      "matches your role's output schema." + directive)
            return {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": context + marker},
                ],
            }
        system = ("You are one agent in a simulated company. "
                  "Submit your structured output by calling the "
                  f"{TOOL_NAME} tool exactly once; its arguments "
                  "are your complete output and must match your "
                  "role's output schema. Do NOT emit placeholder, "
                  "dummy, or partial tool calls: your FIRST "
                  f"{TOOL_NAME} call must be your complete final "
                  "answer (a single JSON object)." + directive)
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "tools": [self._tool_for(role)],
            "tool_choice": {"type": "function",
                            "function": {"name": TOOL_NAME}},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": context + marker},
            ],
        }

    # --- reply parsing ------------------------------------------------------
    # The parsing + truncation detection moved to runtime/llm_api_parse.py
    # (Phase 4); these staticmethods delegate so
    # ``OpenAIBackend._parse_tool_args(...)`` etc. keep working unchanged.

    @staticmethod
    def _plausible_json_prefix(raw: str) -> bool:
        return plausible_json_prefix(raw)

    @staticmethod
    def _unbalanced_json(raw: str) -> bool:
        return unbalanced_json(raw)

    @staticmethod
    def _is_truncation(raw: str, finish_reason: str,
                       err: Optional[json.JSONDecodeError] = None) -> bool:
        return is_truncation(raw, finish_reason, err)

    @staticmethod
    def _truncation_note(raw: str, finish_reason: str) -> str:
        return truncation_note(raw, finish_reason)

    @staticmethod
    def _parse_json_documents(raw: str) -> List[Any]:
        return parse_json_documents(raw)

    @staticmethod
    def _parse_tool_args(raw: str, finish_reason: str) -> Tuple[
            Optional[Any], Optional[Any]]:
        return parse_tool_args(raw, finish_reason)

    @staticmethod
    def _parse(data: Dict[str, Any], finish_reason: str = "") -> Tuple[Dict[str, Any], str]:
        return parse_reply(data, finish_reason)

    @staticmethod
    def _recover_tool_call(content: str) -> Optional[Dict[str, Any]]:
        return recover_tool_call(content)

    # --- reporting ----------------------------------------------------------

    def _report(self, role, outcome: str, t0: float, error: str = "",
              warning: str = "") -> None:
        if self.on_call is None:
            return
        try:
            self.on_call({
                "ts": time.time(),
                "role": getattr(role, "id", ""),
                "department": getattr(role, "department", ""),
                "phase": self._current_phase,
                "mode": self.structured,
                "outcome": outcome,
                "error": error,
                # D4: a non-fatal warning (e.g. a wrong-typed nested key) is
                # logged in its own `warning` field — NOT the `error` field —
                # so a warning doesn't look like a failure in the audit trail.
                "warning": warning,
                "error_type": self._error_type(outcome, error),
                "latency": round(time.time() - t0, 3),
            })
        except Exception:
            pass  # observability must never break the pipeline

    def _error_type(self, outcome: str, error: str) -> Optional[str]:
        """Classify a failure (`timeout|truncation|parse|transport|other`) so
        the dashboard can segment failures without pattern-matching the
        free-form `error` string (A0). `None` on a successful call."""
        if outcome in ("tool_call", "content_fallback"):
            return None
        if outcome == "quarantined":
            return "quarantined"  # Story 4: a dropped malformed tool_call
        e = (error or "").lower()
        if "timeout" in e or "timed out" in e:
            return "timeout"
        if "truncat" in e:
            return "truncation"
        if "malformed" in e or "parse" in e or "no tool call" in e:
            return "parse"
        if ("connect" in e or "protocol" in e or "httpstatus" in e
                or "reset" in e or "httpx" in e):
            return "transport"
        return "other"

    def _emit_stream(self, stream_id: str, role, kind: str, text: str,
                     reasoning=None) -> None:
        """Forward one streamed chunk to the on_stream callback (the dashboard's
        live "model stream" window). The chunk carries the role's full label
        (id · sub_architype · (personality) · department) and the reasoning
        level actually used (HIGH/MEDIUM/LOW) — NOT the model name (every role
        shares the same backbone, so it carries no useful info). Exceptions are
        swallowed: observability must never break the pipeline (same guarantee
        as on_call)."""
        if self.on_stream is None:
            return
        try:
            self.on_stream(
                stream_id, role.id, self.model, kind, text,
                _role_label(role),
                reasoning.value.upper() if reasoning is not None else "LOW",
            )
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

    # --- the invoke ---------------------------------------------------------

    def invoke(self, role, context: str,
               reasoning: Reasoning = Reasoning.LOW,
               timeout: Optional[float] = None,
               phase: Optional[int] = None) -> Dict[str, Any]:
        """Run one live invoke: build the payload, stream the completion with
        the progress-based idle timeout, retry on a timeout or a truncated
        output (bounded, shared attempt budget), and parse the reply into the
        shared output envelope (quarantining a malformed tool_call). Delegates
        to ``runtime/llm_api_stream.run_invoke_loop`` (the streaming + bounded
        retry loop)."""
        import runtime.llm_api_stream as _stream  # lazy (avoids a cycle)
        return _stream.run_invoke_loop(
            self, role, context, reasoning, timeout, phase)


def make_backend() -> LLMBackend:
    """Select the backend from the environment (``.env``):
    ``LLM_BACKEND=stub`` (default) -> the offline ``StubBackend``;
    ``LLM_BACKEND=api`` -> ``OpenAIBackend`` built from ``LLM_MODEL`` /
    ``LLM_BASE_URL`` / ``LLM_API_KEY`` (structured-output mode from
    ``LLM_STRUCTURED``: ``tools`` (default) or ``json``; generation budget
    from ``LLM_MAX_TOKENS``: default ``8192``; idle timeout from
    ``LLM_IDLE_TIMEOUT_SECONDS``: default ``180``; bounded timeout retries
    from ``LLM_MAX_RETRIES``: default ``3``).
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
            max_retries=os.getenv("LLM_MAX_RETRIES", "3"),
        )
    return StubBackend()


def __getattr__(name: str) -> Any:
    """Facade re-export (PEP 562): ``run_invoke_loop`` lives in
    ``runtime/llm_api_stream.py`` (Phase 4); resolve it lazily so
    ``from runtime.llm_api import run_invoke_loop`` keeps working without a
    module-level import cycle."""
    if name == "run_invoke_loop":
        import runtime.llm_api_stream as _stream
        return _stream.run_invoke_loop
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # core (kept here)
    "_role_label",
    "validate_and_quarantine",
    "OpenAIOutputError",
    "OpenAIBackend",
    "make_backend",
    # facade re-exports (moved to focused modules)
    "TOOL_NAME",
    "TOOL_DESCRIPTION",
    "plausible_json_prefix",
    "unbalanced_json",
    "is_truncation",
    "truncation_note",
    "parse_json_documents",
    "parse_tool_args",
    "parse_reply",
    "recover_tool_call",
    "run_invoke_loop",
]
