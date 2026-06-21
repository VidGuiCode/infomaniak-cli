from __future__ import annotations

import re

_BEARER_RE = re.compile(r"Bearer\s+[^\s]+", re.IGNORECASE)


def redact_secret(message: str) -> str:
    """Redact credential-like strings from an error/log message."""
    return _BEARER_RE.sub("Bearer ***", message)


class InformaniakAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(redact_secret(message))
