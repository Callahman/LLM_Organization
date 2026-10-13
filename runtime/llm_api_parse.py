"""The real backend — reply parsing + truncation detection.

The parsing half of ``OpenAIBackend``: extracting the shared output envelope
from a chat completion reply (the forced ``submit_output`` tool call's JSON
arguments, a plain JSON ``content`` fallback, and a text-shape recovery for a
call the model wrote as text), and classifying a parse failure as a
*truncation* (the stream ended mid-JSON: the generation budget was exhausted,
or a truncation-shaped parse on a plausible, unbalanced JSON prefix) versus a
malformed shape the model chose. Truncations are transient — the bounded
retry loop (``runtime/llm_api_stream.py``) retries them; malformed shapes are
not.

**Decomposition (Phase 4):** extracted from ``runtime/llm_api.py`` (the
backend class + facade stay there; ``OpenAIBackend`` keeps staticmethod
delegations to these functions, so ``OpenAIBackend._parse_tool_args(...)``
etc. keep working). ``OpenAIOutputError`` is imported lazily inside the
functions that construct it (keeps the module-level dependency direction
acyclic: ``llm_api`` -> ``llm_api_parse``, never the reverse).
"""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

# The single tool the model must call to submit its structured output.
TOOL_NAME = "submit_output"
TOOL_DESCRIPTION = (
    "Submit your structured output for this task. Call this tool exactly "
    "once; its arguments are your complete output and must match your "
    "role's output schema. Do not emit placeholder, dummy, or partial "
    "calls: your first call must be your complete final answer."
)

# json.JSONDecodeError.msg prefixes that mean the input ENDED mid-value (a
# truncation) rather than a complete-but-broken shape. A cut-off JSON fails
# with one of these; a balanced (even if malformed) shape fails with a
# different message or parses.
_TRUNCATION_ERR_PREFIXES = (
    "Unterminated string",
    "Expecting value",
    "Expecting ',' delimiter",
    "Expecting property name enclosed in double quotes",
)


def plausible_json_prefix(raw: str) -> bool:
    """True if raw begins like the model's ``submit_output`` JSON (an
    object whose first member is a string key: ``{"``). A *truncation* is
    a valid prefix of the model's well-formed output, so it always starts
    this way; a *malformed* shape the model wrote as garbage (``{not
    json``) does not. This is the discriminator that keeps the truncation
    heuristic from retrying genuine garbage."""
    return raw.lstrip().startswith('{"')


def unbalanced_json(raw: str) -> bool:
    """True if raw has unclosed structure (string-aware): more open than
    close braces, or an unterminated string at the end. A complete shape
    (even a malformed one, e.g. ``{"a": 1,}``) is balanced; a cut-off one
    is not. The scan is string-aware, so a summary full of ``{``/``}``
    cannot confuse it."""
    depth = 0
    in_str = False
    esc = False
    for ch in raw:
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
    return depth > 0 or in_str


def is_truncation(raw: str, finish_reason: str,
                  err: Optional[json.JSONDecodeError] = None) -> bool:
    """True when a parse failure is a *truncation* (the stream ended
    mid-output) rather than a malformed shape the model chose.

    - ``finish_reason == "length"`` is authoritative: the server cut the
      generation at the max_tokens budget, so anything that failed to
      parse is cut off.
    - Otherwise a heuristic: a truncation-shaped JSONDecodeError (the input
      ended mid-value) on a plausible JSON prefix (it began like the
      model's ``submit_output`` JSON) that is unbalanced (unclosed braces /
      an unterminated string). A complete-but-broken shape (balanced) or a
      garbage shape (not a plausible prefix) is NOT a truncation and is not
      retried."""
    if finish_reason == "length":
        return True
    if err is None:
        return False
    if not any(err.msg.startswith(p)
               for p in _TRUNCATION_ERR_PREFIXES):
        return False
    if not plausible_json_prefix(raw):
        return False  # garbage, not a cut-off of valid JSON
    return unbalanced_json(raw)


def truncation_note(raw: str, finish_reason: str) -> str:
    """An empty string, or a `` (TRUNCATED: ...)`` diagnosis appended to
    the error message: WHY the output is truncated (``finish_reason=length``
    = the generation budget was exhausted; otherwise a truncation-shaped
    parse failure on unbalanced JSON) and how much accumulated (the
    model's chain-of-thought likely consumed most of the budget)."""
    if finish_reason == "length":
        why = "finish_reason=length — the generation budget was exhausted"
    else:
        why = "truncation-shaped parse failure on unbalanced JSON"
    return (f" (TRUNCATED: {why}; {len(raw)} chars accumulated — the "
            f"model's chain-of-thought likely consumed most of the "
            f"generation budget)")


def parse_json_documents(raw: str) -> List[Any]:
    """Parse a string that may hold MULTIPLE concatenated top-level JSON
    documents (a model quirk: two submit_output calls whose argument
    strings get merged — by the server, or by an index-blind accumulation
    — into one "Extra data" string). Returns the list of parsed values.
    Raises the JSONDecodeError of the first document that fails to parse
    (a mid-value failure on a trailing document is a truncation signal —
    the caller classifies it)."""
    dec = json.JSONDecoder()
    values: List[Any] = []
    i = 0
    n = len(raw)
    while i < n:
        while i < n and raw[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        value, i = dec.raw_decode(raw, i)
        values.append(value)
    return values


def parse_tool_args(raw: str, finish_reason: str) -> Tuple[
        Optional[Any], Optional[Any]]:
    """Parse a submit_output tool call's arguments string. Accepts a
    single JSON document OR multiple concatenated documents (the
    "Extra data" case — a model quirk: a placeholder call + the real one
    merged into one string); for multiple, the LAST top-level value wins
    (the model's final answer comes last). Returns ``(value, None)`` on
    success or ``(None, error)`` on failure — the error keeps the
    truncation flag so the bounded retry loop in ``invoke`` can act on
    it."""
    from runtime.llm_api import OpenAIOutputError  # lazy (acyclic)
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        pass  # "Extra data" (or a single broken document) — try below
    try:
        values = parse_json_documents(raw)
    except json.JSONDecodeError as e:
        truncated = is_truncation(raw, finish_reason, e)
        note = (truncation_note(raw, finish_reason)
                if truncated else "")
        err = OpenAIOutputError(
            f"{TOOL_NAME} arguments are not valid JSON"
            f"{note}: {raw[:300]!r} ({e})",
            truncated=truncated,
        )
        err.__cause__ = e
        return None, err
    if not values:
        return None, OpenAIOutputError(
            f"{TOOL_NAME} arguments are empty: {raw[:300]!r}")
    return values[-1], None


def parse_reply(data: Dict[str, Any],
                finish_reason: str = "") -> Tuple[Dict[str, Any], str]:
    """Extract the shared output envelope from a chat completion reply.

    Returns ``(envelope, outcome)`` where outcome is ``"tool_call"`` or
    ``"content_fallback"``. Preferred: the ``submit_output`` tool call's
    JSON arguments. A model (a known Qwen3 quirk, via KoboldCpp jinja
    tools) can call the forced tool TWICE in one reply — a placeholder /
    dummy call followed by the real one — so the **last** parseable
    ``submit_output`` envelope wins (the model's final answer comes
    last); if none parses, the first parse failure is raised (visible,
    never silent) — flagged ``truncated=True`` when the failure is a
    truncation (the stream ended mid-JSON: ``finish_reason`` is
    ``"length"`` or the parse is truncation-shaped on a plausible,
    unbalanced JSON prefix), which the bounded retry loop in ``invoke``
    treats as transient. Fallback: plain JSON ``content`` (a server that
    ignored the tool), or a call the model wrote as **text** inside
    ``content`` (a fenced JSON block or an embedded JSON object, via
    ``recover_tool_call``).
    """
    from runtime.llm_api import OpenAIOutputError  # lazy (acyclic)
    message = data["choices"][0]["message"]
    last_envelope: Optional[Dict[str, Any]] = None
    first_err: Optional[Any] = None
    for tc in message.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        if fn.get("name", TOOL_NAME) != TOOL_NAME:
            continue
        raw = fn.get("arguments", "")
        if isinstance(raw, dict):
            last_envelope = raw
            continue
        if not (isinstance(raw, str) and raw.strip()):
            continue
        out, err = parse_tool_args(raw, finish_reason)
        if err is not None:
            if first_err is None:
                first_err = err
            continue  # a LATER tool call may still parse
        if not isinstance(out, dict):
            if first_err is None:
                first_err = OpenAIOutputError(
                    f"{TOOL_NAME} arguments are not a JSON object: "
                    f"{raw[:300]!r}")
            continue
        last_envelope = out
    if last_envelope is not None:
        return last_envelope, "tool_call"
    content = message.get("content") or ""
    content_err: Optional[json.JSONDecodeError] = None
    if content.strip():
        try:
            out = json.loads(content)
            if isinstance(out, dict):
                return out, "content_fallback"
        except json.JSONDecodeError as e:
            content_err = e  # a truncation-shaped failure on the content
        recovered = recover_tool_call(content)
        if recovered is not None:
            return recovered, "content_fallback"
    if first_err is not None:
        # A tool call WAS present but none of them parsed — raise the
        # first parse failure (it carries the truncation flag for the
        # retry loop), not the "no tool call" error.
        raise first_err
    truncated = is_truncation(content, finish_reason, content_err)
    note = (truncation_note(content, finish_reason)
            if truncated else "")
    # An empty reply (no tool call, no content) is a transient failure — the
    # model produced nothing this attempt (a fresh attempt may produce
    # something), so it is retryable just like a truncation.
    raise OpenAIOutputError(
        f"reply has no {TOOL_NAME} tool call and no JSON object content"
        f"{note}: {content[:300]!r}"
    , truncated=truncated, retryable=(truncated or not content.strip()))


def recover_tool_call(content: str) -> Optional[Dict[str, Any]]:
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
    # Fenced blocks: ```json ... ``` (or any ``` ... ``` fence). A model
    # quirk can fence TWO blocks (a placeholder + the real one) — try
    # them LAST-FIRST (the model's final answer comes last).
    fenced: list = []
    for m in re.finditer(r"```[a-zA-Z0-9_-]*[ \t]*\n(.*?)```",
                         content, re.DOTALL):
        block = m.group(1).strip()
        if block:
            fenced.append(block)
    candidates.extend(reversed(fenced))
    # All top-level brace-delimited spans in the raw text (covers a bare
    # JSON object surrounded by prose; the scanner is string-aware so
    # braces inside string values do not confuse it). A model quirk can
    # write TWO objects (a placeholder + the real one) — try them
    # LAST-FIRST (the model's final answer comes last).
    spans: list = []
    depth = 0
    in_str = False
    esc = False
    start = -1
    for i, ch in enumerate(content):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                spans.append(content[start:i + 1])
                start = -1
    candidates.extend(reversed(spans))
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


__all__ = [
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
]
