from __future__ import annotations

from typing import Any, Mapping


def list_accounts(api: Any) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get("/1/accounts")))


def slim_account(account: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("id", "name", "type", "legal_entity_type")
    return {field: account[field] for field in fields if field in account and account[field] is not None}


def slim_accounts(accounts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_account(account) for account in accounts]


def list_products(api: Any, account_id: str) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get(f"/1/accounts/{account_id}/products")))


def slim_product(product: Mapping[str, Any]) -> dict[str, Any]:
    projected = {
        "id": product.get("id") or product.get("product_id") or product.get("service_id"),
        "name": product.get("service_name") or product.get("customer_name"),
        "type": product.get("service_name"),
    }
    return {field: value for field, value in projected.items() if value is not None}


def slim_products(products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_product(product) for product in products]


def list_services(api: Any, account_id: str) -> list[Mapping[str, Any]]:
    return _as_items(_unwrap(api.get(f"/1/accounts/{account_id}/services")))


_SERVICE_WORKFLOWS: dict[str, tuple[str, str]] = {
    "drive": ("drive", "ik drive list"),
    "kdrive": ("drive", "ik drive list"),
    "email_hosting": ("mail", "ik mail mailboxes"),
    "mail_hosting": ("mail", "ik mail mailboxes"),
    "mail": ("mail", "ik mail mailboxes"),
    "kchat": ("chat", "ik chat channels"),
    "chat": ("chat", "ik chat channels"),
    "calendar": ("calendar", "ik calendar upcoming"),
    "caldav": ("calendar", "ik calendar upcoming"),
    "contacts": ("contacts", "ik contacts list"),
    "carddav": ("contacts", "ik contacts list"),
}


def slim_service(service: Mapping[str, Any]) -> dict[str, Any]:
    """Project catalog service data into a stable workflow-facing shape."""
    service_id = service.get("id") or service.get("service_id") or service.get("product_id")
    name = service.get("name") or service.get("service_name") or service.get("type")
    projected: dict[str, Any] = {}
    if service_id is not None:
        projected["id"] = service_id
    if name is not None:
        projected["name"] = name
    if service.get("count") is not None:
        projected["count"] = service["count"]

    key = str(name or "").strip().lower().replace("-", "_").replace(" ", "_")
    workflow = _SERVICE_WORKFLOWS.get(key)
    if workflow is not None:
        area, command = workflow
        projected["area"] = area
        projected["actionable"] = True
        projected["command"] = command
    else:
        projected["actionable"] = False
    return projected


def slim_services(services: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_service(service) for service in services]


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
