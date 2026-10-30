"""Root pytest configuration for running the suite under the DSH file sandbox.

The DSH file sandbox has two quirks that break pytest out of the box:

1. **Tainted basetemp** — a directory created with an explicit mode
   (``mkdir(mode=0o700)``) or on which ``Path.resolve()`` was called becomes
   inaccessible: the sandbox denies file writes, directory scans
   (``os.scandir``/``iterdir``), and subdirectory creation inside it, and the
   denial persists across processes. pytest's ``TempPathFactory.getbasetemp()``
   does ``basetemp.mkdir(mode=0o700)`` followed by ``basetemp.resolve()``, and
   ``make_numbered_dir`` (which creates each ``tmp_path`` directory) does
   ``new_path.mkdir(mode=0o700)`` — so the ``tmp_path`` fixture fails with
   ``PermissionError`` once the basetemp is tainted.

2. **Denied atomic renames** — ``os.replace`` (the write-tmp-then-swap rename)
   is intermittently denied. The code handles this in ``runtime/atomic.py``
   (each atomic write / rename falls back to a direct write / copy+remove), so
   a denied rename no longer crashes the run.

This ``conftest.py`` auto-loads (pytest loads the rootdir ``conftest.py`` for
every run) and fixes quirk #1 by:

1. pointing ``--basetemp`` at a fresh directory inside the session workspace
   when none was given (the system temp dir is a fixed location that gets
   tainted and stays tainted);
2. patching ``TempPathFactory.getbasetemp`` to use the default mkdir mode and
   to skip the ``resolve()`` call (the path is already absolute, so the result
   is identical);
3. patching ``make_numbered_dir`` to use the default mkdir mode;
4. making the session-finish dead-symlink cleanup best-effort.

The logic is harmless in a non-sandboxed environment (a fresh in-workspace
basetemp and default-mode mkdir are both fine there).
"""
import os
import shutil
import time
from pathlib import Path


def _fresh_basetemp() -> Path:
    """A fresh, never-reused basetemp directly in the current working
    directory. (A previously-used subdirectory may itself be tainted by an
    earlier run, and creating children inside a tainted directory is denied.)
    """
    return Path(os.getcwd()) / f"pytest_basetemp_{int(time.time() * 1000)}_{os.getpid()}"


def _safe_getbasetemp(self):
    """Like TempPathFactory.getbasetemp, but with default-mode mkdir and no
    Path.resolve() (both taint the directory under the DSH sandbox)."""
    if self._basetemp is not None:
        return self._basetemp
    if self._given_basetemp is not None:
        basetemp = self._given_basetemp
        if basetemp.exists():
            shutil.rmtree(basetemp, ignore_errors=True)
        basetemp.mkdir(parents=True)
    else:
        raise RuntimeError(
            "conftest: --basetemp must be set (auto-set in pytest_configure)"
        )
    self._basetemp = basetemp
    return self._basetemp


def _safe_make_numbered_dir(root, prefix, mode=0o700):
    """Like _pytest.pathlib.make_numbered_dir, but with default-mode mkdir
    (an explicit mode taints the directory under the DSH sandbox)."""
    from _pytest import pathlib as pmod

    for i in range(10):
        max_existing = max(
            map(pmod.parse_num, pmod.find_suffixes(root, prefix)), default=-1
        )
        new_path = root.joinpath(f"{prefix}{max_existing + 1}")
        try:
            new_path.mkdir()
        except Exception:
            pass
        else:
            pmod._force_symlink(root, prefix + "current", new_path)
            return new_path
    raise OSError(
        "could not create numbered dir with prefix "
        f"{prefix} in {root} after 10 tries"
    )


def _safe_cleanup(root):
    try:
        shutil.rmtree(root, ignore_errors=True)
    except Exception:
        pass


def pytest_configure(config):
    if getattr(config.option, "basetemp", None) is None:
        config.option.basetemp = _fresh_basetemp()

    from _pytest import pathlib as pmod
    from _pytest import tmpdir as tmpdir_mod

    tmpdir_mod.TempPathFactory.getbasetemp = _safe_getbasetemp
    # tmpdir.py does "from .pathlib import make_numbered_dir", so patch the
    # name in the tmpdir module's namespace (and pathlib's, for good measure).
    tmpdir_mod.make_numbered_dir = _safe_make_numbered_dir
    pmod.make_numbered_dir = _safe_make_numbered_dir
    tmpdir_mod.cleanup_dead_symlinks = _safe_cleanup
