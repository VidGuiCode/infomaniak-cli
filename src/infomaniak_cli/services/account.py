from __future__ import annotations

from typing import Any, Mapping


def list_accounts(api: Any) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get("/1/accounts")))


def list_products(api: Any, account_id: str) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get(f"/1/accounts/{account_id}/products")))


def list_services(api: Any, account_id: str) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get(f"/1/accounts/{account_id}/services")))


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


def _as_items(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("data", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []
