from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"(Authorization:\s*Bearer\s+)[^\s,;]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[^\s,;]+", re.IGNORECASE),
    re.compile(r"((?:token|password|secret|cookie)=)[^\s,;]+", re.IGNORECASE),
)


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted


def pretty_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def compact_json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def error_json(error_type: str, message: str, exit_code: int) -> str:
    return compact_json(
        {
            "error": {
                "type": error_type,
                "message": redact(message),
                "exit_code": exit_code,
            }
        }
    )


def render_table(rows: Iterable[Mapping[str, Any]], columns: list[tuple[str, str]]) -> str:
    materialized = list(rows)
    widths = {
        key: max(
            len(label),
            *(len(_format_cell(row.get(key))) for row in materialized),
        )
        for key, label in columns
    }
    header = "  ".join(label.ljust(widths[key]) for key, label in columns).rstrip()
    separator = "  ".join("-" * widths[key] for key, _label in columns).rstrip()
    body = [
        "  ".join(_format_cell(row.get(key)).ljust(widths[key]) for key, _label in columns).rstrip()
        for row in materialized
    ]
    return "\n".join([header, separator, *body])


def _format_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return compact_json(value)
    return str(value)
