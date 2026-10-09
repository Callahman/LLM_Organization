"""Bounded-retry guard for user-approval callbacks (Story 11, B11).

The user-approval functions (`user_answer_fn`, `user_permission_fn`) are
operator-supplied callbacks that the session invokes to get the user's answer
or permission. A transient failure (e.g. a flaky stdin read, a timeout) should
not crash the session — it should be retried (bounded) and, on final failure,
escalated visibly (never a silent crash).

This module provides `guarded_call`: a bounded-retry wrapper that:
1. Tries the callback.
2. On failure, logs a visible `[session] user-approval call failed: <reason>`
   note and retries (up to `max_attempts` attempts).
3. On final failure, raises a `UserApprovalError` (visible, never silent).
"""

from __future__ import annotations

import sys
from typing import Any, Callable


class UserApprovalError(RuntimeError):
    """Raised when a user-approval callback fails after all bounded retries.

    The message carries the last failure reason, so the operator can see *why*
    the callback failed (not just that it failed).
    """


def guarded_call(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 2,
    **kwargs: Any,
) -> Any:
    """Call ``fn(*args, **kwargs)`` with a bounded retry.

    On each failure, a visible ``[session] user-approval call failed: <reason>``
    note is written to stderr and the call is retried (up to ``max_attempts``
    attempts). On final failure, a ``UserApprovalError`` is raised (visible,
    never a silent crash).
    """
    last_reason = ""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — any callback failure is retried
            last_reason = str(e) or e.__class__.__name__
            print(
                f"[session] user-approval call failed (attempt {attempt}/"
                f"{max_attempts}): {last_reason}",
                file=sys.stderr,
            )
    raise UserApprovalError(
        f"user-approval call failed after {max_attempts} attempts: {last_reason}"
    )
