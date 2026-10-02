"""Output schemas for the worker roles (department heads, managers, ICs).

The Leader has a rich ``output_schema`` (``roles/leader.py``), but the worker
roles are spun up dynamically with an **empty** schema (``roles/base.py``
defaults ``output_schema`` to ``{}``). Because ``OpenAIBackend`` offers the
role's ``output_schema`` as the forced ``submit_output`` tool, an empty schema
meant the model was unconstrained and free-formed its Phase-4 ``decomposition``
(sometimes a dict, sometimes a string) -- which crashed ``dispatch`` on
``head_out["decomposition"].get(...)``.

These schemas give every worker role that produces structured JSON a real,
forced shape -- the same fix that resolved the Phase-3 ``org_recommendation``
regression, applied to the rest of the org. ``worker_output_schema(architype)``
returns the schema for a given architype (so the role-creation sites in
``runtime/org.py`` and ``runtime/dispatch.py`` can attach it).
"""

from __future__ import annotations

from typing import Any, Dict

# The shared output envelope every role produces (and extends).
_ENVELOPE = {
    "summary": {"type": "string"},
    "findings": {"type": "array"},
    "recommendation": {"type": "string"},
    "confidence": {"type": "number"},
}


def _schema(properties: Dict[str, Any], required: list) -> Dict[str, Any]:
    """Build a role output schema from an envelope + phase-specific properties."""
    props = dict(_ENVELOPE)
    props.update(properties)
    return {"type": "object", "properties": props,
            "required": ["summary", "confidence"] + required}


# Department head (Phase 4): decompose a department objective into team
# objectives. The `team_objectives` array is REQUIRED -- the exact shape
# `runtime/dispatch.py::dispatch` reads (`team_objectives[].manager_id` /
# `ic_id` / `objective`).
HEAD_OUTPUT_SCHEMA: Dict[str, Any] = _schema(
    {
        "decomposition": {
            "type": "object",
            "properties": {
                "team_objectives": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "manager_id": {"type": "string"},
                            "ic_id": {"type": "string"},
                            "team": {"type": "string"},
                            "objective": {"type": "string"},
                        },
                        "required": ["objective"],
                    },
                },
            },
            "required": ["team_objectives"],
        },
    },
    required=[],
)

# Manager (Phase 4): decompose a team objective into IC tasks. The `ic_tasks`
# array is REQUIRED -- the exact shape `dispatch` reads (`ic_tasks[].ic_id` /
# `task`).
MANAGER_OUTPUT_SCHEMA: Dict[str, Any] = _schema(
    {
        "decomposition": {
            "type": "object",
            "properties": {
                "ic_tasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ic_id": {"type": "string"},
                            "task": {"type": "string"},
                        },
                        "required": ["ic_id", "task"],
                    },
                },
            },
            "required": ["ic_tasks"],
        },
    },
    required=[],
)

# IC (Phase 4): do the work and report up. `work_path` (where the work lives)
# and `code_edits` (gated self-edits) are the structured extensions `dispatch`
# reads.
IC_OUTPUT_SCHEMA: Dict[str, Any] = _schema(
    {
        "work_path": {"type": "string"},
        "code_edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    required=[],
)

# The architype -> output schema map (the worker roles only; the Leader has its
# own schema in roles/leader.py).
_WORKER_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "department_head": HEAD_OUTPUT_SCHEMA,
    "manager": MANAGER_OUTPUT_SCHEMA,
    "ic": IC_OUTPUT_SCHEMA,
}


def worker_output_schema(architype: str) -> Dict[str, Any]:
    """Return the output schema for a worker architype (empty for the Leader or
    an unknown architype -- the Leader carries its own schema)."""
    return _WORKER_SCHEMAS.get(architype, {})
