from __future__ import annotations

from typing import Any, Mapping


def list_mail_hostings(client: Any, account_id: str) -> list[Mapping[str, Any]]:
    """Return mail hosting resources from confirmed account product/service catalog endpoints."""
    products = _items(_unwrap(client.get(f"/1/accounts/{account_id}/products")))
    services = _items(_unwrap(client.get(f"/1/accounts/{account_id}/services")))
    return [item for item in [*products, *services] if _is_mail_hosting(item)]


def list_mailboxes(client: Any, mail_hosting_id: str) -> list[Mapping[str, Any]]:
    """Return mailboxes from the confirmed mail hosting mailbox endpoint."""
    return _items(_unwrap(client.get(f"/1/mail_hostings/{mail_hosting_id}/mailboxes")))


def slim_mail_hosting(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(_item_id(item)),
        "name": _string_or_none(_item_name(item)),
        "type": _string_or_none(item.get("type") or item.get("service_type") or item.get("service_name")),
        "customer_name": _string_or_none(item.get("customer_name")),
    }


def slim_mailbox(item: Mapping[str, Any], *, mail_hosting_id: str | None = None, source: str | None = None) -> dict[str, Any]:
    return {
        "id": _string_or_none(_item_id(item)),
        "email": _string_or_none(mailbox_address(item)),
        "name": _string_or_none(_item_name(item)),
        "login": _string_or_none(item.get("login")),
        "mail_hosting_id": _string_or_none(mail_hosting_id or item.get("mail_hosting_id")),
        "source": _string_or_none(source),
    }


def mailbox_address(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("email", "mailbox", "mailbox_name", "address", "name", "login"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def select_default_mailbox(mailboxes: list[Mapping[str, Any]], preferred_email: str | None = None) -> str | None:
    preferred = (preferred_email or "").strip().lower()
    if preferred:
        for mailbox in mailboxes:
            address = (mailbox_address(mailbox) or "").strip().lower()
            if address == preferred:
                return mailbox_address(mailbox)
    if mailboxes:
        return mailbox_address(mailboxes[0])
    return None


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


def _items(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("data", "items", "results", "mailboxes", "hostings"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _is_mail_hosting(item: Mapping[str, Any]) -> bool:
    searchable = " ".join(str(value).lower() for value in item.values() if value is not None)
    return any(needle in searchable for needle in ("mail_hosting", "email_hosting", "mail hosting"))


def _item_id(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("id", "mail_hosting_id", "service_id", "product_id"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _item_name(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("name", "display_name", "label", "title", "description", "customer_name", "email"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
