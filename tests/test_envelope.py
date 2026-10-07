"""Tests for Story 4 — live-path envelope validation + tool_call quarantine.

`validate_and_quarantine` (in `runtime/llm_api.py`) is the function
`OpenAIBackend.invoke` calls on every live output: it envelope-validates the
output (a visible note + a safe fallback on a malformed envelope — never a
crash) and quarantines a malformed `tool_call` (dropped + logged, never
propagated). A missing *optional* envelope key (`findings` / `recommendation`)
is not a malformation — the role schemas only require `summary` + `confidence`.
"""

from types import SimpleNamespace

from roles.base import validate_envelope
from runtime.llm_api import validate_and_quarantine


def _role():
    return SimpleNamespace(id="test_role")


def _valid_envelope(**extra):
    # A well-formed envelope: the always-required keys (+ optional extras).
    out = {"summary": "did the work", "confidence": 0.8}
    out.update(extra)
    return out


# --- (a) malformed envelope -> safe fallback --------------------------------


def test_malformed_envelope_list_returns_fallback():
    # A list instead of a dict is not a valid envelope -> the safe fallback
    # (a valid envelope + an `error` marker), never a crash.
    out, events = validate_and_quarantine(_role(), ["not", "a", "dict"])
    assert out["error"] == "invalid_envelope"
    assert out["summary"] == ""
    assert out["confidence"] == 0.0
    # The visible note is produced (the caller prints + logs it).
    assert any("invalid envelope" in ev for ev in events)


def test_malformed_envelope_missing_required_key_returns_fallback():
    # Missing an always-required key (`summary` / `confidence`) is a
    # malformation -> the safe fallback.
    out, events = validate_and_quarantine(
        _role(), {"findings": [], "recommendation": "x"})
    assert out["error"] == "invalid_envelope"
    assert any("invalid envelope" in ev for ev in events)


def test_wellformed_envelope_omitting_optional_keys_passes_through():
    # A well-formed output that omits the OPTIONAL keys (`findings` /
    # `recommendation`) is NOT a malformation (the schemas only require
    # `summary` + `confidence`) -> it passes through unchanged.
    out = _valid_envelope(decomposition={"team_objectives": []})
    result, events = validate_and_quarantine(_role(), out)
    assert result is out  # the same object, not a fallback
    assert result["decomposition"] == {"team_objectives": []}
    assert events == []


# --- (b) malformed tool_call -> quarantined ---------------------------------


def test_malformed_tool_call_not_a_dict_is_quarantined():
    # A `tool_call` that is not a dict is quarantined (dropped to None + a
    # visible note), and the rest of the output is returned.
    out = _valid_envelope(tool_call="not-a-dict")
    result, events = validate_and_quarantine(_role(), out)
    assert result["tool_call"] is None  # dropped — never propagated
    assert result["summary"] == "did the work"  # the rest is intact
    assert any("quarantined malformed tool_call" in ev for ev in events)


def test_malformed_tool_call_missing_name_is_quarantined():
    # A `tool_call` with no `name` is quarantined.
    out = _valid_envelope(tool_call={"args": {"x": 1}})
    result, events = validate_and_quarantine(_role(), out)
    assert result["tool_call"] is None
    assert any("quarantined malformed tool_call" in ev for ev in events)


def test_malformed_tool_call_unparseable_args_is_quarantined():
    # A `tool_call` whose `args` is a non-parseable string is quarantined.
    out = _valid_envelope(tool_call={"name": "do_thing", "args": "{not json"})
    result, events = validate_and_quarantine(_role(), out)
    assert result["tool_call"] is None
    assert any("quarantined malformed tool_call" in ev for ev in events)


def test_wellformed_tool_call_is_kept():
    # A well-formed `tool_call` (a dict with a `name` + parseable args) is
    # kept (not quarantined).
    tc = {"name": "do_thing", "args": {"x": 1}}
    out = _valid_envelope(tool_call=tc)
    result, events = validate_and_quarantine(_role(), out)
    assert result["tool_call"] == tc  # kept
    assert events == []


# --- validate_envelope: required vs optional keys ---------------------------


def test_validate_envelope_required_vs_optional_keys():
    # `validate_envelope` requires only `summary` + `confidence`; a missing
    # optional key (`findings` / `recommendation`) is NOT a problem.
    assert validate_envelope({"summary": "s", "confidence": 0.5}) == []
    # A missing required key IS a problem.
    assert validate_envelope({"confidence": 0.5})  # missing `summary`
    assert validate_envelope({"summary": "s"})  # missing `confidence`
    # A wrong-typed present key is a problem.
    assert validate_envelope({"summary": "s", "confidence": 0.5,
                              "findings": "not-a-list"})
