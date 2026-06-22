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


def search_files(
    api: Any,
    drive_id: str,
    query: str,
    *,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    query_lower = query.casefold()
    matches = [
        file_item
        for file_item in list_files(api, drive_id)
        if query_lower in str(file_item.get("name") or "").casefold()
    ]
    if limit is not None:
        return matches[:limit]
    return matches


def find_file(api: Any, drive_id: str, file_id: str) -> Mapping[str, Any] | None:
    for file_item in list_files(api, drive_id):
        if str(file_item.get("id")) == str(file_id):
            return file_item
    return None


def slim_file(file_item: Mapping[str, Any], *, drive_id: str | None = None) -> dict[str, Any]:
    return {
        "id": _string_or_none(file_item.get("id")),
        "name": _string_or_none(file_item.get("name") or file_item.get("display_name")),
        "type": _file_type(file_item),
        "parent_id": _parent_id(file_item),
        "drive_id": _string_or_none(file_item.get("drive_id") or drive_id),
        "visibility": _string_or_none(file_item.get("visibility") or file_item.get("visibility_type")),
        "created_at": file_item.get("created_at") or file_item.get("created"),
        "last_modified_at": (
            file_item.get("last_modified_at")
            or file_item.get("modified_at")
            or file_item.get("updated_at")
            or file_item.get("updated")
        ),
    }


def slim_files(files: list[Mapping[str, Any]], *, drive_id: str | None = None) -> list[dict[str, Any]]:
    return [slim_file(file_item, drive_id=drive_id) for file_item in files]


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


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _file_type(file_item: Mapping[str, Any]) -> str | None:
    value = file_item.get("type")
    if value is not None:
        return str(value)
    if file_item.get("is_dir") or file_item.get("is_directory") or file_item.get("is_folder"):
        return "folder"
    if file_item.get("mime_type") or file_item.get("size") is not None:
        return "file"
    return None


def _parent_id(file_item: Mapping[str, Any]) -> str | None:
    value = file_item.get("parent_id")
    if value is not None:
        return str(value)
    parent = file_item.get("parent")
    if isinstance(parent, Mapping):
        value = parent.get("id")
        if value is not None:
            return str(value)
    return None
