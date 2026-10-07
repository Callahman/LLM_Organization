"""Central config loader (D1) — reads the ``.env`` org-tuning knobs with the
correct key mapping and hands them to ``Session``.

Before this, ``run_session.py`` only put ``timeout_seconds`` /
``ic_timeout_seconds`` in the config dict, so the pipeline silently used
hardcoded defaults for every other knob (the ``.env`` values were dead). This
loader maps each ``.env`` key to its ``Session`` config key (with the right
cast) and warns on unknown/unused ``.env`` keys (so a typo'd knob is visible,
not silently ignored).

The ``LLM_*`` keys (``LLM_BACKEND``, ``LLM_MODEL``, ...) are read directly by
``make_backend`` from the environment; this loader only handles the
non-``LLM_*`` org-tuning knobs (plus the two timeout backstops).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Tuple

# ``.env`` key -> (Session config key, cast). The cast is applied to the raw
# env string; a value that fails to cast falls back to the code default (a
# warning is printed, the run continues).
ENV_TO_CONFIG: Dict[str, Tuple[str, Any]] = {
    "CONFIDENCE_THRESHOLD": ("confidence_threshold", float),
    "QUESTION_BUDGET_ROUNDS": ("question_budget", int),
    "MISSION_REASK_BUDGET": ("mission_reask_budget", int),
    "POD_MIN_ROLES": ("pod_min_roles", int),
    "POD_MAX_ROLES": ("pod_max_roles", int),
    "POD_MAX_ROUNDS": ("pod_max_rounds", int),
    "DIRECT_IC_CAP": ("direct_ic_cap", int),
    "CONTEXT_BUDGET_TOKENS": ("context_budget_tokens", int),
    "ROLE_MEMORY_MAX_ENTRIES": ("role_memory_max_entries", int),
    "HISTORY_WINDOW_SESSIONS": ("history_window_sessions", int),
    "ARCHIVE_CAP_MB": ("archive_cap_mb", int),
    # The two wall-clock timeout backstops (the primary bound is the backend's
    # idle timeout, LLM_IDLE_TIMEOUT_SECONDS, read by make_backend).
    "LLM_TIMEOUT_SECONDS": ("timeout_seconds", float),
    "LLM_IC_TIMEOUT_SECONDS": ("ic_timeout_seconds", float),
    # D6: the Phase 4/5 iteration cap (was hardcoded 2 in run_session.py).
    "MAX_ITERATIONS": ("max_iterations", int),
}

# The ``LLM_*`` keys read directly by ``make_backend`` (not mapped here, but
# known — so they don't trigger the "unused .env key" warning).
LLM_BACKEND_KEYS = frozenset({
    "LLM_BACKEND", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY",
    "LLM_STRUCTURED", "LLM_MAX_TOKENS", "LLM_IDLE_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
})


def _warn(msg: str) -> None:
    print(f"[config] {msg}", file=sys.stderr)


def _read_env_file_keys() -> set:
    """Return the keys defined in the project ``.env`` file (not the ambient
    shell environment). Used to warn only on typo'd/unused ``.env`` knobs —
    warning on every Windows/VS Code shell var (ALLUSERSPROFILE, VSCODE_*, ...)
    would be noise."""
    keys = set()
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".env")
    if not os.path.exists(env_path):
        return keys
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.add(key)
    except OSError:
        pass
    return keys


def load_config() -> Dict[str, Any]:
    """Read the ``.env`` org-tuning knobs and return the ``Session`` config
    dict. Unknown/unused ``.env`` keys produce a visible warning (so a typo'd
    knob is not silently ignored)."""
    config: Dict[str, Any] = {}
    for env_key, (config_key, cast) in ENV_TO_CONFIG.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        try:
            config[config_key] = cast(raw)
        except (TypeError, ValueError):
            _warn(f"invalid value for {env_key}: {raw!r} (using the code default)")
    # Warn on unknown/unused .env keys — but only keys actually defined in the
    # project .env file (not the ambient shell environment, which on Windows
    # carries ALLUSERSPROFILE / COMPUTERNAME / VSCODE_* / EFC_* / ... and would
    # otherwise flood the output with false "unused" warnings).
    known = set(ENV_TO_CONFIG) | LLM_BACKEND_KEYS
    for key in _read_env_file_keys():
        if key in known:
            continue
        _warn(f"unused .env key: {key} (not read by the pipeline)")
    return config
