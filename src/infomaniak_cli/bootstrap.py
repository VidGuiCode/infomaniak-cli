from __future__ import annotations

from typing import Any, Mapping

from .api import InformaniakAPIError
from .profiles import ProfileManager


class BootstrapError(RuntimeError):
    pass


def bootstrap_profile(
    profile_name: str,
    api: Any,
    *,
    manager: ProfileManager | None = None,
    account_id: str | None = None,
    non_interactive: bool = False,
) -> dict[str, Any]:
    manager = manager or ProfileManager()
    if not manager.exists(profile_name):
        manager.create_or_update(profile_name, make_default=True)

    profile_data = _unwrap(api.get("/2/profile"))
    accounts = _as_items(_unwrap(api.get("/1/accounts")))
    account = _select_account(accounts, account_id=account_id, non_interactive=non_interactive)
    selected_account_id = _item_id(account)
    if not selected_account_id:
        raise BootstrapError("Selected account has no usable ID")

    products = _as_items(_unwrap(api.get(f"/1/accounts/{selected_account_id}/products")))
    services = _as_items(_unwrap(api.get(f"/1/accounts/{selected_account_id}/services")))
    my_ksuite = _optional_get(api, "/1/my_ksuite/current")

    mail_hosting = _find_item([*products, *services], "mail_hosting", "mail hosting", "mail")
    mailboxes = _discover_mailboxes(api, mail_hosting)
    drives = _as_items(_optional_get(api, "/2/drive"))
    kchat_teams = _as_items(_optional_get(api, "/api/v4/teams"))

    drive = _first_item(drives) or _find_item([*services, *products], "kdrive", "drive")
    kchat = _first_item(kchat_teams) or _find_item([*services, *products], "kchat", "chat")
    default_mailbox = _mailbox_address(_first_item(mailboxes))

    metadata = {
        "informaniak_user": _profile_user(profile_data),
        "account_id": selected_account_id,
        "account_name": _item_name(account),
        "ksuite_id": _item_id(my_ksuite) if isinstance(my_ksuite, Mapping) else None,
        "mail_hosting_id": _item_id(mail_hosting) if mail_hosting else None,
        "default_mailbox": default_mailbox,
        "default_drive_id": _item_id(drive) if drive else None,
        "default_drive_name": _item_name(drive) if drive else None,
        "kchat_team_id": _item_id(kchat) if kchat else None,
    }
    profile = manager.create_or_update(profile_name, make_default=True, **metadata)

    return {
        "profile": profile.name,
        "informaniak_user": profile.informaniak_user,
        "account": {"id": profile.account_id, "name": profile.account_name},
        "ksuite_id": profile.ksuite_id,
        "mail_hosting_id": profile.mail_hosting_id,
        "default_mailbox": profile.default_mailbox,
        "default_drive": {"id": profile.default_drive_id, "name": profile.default_drive_name},
        "kchat_team_id": profile.kchat_team_id,
        "counts": {
            "accounts": len(accounts),
            "products": len(products),
            "services": len(services),
            "mailboxes": len(mailboxes),
            "drives": len(drives),
            "kchat_teams": len(kchat_teams),
        },
    }


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


def _optional_get(api: Any, path: str) -> Any:
    try:
        return _unwrap(api.get(path))
    except (InformaniakAPIError, KeyError):
        return None


def _discover_mailboxes(api: Any, mail_hosting: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    mail_hosting_id = _item_id(mail_hosting)
    if not mail_hosting_id:
        return []
    return _as_items(_optional_get(api, f"/1/mail_hostings/{mail_hosting_id}/mailboxes"))


def _as_items(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("data", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _first_item(items: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return items[0] if items else None


def _select_account(
    accounts: list[Mapping[str, Any]],
    *,
    account_id: str | None,
    non_interactive: bool,
) -> Mapping[str, Any]:
    if not accounts:
        raise BootstrapError("No accessible Informaniak accounts found")

    if account_id:
        for account in accounts:
            if _item_id(account) == str(account_id):
                return account
        choices = _format_choices(accounts)
        raise BootstrapError(f"Account not found: {account_id}. Available accounts: {choices}")

    if len(accounts) == 1:
        return accounts[0]

    if non_interactive:
        choices = _format_choices(accounts)
        raise BootstrapError(f"Multiple accounts found; rerun with --account-id. Available accounts: {choices}")

    print("Found accounts:")
    for index, account in enumerate(accounts, start=1):
        print(f"{index}. {_item_name(account) or 'unnamed'} ({_item_id(account) or 'no id'})")
    selected = input("Use which account? ").strip()
    try:
        choice = int(selected)
    except ValueError as exc:
        raise BootstrapError(f"Invalid account selection: {selected}") from exc
    if choice < 1 or choice > len(accounts):
        raise BootstrapError(f"Invalid account selection: {selected}")
    return accounts[choice - 1]


def _format_choices(items: list[Mapping[str, Any]]) -> str:
    return ", ".join(f"{_item_id(item) or '?'}: {_item_name(item) or 'unnamed'}" for item in items)


def _item_id(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("id", "account_id", "service_id", "product_id", "my_k_suite_id", "ksuite_id"):
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def _item_name(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("name", "display_name", "label", "title", "description", "company_name"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _mailbox_address(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    for key in ("email", "mailbox", "mailbox_name", "address", "name", "login"):
        value = item.get(key)
        if value:
            return str(value)
    return None


def _profile_user(profile_data: Any) -> str | None:
    if not isinstance(profile_data, Mapping):
        return None
    for key in ("email", "login", "username", "display_name", "name"):
        value = profile_data.get(key)
        if isinstance(value, str) and value:
            return value
    emails = profile_data.get("emails")
    if isinstance(emails, list):
        for email in emails:
            if isinstance(email, str) and email:
                return email
            if isinstance(email, Mapping):
                value = email.get("email") or email.get("address")
                if value:
                    return str(value)
    return None


def _find_item(items: list[Mapping[str, Any]], *needles: str) -> Mapping[str, Any] | None:
    lowered_needles = tuple(needle.lower() for needle in needles)
    for item in items:
        searchable = " ".join(str(value).lower() for value in item.values() if value is not None)
        if any(needle in searchable for needle in lowered_needles):
            return item
    return None
