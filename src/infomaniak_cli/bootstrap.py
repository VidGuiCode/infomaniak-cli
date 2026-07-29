from __future__ import annotations

from typing import Any, Callable, Mapping

from .api import InformaniakAPIError
from .profiles import ProfileManager
from .services.mail_discovery import mailbox_address


class BootstrapError(RuntimeError):
    pass


_CATALOG_KEYS = {
    "service_id",
    "service_name",
    "parent_id",
    "parent_service_id",
    "parent_service_name",
    "customer_name",
    "unique_id",
    "is_free",
    "is_trial",
    "is_zero_price",
    "rights",
    "count",
}


def bootstrap_profile(
    profile_name: str,
    api: Any,
    *,
    manager: ProfileManager | None = None,
    account_id: str | None = None,
    drive_id: str | None = None,
    mailbox: str | None = None,
    non_interactive: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    manager = manager or ProfileManager()
    if not manager.exists(profile_name):
        manager.create_or_update(profile_name, make_default=True)
    existing_profile = manager.get(profile_name)

    profile_data = _unwrap(api.get("/2/profile"))
    accounts = _as_items(_unwrap(api.get("/1/accounts")))
    account = _select_account(accounts, account_id=account_id, non_interactive=non_interactive)
    selected_account_id = _item_id(account)
    if not selected_account_id:
        raise BootstrapError("Selected account has no usable ID")

    products = _as_items(_unwrap(api.get(f"/1/accounts/{selected_account_id}/products")))
    services = _as_items(_unwrap(api.get(f"/1/accounts/{selected_account_id}/services")))

    mail_hosting = _find_item([*products, *services], "mail_hosting", "email_hosting", "mail hosting", "mail")
    mailboxes = _discover_mailboxes(api, mail_hosting)
    drives = _discover_drives(api, selected_account_id)

    drive = _select_one(
        drives,
        kind="drives",
        flag="--drive-id",
        explicit=drive_id,
        non_interactive=non_interactive,
        identify=_drive_id,
        required=False,
    )

    # The preference chain is a justified match, not a guess: the user's own
    # address, then whatever is already configured. Only when neither matches
    # does ambiguity apply.
    default_mailbox = _preferred_mailbox(
        mailboxes, _profile_user(profile_data), existing_profile.default_mailbox
    )
    if default_mailbox is None and mailboxes:
        chosen = _select_one(
            mailboxes,
            kind="mailboxes",
            flag="--mailbox",
            explicit=mailbox,
            non_interactive=non_interactive,
            identify=_mailbox_address,
            required=False,
        )
        default_mailbox = _mailbox_address(chosen) if chosen else None
    if default_mailbox is None and not mailboxes:
        default_mailbox = existing_profile.default_mailbox
    default_drive_id = _drive_id(drive) if drive else existing_profile.default_drive_id
    default_drive_name = _item_name(drive) if drive else existing_profile.default_drive_name

    metadata = {
        "informaniak_user": _profile_user(profile_data),
        "account_id": selected_account_id,
        "account_name": _item_name(account),
        "ksuite_id": existing_profile.ksuite_id,
        "mail_hosting_id": _item_id(mail_hosting) if mail_hosting else existing_profile.mail_hosting_id,
        "default_mailbox": default_mailbox,
        "default_drive_id": default_drive_id,
        "default_drive_name": default_drive_name,
        "kchat_team_id": existing_profile.kchat_team_id,
    }

    # What the profile defaults would become, shown before anything is saved.
    selection = {
        "account": {"id": selected_account_id, "name": _item_name(account)},
        "drive": {"id": default_drive_id, "name": default_drive_name},
        "mailbox": default_mailbox,
        "candidates": {
            "accounts": len(accounts),
            "drives": len(drives),
            "mailboxes": len(mailboxes),
        },
        "writes": "local profile config only",
    }

    if dry_run:
        return {
            "profile": profile_name,
            "dry_run": True,
            "saved": False,
            "selection": selection,
            "informaniak_user": _profile_user(profile_data),
            "account": selection["account"],
            "default_mailbox": default_mailbox,
            "default_drive": selection["drive"],
            "counts": {
                "accounts": len(accounts),
                "products": len(products),
                "services": len(services),
                "mailboxes": len(mailboxes),
                "drives": len(drives),
                "kchat_teams": 0,
            },
            "discovered": {
                "products": products,
                "services": services,
                "mailboxes": mailboxes,
                "drives": drives,
            },
        }

    profile = manager.replace_metadata(profile_name, make_default=True, **metadata)

    return {
        "saved": True,
        "selection": selection,
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
            "kchat_teams": 0,
        },
        "discovered": {
            "products": products,
            "services": services,
            "mailboxes": mailboxes,
            "drives": drives,
        },
    }


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


def _optional_get(api: Any, path: str, params: Mapping[str, Any] | None = None, *, raw: bool = False) -> Any:
    try:
        if raw and hasattr(api, "get_raw"):
            return api.get_raw(path, params=params)
        return _unwrap(api.get(path, params=params))
    except (InformaniakAPIError, KeyError):
        return None


def _discover_mailboxes(api: Any, mail_hosting: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    mail_hosting_id = _item_id(mail_hosting)
    if not mail_hosting_id:
        return []
    return _as_items(_optional_get(api, f"/1/mail_hostings/{mail_hosting_id}/mailboxes"))


def _discover_drives(api: Any, account_id: str) -> list[Mapping[str, Any]]:
    data = _optional_get(api, "/2/drive", params={"account_id": account_id})
    return _drive_resources(data)


def _as_items(data: Any) -> list[Mapping[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("data", "items", "results", "drives", "teams"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
    return []


def _preferred_mailbox(
    mailboxes: list[Mapping[str, Any]],
    preferred_email: str | None,
    existing_email: str | None,
) -> str | None:
    """Match the user's own address, then the configured one. Never guess.

    `mail_discovery.select_default_mailbox` falls back to the first mailbox when
    neither matches; bootstrap deliberately does not, so an ambiguous choice
    surfaces instead of silently redirecting every later mail command.
    """
    for candidate in (preferred_email, existing_email):
        wanted = (candidate or "").strip().casefold()
        if not wanted:
            continue
        for mailbox in mailboxes:
            address = (_mailbox_address(mailbox) or "").strip()
            if address.casefold() == wanted:
                return address
    return None


def _drive_resources(data: Any) -> list[Mapping[str, Any]]:
    return [item for item in _as_items(data) if _is_drive_resource(item)]


def _is_drive_resource(item: Mapping[str, Any]) -> bool:
    return _drive_id(item) is not None and _item_name(item) is not None and not _looks_like_catalog_item(item)


def _looks_like_catalog_item(item: Mapping[str, Any]) -> bool:
    return bool(_CATALOG_KEYS.intersection(item.keys()))


def _select_one(
    items: list[Mapping[str, Any]],
    *,
    kind: str,
    flag: str,
    explicit: str | None,
    non_interactive: bool,
    identify: Callable[[Mapping[str, Any]], str | None] = None,
    required: bool = True,
) -> Mapping[str, Any] | None:
    """Choose exactly one candidate, never silently picking the first of many.

    A wrong default here silently redirects every later read *and protected
    write* at the wrong drive or mailbox, so ambiguity is reported with the flag
    that resolves it rather than guessed.
    """
    identify = identify or _item_id
    if not items:
        if required:
            raise BootstrapError(f"No accessible {kind} found")
        return None

    if explicit:
        for item in items:
            if str(identify(item) or "") == str(explicit):
                return item
        raise BootstrapError(
            f"{kind.capitalize()} not found: {explicit}. Available: {_format_choices(items, identify)}"
        )

    if len(items) == 1:
        return items[0]

    if non_interactive:
        raise BootstrapError(
            f"Multiple {kind} found; rerun with {flag}. Available: {_format_choices(items, identify)}"
        )

    print(f"Found {kind}:")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {_item_name(item) or 'unnamed'} ({identify(item) or 'no id'})")
    selected = input(f"Use which {kind.rstrip('s')}? ").strip()
    try:
        choice = int(selected)
    except ValueError as exc:
        raise BootstrapError(f"Invalid {kind} selection: {selected}") from exc
    if choice < 1 or choice > len(items):
        raise BootstrapError(f"Invalid {kind} selection: {selected}")
    return items[choice - 1]


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


def _format_choices(items: list[Mapping[str, Any]], identify: Callable | None = None) -> str:
    identify = identify or _item_id
    return ", ".join(f"{identify(item) or '?'}: {_item_name(item) or 'unnamed'}" for item in items)


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


def _drive_id(item: Mapping[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("id")
    if value is not None:
        return str(value)
    return None


def _mailbox_address(item: Mapping[str, Any] | None) -> str | None:
    return mailbox_address(item)


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
