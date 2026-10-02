"""Unit tests for `runtime/coerce.py` — tolerant coercion of LLM structured
outputs.

The real LLM free-forms a structured output (the forced submit_output schema
constrains it, but the model occasionally ignores it). The pipeline's readers
must degrade gracefully (visible, never an AttributeError crash) when a key
arrives as the wrong type. These tests pin the coercion helpers' behavior.
"""

from runtime.coerce import as_float, as_str_list, as_dict_list


def test_as_float():
    # A number.
    assert as_float(0.9) == 0.9
    # A numeric string.
    assert as_float("0.9") == 0.9
    # A free-form prose string -> default.
    assert as_float("prose", 0.0) == 0.0
    # None -> default.
    assert as_float(None, 0.5) == 0.5
    # A dict -> default.
    assert as_float({"a": 1}, 0.2) == 0.2


def test_as_str_list():
    # A list of values.
    assert as_str_list(["a", "b"]) == ["a", "b"]
    # A single string -> one-element list (NOT a list of characters).
    assert as_str_list("one") == ["one"]
    # A whitespace-only string -> empty list.
    assert as_str_list("   ") == []
    # A number -> empty list.
    assert as_str_list(5) == []
    # None -> empty list.
    assert as_str_list(None) == []
    # Non-string list items are stringified; None items dropped.
    assert as_str_list([1, "x", None]) == ["1", "x"]


def test_as_dict_list():
    # A list of dicts (non-dict items dropped).
    assert as_dict_list([{"p": 1}, "x", 3]) == [{"p": 1}]
    # A single dict -> one-element list.
    assert as_dict_list({"p": 1}) == [{"p": 1}]
    # A string -> empty list.
    assert as_dict_list("str") == []
    # A number -> empty list.
    assert as_dict_list(5) == []
    # None -> empty list.
    assert as_dict_list(None) == []
