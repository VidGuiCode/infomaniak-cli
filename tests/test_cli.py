import json
import os
import subprocess
import sys

import pytest


def run_ik(tmp_path, *args):
    env = os.environ.copy()
    env["IK_CONFIG_DIR"] = str(tmp_path / "config")
    env["PYTHONPATH"] = "src"
    return subprocess.run(
        [sys.executable, "-m", "infomaniak_cli.cli", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cli_setup_whoami_and_doctor_json(tmp_path):
    setup = run_ik(tmp_path, "setup", "--profile", "work", "--non-interactive")
    assert setup.returncode == 0, setup.stderr
    assert "Profile ready: work" in setup.stdout

    whoami = run_ik(tmp_path, "whoami", "--json")
    assert whoami.returncode == 0, whoami.stderr
    data = json.loads(whoami.stdout)
    assert data["profile"] == "work"

    doctor = run_ik(tmp_path, "doctor", "--json")
    assert doctor.returncode == 0, doctor.stderr
    checks = json.loads(doctor.stdout)["checks"]
    assert checks["profile_configured"] is True
    assert checks["token_configured"] is False


def test_cli_bootstrap_requires_token(tmp_path):
    setup = run_ik(tmp_path, "setup", "--profile", "work", "--non-interactive")
    assert setup.returncode == 0, setup.stderr

    bootstrap = run_ik(tmp_path, "bootstrap", "--non-interactive")

    assert bootstrap.returncode == 1
    assert "No token configured for profile: work" in bootstrap.stderr


HELP_COMMANDS = [
    (),
    ("--help",),
    ("setup", "--help"),
    ("whoami", "--help"),
    ("doctor", "--help"),
    ("bootstrap", "--help"),
    ("version", "--help"),
    ("update", "--help"),
    ("debug", "--help"),
    ("debug", "probe", "--help"),
    ("profile", "--help"),
    ("profile", "list", "--help"),
    ("profile", "show", "--help"),
    ("profile", "use", "--help"),
    ("profile", "rename", "--help"),
    ("profile", "delete", "--help"),
    ("auth", "--help"),
    ("auth", "token", "--help"),
    ("auth", "check", "--help"),
    ("auth", "status", "--help"),
    ("auth", "logout", "--help"),
    ("auth", "mail", "--help"),
    ("auth", "contacts", "--help"),
    ("auth", "calendar", "--help"),
    ("auth", "chat", "--help"),
    ("account", "--help"),
    ("account", "list", "--help"),
    ("account", "products", "--help"),
    ("account", "services", "--help"),
    ("drive", "--help"),
    ("drive", "list", "--help"),
    ("drive", "folders", "--help"),
    ("drive", "tree", "--help"),
    ("drive", "recent", "--help"),
    ("drive", "shared", "--help"),
    ("drive", "search", "--help"),
    ("drive", "info", "--help"),
    ("mail", "--help"),
    ("mail", "mailboxes", "--help"),
    ("mail", "accounts", "--help"),
    ("mail", "hostings", "--help"),
    ("mail", "folders", "--help"),
    ("mail", "labels", "--help"),
    ("mail", "list", "--help"),
    ("mail", "unread", "--help"),
    ("mail", "search", "--help"),
    ("mail", "read", "--help"),
    ("mail", "threads", "--help"),
    ("contacts", "--help"),
    ("contacts", "list", "--help"),
    ("contacts", "search", "--help"),
    ("contacts", "show", "--help"),
    ("calendar", "--help"),
    ("calendar", "list", "--help"),
    ("calendar", "upcoming", "--help"),
    ("calendar", "today", "--help"),
    ("calendar", "search", "--help"),
    ("calendar", "show", "--help"),
    ("chat", "--help"),
    ("chat", "teams", "--help"),
    ("chat", "channels", "--help"),
    ("chat", "users", "--help"),
]


@pytest.mark.parametrize("args", HELP_COMMANDS)
def test_cli_help_smoke_all_command_groups(tmp_path, args):
    result = run_ik(tmp_path, *args)

    assert result.returncode == 0, result.stderr
    assert "usage: ik" in result.stdout
    assert result.stderr == ""


def test_cli_root_without_args_prints_friendly_next_steps(tmp_path):
    result = run_ik(tmp_path)

    assert result.returncode == 0
    assert "usage: ik" in result.stdout
    assert "ik setup --profile work" in result.stdout
    assert "ik whoami" in result.stdout
    assert "ik doctor" in result.stdout
    assert "ik account services --json" in result.stdout
    assert "ik --help" in result.stdout
    assert result.stderr == ""


def test_public_docs_do_not_advertise_unimplemented_commands():
    docs = "\n".join(
        [
            open("README.md", encoding="utf-8").read(),
            open("docs/commands.md", encoding="utf-8").read(),
        ]
    )

    assert "ik auth login" not in docs
    assert "ik auth refresh" not in docs
    assert "ik admin" not in docs
    assert "ik mail send" not in docs
    assert "ik mail draft" not in docs
