from __future__ import annotations

import os


def normalize_local_path(path: str, *, os_name: str | None = None) -> str:
    """Normalize user-entered local paths without changing ordinary Unix paths.

    Git Bash/MSYS presents Windows paths as ``/c/...``.  Convert that shape
    centrally on Windows so upload and download accept the same inputs.
    """
    platform = os.name if os_name is None else os_name
    if (
        platform == "nt"
        and len(path) >= 2
        and path[0] == "/"
        and path[1].isalpha()
        and (len(path) == 2 or path[2] == "/")
    ):
        drive = path[1].upper()
        tail = path[3:] if len(path) > 2 else ""
        return f"{drive}:\\{tail.replace('/', chr(92))}"
    return path
