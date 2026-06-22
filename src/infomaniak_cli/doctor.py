from __future__ import annotations

from typing import Any

from .auth import MailPasswordStore, TokenStore
from .config_paths import get_config_dir
from .profiles import ProfileManager


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
        "default_drive_selected": False,
    }

    profile_data = None
    if checks["profile_configured"] and selected:
        profile = manager.get(selected)
        profile_data = profile.to_dict()
        checks["account_selected"] = bool(profile.account_id or profile.account_name)
        checks["default_mailbox_selected"] = bool(profile.default_mailbox)
        checks["mail_password_configured"] = bool(selected and MailPasswordStore().has_password(selected))
        checks["default_drive_selected"] = bool(profile.default_drive_id or profile.default_drive_name)

    return {
        "profile": selected,
        "profiles": names,
        "checks": checks,
        "profile_data": profile_data,
    }
