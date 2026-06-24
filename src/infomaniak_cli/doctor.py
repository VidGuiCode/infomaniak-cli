from __future__ import annotations

from typing import Any

from .auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, MailPasswordStore, TokenStore
from .config_paths import get_config_dir
from .profiles import ProfileManager
from .readiness import build_readiness


def run_doctor(profile_name: str | None = None) -> dict[str, Any]:
    manager = ProfileManager()
    names = manager.list_names()
    selected = profile_name or manager.get_current_name()
    token_store = TokenStore()

    checks = {
        "config_dir": str(get_config_dir()),
        "profiles_found": len(names),
        "profile_configured": selected is not None and selected in names,
        "token_configured": bool(selected and token_store.has_token(selected)),
        "account_selected": False,
        "default_mailbox_selected": False,
        "mail_password_configured": False,
        "mail_imap_ready": False,
        "mail_rest_discovery_ready": False,
        "default_drive_selected": False,
    }

    profile_data = None
    readiness = None
    if checks["profile_configured"] and selected:
        profile = manager.get(selected)
        profile_data = profile.to_dict()
        readiness = build_readiness(profile, main_token_configured=checks["token_configured"])
        checks["account_selected"] = bool(profile.account_id or profile.account_name)
        checks["default_mailbox_selected"] = bool(profile.default_mailbox)
        checks["mail_password_configured"] = bool(selected and MailPasswordStore().has_password(selected))
        checks["mail_imap_ready"] = bool(checks["default_mailbox_selected"] and checks["mail_password_configured"])
        checks["mail_rest_discovery_ready"] = bool(
            checks["token_configured"] and profile.account_id and profile.mail_hosting_id
        )
        checks["default_drive_selected"] = bool(profile.default_drive_id or profile.default_drive_name)
        checks["contacts_configured"] = bool(profile.contacts_url and profile.contacts_username)
        checks["contacts_password_configured"] = ContactsPasswordStore().has_password(selected)
        checks["contacts_ready"] = bool(checks["contacts_configured"] and checks["contacts_password_configured"])
        checks["calendar_configured"] = bool(profile.calendar_url and profile.calendar_username)
        checks["calendar_password_configured"] = CalendarPasswordStore().has_password(selected)
        checks["calendar_ready"] = bool(checks["calendar_configured"] and checks["calendar_password_configured"])
        checks["chat_configured"] = bool(profile.kchat_url)
        checks["chat_explicit_token_configured"] = ChatTokenStore().has_token(selected)
        checks["chat_main_token_fallback_possible"] = bool(
            readiness and readiness["chat"]["main_token_fallback_possible"]
        )
        checks["chat_ready"] = bool(
            checks["chat_configured"]
            and (checks["chat_explicit_token_configured"] or checks["chat_main_token_fallback_possible"])
        )

    return {
        "profile": selected,
        "profiles": names,
        "checks": checks,
        "profile_data": profile_data,
        "readiness": readiness,
        "missing_setup_actions": readiness["missing_setup_actions"] if readiness else [],
    }
