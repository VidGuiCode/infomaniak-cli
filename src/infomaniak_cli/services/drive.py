from __future__ import annotations

import json
from typing import Any, Mapping

from ..api import redact_secret


class DriveError(ValueError):
    pass


def list_files(
    api: Any,
    drive_id: str,
    *,
    parent_id: str | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    params: dict[str, Any] = {}
    if parent_id:
        params["parent_id"] = parent_id
    if limit is not None:
        params["limit"] = limit

    payload = api.get(f"/2/drive/{drive_id}/files", params=params or None)
    return _file_items(payload)


def slim_file(file_item: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("id", "name", "type", "size", "created_at", "updated_at")
    return {field: file_item[field] for field in fields if field in file_item and file_item[field] is not None}


def slim_files(files: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_file(file_item) for file_item in files]


def _file_items(payload: Any) -> list[Mapping[str, Any]]:
    data = _unwrap_success_data(payload)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    raise DriveError("Unexpected kDrive files response: expected result=success with data list")


def _unwrap_success_data(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]

    if isinstance(payload, Mapping) and payload.get("result") == "error":
        raise DriveError(f"kDrive files request failed: {_error_message(payload)}")

    if isinstance(payload, list):
        return payload

    raise DriveError("Unexpected kDrive files response: expected result=success with data list")


def _error_message(payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping):
        for key in ("message", "description", "code"):
            value = error.get(key)
            if value:
                return redact_secret(str(value))
        try:
            return redact_secret(json.dumps(dict(error), sort_keys=True))
        except TypeError:
            return redact_secret(str(error))
    if error:
        return redact_secret(str(error))
    return redact_secret(str(payload))
