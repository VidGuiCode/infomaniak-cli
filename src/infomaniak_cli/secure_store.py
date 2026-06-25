"""Best-effort owner-only hardening for local credential files.

Credential files written by `ik` (REST API token, mail/contacts/calendar app
passwords, kChat token) are plaintext on disk. This module narrows their
filesystem permissions to the current user as defense-in-depth — it is *not*
encryption. Hardening is best-effort and MUST NOT break credential saving: if a
chmod/icacls step fails (unsupported filesystem, missing ``icacls``, permission
quirk), the secret is still written and a one-line non-fatal warning is emitted.

POSIX uses ``os.chmod`` (files 0o600, dirs 0o700). Windows shells out to the
built-in ``icacls`` to drop inheritance and grant only the current user. The
icacls argv is built by the pure :func:`harden_windows_command` so it can be
unit-tested offline; the apply step runs it with ``check=False`` and swallows
any failure into a warning.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

FILE_MODE = 0o600
DIR_MODE = 0o700

Runner = Callable[[Sequence[str]], "object"]
Warn = Callable[[str], None]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _default_warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    # capture_output keeps icacls' own chatter off the user's terminal; check=False
    # so a non-zero return never raises — we classify it into a warning instead.
    return subprocess.run(list(command), check=False, capture_output=True, text=True)


def harden_windows_command(path: Path | str) -> list[str]:
    """Build the ``icacls`` argv that restricts ``path`` to the current user.

    Pure and side-effect free so it can be asserted in unit tests without
    invoking ``icacls``. Drops inherited ACEs (``/inheritance:r``) and grants the
    current user Full control only (``/grant:r``), never widening access.
    """

    return [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{getpass.getuser()}:F",
    ]


def _harden(path: Path, posix_mode: int, *, runner: Runner | None, warn: Warn | None) -> None:
    warn = warn or _default_warn
    if _is_windows():
        _harden_windows(path, runner=runner, warn=warn)
    else:
        try:
            os.chmod(path, posix_mode)
        except OSError as exc:  # unsupported fs / permission quirk — never fatal
            warn(f"could not restrict permissions on {path}: {exc}")


def _harden_windows(path: Path, *, runner: Runner | None, warn: Warn) -> None:
    runner = runner or _default_runner
    command = harden_windows_command(path)
    try:
        result = runner(command)
    except (OSError, subprocess.SubprocessError) as exc:
        # FileNotFoundError (icacls absent) is an OSError subclass.
        warn(f"could not restrict permissions on {path} via icacls: {exc}")
        return
    returncode = getattr(result, "returncode", 0)
    if returncode:
        warn(f"icacls exited with {returncode} restricting {path}")


def secure_dir(path: Path, *, runner: Runner | None = None, warn: Warn | None = None) -> Path:
    """Create ``path`` if missing and restrict it to the current user (best-effort)."""

    path.mkdir(parents=True, exist_ok=True)
    _harden(path, DIR_MODE, runner=runner, warn=warn)
    return path


def secure_write(path: Path, text: str, *, runner: Runner | None = None, warn: Warn | None = None) -> Path:
    """Write ``text`` to ``path`` then restrict the file to the current user.

    The parent directory is assumed to exist (callers run :func:`secure_dir`
    first); it is created loosely here only as a safety net. Writing always
    happens — a hardening failure is warned about, never raised.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _harden(path, FILE_MODE, runner=runner, warn=warn)
    return path
