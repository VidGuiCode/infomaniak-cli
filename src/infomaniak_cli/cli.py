from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .api import InformaniakAPIClient, InformaniakAPIError
from .auth import TokenStore
from .bootstrap import BootstrapError, bootstrap_profile
from .doctor import run_doctor
from .profiles import ProfileManager


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


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
    token = args.token or input("Informaniak API token: ").strip()
    TokenStore().save_token(name, token)
    print(f"Token saved for profile: {name}")
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

    client = InformaniakAPIClient(token_store.load_token(name))
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ik", description="Informaniak/kSuite CLI bridge")
    parser.add_argument("--profile", help="Profile to use for this command")
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
    auth_token.set_defaults(func=cmd_auth_token)

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
