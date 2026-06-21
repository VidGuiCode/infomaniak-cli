from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from . import __version__
from .api import DEFAULT_BASE_URL, InformaniakAPIClient, InformaniakAPIError
from .auth import TokenStore
from .bootstrap import BootstrapError, bootstrap_profile
from .debug import probe_profile
from .doctor import run_doctor
from .profiles import ProfileManager
from .services.account import list_accounts, list_products, list_services, slim_accounts
from .services.drive import list_files, slim_files


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
            path = f"/2/drive/{drive_id}/files"
            raise ValueError(
                f"kDrive files endpoint returned 404 for {path}; saved kDrive id may be wrong. "
                "Rerun bootstrap or capture this failing path."
            ) from exc
        raise

    if args.json:
        output_files = files if args.raw else slim_files(files)
        print_json({"profile": profile.name, "drive_id": drive_id, "parent_id": args.parent_id, "files": output_files})
    else:
        print(f"Profile: {profile.name}")
        print(f"Drive ID: {drive_id}")
        if args.parent_id:
            print(f"Parent ID: {args.parent_id}")
        if not files:
            print("No files found.")
        for file_item in files:
            print(_display_item(file_item))
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

    debug = sub.add_parser("debug", help="Advanced read-only diagnostics")
    debug_sub = debug.add_subparsers(dest="debug_command", required=True)
    debug_probe = debug_sub.add_parser("probe", help="Probe candidate read-only API endpoints")
    debug_probe.add_argument("--json", action="store_true")
    debug_probe.set_defaults(func=cmd_debug_probe)

    version = sub.add_parser("version", help="Show CLI version")
    version.set_defaults(func=cmd_version)

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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (BootstrapError, InformaniakAPIError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
