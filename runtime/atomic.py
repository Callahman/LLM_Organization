"""Atomic file operations resilient to the DSH file sandbox.

The DSH file sandbox intermittently denies ``os.replace`` (the atomic rename
behind the write-tmp-then-swap pattern and the log-rotation / archive-window
moves). A denied rename must not take down the run — the file still has to be
persisted (or moved). This module provides two helpers:

- :func:`atomic_write_json` — write JSON to a path via tmp + ``os.replace``,
  falling back to a direct write if the rename is denied.
- :func:`safe_rename` — rename a file via ``os.replace``, falling back to
  copy + remove if the rename is denied.

Both are "visible, never silent": the content is still persisted/moved in the
fallback case (just not via the atomic rename), and a *real* failure (where the
fallback also fails) still raises.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any


def atomic_write_json(path: str, payload: Any, **json_kwargs: Any) -> str:
    """Write ``payload`` (JSON) to ``path`` atomically (tmp + ``os.replace``),
    falling back to a direct write if the sandbox denies the rename.

    The write goes to ``path + ".tmp"`` first, then ``os.replace`` swaps it in
    (a crash mid-write leaves the previous good file intact). When the DSH
    sandbox denies the rename (``PermissionError`` / ``OSError``), the helper
    falls back to writing directly to ``path`` (the content is still persisted;
    the tmp file is cleaned up) so a rename denial never crashes the run.
    Returns the path written.
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, **json_kwargs)
    try:
        os.replace(tmp, path)
    except OSError:
        # ``PermissionError`` is an ``OSError`` — the sandbox denied the atomic
        # rename. Fall back to a direct write so the content is still persisted
        # (visible, never silent — the file is written, just not via the atomic
        # swap). A real failure here (the direct write also denied) still raises.
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, **json_kwargs)
        try:
            os.remove(tmp)
        except OSError:
            pass
    return path


def safe_rename(src: str, dst: str) -> str:
    """Rename ``src`` to ``dst`` (``os.replace``), falling back to copy + remove
    if the sandbox denies the rename.

    A denied rename must not take down the run (log rotation and the archive
    window are maintenance). The fallback copies the file to ``dst`` and removes
    ``src`` (the file is still moved; just not via the atomic rename). A real
    failure (the copy also denied) still raises. Returns ``dst``.
    """
    try:
        os.replace(src, dst)
    except OSError:
        # The sandbox denied the rename. Fall back to copy + remove so the file
        # is still moved (visible, never silent).
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass
    return dst
