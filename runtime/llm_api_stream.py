"""The real backend — streaming + bounded retry loop.

The streaming half of ``OpenAIBackend.invoke``: the progress-based idle
timeout (the ``read`` timeout is the max time to wait for the NEXT chunk —
a thinking model keeps emitting chunks so it never trips; a hung model
does), the per-tool-call-index accumulation (a model can call the forced
tool twice in one reply — a placeholder + the real one — so the calls stay
distinct), the bounded retries on a timeout AND on a truncated output (the
two share the attempt budget; a malformed-shape parse error or a
non-timeout transport error is NOT retried), and the per-attempt latency
reporting (D4: the reported latency is PER-ATTEMPT, not cumulative across
retries + backoff sleeps).

**Decomposition (Phase 4):** extracted from ``runtime/llm_api.py`` (the
backend class + facade stay there; ``OpenAIBackend.invoke`` delegates to
``run_invoke_loop``).
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Optional

from runtime.llm import Reasoning
from runtime.llm_api import OpenAIOutputError, validate_and_quarantine
from runtime.llm_api_parse import TOOL_NAME


def run_invoke_loop(backend, role, context: str,
                    reasoning: Reasoning = Reasoning.LOW,
                    timeout: Optional[float] = None,
                    phase: Optional[int] = None) -> Dict[str, Any]:
    """Run one backend invoke against ``backend`` (an ``OpenAIBackend``):
    build the payload, stream the completion with the progress-based idle
    timeout, accumulate the three buffers (reasoning / content /
    per-index tool-call args), retry on a timeout or a truncated output
    (bounded, shared attempt budget), and parse the reply into the shared
    output envelope (quarantining a malformed tool_call).

    ``reasoning`` steers the model's thinking level (HIGH = full thinking,
    LOW = answer directly with no extended chain-of-thought): the
    complexity router routes routine work to LOW, capping the thinking
    tokens that would otherwise consume the generation budget and truncate
    the submit_output JSON. ``timeout`` (a per-invoke wall-clock budget) is
    accepted for interface parity with the wrapper backends. It is NOT
    enforced here: the progress-based idle timeout (the ``read`` timeout)
    is the primary guard within the invoke, and a ``TimeoutBackend``
    wrapper (when present) enforces the overall per-invoke budget.
    """
    import httpx  # lazy: only the api path needs it
    t0 = time.time()
    backend._current_phase = phase  # carried to the tool_calls row (A0)
    payload = backend._payload(role, context, reasoning)
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
    # Bounded retries on a timeout AND on a truncated output: a
    # Read/Connect/Pool timeout means the request (or its stream) stalled;
    # a truncated output (finish_reason="length" / truncation-shaped parse
    # on a plausible, unbalanced JSON prefix) means the generation budget
    # was exhausted mid-JSON. In both cases the model's partial generation
    # is lost (a stateless HTTP request), so the only recovery is to retry
    # the whole request from the start. Up to `max_retries` retries AFTER
    # the first attempt (default 3 -> up to 4 total attempts), with a short
    # backoff; the two share the attempt budget. A malformed-shape parse
    # error or a non-timeout transport error is NOT retried.
    max_attempts = 1 + backend.max_retries
    for attempt in range(1, max_attempts + 1):
        # D4: reset the attempt clock each retry so the reported latency is
        # PER-ATTEMPT (not cumulative across retries + backoff sleeps, which
        # was misleading — a 3rd-attempt success looked like it took the sum
        # of all three attempts plus the backoffs).
        t0 = time.time()
        reasoning_buf = ""
        content_buf = ""
        # Per tool-call index: a model quirk (a known Qwen3 pattern, via
        # KoboldCpp jinja tools) is to call the forced tool TWICE in one
        # reply — a placeholder/dummy call followed by the real one. The
        # OpenAI streaming format identifies each tool call by `index`;
        # accumulate per-index so the calls stay DISTINCT (an index-blind
        # concatenation merged them into one "Extra data" string that
        # crashed the run).
        tool_args_by_index: Dict[int, str] = {}
        tool_name_by_index: Dict[int, str] = {}
        finish_reason = ""
        try:
            with httpx.stream(
                "POST",
                f"{backend.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {backend.api_key}"},
                json=payload,
                # Story 9 (B6): the per-invoke `timeout` (threaded down from
                # the TimeoutBackend) caps the httpx `read` timeout so the
                # underlying HTTP call is bounded to the TimeoutBackend's
                # bound (no long-lived zombie thread). If no per-invoke
                # timeout is provided, keep the existing idle_timeout.
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=(backend.idle_timeout if timeout is None
                          else min(backend.idle_timeout, timeout)),
                    write=10.0, pool=10.0,
                ),
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
                    choice = choices[0]
                    fr = choice.get("finish_reason")
                    if fr:
                        finish_reason = fr  # the final chunk reports it
                    delta = choice.get("delta") or {}
                    rc = delta.get("reasoning_content") or ""
                    if rc:
                        reasoning_buf += rc
                        backend._emit_stream(stream_id, role, "thinking", rc, reasoning)
                    cc = delta.get("content") or ""
                    if cc:
                        content_buf += cc
                        backend._emit_stream(stream_id, role, "content", cc, reasoning)
                    for tc in delta.get("tool_calls") or []:
                        # The tool call's `index` (the OpenAI streaming
                        # format): a second submit_output call in the same
                        # reply streams as index 1, not a continuation of
                        # index 0.
                        try:
                            idx = int(tc.get("index", 0))
                        except (TypeError, ValueError):
                            idx = 0
                        fn = (tc or {}).get("function") or {}
                        if fn.get("name"):
                            tool_name_by_index[idx] = fn["name"]
                        ta = fn.get("arguments") or ""
                        if ta:
                            tool_args_by_index[idx] = (
                                tool_args_by_index.get(idx, "") + ta)
                            backend._emit_stream(stream_id, role,
                                                 "tool_call", ta, reasoning)
            # Reconstruct the non-streaming message shape and reuse _parse
            # (tool-call extraction, content fallback, text-shape
            # recovery). One entry per streamed tool-call index (in index
            # order) — multiple submit_output calls stay separate for
            # _parse to select from (the last parseable one wins).
            message = {"role": "assistant", "content": content_buf}
            tool_calls = [
                {"function": {"name": tool_name_by_index.get(idx,
                                                              TOOL_NAME),
                              "arguments": tool_args_by_index[idx]}}
                for idx in sorted(tool_args_by_index)
            ]
            if tool_calls:
                message["tool_calls"] = tool_calls
            out, outcome = backend._parse(
                {"choices": [{"message": message}]}, finish_reason)
            # Story 4 (A8/A9/R10): envelope-validate the output and
            # quarantine a malformed tool_call (a visible note + a safe
            # fallback / a dropped call — never a crash).
            out, events = validate_and_quarantine(role, out)
            for ev in events:
                print(ev, file=sys.stderr)
            if any("invalid envelope" in ev for ev in events):
                # An invalid envelope: record it as an error (not the
                # standard success row) and return the safe fallback.
                backend._report(role, "error", t0, error="; ".join(events))
                return out
            if any("quarantined malformed tool_call" in ev for ev in events):
                # A quarantined tool_call: record it in the audit trail
                # (mirrors the existing `log_tool_call` wiring via on_call).
                backend._report(role, "quarantined", t0,
                                error="; ".join(events))
            # Observability: log (not reject) a wrong-typed nested key
            # (e.g. a free-form string instead of a JSON object) so future
            # free-forms are visible in tool_calls.jsonl. D4: it goes in the
            # `warning` field (not `error`) — it's non-fatal. A model quirk
            # that called the forced tool TWICE (a placeholder + the real
            # one) is also logged as a `warning` (the call succeeded — the
            # parser used the last parseable call).
            n_submit = sum(
                1 for tc in message.get("tool_calls") or []
                if ((tc or {}).get("function") or {}).get(
                    "name", TOOL_NAME) == TOOL_NAME)
            multi_note = (f"multiple {TOOL_NAME} calls: {n_submit} — "
                          f"used the last" if n_submit > 1 else "")
            warn = " ".join(
                w for w in (multi_note, backend._nested_type_warnings(out))
                if w)
            backend._report(role, outcome, t0, warning=warn)
            return out
        except httpx.TimeoutException as e:
            # A timeout (an idle/connect/read timeout): transient. Retry the
            # whole request (bounded, with a short backoff), then re-raise.
            if attempt < max_attempts:
                backoff = min(30.0, 5.0 * attempt)
                backend._report(role, "retry", t0,
                                f"attempt {attempt}/{max_attempts} timed out "
                                f"({type(e).__name__}); retrying in "
                                f"{backoff:.0f}s")
                time.sleep(backoff)
                continue
            backend._report(role, "error", t0,
                            f"LLM request timed out after {max_attempts} "
                            f"attempts (no response chunk for "
                            f"{backend.idle_timeout}s on the last — the model "
                            f"may be hung) ({type(e).__name__}): {e}")
            raise
        except OpenAIOutputError as e:
            # A parse failure. A *transient* failure is retried (bounded,
            # with a short backoff, sharing the attempt budget with
            # timeouts): a truncation (the stream ended mid-JSON — the
            # generation budget was exhausted, or the parse is
            # truncation-shaped on a plausible, unbalanced JSON prefix; a
            # fresh attempt may think shorter and fit) or an empty reply
            # (the model produced no content this attempt; a fresh attempt
            # may produce something). A malformed shape the model chose is
            # NOT retried (the session's invoke_checked handles malformed
            # output at a higher level).
            if e.retryable and attempt < max_attempts:
                backoff = min(30.0, 5.0 * attempt)
                why = ("truncated output (the generation budget was "
                       "exhausted mid-JSON)" if e.truncated
                       else "an empty reply (no content produced)")
                backend._report(role, "retry", t0,
                                f"attempt {attempt}/{max_attempts} returned "
                                f"{why}; retrying in {backoff:.0f}s")
                time.sleep(backoff)
                continue
            backend._report(role, "error", t0, str(e))
            raise
        except httpx.HTTPError as e:
            # Another transport error (a connection reset, an HTTP status
            # error, ...): not a timeout, so not retried (a visible
            # failure state, never silent).
            backend._report(role, "error", t0, str(e))
            raise
    # Unreachable: the loop either returns or raises on the final attempt.
    raise RuntimeError("unreachable: retry loop exited without a result")


__all__ = ["run_invoke_loop"]
