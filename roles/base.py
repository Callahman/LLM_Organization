"""The role contract.

A `Role` carries the three identity fields (architype, sub-architype,
personality) plus the structured contract (mandate, input spec, output schema)
and the reporting-line fields the rule checks in `org/tiers.py` operate on.

The **shared output envelope** every role produces (and extends):

- `summary`          — one-line extractive summary (the truncation-safe digest)
- `findings`         — list of {claim, evidence} (evidence must cite a source)
- `recommendation`   — the role's recommended next action
- `confidence`       — 0-1 self-assessed confidence in the output
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Architypes (the four tiers).
ARCHITYPES = ("leader", "department_head", "manager", "ic")

# The shared output envelope keys.
OUTPUT_ENVELOPE_KEYS = ("summary", "findings", "recommendation", "confidence")


@dataclass
class Role:
    """A single role in the organization.

    Identity fields
    ---------------
    architype : str
        `leader` / `department_head` / `manager` / `ic` (determines the tier
        and all visibility/communication/pod rules).
    sub_architype : str
        The functional specialty within the architype
        (e.g. `manager_of_analytics`, `head_of_hr`).
    personality : str
        The behavioral bias spun into the system prompt (e.g. `Pragmatist`).
        A personality biases *perspective*, never capability or effort.

    Structured contract
    -------------------
    mandate : str
        The role's job, boundaries, and work discipline (system-level
        instruction).
    input_spec : str
        One line describing what the role's context contains.
    output_schema : dict
        The JSON schema the role's structured output must satisfy (validated
        by the session runtime; bounded retries on malformed output).

    Reporting line
    --------------
    department : str
        The department this role's team belongs to (drives the read scope).
    team : str
        The team directory within the department (drives team-mate +
        cross-team-read checks).
    reports_to : Optional[str]
        The id of this role's direct boss.
    direct_reports : List[str]
        The ids of this role's direct reports.
    """

    id: str
    architype: str
    sub_architype: str = ""
    personality: str = ""
    mandate: str = ""
    input_spec: str = ""
    output_schema: Dict[str, Any] = field(default_factory=dict)
    department: str = ""
    team: str = ""
    reports_to: Optional[str] = None
    direct_reports: List[str] = field(default_factory=list)
    status: str = "active"
    is_required: bool = False  # True for required departments (HR/Safety/Morality)

    def __post_init__(self) -> None:
        if self.architype not in ARCHITYPES:
            raise ValueError(
                f"unknown architype {self.architype!r}; "
                f"expected one of {ARCHITYPES}"
            )

    # --- Convenience -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Role":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


# --- Shared output envelope -------------------------------------------------

def validate_envelope(output: Dict[str, Any]) -> List[str]:
    """Return a list of problems with a structured output (empty if valid).

    Checks the shared envelope is present and well-formed. Roles may extend
    the envelope with their own fields; only the envelope is validated here.
    """
    problems: List[str] = []
    if not isinstance(output, dict):
        return ["output is not a dict"]
    for key in OUTPUT_ENVELOPE_KEYS:
        if key not in output:
            problems.append(f"missing envelope key: {key!r}")
    if "confidence" in output:
        try:
            c = float(output["confidence"])
            if not (0.0 <= c <= 1.0):
                problems.append(f"confidence out of range: {c}")
        except (TypeError, ValueError):
            problems.append("confidence is not a number")
    if "findings" in output and not isinstance(output["findings"], list):
        problems.append("findings is not a list")
    return problems
