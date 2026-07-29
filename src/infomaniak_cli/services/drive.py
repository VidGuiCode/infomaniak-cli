from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping

from ..api import InformaniakAPIError, redact_secret


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


# kDrive represents the drive root as the special directory whose id is 1
# (visibility "is_root", depth 0). New folders are created *inside* a parent
# directory, so mkdir at the top level targets this root id.
DRIVE_ROOT_ID = "1"


def create_folder(
    api: Any,
    drive_id: str,
    name: str,
    *,
    parent_id: str | None = None,
) -> Mapping[str, Any]:
    # kDrive create-directory endpoint: the parent directory id lives in the URL
    # path and the body carries only the name. Default to the drive root (id 1).
    target_parent = str(parent_id) if parent_id else DRIVE_ROOT_ID
    response = api.post(
        f"/2/drive/{drive_id}/files/{target_parent}/directory",
        json={"name": name},
    )
    if not isinstance(response, Mapping):
        raise DriveError("Unexpected kDrive file creation response: expected JSON object")
    
    file_item = response.get("data")
    if file_item is None and response.get("id") is not None:
        file_item = response
    
    if not isinstance(file_item, Mapping):
        raise DriveError("Unexpected kDrive file creation response: missing data object")
    return file_item


def get_file(api: Any, drive_id: str, file_id: str) -> Mapping[str, Any]:
    """Fetch a single kDrive file/folder's metadata by id."""
    payload = api.get(f"/2/drive/{drive_id}/files/{file_id}")
    data = _unwrap_success_data(payload)
    if not isinstance(data, Mapping):
        raise DriveError("Unexpected kDrive file response: expected result=success with a data object")
    return data


def trash_file(api: Any, drive_id: str, file_id: str) -> Mapping[str, Any]:
    """Soft-delete one kDrive item to trash and return its undo metadata."""
    payload = api.delete(f"/2/drive/{drive_id}/files/{file_id}")
    data = _unwrap_success_data(payload)
    if not isinstance(data, Mapping):
        raise DriveError("Unexpected kDrive trash response: expected result=success with a data object")
    return data


def upload_file(
    api: Any,
    drive_id: str,
    content: bytes,
    name: str,
    *,
    parent_id: str | None = None,
) -> Mapping[str, Any]:
    """Upload one file, refusing a remote-name conflict by default."""
    destination = str(parent_id) if parent_id else DRIVE_ROOT_ID
    payload = api.upload(
        f"/3/drive/{drive_id}/upload",
        content,
        params={
            "directory_id": destination,
            "file_name": name,
            "total_size": len(content),
            "conflict": "error",
        },
    )
    return _data_object(payload, "upload")


def rename_file(api: Any, drive_id: str, file_id: str, name: str) -> Mapping[str, Any]:
    payload = api.post(
        f"/2/drive/{drive_id}/files/{file_id}/rename",
        json={"name": name},
    )
    return _data_object(payload, "rename")


def move_file(
    api: Any,
    drive_id: str,
    file_id: str,
    destination_id: str,
) -> Mapping[str, Any]:
    payload = api.post(
        f"/3/drive/{drive_id}/files/{file_id}/move/{destination_id}",
        json={"conflict": "error"},
    )
    return _data_object(payload, "move")


def list_trash(
    api: Any,
    drive_id: str,
    *,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    params = {"limit": limit} if limit is not None else None
    payload = api.get(f"/3/drive/{drive_id}/trash", params=params)
    return _file_items(payload)


def get_trashed_file(api: Any, drive_id: str, file_id: str) -> Mapping[str, Any]:
    payload = api.get(f"/3/drive/{drive_id}/trash/{file_id}")
    return _data_object(payload, "trash lookup")


def restore_file(
    api: Any,
    drive_id: str,
    file_id: str,
    *,
    destination_id: str | None = None,
) -> Mapping[str, Any]:
    body: dict[str, Any] = {}
    if destination_id is not None:
        body["destination_directory_id"] = (
            int(destination_id) if str(destination_id).isdigit() else destination_id
        )
    payload = api.post(
        f"/2/drive/{drive_id}/trash/{file_id}/restore",
        json=body,
    )
    return _data_object(payload, "restore")


def get_share_state(api: Any, drive_id: str, file_id: str) -> dict[str, Mapping[str, Any] | None]:
    """Read exact-target public-link and multi-access state without changing it."""
    try:
        link = _data_object(api.get(f"/2/drive/{drive_id}/files/{file_id}/link"), "share link")
    except InformaniakAPIError as exc:
        if exc.status_code != 404:
            raise
        # The live API represents "no public link" as object_not_found.
        link = None
    access = _data_object(api.get(f"/2/drive/{drive_id}/files/{file_id}/access"), "share access")
    return {"link": link, "access": access}


def download_file(api: Any, drive_id: str, file_id: str) -> tuple[bytes, Mapping[str, str]]:
    """Download a kDrive file's raw bytes, returning ``(content, headers)``.

    Server-side read only: uses ``GET /2/drive/{drive_id}/files/{file_id}/download``.
    """
    return api.download(f"/2/drive/{drive_id}/files/{file_id}/download")


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


def recent_files(
    api: Any,
    drive_id: str,
    *,
    parent_id: str | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    files = list_files(api, drive_id, parent_id=parent_id)
    sorted_files = sorted(files, key=_recent_sort_key, reverse=True)
    if limit is not None:
        return sorted_files[:limit]
    return sorted_files


def shared_files(files: list[Mapping[str, Any]], *, limit: int | None = None) -> list[Mapping[str, Any]]:
    matches = [file_item for file_item in files if is_shared_file(file_item)]
    if limit is not None:
        return matches[:limit]
    return matches


def find_file(api: Any, drive_id: str, file_id: str) -> Mapping[str, Any] | None:
    for file_item in list_files(api, drive_id):
        if str(file_item.get("id")) == str(file_id):
            return file_item
    return None


def list_folders(
    api: Any,
    drive_id: str,
    *,
    parent_id: str | None = None,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    return [file_item for file_item in list_files(api, drive_id, parent_id=parent_id, limit=limit) if is_folder(file_item)]


def build_folder_tree(
    api: Any,
    drive_id: str,
    *,
    parent_id: str | None = None,
    depth: int = 2,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if depth < 1:
        raise DriveError("--depth must be at least 1")
    folders = list_folders(api, drive_id, parent_id=parent_id, limit=limit)
    if parent_id is not None:
        # Defensive: the kDrive files endpoint may ignore the parent_id query
        # param and return the full drive listing, which would make every folder
        # appear as a child of every other folder. Keep only true children.
        folders = [folder for folder in folders if _parent_id(folder) == str(parent_id)]
    return [
        {
            "folder": dict(folder),
            "children": (
                build_folder_tree(api, drive_id, parent_id=str(folder["id"]), depth=depth - 1, limit=limit)
                if depth > 1 and folder.get("id") is not None
                else []
            ),
        }
        for folder in folders
    ]


def slim_file(file_item: Mapping[str, Any], *, drive_id: str | None = None) -> dict[str, Any]:
    slim = {
        "id": _string_or_none(file_item.get("id")),
        "name": _string_or_none(file_item.get("name") or file_item.get("display_name")),
        "type": _file_type(file_item),
        "parent_id": _parent_id(file_item),
        "drive_id": _string_or_none(file_item.get("drive_id") or drive_id),
        "visibility": _string_or_none(file_item.get("visibility") or file_item.get("visibility_type")),
        "created_at": _created_at(file_item),
        "last_modified_at": _modified_at(file_item),
    }
    _add_if_present(slim, "size", _first_present(file_item, "size", "file_size", "bytes"))
    _add_if_present(slim, "mime_type", file_item.get("mime_type") or file_item.get("mimetype") or file_item.get("content_type"))
    _add_if_present(slim, "extension", file_item.get("extension") or file_item.get("file_extension") or file_item.get("ext"))
    _add_if_present(slim, "path_hint", file_item.get("path") or file_item.get("path_hint"))
    _add_if_present(slim, "owner", _owner_display(file_item))
    return slim


def slim_files(files: list[Mapping[str, Any]], *, drive_id: str | None = None) -> list[dict[str, Any]]:
    return [slim_file(file_item, drive_id=drive_id) for file_item in files]


def slim_folder_tree(tree: list[Mapping[str, Any]], *, drive_id: str | None = None) -> list[dict[str, Any]]:
    slim_tree: list[dict[str, Any]] = []
    for node in tree:
        folder = node.get("folder")
        if not isinstance(folder, Mapping):
            continue
        children = node.get("children")
        slim_tree.append(
            {
                "folder": slim_file(folder, drive_id=drive_id),
                "children": slim_folder_tree(children if isinstance(children, list) else [], drive_id=drive_id),
            }
        )
    return slim_tree


def is_folder(file_item: Mapping[str, Any]) -> bool:
    file_type = _file_type(file_item)
    if file_type is None:
        return False
    return file_type.casefold() in {"dir", "directory", "folder"}


def is_shared_file(file_item: Mapping[str, Any]) -> bool:
    for key in ("is_shared", "shared", "public", "is_public", "has_shared_link", "has_public_link", "link_enabled"):
        if file_item.get(key) is True:
            return True

    for key in ("visibility", "visibility_type", "share_status", "sharing_status", "access", "link_status"):
        value = file_item.get(key)
        if value is not None and _shared_text(str(value)):
            return True

    for key in ("share_url", "shared_url", "public_url", "link_url", "public_link", "share_link"):
        value = file_item.get(key)
        if isinstance(value, str) and value.strip():
            return True

    return False


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


def _data_object(payload: Any, action: str) -> Mapping[str, Any]:
    data = _unwrap_success_data(payload)
    if not isinstance(data, Mapping):
        raise DriveError(f"Unexpected kDrive {action} response: expected a data object")
    return data


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


def _created_at(file_item: Mapping[str, Any]) -> Any:
    return file_item.get("created_at") or file_item.get("created") or file_item.get("creation_date")


def _modified_at(file_item: Mapping[str, Any]) -> Any:
    return file_item.get("last_modified_at") or file_item.get("modified_at") or file_item.get("updated_at") or file_item.get("updated")


def _recent_sort_key(file_item: Mapping[str, Any]) -> tuple[int, int, float | str]:
    value = _modified_at(file_item) or _created_at(file_item)
    if value is None:
        return (0, 0, "")
    parsed = _timestamp_value(value)
    if isinstance(parsed, float):
        return (1, 1, parsed)
    return (1, 0, parsed)


def _timestamp_value(value: Any) -> float | str:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC).timestamp()
    except ValueError:
        return text


def _shared_text(value: str) -> bool:
    text = value.casefold().strip()
    normalized = "".join(character if character.isalnum() else " " for character in text)
    tokens = set(normalized.split())
    if tokens & {"not", "private", "none", "disabled", "false", "unshared", "unlinked"}:
        return False
    return bool(tokens & {"shared", "public", "link"})


def _owner_display(file_item: Mapping[str, Any]) -> str | None:
    owner = file_item.get("owner") or file_item.get("user") or file_item.get("created_by")
    if isinstance(owner, Mapping):
        for key in ("display_name", "name", "username", "email"):
            value = owner.get(key)
            if value:
                return str(value)
    if isinstance(owner, str) and owner:
        return owner
    return None


def _add_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        target[key] = value


def _first_present(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item.get(key) is not None:
            return item.get(key)
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
