from __future__ import annotations

import argparse
import datetime
import os
import sys
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from . import update as update_module
from .api import DEFAULT_BASE_URL, InformaniakAPIClient, InformaniakAPIError, redact_secret
from .auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, MailPasswordStore, TokenStore
from .bootstrap import BootstrapError, bootstrap_profile
from .debug import probe_profile
from .doctor import run_doctor
from .completion import generate_bash, generate_fish, generate_powershell, generate_zsh
from .output import compact_json, error_json, pretty_json, redact, render_table
from .local_paths import normalize_local_path
from .pathcheck import plan_path_fix
from .profiles import ProfileManager
from .readiness import build_readiness
from .services.account import (
    list_accounts,
    list_products,
    list_services,
    slim_accounts,
    slim_products,
    slim_services,
)
from .services.calendar import (
    CalendarClient,
    CalendarConflictError,
    CalendarError,
    build_calendar_export_ics,
    build_event_ics,
    find_event,
    parse_ics_events,
    patch_event_ics,
    parse_event_input,
    search_events,
    slim_calendar,
    slim_calendars,
    slim_event,
    slim_events,
)
from .services.chat import (
    ChatClient,
    ChatError,
    derive_kchat_api_base_candidates,
    is_trusted_infomaniak_kchat_url,
    parse_ksuite_kchat_url,
    slim_channels,
    slim_post,
    slim_posts,
    slim_teams,
    slim_users,
)
from .services.contacts import (
    ContactError,
    ContactsClient,
    build_vcard,
    find_contact,
    merge_vcard,
    search_contacts,
    slim_contact,
    slim_contacts,
)
from .services.dav_discovery import (
    DavDiscoveryError,
    discover_addressbooks,
    discover_calendars,
)
from .services.drive import (
    build_folder_tree,
    download_file,
    find_file,
    get_file,
    get_share_state,
    get_trashed_file,
    is_folder,
    recent_files,
    list_files,
    list_folders,
    list_trash,
    move_file,
    rename_file,
    restore_file,
    search_files,
    shared_files,
    slim_file,
    slim_files,
    slim_folder_tree,
    trash_file,
    upload_file,
)
from .services.mail import IMAPClient, MailError, SMTPClient, build_mail_message, slim_message
from .services.mail_discovery import (
    list_mail_hostings,
    list_mailboxes,
    slim_mail_hosting,
    slim_mailbox,
)


DEFAULT_DAV_URL = "https://sync.infomaniak.com/"


def print_json(data: Any) -> None:
    print(pretty_json(data))


def print_machine(data: Any, args: argparse.Namespace) -> None:
    if getattr(args, "compact", False):
        print(compact_json(data))
    else:
        print_json(data)


def _machine_output(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False) or getattr(args, "compact", False))


def _raw_output(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "raw", False) and getattr(args, "json", False) and not getattr(args, "compact", False))


_TRUTHY_ENV = {"1", "true", "yes", "on"}


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY_ENV


def _stdin_is_tty() -> bool:
    isatty = getattr(sys.stdin, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return False


def _is_non_interactive(args: argparse.Namespace) -> bool:
    """True when ik must not block on an interactive prompt.

    Triggers on an explicit ``--non-interactive`` flag, the ``IK_NO_INTERACTIVE``
    env var, or a non-TTY stdin (piped/scripted/agent execution). Keeping this in
    one place means no command silently hangs waiting for input under automation.
    """
    if getattr(args, "non_interactive", False):
        return True
    if _env_flag("IK_NO_INTERACTIVE"):
        return True
    return not _stdin_is_tty()


def _prompt(args: argparse.Namespace, prompt_text: str, *, missing: str, hint: str) -> str:
    """Return interactive input, or fail fast (never hang) when non-interactive."""
    if _is_non_interactive(args):
        raise ValueError(f"{missing} in non-interactive mode. {hint}")
    return input(prompt_text)


def _confirm(args: argparse.Namespace, prompt_text: str, *, action: str) -> bool:
    """Resolve a yes/no confirmation without ever blocking under automation.

    ``--yes`` short-circuits to True. Otherwise machine-output and non-interactive
    callers get a clear "requires --yes" error instead of a hidden prompt; a real
    interactive terminal still prompts.
    """
    if getattr(args, "yes", False):
        return True
    if _machine_output(args):
        raise ValueError(f"{action} requires --yes when --json or --compact is used")
    if _is_non_interactive(args):
        raise ValueError(f"{action} requires --yes in non-interactive mode (no interactive prompt available)")
    return input(prompt_text).strip().lower() in {"y", "yes"}


def _validate_output_modes(args: argparse.Namespace) -> None:
    if getattr(args, "table", False) and _machine_output(args):
        raise ValueError("--table cannot be combined with --json or --compact")


def _error_type(exc: Exception) -> str:
    message = str(exc)
    if "No profile" in message or "Profile from IK_PROFILE" in message or "Profile not found" in message:
        return "missing_profile"
    if "No token configured" in message or "authentication failed" in message.lower() or "Unauthorized" in message:
        return "auth_failure"
    if isinstance(exc, InformaniakAPIError):
        return "api_error"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "runtime_error"


def _resolve_profile_name(manager: ProfileManager, explicit: str | None = None) -> str:
    env_profile = os.environ.get("IK_PROFILE")
    if explicit:
        name = explicit
        source = "--profile"
    elif env_profile:
        name = env_profile
        source = "IK_PROFILE"
    else:
        name = manager.get_current_name()
        source = "current profile"

    if not name:
        raise ValueError("No profile selected. Run `ik setup --profile <name>` first.")

    if source == "IK_PROFILE" and not manager.exists(name):
        raise ValueError(f"Profile from IK_PROFILE not found: {name}. Run `ik profile list` or unset IK_PROFILE.")
    if not manager.exists(name):
        raise ValueError(f"Profile not found: {name}. Run `ik profile list`.")

    return name


def _local_secret_stores() -> tuple[Any, ...]:
    return (
        TokenStore(),
        MailPasswordStore(),
        ContactsPasswordStore(),
        CalendarPasswordStore(),
        ChatTokenStore(),
    )


def _rename_profile_secrets(old: str, new: str) -> None:
    for store in _local_secret_stores():
        store.rename_profile(old, new)


def _profile_secret_rename_conflicts(old: str, new: str) -> list[str]:
    conflicts = []
    if TokenStore().has_token(old) and TokenStore().has_token(new):
        conflicts.append("api_token")
    if MailPasswordStore().has_password(old) and MailPasswordStore().has_password(new):
        conflicts.append("mail_password")
    if ContactsPasswordStore().has_password(old) and ContactsPasswordStore().has_password(new):
        conflicts.append("contacts_password")
    if CalendarPasswordStore().has_password(old) and CalendarPasswordStore().has_password(new):
        conflicts.append("calendar_password")
    if ChatTokenStore().has_token(old) and ChatTokenStore().has_token(new):
        conflicts.append("chat_token")
    return conflicts


def _delete_profile_secrets(name: str) -> None:
    for store in _local_secret_stores():
        store.delete_profile(name)


def _delete_auth_for_profile(name: str, *, all_secrets: bool = False) -> dict[str, bool]:
    token_store = TokenStore()
    mail_store = MailPasswordStore()
    contacts_store = ContactsPasswordStore()
    calendar_store = CalendarPasswordStore()
    chat_store = ChatTokenStore()

    removed = {
        "api_token": token_store.has_token(name),
        "mail_password": all_secrets and mail_store.has_password(name),
        "contacts_password": all_secrets and contacts_store.has_password(name),
        "calendar_password": all_secrets and calendar_store.has_password(name),
        "chat_token": all_secrets and chat_store.has_token(name),
    }

    token_store.delete_token(name)
    if all_secrets:
        mail_store.delete_password(name)
        contacts_store.delete_password(name)
        calendar_store.delete_password(name)
        chat_store.delete_token(name)

    return removed


def _make_api_client(token: str, base_url: str) -> InformaniakAPIClient:
    return InformaniakAPIClient(token, base_url=base_url)


def _unwrap_success_data(payload: Any) -> Any:
    if isinstance(payload, Mapping) and payload.get("result") == "success" and "data" in payload:
        return payload["data"]
    return payload


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


def _kchat_main_token_fallback_possible(profile: Any, profile_name: str) -> bool:
    return bool(
        profile.kchat_url
        and is_trusted_infomaniak_kchat_url(profile.kchat_url)
        and TokenStore().has_token(profile_name)
    )


def _mail_state(profile: Any, profile_name: str) -> dict[str, Any]:
    mail_password_configured = MailPasswordStore().has_password(profile_name)
    imap_host = profile.imap_host or "mail.infomaniak.com"
    imap_port = profile.imap_port or 993
    return {
        "default_mailbox": profile.default_mailbox,
        "mail_hosting_id": profile.mail_hosting_id,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "mail_password_configured": mail_password_configured,
        "imap_ready": bool(profile.default_mailbox and mail_password_configured),
        "rest_discovery_ready": bool(profile.account_id and profile.mail_hosting_id and TokenStore().has_token(profile_name)),
    }


def _kchat_metadata(input_url: str, base_url: str | None, parsed_url: Any, team_id: str | None) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if base_url:
        metadata["kchat_url"] = base_url
    if parsed_url:
        metadata.update(
            {
                "kchat_ksuite_url": parsed_url.original_url,
                "kchat_ksuite_account_id": parsed_url.account_id,
                "kchat_workspace_slug": parsed_url.workspace_slug,
            }
        )
        if parsed_url.channel_slug:
            metadata["kchat_default_channel_slug"] = parsed_url.channel_slug
    elif input_url:
        metadata["kchat_url"] = base_url or input_url
    if team_id:
        metadata["kchat_team_id"] = team_id.strip()
    return metadata


def _discover_kchat_api_base(candidates: list[str], token: str) -> str | None:
    for candidate in candidates:
        if not is_trusted_infomaniak_kchat_url(candidate):
            continue
        try:
            ChatClient(candidate, token, auth_source="main_token_fallback").list_teams()
        except ChatError:
            continue
        return candidate
    return None


def cmd_setup(args: argparse.Namespace) -> int:
    profile_name = args.profile
    if not profile_name and not _is_non_interactive(args):
        profile_name = input("Profile name: ").strip()
    if not profile_name:
        print("error: --profile is required in non-interactive mode", file=sys.stderr)
        return 2

    manager = ProfileManager()
    profile = manager.create_or_update(profile_name, make_default=True)
    print(f"Profile ready: {profile.name}")
    print(f"Next: run `ik --profile {profile.name} auth token`, then `ik --profile {profile.name} bootstrap`.")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    profile_name = _resolve_profile_name(manager, args.profile)

    profile = manager.get(profile_name)
    mail_state = _mail_state(profile, profile.name)
    readiness = build_readiness(profile)
    chat_store = ChatTokenStore()
    chat_url_configured = bool(profile.kchat_url)
    chat_explicit_token_configured = chat_store.has_token(profile.name)
    chat_main_token_fallback_possible = _kchat_main_token_fallback_possible(profile, profile.name)
    data = {
        "profile": profile.name,
        "informaniak_user": profile.informaniak_user,
        "account_id": profile.account_id,
        "account_name": profile.account_name,
        "default_mailbox": profile.default_mailbox,
        "mail": mail_state,
        "default_drive_id": profile.default_drive_id,
        "default_drive_name": profile.default_drive_name,
        "contacts_url": profile.contacts_url,
        "contacts_username": profile.contacts_username,
        "calendar_url": profile.calendar_url,
        "calendar_username": profile.calendar_username,
        "kchat_url": profile.kchat_url,
        "kchat_ksuite_url": profile.kchat_ksuite_url,
        "kchat_ksuite_account_id": profile.kchat_ksuite_account_id,
        "kchat_workspace_slug": profile.kchat_workspace_slug,
        "kchat_default_channel_slug": profile.kchat_default_channel_slug,
        "kchat_team_id": profile.kchat_team_id,
        "kchat_url_configured": chat_url_configured,
        "kchat_explicit_token_configured": chat_explicit_token_configured,
        "kchat_main_token_fallback_possible": chat_main_token_fallback_possible,
        "readiness": readiness,
        "missing_setup_actions": readiness["missing_setup_actions"],
    }
    if _machine_output(args):
        print_machine(data, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Informaniak user: {profile.informaniak_user or 'not configured'}")
        print(f"Account: {profile.account_name or profile.account_id or 'not selected'}")
        if mail_state["imap_ready"]:
            mail_status = f"{profile.default_mailbox} (IMAP ready via {mail_state['imap_host']}:{mail_state['imap_port']})"
        elif profile.default_mailbox:
            mail_status = f"{profile.default_mailbox} (mail password needed)"
        else:
            mail_status = "not selected"
        print(f"Mail: {mail_status}")
        print(f"Default kDrive: {profile.default_drive_name or profile.default_drive_id or 'not selected'}")
        print(f"Contacts: {profile.contacts_username or profile.contacts_url or 'not selected'}")
        print(f"Calendar: {profile.calendar_username or profile.calendar_url or 'not selected'}")
        if not chat_url_configured:
            chat_status = "not selected"
        elif chat_explicit_token_configured:
            chat_status = f"{profile.kchat_url} (explicit token configured)"
        elif chat_main_token_fallback_possible:
            chat_status = f"{profile.kchat_url} (main-token fallback possible)"
        else:
            chat_status = f"{profile.kchat_url} (token needed)"
        print(f"kChat: {chat_status}")
        if readiness["missing_setup_actions"]:
            print("Missing setup actions:")
            for action in readiness["missing_setup_actions"]:
                print(f"  {action}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    profile_name = None
    if args.profile or os.environ.get("IK_PROFILE"):
        profile_name = _resolve_profile_name(manager, args.profile)
    data = run_doctor(profile_name)

    if getattr(args, "fix_path", False):
        return _apply_fix_path(data["path"])

    if _machine_output(args):
        print_machine(data, args)
        return 0

    print(f"Config dir: {data['checks']['config_dir']}")
    print(f"Current profile: {data['profile'] or 'none'}")
    for check, ok in data["checks"].items():
        if check == "config_dir" or check == "profiles_found":
            continue
        marker = "✓" if ok else "⚠"
        if not ok and check == "chat_explicit_token_configured" and data["checks"].get("chat_main_token_fallback_possible"):
            marker = "-"
        print(f"{marker} {check}: {ok}")
    print(f"Install method: {data['install_method']}")
    _print_path_line(data["path"])
    if data.get("missing_setup_actions"):
        print("Missing setup actions:")
        for action in data["missing_setup_actions"]:
            print(f"  {action}")
    return 0


def _print_path_line(path_section: dict[str, Any]) -> None:
    if path_section["on_path"]:
        location = path_section["ik_path"] or path_section["scripts_dir"]
        print(f"✓ ik on PATH: {location}")
        return
    print(f"⚠ ik is installed but not on PATH. Scripts dir: {path_section['scripts_dir']}")
    if path_section.get("fix_hint"):
        print(f"  Fix (per-user PATH): {path_section['fix_hint']}")
        print("  Then open a new terminal. Or run: ik doctor --fix-path")


def _apply_fix_path(path_section: dict[str, Any]) -> int:
    scripts_dir = path_section["scripts_dir"]
    plan = plan_path_fix(scripts_dir, os.environ.get("PATH", ""), os_name=os.name)
    if plan["already_on_path"]:
        print(f"✓ {scripts_dir} is already on PATH. Nothing to do.")
        return 0
    print(f"Applying: {plan['change_description']}")
    
    from .pathcheck import apply_path_fix
    success = apply_path_fix(scripts_dir)
    
    if success:
        print(f"✓ Successfully added {scripts_dir} to your per-user PATH.")
        print("Please open a new terminal or reload your shell so the change takes effect.")
        return 0
    else:
        print(f"error: failed to apply the path fix.", file=sys.stderr)
        print(f"Please run manually: {plan['fix_command']}", file=sys.stderr)
        return 1

def cmd_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    try:
        release = update_module.fetch_latest_release()
        install_method = update_module.detect_install_method()
        plan = update_module.build_update_plan(
            __version__, release, install_method=install_method, force=getattr(args, "force", False)
        )
    except update_module.UpdateCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        output = plan.to_json()
        if args.yes and not args.check and not args.dry_run:
            returncode, result = _run_update_plan_json(plan)
            output["updater"] = result
            print_json(output)
            return returncode
        if args.dry_run and plan.command:
            output["dry_run_command"] = plan.command
        print_json(output)
        return 0

    if not plan.update_available:
        print(f"infomaniak-cli {plan.current_version} is up to date.")
        return 0

    _print_update_plan(plan)

    if args.check:
        return 0

    if args.dry_run:
        if plan.command:
            print(f"Would run: {_format_command(plan.command)}")
        return 0

    if not plan.can_auto_update:
        _print_manual_update_guidance(plan)
        return 0

    if not _confirm(args, "Update now? [y/N] ", action="update"):
        print("Update cancelled.")
        return 0

    return _run_update_plan(plan, verbose=getattr(args, "verbose", False))


def _print_update_plan(plan: update_module.UpdatePlan) -> None:
    print(f"Current version: {plan.current_version}")
    print(f"Latest version: {plan.latest_version}")
    print(f"Release URL: {plan.release_url}")
    print(f"Install method: {plan.install_method}")
    if plan.wheel_url:
        print(f"Wheel URL: {plan.wheel_url}")
    else:
        print("No installable wheel asset was found for this release.")


def _print_manual_update_guidance(plan: update_module.UpdatePlan) -> None:
    if plan.install_method == "source":
        print("Source checkout detected. Automatic source updates are not run by `ik update`.")
        for instruction in plan.instructions or ["git pull", "uv sync"]:
            print(instruction)
        return
    if plan.install_method == "unknown":
        print("Install method could not be detected. Best-effort default install command (review before running):")
        if plan.command:
            print(_format_command(plan.command))
        print("If you installed another way (uv tool / pip / source), use that tool's upgrade command instead.")
        return
    if not plan.wheel_url:
        print("Open the release URL above to update manually.")


def _run_update_plan(plan: update_module.UpdatePlan, *, verbose: bool = False) -> int:
    if not plan.can_auto_update or not plan.command:
        _print_manual_update_guidance(plan)
        return 0
    print(f"Running: {_format_command(plan.command)}")
    result = update_module.run_update_command(plan.command)

    if result.returncode != 0:
        # On failure, surface everything to aid diagnosis.
        if result.stdout:
            print(result.stdout.rstrip())
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        print(f"error: updater command failed with exit code {result.returncode}", file=sys.stderr)
        hint = update_module.update_failure_hint(plan.command, result.stderr)
        if hint:
            print(hint, file=sys.stderr)
        return result.returncode

    # Success: keep it quiet unless asked. The raw pip log is rarely useful.
    if verbose and result.stdout:
        print(result.stdout.rstrip())

    removed = update_module.prune_broken_distributions()
    if removed:
        print(f"Cleaned up {len(removed)} broken package leftover(s): {', '.join(removed)}")

    installed = update_module.installed_version()
    if installed == plan.latest_version:
        print(f"✓ Updated infomaniak-cli {plan.current_version} → {installed}")
    elif installed:
        print(f"✓ Updated infomaniak-cli {plan.current_version} → {installed}")
        print(
            f"warning: expected version {plan.latest_version} but the installed package reports {installed}.",
            file=sys.stderr,
        )
    else:
        print(f"✓ Updated infomaniak-cli to {plan.latest_version} (could not confirm the installed version).")
    return 0


def _run_update_plan_json(plan: update_module.UpdatePlan) -> tuple[int, dict[str, Any]]:
    if not plan.can_auto_update or not plan.command:
        return 0, {"ran": False, "reason": "manual_update_required"}
    result = update_module.run_update_command(plan.command)
    payload = {
        "ran": True,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode == 0:
        payload["cleaned"] = update_module.prune_broken_distributions()
        payload["installed_version"] = update_module.installed_version()
    hint = update_module.update_failure_hint(plan.command, result.stderr)
    if hint:
        payload["hint"] = hint
    return result.returncode, payload


def _format_command(command: list[str]) -> str:
    return " ".join(command)


def cmd_profile_list(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    current = manager.get_current_name()
    names = manager.list_names()
    if args.json:
        print_json({"current": current, "profiles": names})
        return 0
    if not names:
        print("No profiles configured.")
        return 0
    for name in names:
        prefix = "*" if name == current else " "
        print(f"{prefix} {name}")
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.name or _resolve_profile_name(manager, args.profile)
    profile = manager.get(name)
    if args.json:
        print_json(profile.to_dict())
    else:
        for key, value in profile.to_dict().items():
            print(f"{key}: {value if value else 'not configured'}")
    return 0


def cmd_profile_use(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    manager.set_current(args.name)
    print(f"Current profile: {args.name}")
    return 0


def cmd_profile_rename(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    conflicts = _profile_secret_rename_conflicts(args.old, args.new)
    if conflicts:
        raise ValueError(
            f"Cannot rename profile secrets because target profile already has: {', '.join(conflicts)}"
        )
    renamed = manager.rename(args.old, args.new)
    _rename_profile_secrets(args.old, args.new)
    data = {"old": args.old, "new": renamed.name, "current": manager.get_current_name()}
    if _machine_output(args):
        print_machine(data, args)
    else:
        print(f"Profile renamed: {args.old} -> {renamed.name}")
        print(f"Current profile: {data['current'] or 'none'}")
    return 0


def cmd_profile_delete(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    profile = manager.get(args.name)
    if not _confirm(
        args,
        f"Delete local profile '{profile.name}' and its local secrets? [y/N] ",
        action="profile delete",
    ):
        print("Profile delete cancelled.")
        return 0

    deleted = manager.delete(profile.name)
    _delete_profile_secrets(deleted.name)
    data = {"deleted": deleted.name, "current": manager.get_current_name()}
    if _machine_output(args):
        print_machine(data, args)
    else:
        print(f"Profile deleted: {deleted.name}")
        print(f"Current profile: {data['current'] or 'none'}")
    return 0


def cmd_auth_status(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    store = TokenStore()
    data = {"profile": name, "token_configured": store.has_token(name), "token": store.redacted_token(name)}
    if args.json:
        print_json(data)
    else:
        print(f"Profile: {name}")
        print(f"Token configured: {data['token_configured']}")
        if data["token"]:
            print(f"Token: {data['token']}")
    return 0


def cmd_auth_logout(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    scope = "main API token and service-specific local secrets" if args.all else "main API token"
    if not _confirm(args, f"Remove {scope} for profile '{name}'? [y/N] ", action="auth logout"):
        print("Logout cancelled.")
        return 0

    removed = _delete_auth_for_profile(name, all_secrets=args.all)
    data = {"profile": name, "removed": removed}
    if _machine_output(args):
        print_machine(data, args)
    else:
        print(f"Logged out profile: {name}")
        if args.all:
            print("Removed: main API token and service-specific local secrets")
        else:
            print("Removed: main API token")
    return 0


def cmd_auth_token(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    if args.stdin and args.token:
        print("error: use either --token or --stdin, not both", file=sys.stderr)
        return 2
    if args.stdin:
        token = sys.stdin.read().strip()
    elif args.token:
        token = args.token.strip()
    else:
        token = _prompt(
            args,
            "Informaniak API token: ",
            missing="An API token is required",
            hint="Pass --token <value> or pipe it with --stdin.",
        ).strip()
    TokenStore().save_token(name, token)
    print(f"Token saved for profile: {name}")
    return 0


def cmd_auth_check(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)

    token_store = TokenStore()
    if not token_store.has_token(name):
        print(f"No token configured for profile: {name}. Run `ik --profile {name} auth token` first.", file=sys.stderr)
        return 1

    client = _make_api_client(token_store.load_token(name), args.base_url)
    try:
        profile_data = _unwrap_success_data(client.get("/2/profile"))
        user = _profile_user(profile_data)
    except InformaniakAPIError as exc:
        if getattr(args, "compact", False):
            raise
        data = {"ok": False, "profile": name, "user": None, "error": str(exc)}
        if _machine_output(args):
            print_machine(data, args)
        else:
            print("Auth check: failed", file=sys.stderr)
            print(f"Profile: {name}", file=sys.stderr)
            print(f"Error: {data['error']}", file=sys.stderr)
        return 1

    data = {"ok": True, "profile": name, "user": user}
    if _machine_output(args):
        print_machine(data, args)
    else:
        print("Auth check: ok")
        print(f"Profile: {name}")
        print(f"Informaniak user: {user or 'not available'}")
    return 0


def cmd_auth_mail(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    if args.stdin and args.password:
        print("error: use either --password or --stdin, not both", file=sys.stderr)
        return 2
    if args.stdin:
        password = sys.stdin.read().strip()
    elif args.password:
        password = args.password.strip()
    else:
        password = _prompt(
            args,
            "Mail app password: ",
            missing="A mail app password is required",
            hint="Pass --password <value> or pipe it with --stdin.",
        ).strip()
    MailPasswordStore().save_password(name, password)

    # Also update mailbox/email if provided
    metadata = {}
    if args.mailbox:
        metadata["default_mailbox"] = args.mailbox.strip()
    if args.imap_host:
        metadata["imap_host"] = args.imap_host.strip()
    if args.imap_port is not None:
        metadata["imap_port"] = args.imap_port
    if metadata:
        manager.create_or_update(name, **metadata)

    print(f"Mail password saved for profile: {name}")
    return 0


def cmd_auth_contacts(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    if args.stdin and args.password:
        print("error: use either --password or --stdin, not both", file=sys.stderr)
        return 2

    profile = manager.get(name)
    contacts_url = (args.url or profile.contacts_url or DEFAULT_DAV_URL).strip()
    contacts_username = (args.username or profile.contacts_username or "").strip()
    if not contacts_username:
        print("error: --username is required for contacts; use your Infomaniak sync username, e.g. VG00000", file=sys.stderr)
        return 2

    if args.stdin:
        password = sys.stdin.read().strip()
    elif args.password:
        password = args.password.strip()
    else:
        password = _prompt(
            args,
            "Contacts CardDAV password: ",
            missing="A contacts CardDAV password is required",
            hint="Pass --password <value> or pipe it with --stdin.",
        ).strip()
    ContactsPasswordStore().save_password(name, password)

    resolved_url = _resolve_dav_collection_url(
        args,
        contacts_url,
        contacts_username,
        password,
        kind="address book",
        discover=discover_addressbooks,
    )
    manager.create_or_update(name, contacts_url=resolved_url, contacts_username=contacts_username)

    print(f"Contacts password saved for profile: {name}")
    return 0


def cmd_auth_calendar(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    if args.stdin and args.password:
        print("error: use either --password or --stdin, not both", file=sys.stderr)
        return 2

    profile = manager.get(name)
    calendar_url = (args.url or profile.calendar_url or DEFAULT_DAV_URL).strip()
    calendar_username = (args.username or profile.calendar_username or "").strip()
    if not calendar_username:
        print("error: --username is required for calendar; use your Infomaniak sync username, e.g. VG00000", file=sys.stderr)
        return 2

    if args.stdin:
        password = sys.stdin.read().strip()
    elif args.password:
        password = args.password.strip()
    else:
        password = _prompt(
            args,
            "Calendar CalDAV password: ",
            missing="A calendar CalDAV password is required",
            hint="Pass --password <value> or pipe it with --stdin.",
        ).strip()
    CalendarPasswordStore().save_password(name, password)

    resolved_url = _resolve_dav_collection_url(
        args,
        calendar_url,
        calendar_username,
        password,
        kind="calendar",
        discover=discover_calendars,
    )
    manager.create_or_update(name, calendar_url=resolved_url, calendar_username=calendar_username)

    print(f"Calendar password saved for profile: {name}")
    return 0


def _looks_like_dav_collection(url: str) -> bool:
    """Heuristic: a URL with >=2 path segments is already a collection, not a base."""
    path = urllib.parse.urlparse(url).path
    segments = [segment for segment in path.split("/") if segment]
    return len(segments) >= 2


def _resolve_dav_collection_url(
    args: argparse.Namespace,
    url: str,
    username: str,
    password: str,
    *,
    kind: str,
    discover: Callable[..., list[dict[str, Any]]],
) -> str:
    """Auto-discover the real DAV collection from a base URL, never raising.

    Honors an explicit collection-looking --url and --no-discover by saving the
    URL verbatim. On discovery failure or no match, keeps the provided URL and
    prints actionable guidance. Saved password/username are never lost.
    """
    if getattr(args, "no_discover", False) or _looks_like_dav_collection(url):
        return url

    try:
        collections = discover(url, username, password)
    except DavDiscoveryError as exc:
        print(
            f"note: could not auto-discover a {kind} from {url} "
            f"({redact_secret(str(exc), secrets=[password])}). "
            f"Pass --url <collection-url> to set it explicitly.",
            file=sys.stderr,
        )
        return url

    if not collections:
        print(
            f"warning: no {kind} collection found at {url}; keeping it, but reads will fail "
            f"until a real {kind} exists. The Infomaniak service may not be activated for "
            f"this user yet - open the corresponding web app once, then re-run this command. "
            "Pass --url <collection-url> to set the collection explicitly.",
            file=sys.stderr,
        )
        return url

    chosen = _choose_dav_collection(collections)
    if len(collections) > 1:
        print(f"Discovered {len(collections)} {kind}s; using {chosen['url']}.")
        for item in collections:
            print(f"  {item.get('name') or item['url']}\t{item['url']}")
        print(f"Re-run `auth` with --url <collection-url> to choose a different {kind}.")
    else:
        print(f"Discovered {kind}: {chosen['url']}")
    return chosen["url"]


def _choose_dav_collection(collections: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic default: prefer a default/contacts/personal-looking name, else the first."""
    for item in collections:
        name = (item.get("name") or "").casefold()
        url = (item.get("url") or "").casefold()
        if any(hint in name or hint in url for hint in ("default", "contacts", "personal")):
            return item
    return collections[0]


def cmd_auth_chat(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    if args.stdin and args.token:
        print("error: use either --token or --stdin, not both", file=sys.stderr)
        return 2

    profile = manager.get(name)
    input_url = (args.url or profile.kchat_url or "").strip()
    if not input_url:
        print("error: --url is required the first time kChat is configured", file=sys.stderr)
        return 2

    token = None
    if args.stdin:
        token = sys.stdin.read().strip()
    elif args.token:
        token = args.token.strip()

    parsed_ksuite_url = parse_ksuite_kchat_url(input_url)
    candidates = derive_kchat_api_base_candidates(input_url)
    base_url = candidates[0] if candidates else input_url
    metadata = _kchat_metadata(input_url, base_url, parsed_ksuite_url, args.team_id)

    if token:
        ChatTokenStore().save_token(name, token)
        manager.create_or_update(name, **metadata)
        print(f"kChat token saved for profile: {name}")
        return 0

    chat_store = ChatTokenStore()
    if chat_store.has_token(name):
        manager.create_or_update(name, **metadata)
        print(f"kChat settings saved for profile: {name}")
        return 0

    token_store = TokenStore()
    if parsed_ksuite_url and token_store.has_token(name):
        discovered_base_url = _discover_kchat_api_base(candidates, token_store.load_token(name))
        if discovered_base_url:
            manager.create_or_update(
                name,
                **_kchat_metadata(input_url, discovered_base_url, parsed_ksuite_url, args.team_id),
            )
            print(f"kChat API URL discovered and saved for profile: {name}")
            return 0

        manager.create_or_update(name, **_kchat_metadata(input_url, None, parsed_ksuite_url, args.team_id))
        print(
            "error: Could not confirm a working kChat API base URL from the kSuite URL. "
            f"Run `ik --profile {name} auth chat --url {input_url} --stdin` to save a dedicated kChat token.",
            file=sys.stderr,
        )
        return 2

    if is_trusted_infomaniak_kchat_url(base_url) and token_store.has_token(name):
        manager.create_or_update(name, **metadata)
        print(f"kChat URL saved for profile: {name} (main Informaniak API token fallback will be tried)")
        return 0

    if parsed_ksuite_url:
        manager.create_or_update(name, **_kchat_metadata(input_url, None, parsed_ksuite_url, args.team_id))
        print(
            "error: --token or --stdin is required to confirm the kChat API URL from this kSuite browser URL "
            "unless this profile already has a main Informaniak API token.",
            file=sys.stderr,
        )
    elif is_trusted_infomaniak_kchat_url(base_url):
        print(
            "error: --token or --stdin is required unless this profile already has a main Informaniak API token "
            "for trusted Infomaniak kChat host fallback.",
            file=sys.stderr,
        )
    else:
        print(
            "error: --token or --stdin is required for kChat URLs that are not trusted Infomaniak kChat hosts.",
            file=sys.stderr,
        )
    return 2


def _mail_profile(args: argparse.Namespace) -> Any:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    profile = manager.get(name)
    if not profile.default_mailbox:
        raise ValueError(
            f"No default mailbox configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth mail` to set the mailbox email and app password."
        )
    return profile


def _mail_password(profile: Any) -> str:
    mail_store = MailPasswordStore()
    if not mail_store.has_password(profile.name):
        raise ValueError(
            f"No mail password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth mail` to set the mailbox app password."
        )
    return mail_store.load_password(profile.name)


def _mail_profile_or_error(args: argparse.Namespace) -> tuple[Any, str, str, str, str]:
    """Resolve profile and return (profile, host, port, username, password).

    Raises ValueError if any required mail config is missing.
    """
    profile = _mail_profile(args)
    host = profile.imap_host or "mail.infomaniak.com"
    port = profile.imap_port or 993
    password = _mail_password(profile)
    return profile, host, port, profile.default_mailbox, password


def _mail_client(args: argparse.Namespace) -> IMAPClient:
    profile, host, port, mailbox, password = _mail_profile_or_error(args)
    return IMAPClient(host, port, mailbox, password)


def _mail_profile_and_client(args: argparse.Namespace) -> tuple[Any, IMAPClient]:
    profile, host, port, mailbox, password = _mail_profile_or_error(args)
    return profile, IMAPClient(host, port, mailbox, password)


def _contacts_profile(args: argparse.Namespace) -> Any:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)

    profile = manager.get(name)
    if not profile.contacts_url or not profile.contacts_username:
        raise ValueError(
            f"No contacts configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth contacts --username <sync-username> --stdin` first; "
            "it auto-discovers the address-book collection, or pass --url <collection-url> to set it explicitly."
        )

    return profile


def _contacts_client(profile: Any) -> ContactsClient:
    contacts_store = ContactsPasswordStore()
    if not contacts_store.has_password(profile.name):
        raise ValueError(
            f"No contacts password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth contacts --username <sync-username> --stdin` first."
        )

    return ContactsClient(
        profile.contacts_url,
        profile.contacts_username,
        contacts_store.load_password(profile.name),
    )


def _contacts_profile_and_client(args: argparse.Namespace) -> tuple[Any, ContactsClient]:
    profile = _contacts_profile(args)
    return profile, _contacts_client(profile)


def _calendar_profile_and_client(args: argparse.Namespace) -> tuple[Any, CalendarClient]:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)

    profile = manager.get(name)
    if not profile.calendar_url or not profile.calendar_username:
        raise ValueError(
            f"No calendar configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth calendar --username <sync-username> --stdin` first; "
            "it auto-discovers the calendar collection, or pass --url <collection-url> to set it explicitly."
        )

    calendar_store = CalendarPasswordStore()
    if not calendar_store.has_password(name):
        raise ValueError(
            f"No calendar password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth calendar --username <sync-username> --stdin` first."
        )

    password = calendar_store.load_password(name)
    url = _repaired_calendar_url(profile.calendar_url, profile.calendar_username, password)
    return profile, CalendarClient(url, profile.calendar_username, password)


def _repaired_calendar_url(url: str, username: str, password: str) -> str:
    """Recover a usable collection when the saved URL is only the service root.

    A profile whose calendar URL was never resolved past ``sync.infomaniak.com/``
    otherwise fails every read. Discovery is attempted once and is best-effort:
    on any failure the saved URL is returned unchanged so the normal read error
    still surfaces. This never raises and never persists anything.
    """
    if _looks_like_dav_collection(url):
        return url
    try:
        collections = discover_calendars(url, username, password)
    except DavDiscoveryError as exc:
        print(
            f"note: calendar URL {url} is not a collection and auto-discovery failed "
            f"({redact_secret(str(exc), secrets=[password])}). "
            f"Run `ik calendar repair` or `ik auth calendar --url <collection-url>`.",
            file=sys.stderr,
        )
        return url
    if not collections:
        print(
            f"note: calendar URL {url} is not a collection and no calendar was discovered. "
            f"Run `ik calendar repair` or `ik auth calendar --url <collection-url>`.",
            file=sys.stderr,
        )
        return url
    resolved = str(collections[0].get("url") or url)
    ambiguity = (
        f" {len(collections)} calendars were discovered; using the first."
        if len(collections) > 1
        else ""
    )
    print(
        f"note: using an auto-discovered calendar collection for this run.{ambiguity} "
        f"Run `ik calendar repair` to save it to the profile.",
        file=sys.stderr,
    )
    return resolved


def cmd_calendar_repair(args: argparse.Namespace) -> int:
    """Resolve and persist the profile's real CalDAV collection URL.

    Local profile config only: this never writes to the Calendar service.
    """
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    profile = manager.get(name)
    if not profile.calendar_url or not profile.calendar_username:
        raise ValueError(
            f"No calendar configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth calendar --username <sync-username> --stdin` first."
        )

    store = CalendarPasswordStore()
    if not store.has_password(name):
        raise ValueError(
            f"No calendar password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth calendar --username <sync-username> --stdin` first."
        )
    password = store.load_password(name)

    current = profile.calendar_url
    if args.url:
        resolved = args.url.strip()
    else:
        try:
            collections = discover_calendars(current, profile.calendar_username, password)
        except DavDiscoveryError as exc:
            raise ValueError(
                "Calendar discovery failed: "
                f"{redact_secret(str(exc), secrets=[password])}. "
                "Pass --url <collection-url> to set it explicitly."
            ) from exc
        if not collections:
            raise ValueError(
                f"No calendar collection was discovered from {current}. "
                "Pass --url <collection-url> to set it explicitly."
            )
        if len(collections) > 1:
            # Never silently pick a first match on a write, even a config write.
            choices = "\n".join(
                f"  {item.get('name') or '-'}: {item.get('url')}" for item in collections
            )
            raise ValueError(
                f"{len(collections)} calendar collections were discovered; refusing to guess.\n"
                f"{choices}\n"
                "Re-run with --url <collection-url> to choose one."
            )
        resolved = str(collections[0].get("url") or current)

    plan = {
        "profile": profile.name,
        "before": current,
        "after": resolved,
        "changed": resolved != current,
    }

    if args.dry_run:
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "saved": False}, args)
        else:
            print(f"Profile: {profile.name}")
            print(f"Before: {current}")
            print(f"After: {resolved}")
            print("Dry run: the profile was not changed.")
        return 0

    _require_explicit_profile_for_yes(args, "repair the calendar URL")
    if not _machine_output(args):
        print(f"Profile: {profile.name}")
        print(f"Before: {current}")
        print(f"After: {resolved}")
        print("(This only updates local profile config; no calendar data is changed.)")
    if not _confirm(args, "Save this calendar URL? [y/N] ", action="calendar repair"):
        print("Calendar repair cancelled.")
        return 2

    manager.create_or_update(name, calendar_url=resolved)
    readback = manager.get(name).calendar_url
    if _machine_output(args):
        print_machine({**plan, "saved": True, "readback": readback}, args)
    else:
        print(f"Saved calendar URL for profile {profile.name}.")
    return 0


def _chat_profile_and_client(args: argparse.Namespace) -> tuple[Any, ChatClient]:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)

    profile = manager.get(name)
    if not profile.kchat_url:
        raise ValueError(
            f"No kChat configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth chat --url <kchat-base-url> --stdin`, "
            "or omit the token only for trusted Infomaniak kChat hosts with a main API token configured."
        )

    chat_store = ChatTokenStore()
    if chat_store.has_token(name):
        return profile, ChatClient(
            profile.kchat_url,
            chat_store.load_token(name),
            auth_source="explicit_chat_token",
        )

    trusted_host = is_trusted_infomaniak_kchat_url(profile.kchat_url)
    token_store = TokenStore()
    if trusted_host and token_store.has_token(name):
        return profile, ChatClient(
            profile.kchat_url,
            token_store.load_token(name),
            auth_source="main_token_fallback",
        )

    if trusted_host:
        raise ValueError(
            f"No kChat token configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth chat --url <kchat-base-url> --stdin`, "
            "or configure a main Informaniak API token for trusted Infomaniak kChat host fallback."
        )

    raise ValueError(
        f"No kChat token configured for profile: {profile.name}. "
        "Main-token fallback is only allowed for trusted Infomaniak kChat hosts. "
        f"Run `ik --profile {profile.name} auth chat --url <kchat-base-url> --stdin` first."
    )


def _chat_team_id_or_error(args: argparse.Namespace, profile: Any, client: ChatClient) -> str:
    team_id = getattr(args, "team_id", None) or profile.kchat_team_id
    if team_id:
        return str(team_id)
    teams = client.list_teams()
    if len(teams) == 1 and teams[0].get("id"):
        return str(teams[0]["id"])
    raise ValueError(
        f"No kChat team configured for profile: {profile.name}. "
        "Run `ik chat teams --json` and rerun with --team-id <id>, or save one with `ik auth chat --team-id <id>`."
    )


def _today() -> datetime.date:
    """Return today's date. Inject-able for tests."""
    return datetime.date.today()


def _now_utc() -> datetime.datetime:
    """Return current UTC datetime. Inject-able for tests."""
    return datetime.datetime.now(datetime.UTC)


def _parse_calendar_boundary(value: str, option: str) -> datetime.datetime:
    text = value.strip()
    try:
        parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {option}: {value!r}. Use an ISO date or datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _calendar_range(
    args: argparse.Namespace, *, default_days: int
) -> tuple[datetime.datetime, datetime.datetime, int | None]:
    from_value = getattr(args, "from_value", None)
    to_value = getattr(args, "to_value", None)
    days = getattr(args, "days", None)

    if bool(from_value) != bool(to_value):
        raise ValueError("--from and --to must be used together")
    if from_value and to_value:
        if days is not None:
            raise ValueError("--days cannot be combined with --from/--to")
        start = _parse_calendar_boundary(from_value, "--from")
        end = _parse_calendar_boundary(to_value, "--to")
        if end <= start:
            raise ValueError("--to must be after --from")
        return start, end, None

    resolved_days = default_days if days is None else days
    if resolved_days < 1:
        raise ValueError("--days must be at least 1")
    start = _now_utc()
    return start, start + datetime.timedelta(days=resolved_days), resolved_days


def _iso_utc(value: datetime.datetime) -> str:
    return value.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")


def _resolve_mail_dates(args: argparse.Namespace) -> tuple[str | None, str | None, str | None]:
    """Resolve --since/--before/--days/--on into (since, before, on) ISO dates.

    Raises ValueError for mutually exclusive or invalid combinations.
    """
    since = getattr(args, "since", None)
    before = getattr(args, "before", None)
    on = getattr(args, "on", None)
    days = getattr(args, "days", None)

    if days is not None and since:
        raise ValueError("use either --days or --since, not both")
    if on and (since or before):
        raise ValueError("--on cannot be combined with --since or --before")
    if days is not None:
        since = (_today() - datetime.timedelta(days=days)).isoformat()
    return since, before, on


def _render_message_line(item: Mapping[str, Any], show_seen: bool = True) -> str:
    seen_marker = "R" if item.get("seen") else "U"
    uid = item.get("uid", "-")
    subject = item.get("subject") or "(no subject)"
    from_addr = item.get("from") or "(unknown)"
    date = item.get("date") or ""
    if show_seen:
        return f"{seen_marker}\t{uid}\t{date}\t{from_addr}\t{subject}"
    return f"{uid}\t{date}\t{from_addr}\t{subject}"


def cmd_mail_folders(args: argparse.Namespace) -> int:
    profile, client = _mail_profile_and_client(args)

    with client:
        folders = client.list_folders()

    if _machine_output(args):
        output = folders if _raw_output(args) else [{"name": f["name"], "role": f["role"]} for f in folders]
        print_machine({"profile": profile.name, "count": len(folders), "folders": output}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Folders: {len(folders)}")
        for folder in folders:
            role = f" ({folder['role']})" if folder["role"] else ""
            print(f"{folder['name']}{role}")
    return 0


def cmd_mail_list(args: argparse.Namespace) -> int:
    try:
        since, before, on = _resolve_mail_dates(args)
    except ValueError as exc:
        if getattr(args, "compact", False):
            raise
        if getattr(args, "json", False):
            print(error_json(_error_type(exc), str(exc), 2), file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        with client:
            items = client.list_messages(
                folder=args.folder,
                limit=args.limit,
                unread_only=args.unread,
                since=since,
                before=before,
                on=on,
                order="oldest" if args.oldest_first else "newest",
            )
    except MailError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if _machine_output(args):
        output = items if _raw_output(args) else [slim_message(item) for item in items]
        payload = {"profile": profile.name, "folder": args.folder, "count": len(items), "messages": output}
        if getattr(args, "unread", False):
            payload["unread"] = True
        print_machine(payload, args)
    else:
        status = "Unread messages" if args.unread else "Messages"
        print(f"{status} in {args.folder}: {len(items)}")
        for item in items:
            print(_render_message_line(item))
    return 0


def cmd_mail_unread(args: argparse.Namespace) -> int:
    args.unread = True
    args.folder = getattr(args, "folder", "INBOX")
    return cmd_mail_list(args)


def cmd_mail_search(args: argparse.Namespace) -> int:
    try:
        since, before, on = _resolve_mail_dates(args)
    except ValueError as exc:
        if getattr(args, "compact", False):
            raise
        if getattr(args, "json", False):
            print(error_json(_error_type(exc), str(exc), 2), file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    from_addr = getattr(args, "from_addr", None)
    to_addr = getattr(args, "to_addr", None)
    subject = getattr(args, "subject", None)
    if not any(value for value in (args.query, from_addr, to_addr, subject)):
        exc = ValueError("provide a search query or at least one of --from/--to/--subject")
        if _machine_output(args):
            print(error_json(_error_type(exc), str(exc), 2), file=sys.stderr)
            return 2
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        with client:
            items = client.search(
                args.query,
                folder=args.folder,
                limit=args.limit,
                unread_only=args.unread,
                since=since,
                before=before,
                on=on,
                order="oldest" if args.oldest_first else "newest",
                from_addr=from_addr,
                to_addr=to_addr,
                subject=subject,
            )
    except MailError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if _machine_output(args):
        output = items if _raw_output(args) else [slim_message(item) for item in items]
        payload = {
            "profile": profile.name,
            "folder": args.folder,
            "query": args.query,
            "count": len(items),
            "messages": output,
        }
        for key, value in (("from", from_addr), ("to", to_addr), ("subject", subject)):
            if value:
                payload[key] = value
        print_machine(payload, args)
    else:
        status = "Unread search results" if args.unread else "Search results"
        descriptor = _mail_search_descriptor(args.query, from_addr, to_addr, subject)
        print(f"{status} for {descriptor} in {args.folder}: {len(items)}")
        for item in items:
            print(_render_message_line(item))
    return 0


def _mail_search_descriptor(query: str | None, from_addr: str | None, to_addr: str | None, subject: str | None) -> str:
    parts = []
    if query:
        parts.append(f"'{query}'")
    if from_addr:
        parts.append(f"from~'{from_addr}'")
    if to_addr:
        parts.append(f"to~'{to_addr}'")
    if subject:
        parts.append(f"subject~'{subject}'")
    return " ".join(parts) or "(all)"


def cmd_mail_read(args: argparse.Namespace) -> int:
    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    folder = getattr(args, "folder", "INBOX")
    try:
        with client:
            msg = client.fetch_message(args.uid, folder=folder)
    except MailError as exc:
        if _machine_output(args):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if _machine_output(args):
        if not _raw_output(args):
            msg = slim_message(msg)
        print_machine({"profile": profile.name, "uid": args.uid, "folder": folder, "message": msg}, args)
    else:
        print(f"UID: {args.uid}")
        print(f"Folder: {folder}")
        print(f"From: {msg.get('from') or '(unknown)'}")
        print(f"To: {msg.get('to') or '(unknown)'}")
        print(f"Subject: {msg.get('subject') or '(no subject)'}")
        print(f"Date: {msg.get('date') or ''}")
        print()
        if getattr(args, "html", False):
            html = msg.get("body_html")
            if html:
                print(html)
            else:
                print("(no HTML body available; this message has no text/html part)")
        else:
            body = msg.get("body_text") or msg.get("body_preview")
            if body:
                print(body)
            else:
                print("(no body text available)")
    return 0


def _slim_thread(thread: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": thread["thread_id"],
        "subject": thread["subject"],
        "message_count": thread["message_count"],
        "newest_date": thread["newest_date"],
        "messages": [slim_message(m) for m in thread["messages"]],
    }


def cmd_mail_threads(args: argparse.Namespace) -> int:
    try:
        since, before, on = _resolve_mail_dates(args)
    except ValueError as exc:
        if _machine_output(args):
            print(error_json("validation_error", str(exc), 2), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    profile, client = _mail_profile_and_client(args)

    with client:
        threads = client.list_threads(
            folder=args.folder,
            limit=args.limit,
            since=since,
            before=before,
            on=on,
        )

    if _machine_output(args):
        output = threads if _raw_output(args) else [_slim_thread(t) for t in threads]
        print_machine({"profile": profile.name, "folder": args.folder, "count": len(threads), "threads": output}, args)
    else:
        print(f"Threads in {args.folder}: {len(threads)}")
        for thread in threads:
            print(f"[{thread['message_count']}] {thread['subject']} (latest UID {thread['newest_uid']})")
            for item in thread["messages"]:
                print(f"  {_render_message_line(item)}")
    return 0


def _mail_write_plan(args: argparse.Namespace, profile: Any, action: str) -> tuple[dict[str, Any], Any]:
    message = build_mail_message(
        sender=profile.default_mailbox,
        to=list(args.to_addrs),
        cc=list(args.cc_addrs or []),
        bcc=list(args.bcc_addrs or []),
        subject=args.subject,
        body=args.body,
    )
    plan = {
        "profile": profile.name,
        "mailbox": profile.default_mailbox,
        "action": action,
        "from": profile.default_mailbox,
        "to": list(args.to_addrs),
        "cc": list(args.cc_addrs or []),
        "bcc": list(args.bcc_addrs or []),
        "subject": args.subject,
        "body": args.body,
    }
    return plan, message


def _print_mail_write_preview(plan: Mapping[str, Any]) -> None:
    print(f"Profile: {plan['profile']}")
    print(f"Mailbox: {plan['mailbox']}")
    print(f"Action: {plan['action']} one message")
    print(f"From: {plan['from']}")
    print(f"To: {', '.join(plan['to'])}")
    if plan["cc"]:
        print(f"Cc: {', '.join(plan['cc'])}")
    if plan["bcc"]:
        print(f"Bcc: {', '.join(plan['bcc'])}")
    print(f"Subject: {plan['subject']}")
    body = str(plan["body"])
    preview = body if len(body) <= 500 else f"{body[:500]}…"
    print("Body preview:")
    print(preview)


def _validate_mail_write_yes(args: argparse.Namespace, action: str) -> None:
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            f"Refusing to {action} with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE)."
        )


def cmd_mail_draft(args: argparse.Namespace) -> int:
    profile = _mail_profile(args)
    plan, message = _mail_write_plan(args, profile, "save a draft")
    plan["folder"] = args.folder

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "drafted": False}, args)
        else:
            _print_mail_write_preview(plan)
            print("Dry run: no draft was saved.")
        return 0

    _validate_mail_write_yes(args, "save a mail draft")
    if not _machine_output(args):
        _print_mail_write_preview(plan)
    if not _confirm(args, "Save this draft? [y/N] ", action="mail draft"):
        print("Draft save cancelled.")
        return 2

    host = profile.imap_host or "mail.infomaniak.com"
    port = profile.imap_port or 993
    client = IMAPClient(host, port, profile.default_mailbox, _mail_password(profile))
    try:
        result = client.append_draft(message, folder=args.folder)
    finally:
        client.close()
    if _machine_output(args):
        print_machine({**plan, "drafted": True, "result": result}, args)
    else:
        print(f"Saved draft in {result['folder']}.")
    return 0


def cmd_mail_send(args: argparse.Namespace) -> int:
    profile = _mail_profile(args)
    plan, message = _mail_write_plan(args, profile, "send")

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "sent": False}, args)
        else:
            _print_mail_write_preview(plan)
            print("Dry run: no message was sent.")
        return 0

    _validate_mail_write_yes(args, "send mail")
    if not _machine_output(args):
        _print_mail_write_preview(plan)
    if not _confirm(args, "Send this message? [y/N] ", action="mail send"):
        print("Mail send cancelled.")
        return 2

    smtp_host = profile.imap_host or "mail.infomaniak.com"
    client = SMTPClient(smtp_host, 465, profile.default_mailbox, _mail_password(profile))
    result = client.send_message(message)
    if _machine_output(args):
        print_machine({**plan, "sent": True, "result": result}, args)
    else:
        print(f"Sent message to {', '.join(plan['to'])}.")
    return 0


def _profile_for_mail_discovery(args: argparse.Namespace) -> Any:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)
    return manager.get(name)


def _profile_mailbox_item(profile: Any) -> dict[str, Any] | None:
    if not profile.default_mailbox:
        return None
    return {"email": profile.default_mailbox, "mail_hosting_id": profile.mail_hosting_id}


def cmd_mail_mailboxes(args: argparse.Namespace) -> int:
    profile = _profile_for_mail_discovery(args)
    token_store = TokenStore()
    source = "profile"
    mailboxes: list[Mapping[str, Any]] = []

    if profile.mail_hosting_id and token_store.has_token(profile.name):
        client = _make_api_client(token_store.load_token(profile.name), args.base_url)
        mailboxes = list_mailboxes(client, str(profile.mail_hosting_id))
        source = "api"
    else:
        profile_item = _profile_mailbox_item(profile)
        if profile_item:
            mailboxes = [profile_item]

    if not mailboxes:
        raise ValueError(
            f"No configured or discovered mailboxes for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} bootstrap` to discover mailboxes, or "
            f"`ik --profile {profile.name} auth mail --mailbox <email>` to configure one manually."
        )

    if _machine_output(args):
        output_mailboxes = mailboxes if _raw_output(args) else [
            slim_mailbox(mailbox, mail_hosting_id=profile.mail_hosting_id, source=source) for mailbox in mailboxes
        ]
        print_machine(
            {
                "profile": profile.name,
                "account_id": profile.account_id,
                "mail_hosting_id": profile.mail_hosting_id,
                "default_mailbox": profile.default_mailbox,
                "count": len(mailboxes),
                "mailboxes": output_mailboxes,
            },
            args,
        )
    elif getattr(args, "table", False):
        rows = [slim_mailbox(mailbox, mail_hosting_id=profile.mail_hosting_id, source=source) for mailbox in mailboxes]
        print(render_table(rows, [("id", "ID"), ("email", "Email"), ("source", "Source"), ("mail_hosting_id", "Hosting")]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Mail hosting ID: {profile.mail_hosting_id or 'not selected'}")
        print(f"Default mailbox: {profile.default_mailbox or 'not selected'}")
        print(f"Mailboxes: {len(mailboxes)}")
        for mailbox in mailboxes:
            slim = slim_mailbox(mailbox, mail_hosting_id=profile.mail_hosting_id, source=source)
            print(f"{slim['id'] or '-'}\t{slim['email'] or '-'}\t{slim['source'] or '-'}")
    return 0


def cmd_mail_hostings(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    account_id = _account_id_or_error(args, profile)
    hostings = list_mail_hostings(client, account_id)

    if _machine_output(args):
        output_hostings = hostings if _raw_output(args) else [slim_mail_hosting(hosting) for hosting in hostings]
        print_machine(
            {
                "profile": profile.name,
                "account_id": account_id,
                "count": len(hostings),
                "hostings": output_hostings,
            },
            args,
        )
    elif getattr(args, "table", False):
        print(render_table([slim_mail_hosting(hosting) for hosting in hostings], [
            ("id", "ID"),
            ("name", "Name"),
            ("type", "Type"),
        ]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Account ID: {account_id}")
        print(f"Mail hostings: {len(hostings)}")
        if not hostings:
            print("No mail hostings found.")
        for hosting in hostings:
            slim = slim_mail_hosting(hosting)
            print(f"{slim['id'] or '-'}\t{slim['name'] or '-'}\t{slim['type'] or '-'}")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, args.profile)

    token_store = TokenStore()
    if not token_store.has_token(name):
        print(f"No token configured for profile: {name}. Run `ik --profile {name} auth token` first.", file=sys.stderr)
        return 1

    client = _make_api_client(token_store.load_token(name), args.base_url)
    result = bootstrap_profile(
        name,
        client,
        manager=manager,
        account_id=args.account_id,
        non_interactive=args.non_interactive,
    )
    profile = manager.get(name)
    readiness = build_readiness(profile, main_token_configured=True)
    output = _bootstrap_readiness_output(result, readiness)
    if _machine_output(args):
        print_machine(output, args)
    else:
        print(f"Profile bootstrapped: {output['profile']}")
        print(f"Informaniak user: {output['informaniak_user'] or 'not found'}")
        account = output["account"]
        print(f"Account: {account['name'] or account['id'] or 'not selected'}")
        print(f"Products/services: {output['counts']['products']} products, {output['counts']['services']} services")
        mail = output["mail"]
        if mail["imap_ready"]:
            mail_status = f"{mail['default_mailbox']} (IMAP ready)"
        elif mail["default_mailbox"]:
            mail_status = f"{mail['default_mailbox']} (mail password needed)"
        else:
            mail_status = "not selected"
        print(f"Mail: {mail_status}")
        drive = output["drive"]["default_drive"]
        print(f"Default kDrive: {drive['name'] or drive['id'] or 'not selected'}")
        print(f"Contacts: {'ready' if output['contacts']['ready'] else 'setup needed'}")
        print(f"Calendar: {'ready' if output['calendar']['ready'] else 'setup needed'}")
        print(f"kChat: {'ready' if output['chat']['ready'] else 'setup needed'}")
        if output["missing_setup_actions"]:
            print("Missing setup actions:")
            for action in output["missing_setup_actions"]:
                print(f"  {action}")
    return 0


def _bootstrap_readiness_output(result: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    account = dict(readiness["account"])
    output = {
        key: value
        for key, value in result.items()
        if key not in {"account", "mail_hosting_id", "default_mailbox", "default_drive", "kchat_team_id"}
    }
    output.update(
        {
            "account": account,
            "auth": readiness["auth"],
            "mail": {
                **dict(readiness["mail"]),
                "discovered_mailboxes_count": result.get("counts", {}).get("mailboxes", 0),
            },
            "drive": {
                **dict(readiness["drive"]),
                "discovered_drives_count": result.get("counts", {}).get("drives", 0),
            },
            "contacts": readiness["contacts"],
            "calendar": readiness["calendar"],
            "chat": readiness["chat"],
            "missing_setup_actions": readiness["missing_setup_actions"],
            "mail_hosting_id": readiness["mail"]["mail_hosting_id"],
            "default_mailbox": readiness["mail"]["default_mailbox"],
            "default_drive": readiness["drive"]["default_drive"],
            "kchat_team_id": readiness["chat"]["team_id"],
            "readiness": readiness,
        }
    )
    return output


def _profile_and_client(profile_name: str | None = None, base_url: str = DEFAULT_BASE_URL) -> tuple[Any, InformaniakAPIClient]:
    manager = ProfileManager()
    name = _resolve_profile_name(manager, profile_name)

    profile = manager.get(name)
    token_store = TokenStore()
    if not token_store.has_token(name):
        raise ValueError(f"No token configured for profile: {name}. Run `ik --profile {name} auth token` first.")

    return profile, _make_api_client(token_store.load_token(name), base_url)


def _account_id_or_error(args: argparse.Namespace, profile: Any) -> str:
    account_id = args.account_id or profile.account_id
    if not account_id:
        raise ValueError(
            f"No account selected for profile: {profile.name}. Run `ik bootstrap` or rerun with --account-id <id>."
        )
    return str(account_id)


def _drive_id_or_error(args: argparse.Namespace, profile: Any) -> str:
    drive_id = args.drive_id or profile.default_drive_id
    if not drive_id:
        raise ValueError(
            f"No default kDrive selected for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} bootstrap` or rerun with --drive-id <id>."
        )
    return str(drive_id)


def _display_item(item: Mapping[str, Any]) -> str:
    item_id = item.get("id") or item.get("account_id") or item.get("service_id") or item.get("product_id") or "-"
    name = (
        item.get("name")
        or item.get("display_name")
        or item.get("label")
        or item.get("title")
        or item.get("service_name")
        or item.get("customer_name")
        or "unnamed"
    )
    return f"{item_id}\t{name}"


def _display_drive_item(item: Mapping[str, Any]) -> str:
    item_type = item.get("type") or "-"
    item_id = item.get("id") or "-"
    name = item.get("name") or item.get("display_name") or "unnamed"
    modified = item.get("last_modified_at") or item.get("modified_at") or item.get("updated_at") or ""
    size = item.get("size") if item.get("size") is not None else ""
    return f"{item_type}\t{item_id}\t{size}\t{modified}\t{name}"


def _drive_table(files: list[Mapping[str, Any]], *, drive_id: str) -> str:
    return render_table(
        slim_files(files, drive_id=drive_id),
        [
            ("type", "Type"),
            ("id", "ID"),
            ("size", "Size"),
            ("last_modified_at", "Modified"),
            ("name", "Name"),
        ],
    )


def _display_drive_tree(tree: list[Mapping[str, Any]], *, level: int = 0) -> list[str]:
    lines: list[str] = []
    prefix = "  " * level
    for node in tree:
        folder = node.get("folder")
        if not isinstance(folder, Mapping):
            continue
        item_id = folder.get("id") or "-"
        name = folder.get("name") or folder.get("display_name") or "unnamed"
        lines.append(f"{prefix}{item_id}\t{name}")
        children = node.get("children")
        if isinstance(children, list):
            lines.extend(_display_drive_tree(children, level=level + 1))
    return lines


def _display_contact(contact: Mapping[str, Any]) -> str:
    contact_id = contact.get("id") or "-"
    name = contact.get("display_name") or "unnamed"
    emails = contact.get("emails") or []
    email = emails[0] if isinstance(emails, list) and emails else ""
    organization = contact.get("organization") or ""
    return f"{contact_id}\t{name}\t{email}\t{organization}"


def _display_calendar(calendar: Mapping[str, Any]) -> str:
    calendar_id = calendar.get("id") or "-"
    name = calendar.get("name") or "unnamed"
    url = calendar.get("url") or ""
    return f"{calendar_id}\t{name}\t{url}"


def _display_event(event: Mapping[str, Any]) -> str:
    event_id = event.get("id") or event.get("uid") or "-"
    starts_at = event.get("starts_at") or ""
    ends_at = event.get("ends_at") or ""
    summary = event.get("summary") or "(no summary)"
    location = event.get("location") or ""
    return f"{event_id}\t{starts_at}\t{ends_at}\t{summary}\t{location}"


def _display_chat_team(team: Mapping[str, Any]) -> str:
    team_id = team.get("id") or "-"
    name = team.get("name") or "-"
    display_name = team.get("display_name") or ""
    return f"{team_id}\t{name}\t{display_name}"


def _display_chat_channel(channel: Mapping[str, Any]) -> str:
    channel_id = channel.get("id") or "-"
    name = channel.get("name") or "-"
    display_name = channel.get("display_name") or ""
    channel_type = channel.get("type") or ""
    return f"{channel_id}\t{channel_type}\t{name}\t{display_name}"


def _display_chat_user(user: Mapping[str, Any]) -> str:
    user_id = user.get("id") or "-"
    username = user.get("username") or "-"
    name = " ".join(str(part) for part in (user.get("first_name"), user.get("last_name")) if part)
    email = user.get("email") or ""
    return f"{user_id}\t{username}\t{name}\t{email}"


def _display_chat_post(post: Mapping[str, Any]) -> str:
    slim = slim_post(post)
    post_id = slim.get("id") or "-"
    created = slim.get("created_at") or ""
    channel_id = slim.get("channel_id") or "-"
    user_id = slim.get("user_id") or "-"
    message = (slim.get("message") or "").replace("\n", " ")
    return f"{post_id}\t{created}\t{channel_id}\t{user_id}\t{message}"


def _drive_404_error(drive_id: str) -> ValueError:
    path = f"/2/drive/{drive_id}/files"
    return ValueError(
        f"kDrive files endpoint returned 404 for {path}; saved kDrive id may be wrong. "
        "Rerun bootstrap or capture this failing path."
    )


def cmd_account_list(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    accounts = list_accounts(client)
    if _machine_output(args):
        output_accounts = accounts if _raw_output(args) else slim_accounts(accounts)
        print_machine({"profile": profile.name, "accounts": output_accounts}, args)
    else:
        print(f"Profile: {profile.name}")
        if not accounts:
            print("No accounts found.")
        for account in accounts:
            print(_display_item(account))
    return 0


def cmd_account_products(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    account_id = _account_id_or_error(args, profile)
    products = list_products(client, account_id)
    if _machine_output(args):
        output_products = products if _raw_output(args) else slim_products(products)
        print_machine({"profile": profile.name, "account_id": account_id, "products": output_products}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Account ID: {account_id}")
        print("Catalog products (diagnostic): use `ik account services` for workflow discovery.")
        if not products:
            print("No products found.")
        for product in products:
            print(_display_item(product))
    return 0


def cmd_account_services(args: argparse.Namespace) -> int:
    _validate_output_modes(args)
    profile, client = _profile_and_client(args.profile, args.base_url)
    account_id = _account_id_or_error(args, profile)
    services = list_services(client, account_id)
    workflow_services = slim_services(services)
    if _machine_output(args):
        output_services = services if _raw_output(args) else workflow_services
        print_machine(
            {
                "profile": profile.name,
                "account_id": account_id,
                "count": len(services),
                "services": output_services,
            },
            args,
        )
    elif getattr(args, "table", False):
        print(render_table(workflow_services, [
            ("id", "ID"),
            ("name", "Service"),
            ("count", "Count"),
            ("area", "Area"),
            ("command", "Next command"),
        ]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Account ID: {account_id}")
        print(f"Services: {len(services)}")
        if not services:
            print("No services found.")
        for service in workflow_services:
            service_id = service.get("id") or "-"
            name = service.get("name") or "unnamed"
            count = service.get("count") if service.get("count") is not None else "-"
            command = service.get("command") or "catalog only"
            print(f"{service_id}\t{name}\t{count}\t{command}")
    return 0


def cmd_drive_list(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        files = list_files(client, drive_id, parent_id=args.parent_id, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_files = files if _raw_output(args) else slim_files(files, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "count": len(files),
                "files": output_files,
            },
            args,
        )
    elif getattr(args, "table", False):
        print(_drive_table(files, drive_id=drive_id))
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        if args.parent_id:
            print(f"Parent ID: {args.parent_id}")
        print(f"Files: {len(files)}")
        if not files:
            print("No files found.")
        for file_item in files:
            print(_display_drive_item(file_item))
    return 0


def cmd_drive_recent(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        files = recent_files(client, drive_id, parent_id=args.parent_id, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_files = files if _raw_output(args) else slim_files(files, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "count": len(files),
                "files": output_files,
            },
            args,
        )
    elif getattr(args, "table", False):
        print(_drive_table(files, drive_id=drive_id))
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        if args.parent_id:
            print(f"Parent ID: {args.parent_id}")
        print(f"Recent files: {len(files)}")
        if not files:
            print("No files found.")
        for file_item in files:
            print(_display_drive_item(file_item))
    return 0


def cmd_drive_shared(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        files = shared_files(list_files(client, drive_id), limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_files = files if _raw_output(args) else slim_files(files, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "count": len(files),
                "files": output_files,
            },
            args,
        )
    elif getattr(args, "table", False):
        print(_drive_table(files, drive_id=drive_id))
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Shared files: {len(files)}")
        if not files:
            print("No shared files found.")
        for file_item in files:
            print(_display_drive_item(file_item))
    return 0


def cmd_drive_mkdir(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    name = args.name
    parent_id = getattr(args, "parent_id", None)
    
    if not _confirm(args, f"Create folder '{name}' in drive {drive_id} (parent: {parent_id or 'root'})?", action="mkdir"):
        return 2
        
    try:
        from .services.drive import create_folder
        folder = create_folder(client, drive_id, name, parent_id=parent_id)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        from .services.drive import slim_file
        output_folder = folder if _raw_output(args) else slim_file(folder, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": parent_id,
                "folder": output_folder,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Successfully created folder: {name}")
        print(_display_drive_item(folder))
    return 0


def cmd_drive_folders(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        folders = list_folders(client, drive_id, parent_id=args.parent_id, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_folders = folders if _raw_output(args) else slim_files(folders, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "count": len(folders),
                "folders": output_folders,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        if args.parent_id:
            print(f"Parent ID: {args.parent_id}")
        print(f"Folders: {len(folders)}")
        if not folders:
            print("No folders found.")
        for folder in folders:
            print(_display_drive_item(folder))
    return 0


def cmd_drive_tree(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        tree = build_folder_tree(client, drive_id, parent_id=args.parent_id, depth=args.depth, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_tree = tree if _raw_output(args) else slim_folder_tree(tree, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "depth": args.depth,
                "count": len(tree),
                "tree": output_tree,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        if args.parent_id:
            print(f"Parent ID: {args.parent_id}")
        print(f"Depth: {args.depth}")
        print(f"Folders: {len(tree)}")
        if not tree:
            print("No folders found.")
        for line in _display_drive_tree(tree):
            print(line)
    return 0


def cmd_drive_search(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        files = search_files(client, drive_id, args.query, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if _machine_output(args):
        output_files = files if _raw_output(args) else slim_files(files, drive_id=drive_id)
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "query": args.query,
                "count": len(files),
                "files": output_files,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Query: {args.query}")
        print(f"Files: {len(files)}")
        if not files:
            print("No matching files found.")
        for file_item in files:
            print(_display_drive_item(file_item))
    return 0


def cmd_drive_info(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        file_item = find_file(client, drive_id, args.file_id)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise
    if file_item is None:
        raise ValueError(f"kDrive file not found in drive {drive_id}: {args.file_id}")

    output_file = file_item if _raw_output(args) else slim_file(file_item, drive_id=drive_id)
    if _machine_output(args):
        print_machine({"profile": profile.name, "drive_id": drive_id, "file_id": args.file_id, "file": output_file}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"File ID: {args.file_id}")
        print(f"Name: {output_file.get('name') or 'unnamed'}")
        print(f"Type: {output_file.get('type') or '-'}")
        parent_id = output_file.get("parent_id")
        if parent_id:
            print(f"Parent ID: {parent_id}")
        visibility = output_file.get("visibility")
        if visibility:
            print(f"Visibility: {visibility}")
        created_at = output_file.get("created_at")
        if created_at:
            print(f"Created: {created_at}")
        modified_at = output_file.get("last_modified_at")
        if modified_at:
            print(f"Modified: {modified_at}")
    return 0


def _resolve_download_destination(output: str | None, remote_name: str) -> Path:
    """Compute the local path to write a downloaded file to.

    - no ``--output``            -> ``./<remote_name>`` in the current directory;
    - ``--output`` is a dir      -> ``<output>/<remote_name>``;
    - ``--output`` otherwise     -> used verbatim as the destination file.
    """
    safe_name = os.path.basename(remote_name) or "download"
    if output is None:
        return Path.cwd() / safe_name
    dest = Path(_normalize_download_path(output))
    if dest.is_dir():
        return dest / safe_name
    return dest


def _normalize_download_path(path: str, *, os_name: str | None = None) -> str:
    """Backward-compatible wrapper around central local path normalization."""
    return normalize_local_path(path, os_name=os_name)


def cmd_drive_download(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = args.file_id

    try:
        file_item = get_file(client, drive_id, file_id)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise ValueError(
                f"kDrive file not found in drive {drive_id}: {file_id}. "
                f"Use `ik drive list`/`ik drive search` to find a file id."
            ) from exc
        raise

    remote_name = str(file_item.get("name") or f"file-{file_id}")
    if is_folder(file_item):
        raise ValueError(
            f"'{remote_name}' (id {file_id}) is a folder, not a file. "
            f"`ik drive download` only downloads files."
        )

    destination = _resolve_download_destination(getattr(args, "output", None), remote_name)
    if destination.exists() and not getattr(args, "force", False):
        raise ValueError(
            f"Refusing to overwrite existing file: {destination}. "
            f"Pass --force to overwrite the local file."
        )

    content, _headers = download_file(client, drive_id, file_id)

    destination_parent = destination.parent
    if destination_parent and not destination_parent.exists():
        raise ValueError(
            f"Destination directory does not exist: {destination_parent}. "
            "Create it first or pass an existing directory/path with --output."
        )
    destination.write_bytes(content)

    size = len(content)
    if _machine_output(args):
        print_machine(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "file_id": file_id,
                "name": remote_name,
                "destination": str(destination),
                "bytes": size,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Source: {remote_name} (id {file_id})")
        print(f"Destination: {destination}")
        print(f"Downloaded {size} bytes.")
    return 0


def _print_drive_rm_preview(profile: Any, drive_id: str, target: Mapping[str, Any]) -> None:
    print(f"Profile: {profile.name}")
    print(f"Drive ID: {drive_id}")
    print(f"Target: {target.get('name') or 'unnamed'}")
    print(f"Type: {target.get('type') or '-'}")
    print(f"File ID: {target.get('id') or '-'}")
    print("Action: move this single item to kDrive trash (undoable; not a permanent delete)")


def cmd_drive_rm(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = str(args.file_id)

    try:
        file_item = get_file(client, drive_id, file_id)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise ValueError(
                f"kDrive file not found in drive {drive_id}: {file_id}. "
                "Use `ik drive list`/`ik drive search` to find a file id."
            ) from exc
        raise

    if file_id == "1" or str(file_item.get("visibility") or "").casefold() == "is_root":
        raise ValueError("Refusing to trash the kDrive root directory.")

    target = slim_file(file_item, drive_id=drive_id)
    plan = {
        "profile": profile.name,
        "drive_id": drive_id,
        "file_id": file_id,
        "target": target,
    }

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "trashed": False}, args)
        else:
            _print_drive_rm_preview(profile, drive_id, target)
            print("Dry run: nothing was moved to trash.")
        return 0

    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            "Refusing to trash with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE) so automation cannot write to the wrong account."
        )

    if not _machine_output(args):
        _print_drive_rm_preview(profile, drive_id, target)

    if not _confirm(args, "Move this item to trash? [y/N] ", action="drive rm"):
        print("Trash operation cancelled.")
        return 2

    trash = trash_file(client, drive_id, file_id)
    if _machine_output(args):
        print_machine({**plan, "trashed": True, "trash": dict(trash)}, args)
    else:
        print(f"Moved '{target.get('name') or file_id}' to kDrive trash.")
        if trash.get("cancel_id"):
            print(f"Undo token: {trash['cancel_id']}")
    return 0


def _require_explicit_profile_for_yes(args: argparse.Namespace, action: str) -> None:
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            f"Refusing to {action} with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE) so automation cannot write to the wrong account."
        )


def _drive_change_plan(
    profile: Any,
    drive_id: str,
    *,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "profile": profile.name,
        "drive_id": drive_id,
        "before": dict(before) if before is not None else None,
        "after": dict(after),
    }


def _print_drive_change_preview(plan: Mapping[str, Any], action: str) -> None:
    print(f"Profile: {plan['profile']}")
    print(f"Drive ID: {plan['drive_id']}")
    print(f"Action: {action}")
    before = plan.get("before")
    if before:
        print(f"Before: {before.get('name') or '-'} (id {before.get('id') or '-'})")
    else:
        print("Before: no remote file")
    after = plan.get("after") or {}
    print(f"After: {after.get('name') or '-'}")
    if after.get("parent_id") is not None:
        print(f"Destination folder ID: {after['parent_id']}")


def _validated_remote_name(name: str) -> str:
    clean = name.strip()
    if not clean or clean in {".", ".."}:
        raise ValueError("Remote file name must not be empty, '.' or '..'.")
    if "/" in clean or "\\" in clean:
        raise ValueError("Remote file name must be one name, not a path.")
    return clean


def _resolve_drive_folder(client: Any, drive_id: str, folder_id: str, *, label: str) -> Mapping[str, Any]:
    folder = get_file(client, drive_id, folder_id)
    if not is_folder(folder):
        raise ValueError(f"{label} is not a kDrive folder: {folder_id}")
    return folder


def cmd_drive_upload(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    source = Path(normalize_local_path(args.path))
    if not source.exists():
        raise ValueError(f"Local upload source does not exist: {source}")
    if not source.is_file():
        raise ValueError(f"Local upload source is not a single file: {source}")
    size = source.stat().st_size
    if size > 1_000_000_000:
        raise ValueError("Single-file upload is limited to 1 GB; chunked uploads are not implemented.")

    name = _validated_remote_name(args.name or source.name)
    parent_id = str(args.parent_id or "1")
    _resolve_drive_folder(client, drive_id, parent_id, label="Upload destination")
    after = {
        "name": name,
        "type": "file",
        "parent_id": parent_id,
        "bytes": size,
        "conflict": "error",
    }
    plan = _drive_change_plan(profile, drive_id, before=None, after=after)

    if args.dry_run:
        payload = {**plan, "source": str(source), "dry_run": True, "uploaded": False}
        if _machine_output(args):
            print_machine(payload, args)
        else:
            _print_drive_change_preview(plan, "upload one file (remote overwrite refused)")
            print(f"Local source: {source} ({size} bytes)")
            print("Dry run: nothing was uploaded.")
        return 0

    _require_explicit_profile_for_yes(args, "upload")
    if not _machine_output(args):
        _print_drive_change_preview(plan, "upload one file (remote overwrite refused)")
        print(f"Local source: {source} ({size} bytes)")
    if not _confirm(args, "Upload this file? [y/N] ", action="drive upload"):
        print("Upload cancelled.")
        return 2

    uploaded = upload_file(client, drive_id, source.read_bytes(), name, parent_id=parent_id)
    file_id = uploaded.get("id")
    if file_id is None:
        raise ValueError("kDrive upload succeeded without a file id; cannot perform safe readback.")
    readback = slim_file(get_file(client, drive_id, str(file_id)), drive_id=drive_id)
    payload = {
        **plan,
        "source": str(source),
        "uploaded": True,
        "result": dict(uploaded),
        "readback": readback,
    }
    if _machine_output(args):
        print_machine(payload, args)
    else:
        print(f"Uploaded '{readback.get('name') or name}' (id {readback.get('id')}).")
    return 0


def cmd_drive_rename(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = str(args.file_id)
    item = get_file(client, drive_id, file_id)
    if file_id == "1" or str(item.get("visibility") or "").casefold() == "is_root":
        raise ValueError("Refusing to rename the kDrive root directory.")
    name = _validated_remote_name(args.name)
    before = slim_file(item, drive_id=drive_id)
    after = {**before, "name": name}
    plan = _drive_change_plan(profile, drive_id, before=before, after=after)
    if args.dry_run:
        payload = {**plan, "dry_run": True, "renamed": False}
        if _machine_output(args):
            print_machine(payload, args)
        else:
            _print_drive_change_preview(plan, "rename one exact item")
            print("Dry run: nothing was renamed.")
        return 0

    _require_explicit_profile_for_yes(args, "rename")
    if not _machine_output(args):
        _print_drive_change_preview(plan, "rename one exact item")
    if not _confirm(args, "Rename this item? [y/N] ", action="drive rename"):
        print("Rename cancelled.")
        return 2
    result = rename_file(client, drive_id, file_id, name)
    readback = slim_file(get_file(client, drive_id, file_id), drive_id=drive_id)
    payload = {**plan, "renamed": True, "result": dict(result), "readback": readback}
    if _machine_output(args):
        print_machine(payload, args)
    else:
        print(f"Renamed item {file_id} to '{readback.get('name')}'.")
    return 0


def cmd_drive_move(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = str(args.file_id)
    destination_id = str(args.destination_id)
    item = get_file(client, drive_id, file_id)
    if file_id == "1" or str(item.get("visibility") or "").casefold() == "is_root":
        raise ValueError("Refusing to move the kDrive root directory.")
    if file_id == destination_id:
        raise ValueError("An item cannot be moved into itself.")
    destination = _resolve_drive_folder(client, drive_id, destination_id, label="Move destination")
    before = slim_file(item, drive_id=drive_id)
    after = {**before, "parent_id": destination_id}
    plan = {
        **_drive_change_plan(profile, drive_id, before=before, after=after),
        "destination": slim_file(destination, drive_id=drive_id),
    }
    if args.dry_run:
        payload = {**plan, "dry_run": True, "moved": False}
        if _machine_output(args):
            print_machine(payload, args)
        else:
            _print_drive_change_preview(plan, "move one exact item (name conflict refused)")
            print("Dry run: nothing was moved.")
        return 0

    _require_explicit_profile_for_yes(args, "move")
    if not _machine_output(args):
        _print_drive_change_preview(plan, "move one exact item (name conflict refused)")
    if not _confirm(args, "Move this item? [y/N] ", action="drive move"):
        print("Move cancelled.")
        return 2
    result = move_file(client, drive_id, file_id, destination_id)
    readback = slim_file(get_file(client, drive_id, file_id), drive_id=drive_id)
    payload = {**plan, "moved": True, "result": dict(result), "readback": readback}
    if _machine_output(args):
        print_machine(payload, args)
    else:
        print(f"Moved item {file_id} into folder {destination_id}.")
    return 0


def cmd_drive_trash_list(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    items = list_trash(client, drive_id, limit=args.limit)
    output_items = slim_files(items, drive_id=drive_id)
    if _machine_output(args):
        print_machine({"profile": profile.name, "drive_id": drive_id, "count": len(items), "items": output_items}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Trash items: {len(items)}")
        for item in output_items:
            print(_display_drive_item(item))
    return 0


def cmd_drive_trash_show(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    item = slim_file(get_trashed_file(client, drive_id, str(args.file_id)), drive_id=drive_id)
    if _machine_output(args):
        print_machine({"profile": profile.name, "drive_id": drive_id, "item": item}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(_display_drive_item(item))
    return 0


def cmd_drive_trash_restore(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = str(args.file_id)
    item = get_trashed_file(client, drive_id, file_id)
    before = slim_file(item, drive_id=drive_id)
    destination_id = str(args.destination_id) if args.destination_id is not None else None
    destination = None
    if destination_id is not None:
        destination = _resolve_drive_folder(client, drive_id, destination_id, label="Restore destination")
    after = {**before}
    if destination_id is not None:
        after["parent_id"] = destination_id
    plan = _drive_change_plan(profile, drive_id, before=before, after=after)
    if destination is not None:
        plan["destination"] = slim_file(destination, drive_id=drive_id)
    if args.dry_run:
        payload = {**plan, "dry_run": True, "restored": False}
        if _machine_output(args):
            print_machine(payload, args)
        else:
            _print_drive_change_preview(plan, "restore one exact trashed item")
            print("Dry run: nothing was restored.")
        return 0

    _require_explicit_profile_for_yes(args, "restore")
    if not _machine_output(args):
        _print_drive_change_preview(plan, "restore one exact trashed item")
    if not _confirm(args, "Restore this item? [y/N] ", action="drive trash restore"):
        print("Restore cancelled.")
        return 2
    result = restore_file(client, drive_id, file_id, destination_id=destination_id)
    readback = slim_file(get_file(client, drive_id, file_id), drive_id=drive_id)
    payload = {**plan, "restored": True, "result": dict(result), "readback": readback}
    if _machine_output(args):
        print_machine(payload, args)
    else:
        print(f"Restored '{readback.get('name') or file_id}' (id {file_id}).")
    return 0


def cmd_drive_share_state(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    file_id = str(args.file_id)
    target = slim_file(get_file(client, drive_id, file_id), drive_id=drive_id)
    state = get_share_state(client, drive_id, file_id)
    payload = {
        "profile": profile.name,
        "drive_id": drive_id,
        "file_id": file_id,
        "target": target,
        "state": {key: dict(value) if value is not None else None for key, value in state.items()},
    }
    if _machine_output(args):
        print_machine(payload, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        print(f"Target: {target.get('name') or '-'} (id {file_id})")
        print_json(payload["state"])
    return 0


def cmd_contacts_list(args: argparse.Namespace) -> int:
    profile, client = _contacts_profile_and_client(args)
    contacts = client.list_contacts(limit=args.limit)

    if _machine_output(args):
        output_contacts = contacts if _raw_output(args) else slim_contacts(contacts)
        print_machine({"profile": profile.name, "count": len(contacts), "contacts": output_contacts}, args)
    elif getattr(args, "table", False):
        print(render_table(slim_contacts(contacts), [
            ("id", "ID"),
            ("display_name", "Name"),
            ("emails", "Email"),
            ("organization", "Organization"),
        ]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Contacts: {len(contacts)}")
        if not contacts:
            print("No contacts found.")
        for contact in contacts:
            print(_display_contact(contact))
    return 0


def cmd_contacts_search(args: argparse.Namespace) -> int:
    profile, client = _contacts_profile_and_client(args)
    contacts = search_contacts(client.list_contacts(), args.query, limit=args.limit)

    if _machine_output(args):
        output_contacts = contacts if _raw_output(args) else slim_contacts(contacts)
        print_machine(
            {
                "profile": profile.name,
                "query": args.query,
                "count": len(contacts),
                "contacts": output_contacts,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Query: {args.query}")
        print(f"Contacts: {len(contacts)}")
        if not contacts:
            print("No matching contacts found.")
        for contact in contacts:
            print(_display_contact(contact))
    return 0


def cmd_contacts_show(args: argparse.Namespace) -> int:
    profile, client = _contacts_profile_and_client(args)
    contact = find_contact(client.list_contacts(), args.contact_id)
    if contact is None:
        raise ValueError(f"Contact not found: {args.contact_id}")

    output_contact = contact if _raw_output(args) else slim_contact(contact)
    if _machine_output(args):
        print_machine({"profile": profile.name, "contact_id": args.contact_id, "contact": output_contact}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Contact ID: {args.contact_id}")
        print(f"Name: {output_contact.get('display_name') or 'unnamed'}")
        emails = output_contact.get("emails") or []
        if emails:
            print(f"Email: {emails[0]}")
        phones = output_contact.get("phones") or []
        if phones:
            print(f"Phone: {phones[0]}")
        organization = output_contact.get("organization")
        if organization:
            print(f"Organization: {organization}")
    return 0


def _contact_from_args(
    args: argparse.Namespace,
    *,
    uid: str,
    existing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = existing or {}
    display_name = getattr(args, "name", None)
    if display_name is None:
        display_name = current.get("display_name")
    if not str(display_name or "").strip():
        raise ValueError("Contact --name is required and cannot be empty.")

    def resolved(name: str, key: str) -> Any:
        value = getattr(args, name, None)
        return current.get(key) if value is None else value

    return {
        "id": uid,
        "display_name": str(display_name),
        "given_name": resolved("given_name", "given_name"),
        "family_name": resolved("family_name", "family_name"),
        "emails": resolved("emails", "emails") or [],
        "phones": resolved("phones", "phones") or [],
        "organization": resolved("organization", "organization"),
    }


def _contact_vcard(contact: Mapping[str, Any]) -> str:
    return build_vcard(
        uid=str(contact["id"]),
        display_name=str(contact["display_name"]),
        given_name=contact.get("given_name"),
        family_name=contact.get("family_name"),
        emails=list(contact.get("emails") or []),
        phones=list(contact.get("phones") or []),
        organization=contact.get("organization"),
    )


def _print_contact_write_preview(
    profile: Any,
    action: str,
    after: Mapping[str, Any],
    *,
    before: Mapping[str, Any] | None = None,
) -> None:
    print(f"Profile: {profile.name}")
    print(f"Address book: {profile.contacts_url}")
    print(f"Action: {action} one contact")
    if before is not None:
        print(f"Target: {before.get('display_name') or 'unnamed'} (id {before.get('id')})")
    print(f"Name: {after.get('display_name')}")
    if after.get("emails"):
        print(f"Email: {', '.join(after['emails'])}")
    if after.get("phones"):
        print(f"Phone: {', '.join(after['phones'])}")
    if after.get("organization"):
        print(f"Organization: {after['organization']}")


def cmd_contacts_create(args: argparse.Namespace) -> int:
    profile = _contacts_profile(args)
    uid = str(uuid.uuid4())
    contact = _contact_from_args(args, uid=uid)
    vcard = _contact_vcard(contact)
    plan = {
        "profile": profile.name,
        "addressbook": profile.contacts_url,
        "contact": slim_contact(contact),
    }

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "vcard": vcard, "dry_run": True, "created": False}, args)
        else:
            _print_contact_write_preview(profile, "create", contact)
            print("Dry run: no contact was created.")
        return 0

    client = _contacts_client(profile)
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            "Refusing to create a contact with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE)."
        )
    if not _machine_output(args):
        _print_contact_write_preview(profile, "create", contact)
    if not _confirm(args, "Create this contact? [y/N] ", action="contacts create"):
        print("Contact creation cancelled.")
        return 2

    result = client.create_contact(vcard, uid)
    if _machine_output(args):
        print_machine({**plan, "created": True, "result": result}, args)
    else:
        print(f"Created contact '{contact['display_name']}' (id {uid}).")
    return 0


def cmd_contacts_update(args: argparse.Namespace) -> int:
    profile, client = _contacts_profile_and_client(args)
    changed_fields = ("name", "given_name", "family_name", "emails", "phones", "organization")
    if not any(getattr(args, field, None) is not None for field in changed_fields):
        raise ValueError("Contact update requires at least one field option.")
    resolved_contact = find_contact(client.list_contacts(), args.contact_id)
    if resolved_contact is None:
        raise ValueError(f"Contact not found: {args.contact_id}")
    uid = str(resolved_contact.get("id") or args.contact_id)
    after = _contact_from_args(args, uid=uid, existing=resolved_contact)
    before = slim_contact(resolved_contact)
    after_slim = slim_contact(after)
    raw_vcard = resolved_contact.get("raw_vcard")
    if not isinstance(raw_vcard, str):
        raise ValueError("Resolved contact has no raw vCard; refusing an unsafe update.")
    names_changed = args.given_name is not None or args.family_name is not None
    vcard = merge_vcard(
        raw_vcard,
        uid=uid,
        display_name=after["display_name"] if args.name is not None else None,
        given_name=after.get("given_name") if names_changed else None,
        family_name=after.get("family_name") if names_changed else None,
        emails=list(after.get("emails") or []) if args.emails is not None else None,
        phones=list(after.get("phones") or []) if args.phones is not None else None,
        organization=after.get("organization") if args.organization is not None else None,
    )
    plan = {
        "profile": profile.name,
        "addressbook": profile.contacts_url,
        "contact_id": uid,
        "before": before,
        "after": after_slim,
    }

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "vcard": vcard, "dry_run": True, "updated": False}, args)
        else:
            _print_contact_write_preview(profile, "update", after, before=before)
            print("Dry run: no contact was updated.")
        return 0

    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            "Refusing to update a contact with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE)."
        )
    if not _machine_output(args):
        _print_contact_write_preview(profile, "update", after, before=before)
    if not _confirm(args, "Update this contact? [y/N] ", action="contacts update"):
        print("Contact update cancelled.")
        return 2

    result = client.update_contact(vcard, resolved_contact)
    if _machine_output(args):
        print_machine({**plan, "updated": True, "result": result}, args)
    else:
        print(f"Updated contact '{after['display_name']}' (id {uid}).")
    return 0


def cmd_calendar_list(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    calendars = client.list_calendars()

    if _machine_output(args):
        output_calendars = calendars if _raw_output(args) else slim_calendars(calendars)
        print_machine({"profile": profile.name, "count": len(calendars), "calendars": output_calendars}, args)
    elif getattr(args, "table", False):
        print(render_table(slim_calendars(calendars), [("id", "ID"), ("name", "Name"), ("url", "URL")]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Calendars: {len(calendars)}")
        if not calendars:
            print("No calendars found.")
        for calendar in calendars:
            print(_display_calendar(calendar))
    return 0


def cmd_calendar_upcoming(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    start = _now_utc()
    end = start + datetime.timedelta(days=args.days)
    events = client.list_events(calendar=args.calendar, start=start, end=end, limit=args.limit)

    if _machine_output(args):
        output_events = events if _raw_output(args) else slim_events(events)
        print_machine(
            {
                "profile": profile.name,
                "calendar": args.calendar,
                "days": args.days,
                "count": len(events),
                "events": output_events,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        if args.calendar:
            print(f"Calendar: {args.calendar}")
        print(f"Upcoming days: {args.days}")
        print(f"Events: {len(events)}")
        if not events:
            print("No events found.")
        for event in events:
            print(_display_event(event))
    return 0


def cmd_calendar_today(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    today = _today()
    start = datetime.datetime.combine(today, datetime.time.min, tzinfo=datetime.UTC)
    end = start + datetime.timedelta(days=1)
    events = client.list_events(calendar=args.calendar, start=start, end=end, limit=args.limit)

    if _machine_output(args):
        output_events = events if _raw_output(args) else slim_events(events)
        print_machine(
            {
                "profile": profile.name,
                "calendar": args.calendar,
                "date": today.isoformat(),
                "count": len(events),
                "events": output_events,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        if args.calendar:
            print(f"Calendar: {args.calendar}")
        print(f"Date: {today.isoformat()}")
        print(f"Events: {len(events)}")
        if not events:
            print("No events found.")
        for event in events:
            print(_display_event(event))
    return 0


def cmd_calendar_search(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)

    all_day = None
    if getattr(args, "all_day", False):
        all_day = True
    elif getattr(args, "timed", False):
        all_day = False
    filters = {
        "attendee": getattr(args, "attendee", None),
        "uid": getattr(args, "uid", None),
        "status": getattr(args, "status", None),
        "description": getattr(args, "description", None),
        "all_day": all_day,
    }
    if not args.query and all(value is None for value in filters.values()):
        raise ValueError(
            "calendar search needs a query or at least one filter "
            "(--attendee, --uid, --status, --description, --all-day/--timed)."
        )

    start, end, days = _calendar_range(args, default_days=30)
    events = search_events(
        client.list_events(calendar=args.calendar, start=start, end=end),
        args.query,
        limit=args.limit,
        **filters,
    )
    applied = {key: value for key, value in filters.items() if value is not None}

    if _machine_output(args):
        output_events = events if _raw_output(args) else slim_events(events)
        print_machine(
            {
                "profile": profile.name,
                "calendar": args.calendar,
                "query": args.query,
                "filters": applied,
                "days": days,
                "from": _iso_utc(start),
                "to": _iso_utc(end),
                "count": len(events),
                "events": output_events,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        if args.calendar:
            print(f"Calendar: {args.calendar}")
        if args.query:
            print(f"Query: {args.query}")
        for key, value in applied.items():
            print(f"Filter {key}: {value}")
        print(f"Range: {_iso_utc(start)} to {_iso_utc(end)}")
        print(f"Events: {len(events)}")
        if not events:
            print("No matching events found.")
        for event in events:
            print(_display_event(event))
    return 0


def cmd_calendar_export(args: argparse.Namespace) -> int:
    """Read-only export of a resolved date range, as ICS or JSON."""
    profile, client = _calendar_profile_and_client(args)
    start, end, days = _calendar_range(args, default_days=30)
    events = client.list_events(calendar=args.calendar, start=start, end=end)
    if args.limit is not None:
        events = events[: args.limit]

    skipped: list[str] = []
    if args.format == "ics":
        body, skipped = build_calendar_export_ics(events)
    else:
        body = pretty_json(events if _raw_output(args) else slim_events(events))

    destination = None
    if args.output:
        destination = Path(normalize_local_path(args.output))
        if destination.exists() and not args.force:
            raise ValueError(
                f"Refusing to overwrite an existing export file: {destination}. Pass --force to replace it."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(body, encoding="utf-8", newline="")

    summary = {
        "profile": profile.name,
        "calendar": args.calendar,
        "format": args.format,
        "days": days,
        "from": _iso_utc(start),
        "to": _iso_utc(end),
        "count": len(events) - len(skipped),
        "skipped": skipped,
        "output": str(destination) if destination else None,
    }

    if destination is None:
        if _machine_output(args):
            # Structured output stays structured: the export rides inside the
            # envelope rather than replacing it.
            print_machine({**summary, "body": body}, args)
            return 0
        # Otherwise the export itself is the payload on stdout.
        print(body, end="" if body.endswith("\n") else "\n")
        if skipped:
            print(
                f"note: {len(skipped)} event(s) had no parseable VEVENT and were skipped: "
                f"{', '.join(skipped)}",
                file=sys.stderr,
            )
        return 0

    if _machine_output(args):
        print_machine(summary, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Range: {summary['from']} to {summary['to']}")
        print(f"Exported {summary['count']} event(s) as {args.format} to {destination}")
        if skipped:
            print(f"Skipped {len(skipped)} event(s) with no parseable VEVENT: {', '.join(skipped)}")
    return 0


def cmd_calendar_show(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    event = find_event(client.list_events(calendar=args.calendar), args.event_id)
    if event is None:
        raise ValueError(f"Calendar event not found: {args.event_id}")

    output_event = event if _raw_output(args) else slim_event(event)
    if _machine_output(args):
        print_machine({"profile": profile.name, "calendar": args.calendar, "event_id": args.event_id, "event": output_event}, args)
    else:
        print(f"Profile: {profile.name}")
        if args.calendar:
            print(f"Calendar: {args.calendar}")
        print(f"Event ID: {args.event_id}")
        print(f"Summary: {output_event.get('summary') or '(no summary)'}")
        starts_at = output_event.get("starts_at")
        if starts_at:
            print(f"Starts: {starts_at}")
        ends_at = output_event.get("ends_at")
        if ends_at:
            print(f"Ends: {ends_at}")
        location = output_event.get("location")
        if location:
            print(f"Location: {location}")
    return 0


def _print_calendar_create_preview(profile: Any, target: str, plan: Mapping[str, Any]) -> None:
    print(f"Profile: {profile.name}")
    print(f"Calendar: {target}")
    print(f"Summary: {plan['summary']}")
    print(f"Start: {plan['start']}" + ("  (all day)" if plan["all_day"] else ""))
    print(f"End: {plan['end']}")
    if plan.get("location"):
        print(f"Location: {plan['location']}")
    if plan.get("description"):
        print(f"Description: {plan['description']}")
    if plan.get("reminders"):
        minutes = ", ".join(f"{value} min before" for value in plan["reminders"])
        print(f"Reminders: {minutes}")
    print(f"UID: {plan['uid']}" + ("  (caller-supplied)" if plan.get("uid_explicit") else ""))
    if plan.get("if_missing"):
        print("Mode: --if-missing (an existing event with this UID is left untouched)")
    print("(No attendees are invited; this only writes to your own calendar.)")


def _validated_event_uid(value: str) -> str:
    """Validate a caller-supplied UID; it becomes a CalDAV URL path segment."""
    clean = value.strip()
    if not clean:
        raise ValueError("--uid must not be empty.")
    if any(char in clean for char in ("\r", "\n")):
        raise ValueError("--uid must not contain line breaks.")
    if "/" in clean or "\\" in clean:
        raise ValueError("--uid must not contain a path separator.")
    if len(clean) > 255:
        raise ValueError("--uid must be 255 characters or fewer.")
    return clean


def cmd_calendar_create(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)

    summary = args.summary
    if not summary.strip():
        raise ValueError("Refusing to create an event with an empty --summary.")

    all_day = getattr(args, "all_day", False)
    start = parse_event_input(args.start, all_day=all_day)
    if args.end:
        end = parse_event_input(args.end, all_day=all_day)
    elif all_day:
        end = start + datetime.timedelta(days=1)
    else:
        end = start + datetime.timedelta(hours=1)

    if end <= start:
        raise ValueError(f"--end ({args.end or end}) must be after --start ({args.start}).")

    if_missing = getattr(args, "if_missing", False)
    explicit_uid = getattr(args, "uid", None)
    if if_missing and explicit_uid is None:
        raise ValueError(
            "--if-missing needs a deterministic --uid. Without one, every run generates a new "
            "UID and can never match an existing event."
        )
    # `is not None`, not truthiness: an explicitly empty --uid must be rejected,
    # never silently replaced by a random one.
    uid = (
        _validated_event_uid(explicit_uid)
        if explicit_uid is not None
        else f"{uuid.uuid4()}@infomaniak-cli"
    )

    reminders = list(getattr(args, "reminder_minutes", None) or [])
    dtstamp = datetime.datetime.now(datetime.UTC)
    ics = build_event_ics(
        uid=uid,
        dtstamp=dtstamp,
        summary=summary,
        start=start,
        end=end,
        all_day=all_day,
        description=args.description,
        location=args.location,
        reminders=reminders,
    )

    target = args.calendar or profile.calendar_url
    plan = {
        "profile": profile.name,
        "calendar": target,
        "summary": summary,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "all_day": all_day,
        "location": args.location,
        "description": args.description,
        "uid": uid,
        "uid_explicit": bool(explicit_uid),
        "reminders": reminders,
        "if_missing": if_missing,
    }

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "ics": ics, "dry_run": True, "created": False}, args)
        else:
            _print_calendar_create_preview(profile, target, plan)
            print("Dry run: no event was created. iCalendar body:")
            print(ics.rstrip())
        return 0

    # Automation must target an explicit profile before writing unattended.
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            "Refusing to create with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE) so automation cannot write to the wrong account."
        )

    if not _machine_output(args):
        _print_calendar_create_preview(profile, target, plan)

    if not _confirm(args, "Create this event? [y/N] ", action="calendar create"):
        print("Event creation cancelled.")
        return 2

    try:
        result = client.create_event(ics, uid, calendar=args.calendar)
    except CalendarConflictError:
        if not if_missing:
            raise
        # --if-missing: an event with this UID already exists, so the desired
        # state is already in place. Report a no-op rather than an error.
        if _machine_output(args):
            print_machine({**plan, "created": False, "existed": True}, args)
        else:
            print(f"Event with uid {uid} already exists; nothing was created.")
        return 0

    if _machine_output(args):
        print_machine({**plan, "created": True, "existed": False, "event": result}, args)
    else:
        print(f"Created event '{summary}' (uid {uid}).")
        print(f"Location: {result.get('url')}")
    return 0


def _resolved_calendar_write_event(args: argparse.Namespace, client: CalendarClient) -> Mapping[str, Any]:
    event = find_event(client.list_events(calendar=args.calendar), args.event_id)
    if event is None:
        raise ValueError(f"Calendar event not found: {args.event_id}")
    missing = [name for name in ("url", "etag", "raw_ics") if not event.get(name)]
    if missing:
        raise ValueError(
            "Calendar event cannot be changed safely because its CalDAV "
            f"{', '.join(missing)} metadata is missing. Re-run against the exact calendar collection."
        )
    if event.get("attendees"):
        raise ValueError(
            "Refusing to change an event with attendees: Infomaniak RSVP/invite notification "
            "effects have not been verified. Attendee and invite mutations remain disabled."
        )
    return event


def _calendar_lifecycle_plan(
    profile: Any,
    args: argparse.Namespace,
    event: Mapping[str, Any],
    *,
    action: str,
    mode: str,
    after: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "action": action,
        "mode": mode,
        "profile": profile.name,
        "calendar": args.calendar or profile.calendar_url,
        "event_id": args.event_id,
        "resource_url": event.get("url"),
        "etag": event.get("etag"),
        "before": slim_event(event),
        "after": slim_event(after) if after is not None else None,
        "attendees": list(event.get("attendees") or []),
        "notification_effects": (
            "No attendee notifications are expected: attendee-bearing events are refused until "
            "the Infomaniak scheduling contract is verified."
        ),
    }


def _print_calendar_lifecycle_preview(plan: Mapping[str, Any]) -> None:
    before = plan["before"]
    after = plan.get("after")
    print(f"Profile: {plan['profile']}")
    print(f"Calendar: {plan['calendar']}")
    print(f"Event: {before.get('summary') or '(no summary)'} ({plan['event_id']})")
    print(f"Mode: {plan['mode']}")
    if after is not None:
        print(f"Before: {before.get('starts_at')} -> {before.get('ends_at')} [{before.get('status') or 'no status'}]")
        print(f"After:  {after.get('starts_at')} -> {after.get('ends_at')} [{after.get('status') or 'no status'}]")
    else:
        print("After: resource absent (hard deletion is not recoverable through this command).")
    print(plan["notification_effects"])


def _calendar_write_gate(args: argparse.Namespace, *, verb: str) -> None:
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            f"Refusing to {verb} with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE) so automation cannot write to the wrong account."
        )


def _existing_event_boundary(event: Mapping[str, Any], name: str) -> datetime.date:
    value = event.get(name)
    if not value:
        raise ValueError(f"Calendar event has no {name} value and cannot be updated safely.")
    return parse_event_input(str(value), all_day=bool(event.get("all_day")))


def cmd_calendar_update(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    event = _resolved_calendar_write_event(args, client)
    if not any(
        value is not None
        for value in (args.summary, args.start, args.end, args.location, args.description, args.reminder_minutes)
    ) and not (args.clear_location or args.clear_description):
        raise ValueError("Calendar update requires at least one field change.")
    if args.summary is not None and not args.summary.strip():
        raise ValueError("Refusing to update an event with an empty --summary.")
    if args.location is not None and args.clear_location:
        raise ValueError("--location cannot be combined with --clear-location.")
    if args.description is not None and args.clear_description:
        raise ValueError("--description cannot be combined with --clear-description.")

    all_day = bool(event.get("all_day"))
    start = parse_event_input(args.start, all_day=all_day) if args.start else None
    end = parse_event_input(args.end, all_day=all_day) if args.end else None
    effective_start = start or _existing_event_boundary(event, "starts_at")
    effective_end = end or _existing_event_boundary(event, "ends_at")
    if effective_end <= effective_start:
        raise ValueError("Updated event end must be after its start.")

    ics = patch_event_ics(
        str(event["raw_ics"]),
        summary=args.summary,
        start=start,
        end=end,
        all_day=all_day,
        location=args.location,
        description=args.description,
        clear_location=args.clear_location,
        clear_description=args.clear_description,
        reminder_minutes=args.reminder_minutes,
        dtstamp=_now_utc(),
    )
    after = parse_ics_events(ics, calendar_id=event.get("calendar_id"), fallback_id=str(event.get("id")))[0]
    plan = _calendar_lifecycle_plan(
        profile, args, event, action="calendar.update", mode="conditional-update", after=after
    )
    if args.dry_run:
        if _machine_output(args):
            print_machine({**plan, "ics": ics, "dry_run": True, "updated": False}, args)
        else:
            _print_calendar_lifecycle_preview(plan)
            print("Dry run: no event was updated.")
        return 0

    _calendar_write_gate(args, verb="update")
    if not _machine_output(args):
        _print_calendar_lifecycle_preview(plan)
    if not _confirm(args, "Update this exact event? [y/N] ", action="calendar update"):
        print("Event update cancelled.")
        return 2
    result = client.update_event(str(event["url"]), ics, str(event["etag"]))
    readback = find_event(client.list_events(calendar=args.calendar), str(event.get("uid") or args.event_id))
    if readback is None:
        raise ValueError("Calendar update completed but readback could not find the event.")
    if _machine_output(args):
        print_machine({**plan, "updated": True, "result": result, "readback": slim_event(readback)}, args)
    else:
        print(f"Updated event '{after.get('summary') or '(no summary)'}'.")
    return 0


def cmd_calendar_cancel(args: argparse.Namespace) -> int:
    profile, client = _calendar_profile_and_client(args)
    event = _resolved_calendar_write_event(args, client)
    ics = patch_event_ics(str(event["raw_ics"]), status="CANCELLED", dtstamp=_now_utc())
    after = parse_ics_events(ics, calendar_id=event.get("calendar_id"), fallback_id=str(event.get("id")))[0]
    plan = _calendar_lifecycle_plan(
        profile, args, event, action="calendar.cancel", mode="soft-cancel", after=after
    )
    if args.dry_run:
        if _machine_output(args):
            print_machine({**plan, "ics": ics, "dry_run": True, "cancelled": False}, args)
        else:
            _print_calendar_lifecycle_preview(plan)
            print("Dry run: the event remains active.")
        return 0
    _calendar_write_gate(args, verb="cancel")
    if not _machine_output(args):
        _print_calendar_lifecycle_preview(plan)
    if not _confirm(args, "Soft-cancel this exact event? [y/N] ", action="calendar cancel"):
        print("Event cancellation cancelled.")
        return 2
    result = client.update_event(str(event["url"]), ics, str(event["etag"]))
    readback = find_event(client.list_events(calendar=args.calendar), str(event.get("uid") or args.event_id))
    if readback is None:
        raise ValueError("Calendar cancellation completed but readback could not find the event.")
    if _machine_output(args):
        print_machine({**plan, "cancelled": True, "result": result, "readback": slim_event(readback)}, args)
    else:
        print(f"Soft-cancelled event '{event.get('summary') or '(no summary)'}'.")
    return 0


def cmd_calendar_delete(args: argparse.Namespace) -> int:
    if not args.hard:
        raise ValueError(
            "Calendar delete is a hard resource deletion. Pass --hard to acknowledge it, "
            "or use `ik calendar cancel` for a reversible soft cancellation."
        )
    profile, client = _calendar_profile_and_client(args)
    event = _resolved_calendar_write_event(args, client)
    plan = _calendar_lifecycle_plan(
        profile, args, event, action="calendar.delete", mode="hard-delete", after=None
    )
    if args.dry_run:
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "deleted": False}, args)
        else:
            _print_calendar_lifecycle_preview(plan)
            print("Dry run: the event resource was not deleted.")
        return 0
    _calendar_write_gate(args, verb="hard-delete")
    if not _machine_output(args):
        _print_calendar_lifecycle_preview(plan)
    if not _confirm(args, "Hard-delete this exact event? [y/N] ", action="calendar delete"):
        print("Event deletion cancelled.")
        return 2
    result = client.delete_event(str(event["url"]), str(event["etag"]))
    readback_deleted = find_event(
        client.list_events(calendar=args.calendar), str(event.get("uid") or args.event_id)
    ) is None
    if not readback_deleted:
        raise ValueError("Calendar delete returned success but readback still found the event.")
    if _machine_output(args):
        print_machine({**plan, "deleted": True, "result": result, "readback_deleted": True}, args)
    else:
        print(f"Hard-deleted event '{event.get('summary') or '(no summary)'}'.")
    return 0


def cmd_chat_teams(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    teams = client.list_teams()

    if _machine_output(args):
        output_teams = teams if _raw_output(args) else slim_teams(teams)
        print_machine({"profile": profile.name, "count": len(teams), "teams": output_teams}, args)
    else:
        print(f"Profile: {profile.name}")
        print(f"Teams: {len(teams)}")
        if not teams:
            print("No teams found.")
        for team in teams:
            print(_display_chat_team(team))
    return 0


def cmd_chat_channels(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    team_id = _chat_team_id_or_error(args, profile, client)
    channels = client.list_channels(team_id, limit=args.limit)

    if _machine_output(args):
        output_channels = channels if _raw_output(args) else slim_channels(channels)
        print_machine({"profile": profile.name, "team_id": team_id, "count": len(channels), "channels": output_channels}, args)
    elif getattr(args, "table", False):
        print(render_table(slim_channels(channels), [
            ("id", "ID"),
            ("type", "Type"),
            ("name", "Name"),
            ("display_name", "Display Name"),
        ]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Team ID: {team_id}")
        print(f"Channels: {len(channels)}")
        if not channels:
            print("No channels found.")
        for channel in channels:
            print(_display_chat_channel(channel))
    return 0


def cmd_chat_users(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    team_id = _chat_team_id_or_error(args, profile, client)
    users = client.list_users(team_id, limit=args.limit)

    if _machine_output(args):
        output_users = users if _raw_output(args) else slim_users(users)
        print_machine({"profile": profile.name, "team_id": team_id, "count": len(users), "users": output_users}, args)
    elif getattr(args, "table", False):
        print(render_table(slim_users(users), [
            ("id", "ID"),
            ("username", "Username"),
            ("first_name", "First"),
            ("last_name", "Last"),
            ("email", "Email"),
        ]))
    else:
        print(f"Profile: {profile.name}")
        print(f"Team ID: {team_id}")
        print(f"Users: {len(users)}")
        if not users:
            print("No users found.")
        for user in users:
            print(_display_chat_user(user))
    return 0


def cmd_chat_search(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    team_id = _chat_team_id_or_error(args, profile, client)

    channel_id = None
    channel_name = None
    channel_slug = getattr(args, "channel", None)
    if channel_slug:
        channel = client.resolve_channel(team_id, channel_slug)
        channel_id = channel.get("id")
        channel_name = channel.get("name")

    query = args.query.strip()
    if not query:
        query = "*"

    limit = getattr(args, "limit", None)
    posts = client.search_posts(
        team_id,
        query,
        is_or_search=bool(getattr(args, "or_search", False)),
        limit=limit,
    )
    if channel_id is not None:
        filtered = [post for post in posts if post.get("channel_id") == channel_id]
        if not filtered and posts:
            found_channels = {post.get("channel_id") for post in posts}
            print(f"warning: global search found {len(posts)} posts, but none had channel_id {channel_id}.", file=sys.stderr)
            print(f"Posts found belonged to these channel IDs: {found_channels}", file=sys.stderr)
        posts = filtered
        if limit is not None:
            posts = posts[:limit]

    if _machine_output(args):
        output_posts = posts if _raw_output(args) else slim_posts(posts)
        print_machine(
            {
                "profile": profile.name,
                "team_id": team_id,
                "query": args.query,
                "count": len(posts),
                "posts": output_posts,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Team ID: {team_id}")
        if channel_slug:
            print(f"Channel: {channel_slug}")
        print(f"Query: {args.query}")
        print(f"Posts: {len(posts)}")
        if not posts:
            print("No posts found.")
        for post in posts:
            print(_display_chat_post(post))
    return 0


def cmd_chat_thread(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    posts = client.get_thread(args.post_id)

    if _machine_output(args):
        output_posts = posts if _raw_output(args) else slim_posts(posts)
        print_machine(
            {
                "profile": profile.name,
                "post_id": args.post_id,
                "count": len(posts),
                "posts": output_posts,
            },
            args,
        )
    else:
        print(f"Profile: {profile.name}")
        print(f"Post ID: {args.post_id}")
        print(f"Posts: {len(posts)}")
        if not posts:
            print("No posts found.")
        for post in posts:
            print(_display_chat_post(post))
    return 0


def _profile_is_explicit(args: argparse.Namespace) -> bool:
    """True when the profile was chosen deliberately, not via the ambient default.

    A deliberate choice is the `--profile` flag or the `IK_PROFILE` env var. This
    gates `--yes` on writes so automation can never post to the wrong account by
    silently inheriting the saved current profile.
    """
    return bool(getattr(args, "profile", None) or os.environ.get("IK_PROFILE"))


def _print_chat_post_preview(profile: Any, team_id: str, channel: Mapping[str, Any], message: str) -> None:
    channel_label = channel.get("display_name") or channel.get("name") or "-"
    print(f"Profile: {profile.name}")
    print(f"Team ID: {team_id}")
    print(f"Channel: {channel_label} (id {channel.get('id')})")
    print("Message:")
    for line in message.splitlines() or [""]:
        print(f"  {line}")


def cmd_chat_post(args: argparse.Namespace) -> int:
    profile, client = _chat_profile_and_client(args)
    team_id = _chat_team_id_or_error(args, profile, client)
    channel = client.resolve_channel(team_id, args.channel)
    channel_id = channel.get("id")
    if not channel_id:
        raise ValueError(f"Resolved kChat channel has no id: {args.channel}. Run `ik chat channels`.")

    message = args.message
    if not message.strip():
        raise ValueError("Refusing to post an empty message.")

    plan = {
        "profile": profile.name,
        "team_id": team_id,
        "channel_id": str(channel_id),
        "channel_name": channel.get("name"),
        "channel_display_name": channel.get("display_name"),
        "message": message,
    }

    if getattr(args, "dry_run", False):
        if _machine_output(args):
            print_machine({**plan, "dry_run": True, "posted": False}, args)
        else:
            _print_chat_post_preview(profile, team_id, channel, message)
            print("Dry run: no message was posted.")
        return 0

    # Automation must target an explicit profile before it can post unattended.
    if getattr(args, "yes", False) and not _profile_is_explicit(args):
        raise ValueError(
            "Refusing to post with --yes unless the profile is explicit. "
            "Pass --profile <name> (or set IK_PROFILE) so automation cannot post to the wrong account."
        )

    if not _machine_output(args):
        _print_chat_post_preview(profile, team_id, channel, message)

    if not _confirm(args, "Post this message? [y/N] ", action="chat post"):
        print("Post cancelled.")
        return 2

    post = client.create_post(str(channel_id), message)

    if _machine_output(args):
        output_post = post if _raw_output(args) else slim_post(post)
        print_machine({**plan, "posted": True, "post": output_post}, args)
    else:
        channel_label = channel.get("display_name") or channel.get("name") or channel_id
        print(f"Posted to {channel_label} (message id {post.get('id')}).")
    return 0


def cmd_debug_probe(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    result = probe_profile(profile.name, profile.account_id, client)
    if args.json:
        print_json(result)
    else:
        print(f"Profile: {result['profile']}")
        print(f"Account ID: {result['account_id'] or 'not selected'}")
        for note in result["notes"]:
            print(f"Note: {note}")
        for item in result["results"]:
            params = f" params={item['params']}" if item.get("params") else ""
            print(f"{item['group']}\t{item['status_code']}\t{item['path']}{params}\t{item['shape']}")
    return 0


def cmd_completion(args: argparse.Namespace) -> int:
    parser = build_parser()
    if args.shell == "bash":
        print(generate_bash(parser))
    elif args.shell == "zsh":
        print(generate_zsh(parser))
    elif args.shell == "fish":
        print(generate_fish(parser))
    elif args.shell == "powershell":
        print(generate_powershell(parser))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ik", description="Informaniak/kSuite CLI bridge")
    parser.add_argument("--profile", help="Profile to use for this command")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Informaniak API base URL. Defaults to {DEFAULT_BASE_URL}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Create/update a ready-to-configure profile")
    setup.add_argument(
        "--profile",
        required=False,
        default=argparse.SUPPRESS,
        help="Profile name to create/update",
    )
    setup.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting")
    setup.set_defaults(func=cmd_setup)

    whoami = sub.add_parser("whoami", help="Show active profile/account defaults")
    whoami.add_argument("--json", action="store_true")
    whoami.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    whoami.set_defaults(func=cmd_whoami)

    doctor = sub.add_parser("doctor", help="Run local configuration diagnostics")
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    doctor.add_argument(
        "--fix-path",
        action="store_true",
        help="Preview the per-user PATH fix when ik is not on PATH (apply is deferred; prints the manual command).",
    )
    doctor.set_defaults(func=cmd_doctor)

    bootstrap = sub.add_parser("bootstrap", help="Discover account/service IDs for a profile")
    bootstrap.add_argument("--account-id", help="Account ID to select when multiple accounts are available")
    bootstrap.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting")
    bootstrap.add_argument("--json", action="store_true")
    bootstrap.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    bootstrap.set_defaults(func=cmd_bootstrap)

    account = sub.add_parser("account", help="Discover accessible accounts, products, and services")
    account_sub = account.add_subparsers(dest="account_command", required=True)
    account_list = account_sub.add_parser("list", help="List accessible accounts")
    account_list.add_argument("--json", action="store_true")
    account_list.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    account_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw account payload.")
    account_list.set_defaults(func=cmd_account_list)
    account_products = account_sub.add_parser(
        "products", help="List lower-level product catalog data (diagnostic)"
    )
    account_products.add_argument("--account-id", help="Account ID. Defaults to the selected profile account.")
    account_products.add_argument("--json", action="store_true")
    account_products.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    account_products.add_argument("--raw", action="store_true", help="With --json, emit the full raw product payload.")
    account_products.set_defaults(func=cmd_account_products)
    account_services = account_sub.add_parser(
        "services", help="List workflow-facing services and actionable next commands"
    )
    account_services.add_argument("--account-id", help="Account ID. Defaults to the selected profile account.")
    account_services.add_argument("--json", action="store_true")
    account_services.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    account_services.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    account_services.add_argument("--raw", action="store_true", help="With --json, emit the full raw service payload.")
    account_services.set_defaults(func=cmd_account_services)

    drive = sub.add_parser("drive", help="Use kDrive as the selected profile")
    drive_sub = drive.add_subparsers(dest="drive_command", required=True)
    drive_list = drive_sub.add_parser("list", help="List kDrive files and folders")
    drive_list.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_list.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to list.")
    drive_list.add_argument("--limit", type=int, help="Maximum number of files to request.")
    drive_list.add_argument("--json", action="store_true")
    drive_list.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_list.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    drive_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_list.set_defaults(func=cmd_drive_list)
    drive_folders = drive_sub.add_parser("folders", help="List kDrive folders")
    drive_folders.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_folders.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to list.")
    drive_folders.add_argument("--limit", type=int, help="Maximum number of items to request from the files endpoint.")
    drive_folders.add_argument("--json", action="store_true")
    drive_folders.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_folders.add_argument("--raw", action="store_true", help="With --json, emit the full raw folder payload.")
    drive_folders.set_defaults(func=cmd_drive_folders)

    drive_mkdir = drive_sub.add_parser("mkdir", help="Create a new folder in kDrive")
    drive_mkdir.add_argument("name", help="Name of the new folder")
    drive_mkdir.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_mkdir.add_argument("--parent", "--path", dest="parent_id", help="Parent ID where the folder will be created. Defaults to root.")
    drive_mkdir.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    drive_mkdir.add_argument("--json", action="store_true")
    drive_mkdir.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_mkdir.add_argument("--raw", action="store_true", help="With --json, emit the full raw folder payload.")
    drive_mkdir.set_defaults(func=cmd_drive_mkdir)

    drive_tree = drive_sub.add_parser("tree", help="Show a shallow read-only kDrive folder tree")
    drive_tree.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_tree.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to start from.")
    drive_tree.add_argument("--depth", type=int, default=2, help="Folder depth to fetch. Defaults to 2.")
    drive_tree.add_argument("--limit", type=int, help="Maximum number of items to request per folder.")
    drive_tree.add_argument("--json", action="store_true")
    drive_tree.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_tree.add_argument("--raw", action="store_true", help="With --json, emit the full raw folder payload.")
    drive_tree.set_defaults(func=cmd_drive_tree)
    drive_recent = drive_sub.add_parser("recent", help="List recently changed kDrive files and folders")
    drive_recent.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_recent.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to list.")
    drive_recent.add_argument("--limit", type=int, help="Maximum number of recent files to show after sorting.")
    drive_recent.add_argument("--json", action="store_true")
    drive_recent.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_recent.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    drive_recent.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_recent.set_defaults(func=cmd_drive_recent)
    drive_shared = drive_sub.add_parser("shared", help="List shared/public/link-visible kDrive files")
    drive_shared.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_shared.add_argument("--limit", type=int, help="Maximum number of shared files to show after filtering.")
    drive_shared.add_argument("--json", action="store_true")
    drive_shared.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_shared.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    drive_shared.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_shared.set_defaults(func=cmd_drive_shared)
    drive_search = drive_sub.add_parser("search", help="Search kDrive files and folders by name")
    drive_search.add_argument("query", help="Case-insensitive file/folder name query.")
    drive_search.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_search.add_argument("--limit", type=int, help="Maximum number of matching files to show.")
    drive_search.add_argument("--json", action="store_true")
    drive_search.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_search.set_defaults(func=cmd_drive_search)
    drive_info = drive_sub.add_parser("info", help="Show read-only metadata for a kDrive file or folder")
    drive_info.add_argument("file_id", help="File/folder ID.")
    drive_info.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_info.add_argument("--json", action="store_true")
    drive_info.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_info.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_info.set_defaults(func=cmd_drive_info)

    drive_download = drive_sub.add_parser("download", help="Download a kDrive file to a local path")
    drive_download.add_argument("file_id", help="File ID to download (see `ik drive list`/`ik drive search`).")
    drive_download.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_download.add_argument(
        "--output", "-o",
        help="Destination file or directory. Defaults to the file's name in the current directory.",
    )
    drive_download.add_argument(
        "--force", action="store_true",
        help="Overwrite the local destination if it already exists (local overwrite only).",
    )
    drive_download.add_argument("--json", action="store_true")
    drive_download.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_download.set_defaults(func=cmd_drive_download)

    drive_upload = drive_sub.add_parser("upload", help="Upload one local file without remote overwrite")
    drive_upload.add_argument("path", help="Local file path (Windows, MSYS /c/..., or Unix form).")
    drive_upload.add_argument("--name", help="Remote file name. Defaults to the local base name.")
    drive_upload.add_argument("--parent", dest="parent_id", help="Destination folder ID. Defaults to root.")
    drive_upload.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_upload.add_argument("--dry-run", action="store_true", help="Resolve and preview without uploading.")
    drive_upload.add_argument("--yes", "-y", action="store_true", help="Skip confirmation (requires an explicit profile).")
    drive_upload.add_argument("--json", action="store_true")
    drive_upload.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_upload.set_defaults(func=cmd_drive_upload)

    drive_rename = drive_sub.add_parser("rename", help="Rename one exact kDrive item (protected write)")
    drive_rename.add_argument("file_id", help="Single file/folder ID to rename.")
    drive_rename.add_argument("name", help="New name (not a path).")
    drive_rename.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_rename.add_argument("--dry-run", action="store_true", help="Resolve and preview without renaming.")
    drive_rename.add_argument("--yes", "-y", action="store_true", help="Skip confirmation (requires an explicit profile).")
    drive_rename.add_argument("--json", action="store_true")
    drive_rename.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_rename.set_defaults(func=cmd_drive_rename)

    drive_move = drive_sub.add_parser("move", help="Move one exact kDrive item (protected write)")
    drive_move.add_argument("file_id", help="Single file/folder ID to move.")
    drive_move.add_argument("destination_id", help="Exact destination folder ID.")
    drive_move.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_move.add_argument("--dry-run", action="store_true", help="Resolve and preview without moving.")
    drive_move.add_argument("--yes", "-y", action="store_true", help="Skip confirmation (requires an explicit profile).")
    drive_move.add_argument("--json", action="store_true")
    drive_move.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_move.set_defaults(func=cmd_drive_move)

    drive_trash = drive_sub.add_parser("trash", help="List, inspect, or restore kDrive trash")
    drive_trash_sub = drive_trash.add_subparsers(dest="drive_trash_command", required=True)
    drive_trash_list = drive_trash_sub.add_parser("list", help="List trashed files and folders (read-only)")
    drive_trash_list.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_trash_list.add_argument("--limit", type=int, help="Maximum number of trash items to request.")
    drive_trash_list.add_argument("--json", action="store_true")
    drive_trash_list.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_trash_list.set_defaults(func=cmd_drive_trash_list)
    drive_trash_show = drive_trash_sub.add_parser("show", help="Show one trashed item (read-only)")
    drive_trash_show.add_argument("file_id", help="Exact trashed file/folder ID.")
    drive_trash_show.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_trash_show.add_argument("--json", action="store_true")
    drive_trash_show.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_trash_show.set_defaults(func=cmd_drive_trash_show)
    drive_trash_restore = drive_trash_sub.add_parser("restore", help="Restore one exact trashed item (protected write)")
    drive_trash_restore.add_argument("file_id", help="Exact trashed file/folder ID.")
    drive_trash_restore.add_argument("--destination", dest="destination_id", help="Optional exact destination folder ID.")
    drive_trash_restore.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_trash_restore.add_argument("--dry-run", action="store_true", help="Resolve and preview without restoring.")
    drive_trash_restore.add_argument("--yes", "-y", action="store_true", help="Skip confirmation (requires an explicit profile).")
    drive_trash_restore.add_argument("--json", action="store_true")
    drive_trash_restore.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_trash_restore.set_defaults(func=cmd_drive_trash_restore)

    drive_share_state = drive_sub.add_parser("share-state", help="Read public-link and access state for one item")
    drive_share_state.add_argument("file_id", help="Exact file/folder ID.")
    drive_share_state.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_share_state.add_argument("--json", action="store_true")
    drive_share_state.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_share_state.set_defaults(func=cmd_drive_share_state)

    drive_rm = drive_sub.add_parser("rm", help="Move one kDrive file or folder to trash (protected write)")
    drive_rm.add_argument("file_id", help="Single file/folder ID to move to trash.")
    drive_rm.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_rm.add_argument("--dry-run", action="store_true", help="Resolve and preview the target without deleting it.")
    drive_rm.add_argument("--yes", "-y", action="store_true", help="Skip confirmation (requires an explicit profile).")
    drive_rm.add_argument("--json", action="store_true")
    drive_rm.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    drive_rm.set_defaults(func=cmd_drive_rm)

    debug = sub.add_parser("debug", help="Advanced read-only diagnostics")
    debug_sub = debug.add_subparsers(dest="debug_command", required=True)
    debug_probe = debug_sub.add_parser("probe", help="Probe candidate read-only API endpoints")
    debug_probe.add_argument("--json", action="store_true")
    debug_probe.set_defaults(func=cmd_debug_probe)

    version = sub.add_parser("version", help="Show CLI version")
    version.set_defaults(func=cmd_version)
    update = sub.add_parser("update", help="Check GitHub releases and update this CLI")
    update.add_argument("--yes", action="store_true", help="Update without prompting when auto-update is safe.")
    update.add_argument("--check", action="store_true", help="Only check update status; never install.")
    update.add_argument("--json", action="store_true", help="Emit machine-readable update status.")
    update.add_argument("--dry-run", action="store_true", help="Show the updater command without running it.")
    update.add_argument("--force", action="store_true", help="Force a full reinstall (reinstalls dependencies too).")
    update.add_argument("--verbose", "-v", action="store_true", help="Show the full installer log even on success.")
    update.set_defaults(func=cmd_update)

    profile = sub.add_parser("profile", help="Manage profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_show = profile_sub.add_parser("show")
    profile_show.add_argument("name", nargs="?")
    profile_show.add_argument("--json", action="store_true")
    profile_show.set_defaults(func=cmd_profile_show)
    profile_use = profile_sub.add_parser("use")
    profile_use.add_argument("name")
    profile_use.set_defaults(func=cmd_profile_use)
    profile_rename = profile_sub.add_parser("rename", help="Rename a local profile")
    profile_rename.add_argument("old")
    profile_rename.add_argument("new")
    profile_rename.add_argument("--json", action="store_true")
    profile_rename.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    profile_rename.set_defaults(func=cmd_profile_rename)
    profile_delete = profile_sub.add_parser("delete", help="Delete a local profile and its local secrets")
    profile_delete.add_argument("name")
    profile_delete.add_argument("--yes", action="store_true", help="Delete without prompting.")
    profile_delete.add_argument("--json", action="store_true")
    profile_delete.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    profile_delete.set_defaults(func=cmd_profile_delete)

    completion = sub.add_parser("completion", help="Generate static shell completion scripts")
    completion.add_argument("shell", choices=["bash", "zsh", "fish", "powershell"], help="The shell to generate completion for.")
    completion.set_defaults(func=cmd_completion)

    auth = sub.add_parser("auth", help="Manage per-profile auth material")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_status = auth_sub.add_parser("status")
    auth_status.add_argument("--json", action="store_true")
    auth_status.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    auth_status.set_defaults(func=cmd_auth_status)
    auth_logout = auth_sub.add_parser("logout", help="Remove saved local auth for the selected profile")
    auth_logout.add_argument("--all", action="store_true", help="Also remove mail, contacts, calendar, and chat secrets.")
    auth_logout.add_argument("--yes", action="store_true", help="Remove without prompting.")
    auth_logout.add_argument("--json", action="store_true")
    auth_logout.set_defaults(func=cmd_auth_logout)
    auth_token = auth_sub.add_parser("token")
    auth_token.add_argument("--token", help="Token value. Omit to prompt.")
    auth_token.add_argument("--stdin", action="store_true", help="Read the token from standard input.")
    auth_token.set_defaults(func=cmd_auth_token)
    auth_check = auth_sub.add_parser("check", help="Make one read-only authenticated profile request")
    auth_check.add_argument("--json", action="store_true")
    auth_check.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    auth_check.set_defaults(func=cmd_auth_check)
    auth_mail = auth_sub.add_parser("mail", help="Store the mailbox app password for a profile")
    auth_mail.add_argument("--password", help="Mail app password. Omit to prompt.")
    auth_mail.add_argument("--stdin", action="store_true", help="Read the password from standard input.")
    auth_mail.add_argument("--mailbox", help="Mailbox email address (e.g. user@example.com).")
    auth_mail.add_argument("--imap-host", help="IMAP server host. Defaults to mail.infomaniak.com.")
    auth_mail.add_argument("--imap-port", type=int, help="IMAP server port. Defaults to 993.")
    auth_mail.set_defaults(func=cmd_auth_mail)
    auth_contacts = auth_sub.add_parser("contacts", help="Store CardDAV contacts credentials for a profile")
    auth_contacts.add_argument("--url", help=f"CardDAV DAV URL. Defaults to {DEFAULT_DAV_URL}.")
    auth_contacts.add_argument("--username", help="Infomaniak sync username, e.g. VG00000.")
    auth_contacts.add_argument("--password", help="CardDAV password. Omit to prompt.")
    auth_contacts.add_argument("--stdin", action="store_true", help="Read the password from standard input.")
    auth_contacts.add_argument("--no-discover", action="store_true", help="Skip CardDAV discovery and save --url verbatim.")
    auth_contacts.set_defaults(func=cmd_auth_contacts)
    auth_calendar = auth_sub.add_parser("calendar", help="Store CalDAV calendar credentials for a profile")
    auth_calendar.add_argument("--url", help=f"CalDAV DAV URL. Defaults to {DEFAULT_DAV_URL}.")
    auth_calendar.add_argument("--username", help="Infomaniak sync username, e.g. VG00000.")
    auth_calendar.add_argument("--password", help="CalDAV password. Omit to prompt.")
    auth_calendar.add_argument("--stdin", action="store_true", help="Read the password from standard input.")
    auth_calendar.add_argument("--no-discover", action="store_true", help="Skip CalDAV discovery and save --url verbatim.")
    auth_calendar.set_defaults(func=cmd_auth_calendar)
    auth_chat = auth_sub.add_parser("chat", help="Store kChat/Mattermost connection settings for a profile")
    auth_chat.add_argument("--url", help="kChat base URL.")
    auth_chat.add_argument("--token", help="kChat token. Omit only for trusted main-token fallback.")
    auth_chat.add_argument("--stdin", action="store_true", help="Read the token from standard input.")
    auth_chat.add_argument("--team-id", help="Default kChat team ID.")
    auth_chat.set_defaults(func=cmd_auth_chat)

    mail = sub.add_parser("mail", help="IMAP mail reads and protected draft/send writes")
    mail_sub = mail.add_subparsers(dest="mail_command", required=True)
    mail_folders = mail_sub.add_parser("folders", help="List IMAP folders/labels")
    mail_folders.add_argument("--json", action="store_true")
    mail_folders.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_folders.add_argument(
        "--raw", action="store_true", help="With --json, emit the full raw folder payload."
    )
    mail_folders.set_defaults(func=cmd_mail_folders)
    mail_labels = mail_sub.add_parser("labels", help="Alias for 'folders'")
    mail_labels.add_argument("--json", action="store_true")
    mail_labels.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_labels.add_argument("--raw", action="store_true")
    mail_labels.set_defaults(func=cmd_mail_folders)
    mail_mailboxes = mail_sub.add_parser("mailboxes", help="List configured/discovered mailboxes")
    mail_mailboxes.add_argument("--json", action="store_true")
    mail_mailboxes.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_mailboxes.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    mail_mailboxes.add_argument("--raw", action="store_true", help="With --json, emit the full raw mailbox payload.")
    mail_mailboxes.set_defaults(func=cmd_mail_mailboxes)
    mail_accounts = mail_sub.add_parser("accounts", help="Alias for 'mailboxes'")
    mail_accounts.add_argument("--json", action="store_true")
    mail_accounts.add_argument("--compact", action="store_true")
    mail_accounts.add_argument("--table", action="store_true")
    mail_accounts.add_argument("--raw", action="store_true")
    mail_accounts.set_defaults(func=cmd_mail_mailboxes)
    mail_hostings = mail_sub.add_parser("hostings", help="List mail hostings from account product/service discovery")
    mail_hostings.add_argument("--account-id", help="Account ID. Defaults to the selected profile account.")
    mail_hostings.add_argument("--json", action="store_true")
    mail_hostings.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_hostings.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    mail_hostings.add_argument("--raw", action="store_true", help="With --json, emit the full raw hosting payload.")
    mail_hostings.set_defaults(func=cmd_mail_hostings)
    mail_list = mail_sub.add_parser("list", help="List messages in a folder")
    mail_list.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_list.add_argument("--limit", "-n", type=int, default=20, help="Maximum messages. Defaults to 20.")
    mail_list.add_argument("--unread", action="store_true", help="Only unread messages.")
    mail_list.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_list.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_list.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_list.add_argument("--oldest-first", action="store_true", help="Show oldest matching messages first.")
    mail_list.add_argument("--json", action="store_true")
    mail_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_list.set_defaults(func=cmd_mail_list)
    mail_unread = mail_sub.add_parser("unread", help="Shortcut for 'ik mail list --unread'")
    mail_unread.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_unread.add_argument("--limit", "-n", type=int, default=20, help="Maximum messages. Defaults to 20.")
    mail_unread.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_unread.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_unread.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_unread.add_argument("--oldest-first", action="store_true", help="Show oldest matching messages first.")
    mail_unread.add_argument("--json", action="store_true")
    mail_unread.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_unread.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_unread.set_defaults(func=cmd_mail_unread)
    mail_search = mail_sub.add_parser("search", help="Search messages by query and/or --from/--to/--subject")
    mail_search.add_argument(
        "query",
        nargs="?",
        help="Plain substring matched against SUBJECT or FROM (not a Gmail-style operator). Optional if --from/--to/--subject is given.",
    )
    mail_search.add_argument("--from", dest="from_addr", help="Match the From header (IMAP FROM).")
    mail_search.add_argument("--to", dest="to_addr", help="Match the To header (IMAP TO).")
    mail_search.add_argument("--subject", dest="subject", help="Match the Subject header (IMAP SUBJECT).")
    mail_search.add_argument("--folder", "-f", default="INBOX", help="Folder to search. Defaults to INBOX.")
    mail_search.add_argument("--limit", type=int, help="Maximum number of messages to show.")
    mail_search.add_argument("--unread", action="store_true", help="Only unread messages.")
    mail_search.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_search.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_search.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_search.add_argument("--oldest-first", action="store_true", help="Show oldest matching messages first.")
    mail_search.add_argument("--json", action="store_true")
    mail_search.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_search.add_argument(
        "--raw", action="store_true", help="With --json, emit the full raw message payload."
    )
    mail_search.set_defaults(func=cmd_mail_search)
    mail_read = mail_sub.add_parser("read", help="Read a single message by UID")
    mail_read.add_argument("uid", help="Message UID")
    mail_read.add_argument("--folder", "-f", default="INBOX", help="Folder containing the message. Defaults to INBOX.")
    mail_read.add_argument(
        "--html",
        action="store_true",
        help="Print the raw HTML body instead of the default readable text.",
    )
    mail_read.add_argument("--json", action="store_true")
    mail_read.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_read.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_read.set_defaults(func=cmd_mail_read)

    mail_threads = mail_sub.add_parser("threads", help="Group messages into conversation threads")
    mail_threads.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_threads.add_argument("--limit", "-n", type=int, help="Maximum number of threads to show.")
    mail_threads.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_threads.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_threads.add_argument("--days", type=int, help="Convenience: threads with messages since today - N days.")
    mail_threads.add_argument("--json", action="store_true")
    mail_threads.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_threads.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_threads.set_defaults(func=cmd_mail_threads)

    mail_draft = mail_sub.add_parser("draft", help="Save one plain-text draft (protected write)")
    mail_draft.add_argument("--to", dest="to_addrs", action="append", required=True, help="Recipient; repeatable.")
    mail_draft.add_argument("--cc", dest="cc_addrs", action="append", help="Cc recipient; repeatable.")
    mail_draft.add_argument("--bcc", dest="bcc_addrs", action="append", help="Bcc recipient; repeatable.")
    mail_draft.add_argument("--subject", required=True, help="Message subject.")
    mail_draft.add_argument("--body", required=True, help="Plain-text message body.")
    mail_draft.add_argument("--folder", help="Drafts folder. Defaults to the IMAP special-use Drafts folder.")
    mail_draft.add_argument("--dry-run", action="store_true", help="Preview without saving a draft.")
    mail_draft.add_argument("--yes", "-y", action="store_true", help="Skip confirmation; requires explicit profile.")
    mail_draft.add_argument("--json", action="store_true")
    mail_draft.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_draft.set_defaults(func=cmd_mail_draft)

    mail_send = mail_sub.add_parser("send", help="Send one plain-text message (protected write)")
    mail_send.add_argument("--to", dest="to_addrs", action="append", required=True, help="Recipient; repeatable.")
    mail_send.add_argument("--cc", dest="cc_addrs", action="append", help="Cc recipient; repeatable.")
    mail_send.add_argument("--bcc", dest="bcc_addrs", action="append", help="Bcc recipient; repeatable.")
    mail_send.add_argument("--subject", required=True, help="Message subject.")
    mail_send.add_argument("--body", required=True, help="Plain-text message body.")
    mail_send.add_argument("--dry-run", action="store_true", help="Preview without sending.")
    mail_send.add_argument("--yes", "-y", action="store_true", help="Skip confirmation; requires explicit profile.")
    mail_send.add_argument("--json", action="store_true")
    mail_send.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    mail_send.set_defaults(func=cmd_mail_send)

    contacts = sub.add_parser("contacts", help="CardDAV contacts commands")
    contacts_sub = contacts.add_subparsers(dest="contacts_command", required=True)
    contacts_list = contacts_sub.add_parser("list", help="List contacts")
    contacts_list.add_argument("--limit", type=int, help="Maximum contacts to fetch.")
    contacts_list.add_argument("--json", action="store_true")
    contacts_list.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    contacts_list.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    contacts_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_list.set_defaults(func=cmd_contacts_list)
    contacts_search = contacts_sub.add_parser("search", help="Search contacts by name, email, phone, or organization")
    contacts_search.add_argument("query", help="Case-insensitive contact search query.")
    contacts_search.add_argument("--limit", type=int, help="Maximum matching contacts to show.")
    contacts_search.add_argument("--json", action="store_true")
    contacts_search.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    contacts_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_search.set_defaults(func=cmd_contacts_search)
    contacts_show = contacts_sub.add_parser("show", help="Show one contact by ID")
    contacts_show.add_argument("contact_id", help="Contact ID.")
    contacts_show.add_argument("--json", action="store_true")
    contacts_show.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    contacts_show.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_show.set_defaults(func=cmd_contacts_show)

    contacts_create = contacts_sub.add_parser("create", help="Create one contact (protected write)")
    contacts_create.add_argument("--name", required=True, help="Display name.")
    contacts_create.add_argument("--given-name")
    contacts_create.add_argument("--family-name")
    contacts_create.add_argument("--email", dest="emails", action="append", help="Email address; repeatable.")
    contacts_create.add_argument("--phone", dest="phones", action="append", help="Phone number; repeatable.")
    contacts_create.add_argument("--organization")
    contacts_create.add_argument("--dry-run", action="store_true", help="Preview vCard without writing.")
    contacts_create.add_argument("--yes", "-y", action="store_true", help="Skip confirmation; requires explicit profile.")
    contacts_create.add_argument("--json", action="store_true")
    contacts_create.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    contacts_create.set_defaults(func=cmd_contacts_create)

    contacts_update = contacts_sub.add_parser("update", help="Update one resolved contact (protected write)")
    contacts_update.add_argument("contact_id", help="Contact ID from `ik contacts list`.")
    contacts_update.add_argument("--name", help="Replacement display name.")
    contacts_update.add_argument("--given-name")
    contacts_update.add_argument("--family-name")
    contacts_update.add_argument("--email", dest="emails", action="append", help="Replacement email; repeatable.")
    contacts_update.add_argument("--phone", dest="phones", action="append", help="Replacement phone; repeatable.")
    contacts_update.add_argument("--organization")
    contacts_update.add_argument("--dry-run", action="store_true", help="Resolve and preview without writing.")
    contacts_update.add_argument("--yes", "-y", action="store_true", help="Skip confirmation; requires explicit profile.")
    contacts_update.add_argument("--json", action="store_true")
    contacts_update.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    contacts_update.set_defaults(func=cmd_contacts_update)

    calendar = sub.add_parser("calendar", help="Read-only CalDAV calendar commands")
    calendar_sub = calendar.add_subparsers(dest="calendar_command", required=True)
    calendar_list = calendar_sub.add_parser("list", help="List calendars")
    calendar_list.add_argument("--json", action="store_true")
    calendar_list.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_list.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    calendar_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw calendar payload.")
    calendar_list.set_defaults(func=cmd_calendar_list)
    calendar_upcoming = calendar_sub.add_parser("upcoming", help="List upcoming calendar events")
    calendar_upcoming.add_argument("--days", type=int, default=14, help="Days to include from now. Defaults to 14.")
    calendar_upcoming.add_argument("--calendar", help="Calendar ID or URL to query.")
    calendar_upcoming.add_argument("--limit", type=int, help="Maximum events to fetch.")
    calendar_upcoming.add_argument("--json", action="store_true")
    calendar_upcoming.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_upcoming.add_argument("--raw", action="store_true", help="With --json, emit the full raw event payload.")
    calendar_upcoming.set_defaults(func=cmd_calendar_upcoming)
    calendar_today = calendar_sub.add_parser("today", help="List today's calendar events")
    calendar_today.add_argument("--calendar", help="Calendar ID or URL to query.")
    calendar_today.add_argument("--limit", type=int, help="Maximum events to fetch.")
    calendar_today.add_argument("--json", action="store_true")
    calendar_today.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_today.add_argument("--raw", action="store_true", help="With --json, emit the full raw event payload.")
    calendar_today.set_defaults(func=cmd_calendar_today)
    calendar_search = calendar_sub.add_parser("search", help="Search calendar events")
    calendar_search.add_argument(
        "query", nargs="?",
        help="Case-insensitive event search query. Optional when a filter is supplied.",
    )
    calendar_search.add_argument("--attendee", help="Filter by attendee (case-insensitive substring).")
    calendar_search.add_argument("--uid", help="Filter by exact event UID.")
    calendar_search.add_argument("--status", help="Filter by exact status, e.g. CONFIRMED or CANCELLED.")
    calendar_search.add_argument("--description", help="Filter by description (case-insensitive substring).")
    calendar_search_when = calendar_search.add_mutually_exclusive_group()
    calendar_search_when.add_argument("--all-day", action="store_true", dest="all_day", help="Only all-day events.")
    calendar_search_when.add_argument("--timed", action="store_true", help="Only timed (non all-day) events.")
    calendar_search.add_argument(
        "--days", type=int,
        help="Days to search from now. Defaults to 30 when no explicit range is given.",
    )
    calendar_search.add_argument(
        "--from", dest="from_value",
        help="Range start as an ISO date/datetime (UTC when no offset is supplied).",
    )
    calendar_search.add_argument(
        "--to", dest="to_value",
        help="Range end as an ISO date/datetime (UTC when no offset is supplied).",
    )
    calendar_search.add_argument("--calendar", help="Calendar ID or URL to query.")
    calendar_search.add_argument("--limit", type=int, help="Maximum matching events to show.")
    calendar_search.add_argument("--json", action="store_true")
    calendar_search.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw event payload.")
    calendar_search.set_defaults(func=cmd_calendar_search)
    calendar_repair = calendar_sub.add_parser(
        "repair", help="Resolve and save the profile's real CalDAV collection URL (local config only)"
    )
    calendar_repair.add_argument("--url", help="Set this collection URL explicitly instead of discovering it.")
    calendar_repair.add_argument("--dry-run", action="store_true", help="Show the change without saving it.")
    calendar_repair.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    calendar_repair.add_argument("--json", action="store_true")
    calendar_repair.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_repair.set_defaults(func=cmd_calendar_repair)

    calendar_export = calendar_sub.add_parser(
        "export", help="Export a date range of events as ICS or JSON (read-only)"
    )
    calendar_export.add_argument(
        "--format", choices=("ics", "json"), default="ics", help="Export format. Defaults to ics.",
    )
    calendar_export.add_argument("--output", help="Write to this file instead of stdout.")
    calendar_export.add_argument(
        "--force", action="store_true", help="Overwrite an existing --output file.",
    )
    calendar_export.add_argument(
        "--days", type=int,
        help="Days to export from now. Defaults to 30 when no explicit range is given.",
    )
    calendar_export.add_argument(
        "--from", dest="from_value",
        help="Range start as an ISO date/datetime (UTC when no offset is supplied).",
    )
    calendar_export.add_argument(
        "--to", dest="to_value",
        help="Range end as an ISO date/datetime (UTC when no offset is supplied).",
    )
    calendar_export.add_argument("--calendar", help="Calendar ID or URL to export.")
    calendar_export.add_argument("--limit", type=int, help="Maximum events to export.")
    calendar_export.add_argument("--json", action="store_true")
    calendar_export.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_export.add_argument("--raw", action="store_true", help="With --format json, emit full raw events.")
    calendar_export.set_defaults(func=cmd_calendar_export)

    calendar_show = calendar_sub.add_parser("show", help="Show one calendar event by ID or UID")
    calendar_show.add_argument("event_id", help="Event ID or UID.")
    calendar_show.add_argument("--calendar", help="Calendar ID or URL to query.")
    calendar_show.add_argument("--json", action="store_true")
    calendar_show.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_show.add_argument("--raw", action="store_true", help="With --json, emit the full raw event payload.")
    calendar_show.set_defaults(func=cmd_calendar_show)

    calendar_create = calendar_sub.add_parser("create", help="Create a calendar event (protected write)")
    calendar_create.add_argument("--summary", required=True, help="Event title/summary.")
    calendar_create.add_argument("--start", required=True, help="Start, ISO 8601 (e.g. 2026-07-20T14:00), or a date with --all-day.")
    calendar_create.add_argument("--end", help="End, ISO 8601. Defaults to +1h (timed) or +1 day (all-day).")
    calendar_create.add_argument("--all-day", action="store_true", help="Treat --start/--end as all-day dates (YYYY-MM-DD).")
    calendar_create.add_argument("--location", help="Optional event location.")
    calendar_create.add_argument("--description", help="Optional event description/notes.")
    calendar_create.add_argument("--calendar", help="Target calendar ID or collection URL. Defaults to the profile calendar.")
    calendar_create.add_argument(
        "--reminder-minutes", type=int, action="append", dest="reminder_minutes", metavar="MINUTES",
        help="Display reminder this many minutes before the start. Repeatable.",
    )
    calendar_create.add_argument(
        "--uid",
        help="Deterministic event UID. Re-running with the same UID cannot create a duplicate.",
    )
    calendar_create.add_argument(
        "--if-missing", action="store_true", dest="if_missing",
        help="Treat an existing event with the same --uid as a successful no-op. Requires --uid.",
    )
    calendar_create.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    calendar_create.add_argument(
        "--dry-run", action="store_true",
        help="Show the event and iCalendar body without creating it.",
    )
    calendar_create.add_argument("--json", action="store_true")
    calendar_create.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_create.set_defaults(func=cmd_calendar_create)

    calendar_update = calendar_sub.add_parser(
        "update", help="Conditionally update one exact event (protected write)"
    )
    calendar_update.add_argument("event_id", help="Exact event ID or UID to resolve.")
    calendar_update.add_argument("--summary", help="Replace the event summary.")
    calendar_update.add_argument("--start", help="Replace the start using the event's existing timed/all-day form.")
    calendar_update.add_argument("--end", help="Replace the end using the event's existing timed/all-day form.")
    calendar_update.add_argument("--location", help="Replace the event location.")
    calendar_update.add_argument("--clear-location", action="store_true", help="Remove the event location.")
    calendar_update.add_argument("--description", help="Replace the event description.")
    calendar_update.add_argument("--clear-description", action="store_true", help="Remove the event description.")
    calendar_update.add_argument(
        "--reminder-minutes", type=int,
        help="Change one existing simple alarm while preserving the full VALARM component.",
    )
    calendar_update.add_argument("--calendar", help="Calendar ID or collection URL to query.")
    calendar_update.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    calendar_update.add_argument("--dry-run", action="store_true", help="Resolve and preview without writing.")
    calendar_update.add_argument("--json", action="store_true")
    calendar_update.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_update.set_defaults(func=cmd_calendar_update)

    calendar_cancel = calendar_sub.add_parser(
        "cancel", help="Soft-cancel one exact event with STATUS:CANCELLED (protected write)"
    )
    calendar_cancel.add_argument("event_id", help="Exact event ID or UID to resolve.")
    calendar_cancel.add_argument("--calendar", help="Calendar ID or collection URL to query.")
    calendar_cancel.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    calendar_cancel.add_argument("--dry-run", action="store_true", help="Resolve and preview without writing.")
    calendar_cancel.add_argument("--json", action="store_true")
    calendar_cancel.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_cancel.set_defaults(func=cmd_calendar_cancel)

    calendar_delete = calendar_sub.add_parser(
        "delete", help="Hard-delete one exact event resource (protected write)"
    )
    calendar_delete.add_argument("event_id", help="Exact event ID or UID to resolve.")
    calendar_delete.add_argument(
        "--hard", action="store_true",
        help="Required acknowledgement that this removes the CalDAV resource; prefer cancel when possible.",
    )
    calendar_delete.add_argument("--calendar", help="Calendar ID or collection URL to query.")
    calendar_delete.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    calendar_delete.add_argument("--dry-run", action="store_true", help="Resolve and preview without writing.")
    calendar_delete.add_argument("--json", action="store_true")
    calendar_delete.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    calendar_delete.set_defaults(func=cmd_calendar_delete)

    chat = sub.add_parser("chat", help="Read-only kChat discovery commands")
    chat_sub = chat.add_subparsers(dest="chat_command", required=True)
    chat_teams = chat_sub.add_parser("teams", help="List kChat teams")
    chat_teams.add_argument("--json", action="store_true")
    chat_teams.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_teams.add_argument("--raw", action="store_true", help="With --json, emit the full raw team payload.")
    chat_teams.set_defaults(func=cmd_chat_teams)
    chat_channels = chat_sub.add_parser("channels", help="List kChat channels for a team")
    chat_channels.add_argument("--team-id", help="Team ID. Defaults to saved profile team or the only available team.")
    chat_channels.add_argument("--limit", type=int, help="Maximum channels to show.")
    chat_channels.add_argument("--json", action="store_true")
    chat_channels.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_channels.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    chat_channels.add_argument("--raw", action="store_true", help="With --json, emit the full raw channel payload.")
    chat_channels.set_defaults(func=cmd_chat_channels)
    chat_users = chat_sub.add_parser("users", help="List kChat users for a team")
    chat_users.add_argument("--team-id", help="Team ID. Defaults to saved profile team or the only available team.")
    chat_users.add_argument("--limit", type=int, help="Maximum users to show.")
    chat_users.add_argument("--json", action="store_true")
    chat_users.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_users.add_argument("--table", action="store_true", help="Emit a dense human-readable table.")
    chat_users.add_argument("--raw", action="store_true", help="With --json, emit the full raw user payload.")
    chat_users.set_defaults(func=cmd_chat_users)
    chat_search = chat_sub.add_parser("search", help="Search kChat posts (read-only)")
    chat_search.add_argument("query", help="Search terms.")
    chat_search.add_argument("--team-id", help="Team ID. Defaults to saved profile team or the only available team.")
    chat_search.add_argument("--channel", help="Channel slug or id to resolve read-only and filter results to.")
    chat_search.add_argument("--or", dest="or_search", action="store_true", help="Match any term (is_or_search) instead of all terms.")
    chat_search.add_argument("--limit", type=int, help="Maximum posts to show.")
    chat_search.add_argument("--json", action="store_true")
    chat_search.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw post payload.")
    chat_search.set_defaults(func=cmd_chat_search)
    chat_thread = chat_sub.add_parser("thread", help="Read a kChat thread by post id (read-only)")
    chat_thread.add_argument("post_id", help="Root or reply post id whose thread to read.")
    chat_thread.add_argument("--json", action="store_true")
    chat_thread.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_thread.add_argument("--raw", action="store_true", help="With --json, emit the full raw post payload.")
    chat_thread.set_defaults(func=cmd_chat_thread)

    chat_post = chat_sub.add_parser("post", help="Post a message to a kChat channel (protected write)")
    chat_post.add_argument("message", help="Message text to post.")
    chat_post.add_argument("--channel", required=True, help="Channel slug or id to post to.")
    chat_post.add_argument("--team-id", help="Team ID. Defaults to saved profile team or the only available team.")
    chat_post.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation. Requires an explicit --profile (or IK_PROFILE).",
    )
    chat_post.add_argument(
        "--dry-run", action="store_true",
        help="Resolve the target and show what would be posted, without posting.",
    )
    chat_post.add_argument("--json", action="store_true")
    chat_post.add_argument("--compact", action="store_true", help="Emit compact machine-readable JSON.")
    chat_post.add_argument("--raw", action="store_true", help="With --json, emit the full raw post payload.")
    chat_post.set_defaults(func=cmd_chat_post)

    return parser


def _configure_output_encoding() -> None:
    """Ensure stdout/stderr can emit the CLI's non-ASCII glyphs (✓, ⚠, …).

    On a default Windows console (cp1252) these characters raise
    UnicodeEncodeError. Reconfigure the streams to UTF-8 where supported,
    falling back to errors="replace" so output never crashes.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # Stream does not support reconfiguration (e.g. already detached
            # or a non-text wrapper); leave it as-is.
            pass


def _normalize_global_options(argv: list[str]) -> list[str]:
    """Move global options before the command so argparse accepts them anywhere."""
    global_options: list[str] = []
    command_options: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            command_options.extend(argv[index:])
            break
        if token in {"--profile", "--base-url"}:
            global_options.append(token)
            if index + 1 < len(argv):
                global_options.append(argv[index + 1])
                index += 2
                continue
            index += 1
            continue
        if token.startswith("--profile=") or token.startswith("--base-url="):
            global_options.append(token)
        else:
            command_options.append(token)
        index += 1
    return [*global_options, *command_options]


def main(argv: list[str] | None = None) -> int:
    _configure_output_encoding()
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print(parser.format_help().rstrip())
        print()
        print("Common next steps:")
        print("  ik setup --profile work")
        print("  ik whoami")
        print("  ik doctor")
        print("  ik account services --json")
        print("  ik --help")
        return 0
    args = parser.parse_args(_normalize_global_options(argv))
    try:
        _validate_output_modes(args)
        return args.func(args)
    except (BootstrapError, CalendarError, ChatError, ContactError, InformaniakAPIError, KeyError, MailError, ValueError) as exc:
        if _machine_output(args):
            print(error_json(_error_type(exc), str(exc), 1), file=sys.stderr)
        else:
            print(f"error: {redact(str(exc))}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
