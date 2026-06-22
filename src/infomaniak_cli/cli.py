from __future__ import annotations

import argparse
import datetime
import json
import sys
from typing import Any, Mapping

from . import __version__
from . import update as update_module
from .api import DEFAULT_BASE_URL, InformaniakAPIClient, InformaniakAPIError
from .auth import ContactsPasswordStore, MailPasswordStore, TokenStore
from .bootstrap import BootstrapError, bootstrap_profile
from .debug import probe_profile
from .doctor import run_doctor
from .profiles import ProfileManager
from .services.account import list_accounts, list_products, list_services, slim_accounts
from .services.contacts import (
    ContactError,
    ContactsClient,
    find_contact,
    search_contacts,
    slim_contact,
    slim_contacts,
)
from .services.drive import (
    build_folder_tree,
    find_file,
    list_files,
    list_folders,
    search_files,
    slim_file,
    slim_files,
    slim_folder_tree,
)
from .services.mail import IMAPClient, MailError, slim_message


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


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


def cmd_setup(args: argparse.Namespace) -> int:
    profile_name = args.profile
    if not profile_name and not args.non_interactive:
        profile_name = input("Profile name: ").strip()
    if not profile_name:
        print("error: --profile is required in non-interactive mode", file=sys.stderr)
        return 2

    manager = ProfileManager()
    profile = manager.create_or_update(profile_name, make_default=True)
    print(f"Profile ready: {profile.name}")
    print("Next: run `ik --profile {} auth token` or `ik bootstrap` once auth is implemented.".format(profile.name))
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    profile_name = args.profile or manager.get_current_name()
    if not profile_name:
        print("No profile configured. Run `ik setup --profile <name>` first.", file=sys.stderr)
        return 1

    profile = manager.get(profile_name)
    data = {
        "profile": profile.name,
        "informaniak_user": profile.informaniak_user,
        "account_id": profile.account_id,
        "account_name": profile.account_name,
        "default_mailbox": profile.default_mailbox,
        "default_drive_id": profile.default_drive_id,
        "default_drive_name": profile.default_drive_name,
        "contacts_url": profile.contacts_url,
        "contacts_username": profile.contacts_username,
        "kchat_team_id": profile.kchat_team_id,
    }
    if args.json:
        print_json(data)
    else:
        print(f"Profile: {profile.name}")
        print(f"Informaniak user: {profile.informaniak_user or 'not configured'}")
        print(f"Account: {profile.account_name or profile.account_id or 'not selected'}")
        print(f"Default mailbox: {profile.default_mailbox or 'not selected'}")
        print(f"Default kDrive: {profile.default_drive_name or profile.default_drive_id or 'not selected'}")
        print(f"Contacts: {profile.contacts_username or profile.contacts_url or 'not selected'}")
        print(f"kChat team: {profile.kchat_team_id or 'not selected'}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    data = run_doctor(args.profile)
    if args.json:
        print_json(data)
        return 0

    print(f"Config dir: {data['checks']['config_dir']}")
    print(f"Current profile: {data['profile'] or 'none'}")
    for check, ok in data["checks"].items():
        if check == "config_dir" or check == "profiles_found":
            continue
        marker = "✓" if ok else "⚠"
        print(f"{marker} {check}: {ok}")
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    try:
        release = update_module.fetch_latest_release()
        install_method = update_module.detect_install_method()
        plan = update_module.build_update_plan(__version__, release, install_method=install_method)
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

    if not args.yes:
        answer = input("Update now? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Update cancelled.")
            return 0

    return _run_update_plan(plan)


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
        print("Install method could not be detected. A safe install command is:")
        if plan.command:
            print(_format_command(plan.command))
        return
    if not plan.wheel_url:
        print("Open the release URL above to update manually.")


def _run_update_plan(plan: update_module.UpdatePlan) -> int:
    if not plan.can_auto_update or not plan.command:
        _print_manual_update_guidance(plan)
        return 0
    print(f"Running: {_format_command(plan.command)}")
    result = update_module.run_update_command(plan.command)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        print(f"error: updater command failed with exit code {result.returncode}", file=sys.stderr)
        hint = update_module.update_failure_hint(plan.command, result.stderr)
        if hint:
            print(hint, file=sys.stderr)
        return result.returncode
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
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1
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


def cmd_auth_status(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1
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


def cmd_auth_token(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1
    if args.stdin and args.token:
        print("error: use either --token or --stdin, not both", file=sys.stderr)
        return 2
    if args.stdin:
        token = sys.stdin.read().strip()
    else:
        token = args.token.strip() if args.token else input("Informaniak API token: ").strip()
    TokenStore().save_token(name, token)
    print(f"Token saved for profile: {name}")
    return 0


def cmd_auth_check(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1

    token_store = TokenStore()
    if not token_store.has_token(name):
        print(f"No token configured for profile: {name}. Run `ik --profile {name} auth token` first.", file=sys.stderr)
        return 1

    client = _make_api_client(token_store.load_token(name), args.base_url)
    try:
        profile_data = _unwrap_success_data(client.get("/2/profile"))
        user = _profile_user(profile_data)
    except InformaniakAPIError as exc:
        data = {"ok": False, "profile": name, "user": None, "error": str(exc)}
        if args.json:
            print_json(data)
        else:
            print("Auth check: failed", file=sys.stderr)
            print(f"Profile: {name}", file=sys.stderr)
            print(f"Error: {data['error']}", file=sys.stderr)
        return 1

    data = {"ok": True, "profile": name, "user": user}
    if args.json:
        print_json(data)
    else:
        print("Auth check: ok")
        print(f"Profile: {name}")
        print(f"Informaniak user: {user or 'not available'}")
    return 0


def cmd_auth_mail(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1
    if args.stdin and args.password:
        print("error: use either --password or --stdin, not both", file=sys.stderr)
        return 2
    if args.stdin:
        password = sys.stdin.read().strip()
    else:
        password = args.password.strip() if args.password else input("Mail app password: ").strip()
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
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected.", file=sys.stderr)
        return 1
    if args.stdin and args.password:
        print("error: use either --password or --stdin, not both", file=sys.stderr)
        return 2

    profile = manager.get(name)
    contacts_url = (args.url or profile.contacts_url or "").strip()
    contacts_username = (args.username or profile.contacts_username or "").strip()
    if not contacts_url:
        print("error: --url is required the first time contacts are configured", file=sys.stderr)
        return 2
    if not contacts_username:
        print("error: --username is required the first time contacts are configured", file=sys.stderr)
        return 2

    if args.stdin:
        password = sys.stdin.read().strip()
    else:
        password = args.password.strip() if args.password else input("Contacts CardDAV password: ").strip()
    ContactsPasswordStore().save_password(name, password)
    manager.create_or_update(name, contacts_url=contacts_url, contacts_username=contacts_username)

    print(f"Contacts password saved for profile: {name}")
    return 0


def _mail_profile_or_error(args: argparse.Namespace) -> tuple[Any, str, str, str]:
    """Resolve profile and return (profile, host, port, username, password).

    Raises ValueError if any required mail config is missing.
    """
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        raise ValueError("No profile configured. Run `ik setup --profile <name>` first.")

    profile = manager.get(name)
    mailbox = profile.default_mailbox
    if not mailbox:
        raise ValueError(
            f"No default mailbox configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth mail` to set the mailbox email and app password."
        )

    mail_store = MailPasswordStore()
    if not mail_store.has_password(name):
        raise ValueError(
            f"No mail password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth mail` to set the mailbox app password."
        )

    host = profile.imap_host or "mail.infomaniak.com"
    port = profile.imap_port or 993
    password = mail_store.load_password(name)
    return profile, host, port, mailbox, password


def _mail_client(args: argparse.Namespace) -> IMAPClient:
    profile, host, port, mailbox, password = _mail_profile_or_error(args)
    return IMAPClient(host, port, mailbox, password)


def _mail_profile_and_client(args: argparse.Namespace) -> tuple[Any, IMAPClient]:
    profile, host, port, mailbox, password = _mail_profile_or_error(args)
    return profile, IMAPClient(host, port, mailbox, password)


def _contacts_profile_and_client(args: argparse.Namespace) -> tuple[Any, ContactsClient]:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        raise ValueError("No profile configured. Run `ik setup --profile <name>` first.")

    profile = manager.get(name)
    if not profile.contacts_url or not profile.contacts_username:
        raise ValueError(
            f"No contacts configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth contacts --url <carddav-url> --username <email>` first."
        )

    contacts_store = ContactsPasswordStore()
    if not contacts_store.has_password(name):
        raise ValueError(
            f"No contacts password configured for profile: {profile.name}. "
            f"Run `ik --profile {profile.name} auth contacts --url <carddav-url> --username <email>` first."
        )

    return profile, ContactsClient(profile.contacts_url, profile.contacts_username, contacts_store.load_password(name))


def _today() -> datetime.date:
    """Return today's date. Inject-able for tests."""
    return datetime.date.today()


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
    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        with client:
            folders = client.list_folders()
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        output = folders if args.raw else [{"name": f["name"], "role": f["role"]} for f in folders]
        print_json({"profile": profile.name, "count": len(folders), "folders": output})
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
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
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
            )
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        output = items if args.raw else [slim_message(item) for item in items]
        print_json({"profile": profile.name, "folder": args.folder, "count": len(items), "messages": output})
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
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
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
            )
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        output = items if args.raw else [slim_message(item) for item in items]
        print_json(
            {
                "profile": profile.name,
                "folder": args.folder,
                "query": args.query,
                "count": len(items),
                "messages": output,
            }
        )
    else:
        status = "Unread search results" if args.unread else "Search results"
        print(f"{status} for '{args.query}' in {args.folder}: {len(items)}")
        for item in items:
            print(_render_message_line(item))
    return 0


def cmd_mail_read(args: argparse.Namespace) -> int:
    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    folder = getattr(args, "folder", "INBOX")
    try:
        with client:
            msg = client.fetch_message(args.uid, folder=folder)
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        if not args.raw:
            msg = slim_message(msg)
        print_json({"profile": profile.name, "uid": args.uid, "folder": folder, "message": msg})
    else:
        print(f"UID: {args.uid}")
        print(f"Folder: {folder}")
        print(f"From: {msg.get('from') or '(unknown)'}")
        print(f"To: {msg.get('to') or '(unknown)'}")
        print(f"Subject: {msg.get('subject') or '(no subject)'}")
        print(f"Date: {msg.get('date') or ''}")
        print()
        preview = msg.get("body_preview")
        if preview:
            print(preview)
        else:
            print("(no body preview available)")
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
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile, client = _mail_profile_and_client(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        with client:
            threads = client.list_threads(
                folder=args.folder,
                limit=args.limit,
                since=since,
                before=before,
                on=on,
            )
    except MailError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        output = threads if args.raw else [_slim_thread(t) for t in threads]
        print_json({"profile": profile.name, "folder": args.folder, "count": len(threads), "threads": output})
    else:
        print(f"Threads in {args.folder}: {len(threads)}")
        for thread in threads:
            print(f"[{thread['message_count']}] {thread['subject']} (latest UID {thread['newest_uid']})")
            for item in thread["messages"]:
                print(f"  {_render_message_line(item)}")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    manager = ProfileManager()
    name = args.profile or manager.get_current_name()
    if not name:
        print("No profile selected. Run `ik setup --profile <name>` first.", file=sys.stderr)
        return 1

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
    if args.json:
        print_json(result)
    else:
        print(f"Profile bootstrapped: {result['profile']}")
        print(f"Informaniak user: {result['informaniak_user'] or 'not found'}")
        account = result["account"]
        print(f"Account: {account['name'] or account['id'] or 'not selected'}")
        drive = result["default_drive"]
        print(f"Default kDrive: {drive['name'] or drive['id'] or 'not selected'}")
    return 0


def _profile_and_client(profile_name: str | None = None, base_url: str = DEFAULT_BASE_URL) -> tuple[Any, InformaniakAPIClient]:
    manager = ProfileManager()
    name = profile_name or manager.get_current_name()
    if not name:
        raise ValueError("No profile selected. Run `ik setup --profile <name>` first.")

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
    name = item.get("name") or item.get("display_name") or item.get("label") or item.get("title") or "unnamed"
    return f"{item_id}\t{name}"


def _display_drive_item(item: Mapping[str, Any]) -> str:
    item_type = item.get("type") or "-"
    item_id = item.get("id") or "-"
    name = item.get("name") or item.get("display_name") or "unnamed"
    modified = item.get("last_modified_at") or item.get("modified_at") or item.get("updated_at") or ""
    return f"{item_type}\t{item_id}\t{modified}\t{name}"


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


def _drive_404_error(drive_id: str) -> ValueError:
    path = f"/2/drive/{drive_id}/files"
    return ValueError(
        f"kDrive files endpoint returned 404 for {path}; saved kDrive id may be wrong. "
        "Rerun bootstrap or capture this failing path."
    )


def cmd_account_list(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    accounts = list_accounts(client)
    if args.json:
        output_accounts = accounts if args.raw else slim_accounts(accounts)
        print_json({"profile": profile.name, "accounts": output_accounts})
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
    if args.json:
        print_json({"profile": profile.name, "account_id": account_id, "products": products})
    else:
        print(f"Profile: {profile.name}")
        print(f"Account ID: {account_id}")
        if not products:
            print("No products found.")
        for product in products:
            print(_display_item(product))
    return 0


def cmd_account_services(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    account_id = _account_id_or_error(args, profile)
    services = list_services(client, account_id)
    if args.json:
        print_json({"profile": profile.name, "account_id": account_id, "services": services})
    else:
        print(f"Profile: {profile.name}")
        print(f"Account ID: {account_id}")
        if not services:
            print("No services found.")
        for service in services:
            print(_display_item(service))
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

    if args.json:
        output_files = files if args.raw else slim_files(files, drive_id=drive_id)
        print_json(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "count": len(files),
                "files": output_files,
            }
        )
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


def cmd_drive_folders(args: argparse.Namespace) -> int:
    profile, client = _profile_and_client(args.profile, args.base_url)
    drive_id = _drive_id_or_error(args, profile)
    try:
        folders = list_folders(client, drive_id, parent_id=args.parent_id, limit=args.limit)
    except InformaniakAPIError as exc:
        if exc.status_code == 404:
            raise _drive_404_error(drive_id) from exc
        raise

    if args.json:
        output_folders = folders if args.raw else slim_files(folders, drive_id=drive_id)
        print_json(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "count": len(folders),
                "folders": output_folders,
            }
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

    if args.json:
        output_tree = tree if args.raw else slim_folder_tree(tree, drive_id=drive_id)
        print_json(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "parent_id": args.parent_id,
                "depth": args.depth,
                "count": len(tree),
                "tree": output_tree,
            }
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

    if args.json:
        output_files = files if args.raw else slim_files(files, drive_id=drive_id)
        print_json(
            {
                "profile": profile.name,
                "drive_id": drive_id,
                "query": args.query,
                "count": len(files),
                "files": output_files,
            }
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

    output_file = file_item if args.raw else slim_file(file_item, drive_id=drive_id)
    if args.json:
        print_json({"profile": profile.name, "drive_id": drive_id, "file_id": args.file_id, "file": output_file})
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


def cmd_contacts_list(args: argparse.Namespace) -> int:
    profile, client = _contacts_profile_and_client(args)
    contacts = client.list_contacts(limit=args.limit)

    if args.json:
        output_contacts = contacts if args.raw else slim_contacts(contacts)
        print_json({"profile": profile.name, "count": len(contacts), "contacts": output_contacts})
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

    if args.json:
        output_contacts = contacts if args.raw else slim_contacts(contacts)
        print_json(
            {
                "profile": profile.name,
                "query": args.query,
                "count": len(contacts),
                "contacts": output_contacts,
            }
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

    output_contact = contact if args.raw else slim_contact(contact)
    if args.json:
        print_json({"profile": profile.name, "contact_id": args.contact_id, "contact": output_contact})
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
    setup.add_argument("--profile", required=False, help="Profile name to create/update")
    setup.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting")
    setup.set_defaults(func=cmd_setup)

    whoami = sub.add_parser("whoami", help="Show active profile/account defaults")
    whoami.add_argument("--json", action="store_true")
    whoami.set_defaults(func=cmd_whoami)

    doctor = sub.add_parser("doctor", help="Run local configuration diagnostics")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    bootstrap = sub.add_parser("bootstrap", help="Discover account/service IDs for a profile")
    bootstrap.add_argument("--account-id", help="Account ID to select when multiple accounts are available")
    bootstrap.add_argument("--non-interactive", action="store_true", help="Fail instead of prompting")
    bootstrap.add_argument("--json", action="store_true")
    bootstrap.set_defaults(func=cmd_bootstrap)

    account = sub.add_parser("account", help="Discover accessible accounts, products, and services")
    account_sub = account.add_subparsers(dest="account_command", required=True)
    account_list = account_sub.add_parser("list", help="List accessible accounts")
    account_list.add_argument("--json", action="store_true")
    account_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw account payload.")
    account_list.set_defaults(func=cmd_account_list)
    account_products = account_sub.add_parser("products", help="List products for an account")
    account_products.add_argument("--account-id", help="Account ID. Defaults to the selected profile account.")
    account_products.add_argument("--json", action="store_true")
    account_products.set_defaults(func=cmd_account_products)
    account_services = account_sub.add_parser("services", help="List services for an account")
    account_services.add_argument("--account-id", help="Account ID. Defaults to the selected profile account.")
    account_services.add_argument("--json", action="store_true")
    account_services.set_defaults(func=cmd_account_services)

    drive = sub.add_parser("drive", help="Use kDrive as the selected profile")
    drive_sub = drive.add_subparsers(dest="drive_command", required=True)
    drive_list = drive_sub.add_parser("list", help="List kDrive files and folders")
    drive_list.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_list.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to list.")
    drive_list.add_argument("--limit", type=int, help="Maximum number of files to request.")
    drive_list.add_argument("--json", action="store_true")
    drive_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_list.set_defaults(func=cmd_drive_list)
    drive_folders = drive_sub.add_parser("folders", help="List kDrive folders")
    drive_folders.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_folders.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to list.")
    drive_folders.add_argument("--limit", type=int, help="Maximum number of items to request from the files endpoint.")
    drive_folders.add_argument("--json", action="store_true")
    drive_folders.add_argument("--raw", action="store_true", help="With --json, emit the full raw folder payload.")
    drive_folders.set_defaults(func=cmd_drive_folders)
    drive_tree = drive_sub.add_parser("tree", help="Show a shallow read-only kDrive folder tree")
    drive_tree.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_tree.add_argument("--parent", "--path", dest="parent_id", help="Folder/parent ID to start from.")
    drive_tree.add_argument("--depth", type=int, default=2, help="Folder depth to fetch. Defaults to 2.")
    drive_tree.add_argument("--limit", type=int, help="Maximum number of items to request per folder.")
    drive_tree.add_argument("--json", action="store_true")
    drive_tree.add_argument("--raw", action="store_true", help="With --json, emit the full raw folder payload.")
    drive_tree.set_defaults(func=cmd_drive_tree)
    drive_search = drive_sub.add_parser("search", help="Search kDrive files and folders by name")
    drive_search.add_argument("query", help="Case-insensitive file/folder name query.")
    drive_search.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_search.add_argument("--limit", type=int, help="Maximum number of matching files to show.")
    drive_search.add_argument("--json", action="store_true")
    drive_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_search.set_defaults(func=cmd_drive_search)
    drive_info = drive_sub.add_parser("info", help="Show read-only metadata for a kDrive file or folder")
    drive_info.add_argument("file_id", help="File/folder ID.")
    drive_info.add_argument("--drive-id", help="kDrive ID. Defaults to the selected profile default kDrive.")
    drive_info.add_argument("--json", action="store_true")
    drive_info.add_argument("--raw", action="store_true", help="With --json, emit the full raw file payload.")
    drive_info.set_defaults(func=cmd_drive_info)

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
    update.set_defaults(func=cmd_update)

    profile = sub.add_parser("profile", help="Manage profiles")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_sub.add_parser("list")
    profile_list.add_argument("--json", action="store_true")
    profile_list.set_defaults(func=cmd_profile_list)
    profile_show = profile_sub.add_parser("show")
    profile_show.add_argument("name", nargs="?")
    profile_show.add_argument("--json", action="store_true")
    profile_show.set_defaults(func=lambda args: (setattr(args, "profile", args.name) or cmd_profile_show(args)))
    profile_use = profile_sub.add_parser("use")
    profile_use.add_argument("name")
    profile_use.set_defaults(func=cmd_profile_use)

    auth = sub.add_parser("auth", help="Manage per-profile auth material")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_status = auth_sub.add_parser("status")
    auth_status.add_argument("--json", action="store_true")
    auth_status.set_defaults(func=cmd_auth_status)
    auth_token = auth_sub.add_parser("token")
    auth_token.add_argument("--token", help="Token value. Omit to prompt.")
    auth_token.add_argument("--stdin", action="store_true", help="Read the token from standard input.")
    auth_token.set_defaults(func=cmd_auth_token)
    auth_check = auth_sub.add_parser("check", help="Make one read-only authenticated profile request")
    auth_check.add_argument("--json", action="store_true")
    auth_check.set_defaults(func=cmd_auth_check)
    auth_mail = auth_sub.add_parser("mail", help="Store the mailbox app password for a profile")
    auth_mail.add_argument("--password", help="Mail app password. Omit to prompt.")
    auth_mail.add_argument("--stdin", action="store_true", help="Read the password from standard input.")
    auth_mail.add_argument("--mailbox", help="Mailbox email address (e.g. user@example.com).")
    auth_mail.add_argument("--imap-host", help="IMAP server host. Defaults to mail.infomaniak.com.")
    auth_mail.add_argument("--imap-port", type=int, help="IMAP server port. Defaults to 993.")
    auth_mail.set_defaults(func=cmd_auth_mail)
    auth_contacts = auth_sub.add_parser("contacts", help="Store CardDAV contacts credentials for a profile")
    auth_contacts.add_argument("--url", help="CardDAV address-book collection URL.")
    auth_contacts.add_argument("--username", help="CardDAV username, usually the full email address.")
    auth_contacts.add_argument("--password", help="CardDAV password. Omit to prompt.")
    auth_contacts.add_argument("--stdin", action="store_true", help="Read the password from standard input.")
    auth_contacts.set_defaults(func=cmd_auth_contacts)

    mail = sub.add_parser("mail", help="Read-only IMAP mail commands")
    mail_sub = mail.add_subparsers(dest="mail_command", required=True)
    mail_folders = mail_sub.add_parser("folders", help="List IMAP folders/labels")
    mail_folders.add_argument("--json", action="store_true")
    mail_folders.add_argument(
        "--raw", action="store_true", help="With --json, emit the full raw folder payload."
    )
    mail_folders.set_defaults(func=cmd_mail_folders)
    mail_labels = mail_sub.add_parser("labels", help="Alias for 'folders'")
    mail_labels.add_argument("--json", action="store_true")
    mail_labels.add_argument("--raw", action="store_true")
    mail_labels.set_defaults(func=cmd_mail_folders)
    mail_list = mail_sub.add_parser("list", help="List messages in a folder")
    mail_list.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_list.add_argument("--limit", "-n", type=int, default=20, help="Maximum messages. Defaults to 20.")
    mail_list.add_argument("--unread", action="store_true", help="Only unread messages.")
    mail_list.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_list.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_list.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_list.add_argument("--json", action="store_true")
    mail_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_list.set_defaults(func=cmd_mail_list)
    mail_unread = mail_sub.add_parser("unread", help="Shortcut for 'ik mail list --unread'")
    mail_unread.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_unread.add_argument("--limit", "-n", type=int, default=20, help="Maximum messages. Defaults to 20.")
    mail_unread.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_unread.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_unread.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_unread.add_argument("--json", action="store_true")
    mail_unread.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_unread.set_defaults(func=cmd_mail_unread)
    mail_search = mail_sub.add_parser("search", help="Search messages by query")
    mail_search.add_argument("query", help="Search query string")
    mail_search.add_argument("--folder", "-f", default="INBOX", help="Folder to search. Defaults to INBOX.")
    mail_search.add_argument("--limit", type=int, help="Maximum number of messages to show.")
    mail_search.add_argument("--unread", action="store_true", help="Only unread messages.")
    mail_search.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_search.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_search.add_argument("--days", type=int, help="Convenience: messages since today - N days.")
    mail_search.add_argument("--json", action="store_true")
    mail_search.add_argument(
        "--raw", action="store_true", help="With --json, emit the full raw message payload."
    )
    mail_search.set_defaults(func=cmd_mail_search)
    mail_read = mail_sub.add_parser("read", help="Read a single message by UID")
    mail_read.add_argument("uid", help="Message UID")
    mail_read.add_argument("--folder", "-f", default="INBOX", help="Folder containing the message. Defaults to INBOX.")
    mail_read.add_argument("--json", action="store_true")
    mail_read.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_read.set_defaults(func=cmd_mail_read)

    mail_threads = mail_sub.add_parser("threads", help="Group messages into conversation threads")
    mail_threads.add_argument("--folder", "-f", default="INBOX", help="Folder to list. Defaults to INBOX.")
    mail_threads.add_argument("--limit", "-n", type=int, help="Maximum number of threads to show.")
    mail_threads.add_argument("--since", help="Start date (YYYY-MM-DD, inclusive).")
    mail_threads.add_argument("--before", help="End date (YYYY-MM-DD, exclusive).")
    mail_threads.add_argument("--days", type=int, help="Convenience: threads with messages since today - N days.")
    mail_threads.add_argument("--json", action="store_true")
    mail_threads.add_argument("--raw", action="store_true", help="With --json, emit the full raw message payload.")
    mail_threads.set_defaults(func=cmd_mail_threads)

    contacts = sub.add_parser("contacts", help="Read-only CardDAV contacts commands")
    contacts_sub = contacts.add_subparsers(dest="contacts_command", required=True)
    contacts_list = contacts_sub.add_parser("list", help="List contacts")
    contacts_list.add_argument("--limit", type=int, help="Maximum contacts to fetch.")
    contacts_list.add_argument("--json", action="store_true")
    contacts_list.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_list.set_defaults(func=cmd_contacts_list)
    contacts_search = contacts_sub.add_parser("search", help="Search contacts by name, email, phone, or organization")
    contacts_search.add_argument("query", help="Case-insensitive contact search query.")
    contacts_search.add_argument("--limit", type=int, help="Maximum matching contacts to show.")
    contacts_search.add_argument("--json", action="store_true")
    contacts_search.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_search.set_defaults(func=cmd_contacts_search)
    contacts_show = contacts_sub.add_parser("show", help="Show one contact by ID")
    contacts_show.add_argument("contact_id", help="Contact ID.")
    contacts_show.add_argument("--json", action="store_true")
    contacts_show.add_argument("--raw", action="store_true", help="With --json, emit the full raw contact payload.")
    contacts_show.set_defaults(func=cmd_contacts_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (BootstrapError, ContactError, InformaniakAPIError, KeyError, MailError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
