from __future__ import annotations

from typing import Any, Mapping

from .api import InformaniakAPIError, redact_secret


KCHAT_NOTE = "kChat may require a different host or token than the Informaniak Manager API token."


def build_probe_candidates(account_id: str | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = [
        {"group": "kdrive", "path": "/2/drive", "params": None},
        {"group": "kdrive", "path": "/3/drive", "params": None},
        {"group": "kdrive", "path": "/1/drive", "params": None},
        {"group": "kdrive", "path": "/2/kdrive", "params": None},
        {"group": "kchat", "path": "/1/kchat", "params": None},
        {"group": "kchat", "path": "/2/kchat", "params": None},
    ]
    if account_id:
        candidates.insert(1, {"group": "kdrive", "path": "/2/drive", "params": {"account_id": str(account_id)}})
        candidates.append({"group": "kchat", "path": f"/1/accounts/{account_id}/kchat", "params": None})
    candidates.extend(
        [
            {"group": "ksuite", "path": "/1/my_ksuite/current", "params": None},
            {"group": "ksuite", "path": "/1/my_ksuite", "params": None},
        ]
    )
    return candidates


def probe_profile(profile: str, account_id: str | None, client: Any) -> dict[str, Any]:
    return {
        "profile": profile,
        "account_id": account_id,
        "notes": [KCHAT_NOTE],
        **probe_endpoints(client, build_probe_candidates(account_id)),
    }


def probe_endpoints(client: Any, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    results = []
    for candidate in candidates:
        path = candidate["path"]
        params = candidate.get("params")
        try:
            response = client.probe_get(path, params=params)
        except InformaniakAPIError as exc:
            response = {"status_code": exc.status_code, "json": None, "error": str(exc)}

        entry = {
            "group": candidate["group"],
            "path": path,
            "params": params,
            "status_code": response.get("status_code"),
            "shape": shape_summary(response.get("json")),
        }
        if response.get("error"):
            entry["error"] = redact_secret(str(response["error"]))
        results.append(entry)
    return {"results": results}


def shape_summary(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        summary: dict[str, Any] = {"type": "object", "keys": _safe_keys(payload)}
        if "data" in payload:
            summary["data"] = shape_summary(payload["data"])
        return summary

    if isinstance(payload, list):
        summary = {"type": "list", "count": len(payload)}
        if payload and isinstance(payload[0], Mapping):
            summary["first_item_keys"] = _safe_keys(payload[0])
        return summary

    if payload is None:
        return {"type": "null"}

    return {"type": type(payload).__name__}


def _safe_keys(payload: Mapping[Any, Any]) -> list[str]:
    keys = [redact_secret(str(key))[:80] for key in payload.keys()]
    return sorted(keys)[:50]
