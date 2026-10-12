"""Identity spin for dynamically-created roles.

Dynamically-spun roles (managers/ICs in Phase 4) are created without a
behavioral bias; these helpers give them a stable, deterministic identity
(``personality`` + ``sub_architype``) so a spun role is never left with an
empty identity and its persisted memory stays consistent across runs.
"""

from __future__ import annotations

import hashlib

# The fixed personality catalog. A personality biases *perspective*, never
# capability or effort.
PERSONALITIES = (
    "Pragmatist",    # ship the working version, iterate
    "Perfectionist", # polish before declaring done
    "Innovator",     # explore a better / more creative approach
    "Guardian",      # protect quality, safety, and the mission
    "Analyst",       # measure and reason from evidence
    "Catalyst",      # unblock and move the team forward
)


def spin_personality(role_id: str) -> str:
    """A stable personality pick from the catalog, keyed on the role id.

    Dynamically-spun roles (managers/ICs in Phase 4) were created without a
    behavioral bias (``personality`` defaulted to ``""``). Uses a SHA-256
    digest (not the built-in ``hash``, which is randomized per process) so the
    same role id always maps to the same personality across runs — a role's
    persisted memory stays consistent.
    """
    if not role_id:
        return PERSONALITIES[0]
    digest = hashlib.sha256(role_id.encode("utf-8")).hexdigest()
    return PERSONALITIES[int(digest, 16) % len(PERSONALITIES)]


def spin_sub_architype(architype: str, role_id: str) -> str:
    """A functional specialty for a dynamically-spun role
    (e.g. ``ic_of_revenue_finance``), consistent with the department-head
    ``head_of_<dept>`` form. Falls back to the bare architype when the role id
    is empty."""
    if not role_id:
        return architype
    return f"{architype}_of_{role_id}"
