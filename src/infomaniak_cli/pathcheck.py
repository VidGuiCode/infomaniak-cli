"""Read-only install/PATH diagnostics for the `ik` entry point.

Everything here is pure and injectable: callers pass in the PATH string, the
scripts directory, the resolved executable, and the OS selector, so tests run
fully offline and never read or mutate the real environment. The only function
that touches the real interpreter config is :func:`scripts_dir`, and the only
one that reads the real PATH is :func:`locate_entry_point` (via ``shutil.which``)
— both are read-only.
"""

from __future__ import annotations

import os
import shutil
import sysconfig
from typing import Any, Callable


def locate_entry_point(which: Callable[[str], str | None] = shutil.which, *, name: str = "ik") -> str | None:
    """Return the resolved path to the `ik` executable, or None if not found."""
    return which(name)


def scripts_dir() -> str:
    """Return the scripts/bin directory for the current interpreter."""
    return sysconfig.get_path("scripts")


def user_scripts_dir() -> str | None:
    """Return the per-user scripts/bin directory, or None if unavailable."""
    scheme = f"{os.name}_user"
    if scheme not in sysconfig.get_scheme_names():
        return None
    try:
        return sysconfig.get_path("scripts", scheme)
    except (KeyError, ValueError):
        return None


def path_status(
    *,
    scripts_dir: str | None,
    ik_path: str | None,
    path_env: str,
    sep: str = os.pathsep,
) -> dict[str, Any]:
    """Compute PATH health purely from injected values.

    ``on_path`` reflects whether the resolved `ik` executable's directory is on
    PATH; ``dir_on_path`` reflects whether the install scripts directory is on
    PATH. Comparison is path-normalized and case-insensitive on Windows.
    """
    entries = {_normalize_dir(entry) for entry in path_env.split(sep) if entry}
    scripts_norm = _normalize_dir(scripts_dir) if scripts_dir else None
    dir_on_path = bool(scripts_norm and scripts_norm in entries)

    ik_dir = os.path.dirname(ik_path) if ik_path else None
    on_path = bool(ik_dir and _normalize_dir(ik_dir) in entries)

    return {
        "on_path": on_path,
        "scripts_dir": scripts_dir,
        "ik_path": ik_path,
        "ik_dir": ik_dir,
        "dir_on_path": dir_on_path,
    }


def fix_path_command(*, scripts_dir: str, os_name: str = os.name) -> str:
    """Return an exact, copy-pasteable per-user PATH fix command. Never executes.

    Windows uses a PowerShell User-scope setter (no admin, never touches the
    system or machine PATH). POSIX appends an export line to the shell rc.
    """
    if os_name == "nt":
        return (
            "powershell -NoProfile -Command "
            "\"[Environment]::SetEnvironmentVariable('Path', "
            "[Environment]::GetEnvironmentVariable('Path','User') + "
            f"';{scripts_dir}', 'User')\""
        )
    return f'echo \'export PATH="{scripts_dir}:$PATH"\' >> ~/.bashrc'


def plan_path_fix(
    scripts_dir: str,
    current_user_path: str,
    *,
    os_name: str = os.name,
    sep: str = os.pathsep,
) -> dict[str, Any]:
    """Pure compute for a per-user PATH fix; idempotent and side-effect-free.

    Returns ``already_on_path``, the computed ``new_path`` (None when already on
    PATH), a human ``change_description``, and the ``fix_command`` to run.
    """
    entries = {_normalize_dir(entry) for entry in current_user_path.split(sep) if entry}
    already_on_path = bool(scripts_dir and _normalize_dir(scripts_dir) in entries)
    if already_on_path:
        return {
            "already_on_path": True,
            "new_path": None,
            "change_description": f"{scripts_dir} is already on PATH; no change needed.",
            "fix_command": None,
        }
    new_path = f"{current_user_path}{sep}{scripts_dir}" if current_user_path else scripts_dir
    return {
        "already_on_path": False,
        "new_path": new_path,
        "change_description": f"Append {scripts_dir} to your per-user PATH.",
        "fix_command": fix_path_command(scripts_dir=scripts_dir, os_name=os_name),
    }


def _normalize_dir(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))
