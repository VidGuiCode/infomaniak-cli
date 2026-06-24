from __future__ import annotations

from typing import Any

from .auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, MailPasswordStore, TokenStore
from .profiles import Profile
from .services.chat import is_trusted_infomaniak_kchat_url


def build_readiness(profile: Profile, *, main_token_configured: bool | None = None) -> dict[str, Any]:
    profile_name = profile.name
    if main_token_configured is None:
        main_token_configured = TokenStore().has_token(profile_name)

    mail_password_configured = MailPasswordStore().has_password(profile_name)
    contacts_password_configured = ContactsPasswordStore().has_password(profile_name)
    calendar_password_configured = CalendarPasswordStore().has_password(profile_name)
    chat_explicit_token_configured = ChatTokenStore().has_token(profile_name)
    chat_main_token_fallback_possible = bool(
        profile.kchat_url and is_trusted_infomaniak_kchat_url(profile.kchat_url) and main_token_configured
    )

    email = _suggested_email(profile)
    mail_setup_action = None
    if not (profile.default_mailbox and mail_password_configured):
        mailbox = profile.default_mailbox or "<mailbox>"
        mail_setup_action = f"ik auth mail --mailbox {mailbox} --password <device-password>"

    contacts_ready = bool(profile.contacts_url and profile.contacts_username and contacts_password_configured)
    contacts_setup_action = None
    if not contacts_ready:
        contacts_setup_action = f"ik auth contacts --url <carddav-url> --username {email} --stdin"

    calendar_ready = bool(profile.calendar_url and profile.calendar_username and calendar_password_configured)
    calendar_setup_action = None
    if not calendar_ready:
        calendar_setup_action = f"ik auth calendar --url <caldav-url> --username {email} --stdin"

    chat_configured = bool(profile.kchat_url)
    chat_ready = bool(chat_configured and (chat_explicit_token_configured or chat_main_token_fallback_possible))
    chat_setup_action = None
    if not chat_ready:
        chat_setup_action = "ik auth chat --url <ksuite-kchat-url>"

    missing_setup_actions = [
        action
        for action in (mail_setup_action, contacts_setup_action, calendar_setup_action, chat_setup_action)
        if action
    ]

    return {
        "auth": {
            "main_api_token_configured": bool(main_token_configured),
        },
        "account": {
            "id": profile.account_id,
            "name": profile.account_name,
            "selected": bool(profile.account_id or profile.account_name),
        },
        "mail": {
            "mail_hosting_id": profile.mail_hosting_id,
            "default_mailbox": profile.default_mailbox,
            "mail_password_configured": mail_password_configured,
            "imap_ready": bool(profile.default_mailbox and mail_password_configured),
            "rest_discovery_ready": bool(main_token_configured and profile.account_id and profile.mail_hosting_id),
            "setup_action": mail_setup_action,
        },
        "drive": {
            "default_drive": {"id": profile.default_drive_id, "name": profile.default_drive_name},
            "configured": bool(profile.default_drive_id or profile.default_drive_name),
        },
        "contacts": {
            "url": profile.contacts_url,
            "username": profile.contacts_username,
            "configured": bool(profile.contacts_url and profile.contacts_username),
            "password_configured": contacts_password_configured,
            "ready": contacts_ready,
            "setup_action": contacts_setup_action,
        },
        "calendar": {
            "url": profile.calendar_url,
            "username": profile.calendar_username,
            "configured": bool(profile.calendar_url and profile.calendar_username),
            "password_configured": calendar_password_configured,
            "ready": calendar_ready,
            "setup_action": calendar_setup_action,
        },
        "chat": {
            "url": profile.kchat_url,
            "api_base": profile.kchat_url,
            "team_id": profile.kchat_team_id,
            "configured": chat_configured,
            "explicit_token_configured": chat_explicit_token_configured,
            "main_token_fallback_possible": chat_main_token_fallback_possible,
            "ready": chat_ready,
            "setup_action": chat_setup_action,
        },
        "missing_setup_actions": missing_setup_actions,
    }


def _suggested_email(profile: Profile) -> str:
    return profile.default_mailbox or profile.informaniak_user or "<email>"
