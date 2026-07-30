"""Read-only Infomaniak Manager/admin inventory services.

Every function here performs a GET against an endpoint live-confirmed in
context/LIVE_API_FINDINGS.md (2026-07-30). No admin write of any kind belongs
in this module while the 0.3.x line is read-only.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Mapping


def list_account_users(client: Any, account_id: str) -> list[Mapping[str, Any]]:
    """Return the Manager user list for one account (v2 endpoint; v1 is 404)."""
    return _items(_unwrap(client.get(f"/2/accounts/{account_id}/users")))


def get_account_admin(client: Any, account_id: str) -> Mapping[str, Any]:
    return _mapping(_unwrap(client.get(f"/1/accounts/{account_id}")))


def mailbox_key(value: str) -> str:
    """The API keys mailboxes by local part; accept a full address too."""
    local = str(value).split("@", 1)[0]
    if not local:
        raise ValueError("Mailbox name is required")
    return local


def _quote(segment: Any) -> str:
    """Percent-encode one URL path segment so a caller-supplied value can
    never extend or redirect the request path (chat/calendar/contacts do the
    same at their request boundaries)."""
    return urllib.parse.quote(str(segment), safe="")


def list_mail_hostings_admin(client: Any) -> list[Mapping[str, Any]]:
    """Return every mail hosting visible to the token, with admin fields."""
    return _items(_unwrap(client.get("/1/mail_hostings")))


def get_mailbox_admin(client: Any, mail_hosting_id: str, mailbox_name: str) -> Mapping[str, Any]:
    return _mapping(
        _unwrap(client.get(f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}"))
    )


def get_mailbox_aliases(client: Any, mail_hosting_id: str, mailbox_name: str) -> Mapping[str, Any]:
    return _mapping(
        _unwrap(client.get(f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/aliases"))
    )


def get_mailbox_forwarding(client: Any, mail_hosting_id: str, mailbox_name: str) -> Mapping[str, Any]:
    return _mapping(
        _unwrap(
            client.get(
                f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/forwarding_addresses"
            )
        )
    )


def get_mailbox_signatures(client: Any, mail_hosting_id: str, mailbox_name: str) -> Mapping[str, Any]:
    return _mapping(
        _unwrap(client.get(f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/signatures"))
    )


def slim_account_overview(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "nb_users": item.get("nb_users"),
    }


def slim_admin_user(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "user_id": item.get("user_id"),
        "email": item.get("email"),
        "display_name": item.get("display_name"),
        "role_type": item.get("role_type"),
        "state_in_account": item.get("state_in_account"),
        "user_status": item.get("user_status"),
        "has_billing_access": item.get("has_billing_access"),
        "is_workspace_only": item.get("is_workspace_only"),
        "last_login_at": item.get("last_login_at"),
    }


def slim_admin_hosting(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "customer_name": item.get("customer_name"),
        "main_fqdn": item.get("main_fqdn"),
        "service_name": item.get("service_name"),
        "is_locked": item.get("is_locked"),
        "dns_error": item.get("dns_error"),
    }


def slim_admin_mailbox(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mailbox": item.get("mailbox"),
        "mailbox_name": item.get("mailbox_name"),
        "type": item.get("type"),
        "is_limited": item.get("is_limited"),
        "is_free_mail": item.get("is_free_mail"),
        "is_used_for_account": item.get("is_used_for_account"),
    }


def slim_aliases(item: Mapping[str, Any]) -> dict[str, Any]:
    aliases = item.get("aliases")
    return {
        "aliases": aliases if isinstance(aliases, list) else [],
        "enabled_alias": item.get("enabled_alias"),
    }


def slim_forwarding(item: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize the API's own `redirect_adresses` spelling; `--raw` keeps it."""
    addresses = item.get("redirect_adresses")
    if addresses is None:
        addresses = item.get("redirect_addresses")
    return {
        "is_enabled": item.get("is_enabled"),
        "redirect_addresses": addresses,
        "has_dont_deliver": item.get("has_dont_deliver"),
        "has_forward_spam": item.get("has_forward_spam"),
    }


def summarize_signatures(item: Mapping[str, Any]) -> dict[str, Any]:
    """Signature inventory summary only — bodies can embed personal data."""
    signatures = item.get("signatures")
    return {
        "count": len(signatures) if isinstance(signatures, list) else 0,
        "default_signature_id": item.get("default_signature_id"),
        "default_reply_signature_id": item.get("default_reply_signature_id"),
        "is_forced": item.get("is_forced"),
    }


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


def _items(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    return []


def _mapping(data: Any) -> Mapping[str, Any]:
    if isinstance(data, Mapping):
        return data
    return {}
