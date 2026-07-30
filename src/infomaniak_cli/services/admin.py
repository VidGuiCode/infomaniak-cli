"""Infomaniak Manager/admin services: inventory reads plus protected writes.

Reads are GETs against endpoints live-confirmed in context/LIVE_API_FINDINGS.md
(2026-07-30). Writes are added one reversible, single-resource operation at a
time, each behind the shared protected-write contract and explicit maintainer
sign-off (A10c). Current writes: mailbox alias add/remove (0.3.1).
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Mapping


def list_account_users(client: Any, account_id: str) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Return (users, page_info) for one account (v2 endpoint; v1 is 404).

    This endpoint does not paginate today, but the envelope is returned anyway
    so `complete` stays truthful if that ever changes.
    """
    payload = client.get(f"/2/accounts/{_quote(account_id)}/users")
    return _items(_unwrap(payload)), page_info(payload)


def list_account_teams(client: Any, account_id: str) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Return (teams, page_info). This endpoint paginates."""
    payload = client.get(f"/1/accounts/{_quote(account_id)}/teams")
    return _items(_unwrap(payload)), page_info(payload)


def page_info(payload: Any) -> dict[str, Any]:
    """Extract the server's pagination figures, or nulls when absent.

    Reporting `count` from one page as if it were the whole inventory is the
    same class of dishonesty as a silent first-match, so callers need `total`.
    """
    if not isinstance(payload, Mapping):
        return {"total": None, "page": None, "pages": None, "items_per_page": None}
    return {
        "total": payload.get("total"),
        "page": payload.get("page"),
        "pages": payload.get("pages"),
        "items_per_page": payload.get("items_per_page"),
    }


def slim_admin_team(item: Mapping[str, Any]) -> dict[str, Any]:
    children = item.get("children")
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "parent_id": item.get("parent_id"),
        "children": len(children) if isinstance(children, list) else 0,
        "owned_by_id": item.get("owned_by_id"),
        "position": item.get("position"),
    }


def get_account_admin(client: Any, account_id: str) -> Mapping[str, Any]:
    return _mapping(_unwrap(client.get(f"/1/accounts/{_quote(account_id)}")))


def mailbox_key(value: str) -> str:
    """The API keys mailboxes by local part; accept a full address too."""
    local = str(value).split("@", 1)[0]
    if not local:
        raise ValueError("Mailbox name is required")
    return local


def _quote(segment: Any) -> str:
    """Percent-encode one URL path segment so a caller-supplied value can
    never extend or redirect the request path (chat/calendar/contacts do the
    same at their request boundaries). Dot segments are refused outright:
    quote() leaves `.` unescaped, and an upstream proxy may normalize them."""
    text = str(segment)
    if text in ("", ".", ".."):
        raise ValueError(f"Invalid URL path segment: {text!r}")
    return urllib.parse.quote(text, safe="")


def list_mail_hostings_admin(client: Any) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Return (hostings, page_info) for every mail hosting visible to the token."""
    payload = client.get("/1/mail_hostings")
    return _items(_unwrap(payload)), page_info(payload)


def list_mailboxes_paged(client: Any, mail_hosting_id: str) -> tuple[list[Mapping[str, Any]], dict[str, Any]]:
    """Return (mailboxes, page_info). This endpoint paginates."""
    payload = client.get(f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes")
    return _items(_unwrap(payload)), page_info(payload)


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


def add_mailbox_alias(client: Any, mail_hosting_id: str, mailbox_name: str, alias: str) -> Any:
    """POST one alias onto one mailbox (contract in context/LIVE_API_FINDINGS.md)."""
    return client.post(
        f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/aliases",
        json={"alias": alias},
    )


def delete_mailbox_alias(client: Any, mail_hosting_id: str, mailbox_name: str, alias: str) -> Any:
    """DELETE one alias from one mailbox."""
    return client.delete(
        f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/aliases/{_quote(alias)}"
    )


_ALIAS_LOCAL_PART_RE = re.compile(r"^[A-Za-z0-9._%+-]+$")


def alias_local_part(value: str) -> str:
    """Validate a caller-supplied alias: local part only, conservative charset."""
    alias = str(value).strip()
    if not alias:
        raise ValueError("Alias is required")
    if "@" in alias:
        raise ValueError(
            f"Alias must be the local part only (got: {alias}). "
            "Infomaniak aliases apply to the hosting's domains; pass the part before the @."
        )
    if not _ALIAS_LOCAL_PART_RE.match(alias):
        raise ValueError(
            f"Alias contains characters that are not valid in a mail local part: {alias}. "
            "Allowed: letters, digits, and . _ % + -"
        )
    return alias


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


def set_mailbox_forwarding(
    client: Any,
    mail_hosting_id: str,
    mailbox_name: str,
    *,
    addresses: list[str],
    is_enabled: bool,
    has_dont_deliver: bool,
    has_forward_spam: bool,
) -> Any:
    """PUT the COMPLETE forwarding configuration for one mailbox.

    The endpoint is a full replace, not a patch, so every field is always sent:
    omitting one would blank it. Note the write takes `redirect_addresses`
    (correct spelling, plain strings) while the read returns `redirect_adresses`
    (single d, objects) — see context/LIVE_API_FINDINGS.md.
    """
    return client.request(
        "PUT",
        f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/forwarding_addresses",
        json={
            "redirect_addresses": list(addresses),
            "is_enabled": bool(is_enabled),
            "has_dont_deliver": bool(has_dont_deliver),
            "has_forward_spam": bool(has_forward_spam),
        },
    )


def forwarding_addresses(item: Mapping[str, Any]) -> list[str]:
    """Map the read's `redirect_adresses` objects to plain address strings."""
    raw = item.get("redirect_adresses")
    if raw is None:
        raw = item.get("redirect_addresses")
    if not isinstance(raw, list):
        return []
    addresses = []
    for entry in raw:
        if isinstance(entry, Mapping):
            value = entry.get("email") or entry.get("email_idn")
        else:
            value = entry
        if value:
            addresses.append(str(value))
    return addresses


_FORWARDING_ADDRESS_RE = re.compile(r"^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$")


def forwarding_address(value: str) -> str:
    """Validate a forwarding target: a full address, since a typo misroutes mail."""
    address = str(value).strip()
    if not address:
        raise ValueError("Forwarding address is required")
    if not _FORWARDING_ADDRESS_RE.match(address):
        raise ValueError(
            f"Not a valid forwarding address: {address}. "
            "Pass a full address such as person@example.com."
        )
    return address


# The only fields this CLI will PATCH. The endpoint accepts more (spam and
# filtering flags, has_responder), but those cannot be read back at all, and a
# setting that cannot be previewed, diffed or confirmed is not one we write.
WRITABLE_MAILBOX_FIELDS = frozenset({"note", "blocked_senders", "authorized_senders"})

# Sender lists are absent from the default mailbox read and must be requested.
MAILBOX_SETTINGS_WITH = "blocked_senders,authorized_senders"


def get_mailbox_settings(client: Any, mail_hosting_id: str, mailbox_name: str) -> Mapping[str, Any]:
    """Read a mailbox INCLUDING its sender lists.

    Without `?with=`, the response omits both arrays entirely. Since the PATCH
    replaces an array wholesale, reading without them and writing back would
    destroy every existing entry.
    """
    return _mapping(
        _unwrap(
            client.get(
                f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}",
                {"with": MAILBOX_SETTINGS_WITH},
            )
        )
    )


def update_mailbox_settings(
    client: Any, mail_hosting_id: str, mailbox_name: str, fields: Mapping[str, Any]
) -> Any:
    """PATCH mailbox settings. Partial per field, but array fields replace wholesale."""
    unknown = set(fields) - WRITABLE_MAILBOX_FIELDS
    if unknown:
        raise ValueError(
            f"Refusing to write mailbox fields this CLI does not support: {sorted(unknown)}. "
            "Only fields that can be read back are writable."
        )
    return client.request(
        "PATCH",
        f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}",
        json=dict(fields),
    )


def sender_list(item: Mapping[str, Any], key: str) -> list[str]:
    """Return a sender list, refusing to guess when the read omitted it.

    Returning `[]` for an absent key would make a read-modify-write silently
    replace the real list with a single entry.
    """
    if key not in item:
        raise ValueError(
            f"The mailbox read did not include `{key}`, so this CLI cannot safely replace the "
            "list (the API replaces it wholesale). Refusing rather than risk dropping entries."
        )
    value = item.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Unexpected shape for `{key}`: expected a list, got {type(value).__name__}.")
    # Read/write asymmetry, confirmed live: entries come back as objects
    # ({email, locked}) but must be sent as plain address strings. Writing the
    # read shape back would corrupt the list.
    addresses = []
    for entry in value:
        if isinstance(entry, Mapping):
            address = entry.get("email") or entry.get("email_idn")
        else:
            address = entry
        if address:
            addresses.append(str(address))
    return addresses


def slim_mailbox_settings(item: Mapping[str, Any]) -> dict[str, Any]:
    """Project the readable mailbox settings, stating effects rather than flag names."""
    return {
        "note": item.get("note"),
        "blocked_senders": sender_list(item, "blocked_senders"),
        "authorized_senders": sender_list(item, "authorized_senders"),
    }


MAX_MAILBOX_NOTE = 80


def mailbox_note(value: str) -> str:
    note = str(value)
    if len(note) > MAX_MAILBOX_NOTE:
        raise ValueError(
            f"Note is {len(note)} characters; the API accepts at most {MAX_MAILBOX_NOTE}."
        )
    return note


def _signatures_path(mail_hosting_id: str, mailbox_name: str) -> str:
    return f"/1/mail_hostings/{_quote(mail_hosting_id)}/mailboxes/{_quote(mailbox_name)}/signatures"


def create_signature(client: Any, mail_hosting_id: str, mailbox_name: str, fields: Mapping[str, Any]) -> Any:
    """POST a new signature. Only `name` is required by the API."""
    return client.post(_signatures_path(mail_hosting_id, mailbox_name), json=dict(fields))


def update_signature(
    client: Any, mail_hosting_id: str, mailbox_name: str, signature_id: Any, fields: Mapping[str, Any]
) -> Any:
    """PATCH one signature. A genuine partial update: only given fields are sent."""
    return client.request(
        "PATCH",
        f"{_signatures_path(mail_hosting_id, mailbox_name)}/{_quote(signature_id)}",
        json=dict(fields),
    )


def delete_signature(client: Any, mail_hosting_id: str, mailbox_name: str, signature_id: Any) -> Any:
    return client.delete(f"{_signatures_path(mail_hosting_id, mailbox_name)}/{_quote(signature_id)}")


def set_default_signatures(
    client: Any, mail_hosting_id: str, mailbox_name: str, fields: Mapping[str, Any]
) -> Any:
    """POST the mailbox-level default send/reply signature pointers."""
    return client.post(f"{_signatures_path(mail_hosting_id, mailbox_name)}/set_defaults", json=dict(fields))


def signature_items(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    signatures = payload.get("signatures")
    return [item for item in signatures if isinstance(item, Mapping)] if isinstance(signatures, list) else []


def slim_signature(
    item: Mapping[str, Any],
    *,
    default_signature_id: Any = None,
    default_reply_signature_id: Any = None,
) -> dict[str, Any]:
    """Project one signature. Content is reported as a length, not a body.

    Signature bodies routinely carry names, phone numbers and addresses, so the
    list view reports size and `--raw`/`show` expose the content itself.
    """
    content = item.get("content")
    signature_id = item.get("id")
    return {
        "id": signature_id,
        "name": item.get("name"),
        "fullname": item.get("fullname") or item.get("full_name"),
        "position": item.get("position"),
        "content_length": len(content) if isinstance(content, str) else 0,
        "has_infomaniak_footer": item.get("has_infomaniak_footer"),
        "is_default_send": _same_id(signature_id, default_signature_id),
        "is_default_reply": _same_id(signature_id, default_reply_signature_id),
    }


def _same_id(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    return str(left) == str(right)


def slim_aliases(item: Mapping[str, Any]) -> dict[str, Any]:
    aliases = item.get("aliases")
    normalized = []
    if isinstance(aliases, list):
        # Coerce defensively: a non-string entry must not crash sorting/joining
        # downstream, and must stay visible to the exists-check on writes.
        normalized = [a if isinstance(a, str) else str(a) for a in aliases]
    return {
        "aliases": normalized,
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
