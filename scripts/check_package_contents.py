#!/usr/bin/env python3
"""Assert the built distributions never ship private or secret files.

Inspects the wheel and sdist in ``dist/`` (run ``uv build`` first) and fails if
anything outside the ``infomaniak_cli`` package leaks in — private planning
notes (``context/``), agent/codex caches, temp dirs, tokens, or local config.

This codifies the manual check done before tagging ``0.1.21`` so CI proves it on
every push. Pure stdlib; exits non-zero on any violation.
"""
from __future__ import annotations

import glob
import os
import sys
import tarfile
import zipfile

# Path segments that must never appear in a published artifact.
FORBIDDEN_SEGMENTS = (
    "context",
    ".agents",
    ".codex",
    ".codex-tmp",
    ".tmp",
    ".venv",
    "tokens",
)
# Token/secret file suffixes that must never be packaged.
FORBIDDEN_SUFFIXES = (".token", ".mail", ".contacts", ".calendar", ".chat")


def _violations(member_path: str) -> list[str]:
    problems: list[str] = []
    parts = member_path.replace("\\", "/").split("/")
    for segment in FORBIDDEN_SEGMENTS:
        if segment in parts:
            problems.append(f"forbidden path segment '{segment}'")
    if member_path.endswith(FORBIDDEN_SUFFIXES):
        problems.append("looks like a credential file")
    return problems


def _check_wheel(path: str) -> list[str]:
    """Wheel must contain ONLY the package and its dist-info."""
    errors: list[str] = []
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            top = name.split("/", 1)[0]
            if not (top == "infomaniak_cli" or top.startswith("infomaniak_cli-")):
                errors.append(f"{os.path.basename(path)}: unexpected top-level entry '{name}'")
            errors.extend(f"{os.path.basename(path)}: {v} in '{name}'" for v in _violations(name))
    return errors


def _check_sdist(path: str) -> list[str]:
    errors: list[str] = []
    with tarfile.open(path) as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            errors.extend(f"{os.path.basename(path)}: {v} in '{member.name}'" for v in _violations(member.name))
    return errors


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = os.path.join(repo_root, "dist")
    wheels = sorted(glob.glob(os.path.join(dist, "*.whl")))
    sdists = sorted(glob.glob(os.path.join(dist, "*.tar.gz")))

    if not wheels or not sdists:
        print(f"error: no wheel/sdist in {dist}. Run `uv build` first.", file=sys.stderr)
        return 2

    errors: list[str] = []
    for wheel in wheels:
        errors.extend(_check_wheel(wheel))
    for sdist in sdists:
        errors.extend(_check_sdist(sdist))

    if errors:
        print("Package contents check FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Package contents OK: {len(wheels)} wheel(s), {len(sdists)} sdist(s) ship only infomaniak_cli/**.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
