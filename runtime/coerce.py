"""Tolerant coercion of LLM structured outputs.

The real LLM free-forms a structured output (the forced ``submit_output``
schema constrains it, but the model occasionally ignores it). The pipeline's
readers must degrade gracefully (visible, never an ``AttributeError`` crash)
when a key arrives as the wrong type (e.g. a free-form string instead of a
JSON object or array). This module provides the shared, pure coercion helpers
so every reader behaves the same way:

- ``as_float(val, default)`` — a number / numeric string -> float; else default.
- ``as_str_list(val)`` — a list / single string -> list of strings; else [].
- ``as_dict_list(val)`` — a list of dicts (non-dict items dropped); else [].

These are pure functions (no I/O) so they are unit-testable offline.
"""

from __future__ import annotations

from typing import Any, Dict, List


def as_float(val: Any, default: float = 0.0) -> float:
    """Safely convert a value to a float, tolerating the shapes the real LLM
    free-forms (a number, a numeric string, or anything else). Returns the
    default if the value is not convertible (e.g. a free-form prose string)."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def as_str_list(val: Any) -> List[str]:
    """Safely convert a value to a list of strings, tolerating the shapes the
    real LLM free-forms. A list/tuple of values is stringified (None items
    dropped); a single string becomes a one-element list (NOT a list of
    characters); anything else (None / number / dict) becomes an empty list."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val] if val.strip() else []
    if isinstance(val, (list, tuple)):
        return [str(v) for v in val if v is not None]
    return []


def as_dict_list(val: Any) -> List[Dict[str, Any]]:
    """Safely convert a value to a list of dicts, tolerating the shapes the
    real LLM free-forms. A list/tuple of dicts is returned (non-dict items
    dropped); a single dict becomes a one-element list; anything else (None /
    string / number) becomes an empty list."""
    if val is None:
        return []
    if isinstance(val, dict):
        return [val]
    if isinstance(val, (list, tuple)):
        return [v for v in val if isinstance(v, dict)]
    return []
