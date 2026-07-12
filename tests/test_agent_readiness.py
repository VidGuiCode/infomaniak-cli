"""Agent-readiness pass (0.1.21).

These tests lock the "no hidden prompts in non-interactive/scripted mode"
contract: under automation (the ``IK_NO_INTERACTIVE`` env var, ``--non-interactive``,
or a non-TTY stdin) ``ik`` must fail fast with an actionable message instead of
blocking on ``input()``. They also assert the compact-JSON agent contract and that
missing-config errors point at the exact setup command.
"""

import argparse
import io
import json
import sys

import pytest

from infomaniak_cli import cli
from infomaniak_cli.auth import MailPasswordStore, TokenStore
from infomaniak_cli.profiles import ProfileManager


@pytest.fixture
def work_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    return "work"


# --- non-interactive detection -------------------------------------------------


def test_is_non_interactive_honors_env_flag(monkeypatch):
    args = argparse.Namespace()
    # A real TTY stdin would be interactive; force the env override on.
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    assert cli._is_non_interactive(args) is True


def test_is_non_interactive_true_for_non_tty_stdin(monkeypatch):
    args = argparse.Namespace()
    monkeypatch.delenv("IK_NO_INTERACTIVE", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)
    assert cli._is_non_interactive(args) is True


def test_is_non_interactive_false_for_interactive_tty(monkeypatch):
    args = argparse.Namespace()
    monkeypatch.delenv("IK_NO_INTERACTIVE", raising=False)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    assert cli._is_non_interactive(args) is False


@pytest.mark.parametrize("value,expected", [("1", True), ("true", True), ("YES", True), ("0", False), ("", False)])
def test_env_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("IK_NO_INTERACTIVE", value)
    assert cli._env_flag("IK_NO_INTERACTIVE") is expected


# --- value prompts fail fast instead of hanging --------------------------------


def _no_real_input(monkeypatch):
    """Make any accidental input() call explode rather than block the suite."""

    def _boom(*_args, **_kwargs):
        raise AssertionError("input() must not be called in non-interactive mode")

    monkeypatch.setattr("builtins.input", _boom)


def test_auth_token_without_value_fails_fast_when_non_interactive(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["auth", "token"]) != 0

    err = capsys.readouterr().err
    assert "--stdin" in err
    assert "--token" in err
    assert not TokenStore().has_token("work")


def test_auth_mail_without_value_fails_fast_when_non_interactive(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["auth", "mail", "--mailbox", "user@example.com"]) != 0

    err = capsys.readouterr().err
    assert "--password" in err
    assert "--stdin" in err
    assert not MailPasswordStore().has_password("work")


def test_setup_without_profile_fails_fast_when_non_interactive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["setup"]) == 2
    assert "--profile is required" in capsys.readouterr().err


def test_stdin_path_still_works_under_non_interactive(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO("piped-token\n"))

    assert cli.main(["auth", "token", "--stdin"]) == 0
    assert TokenStore().load_token("work") == "piped-token"


# --- confirmations require --yes instead of prompting --------------------------


def test_profile_delete_requires_yes_when_non_interactive(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["profile", "delete", "work"]) != 0

    assert "--yes" in capsys.readouterr().err
    assert ProfileManager().exists("work")  # not deleted


def test_auth_logout_requires_yes_when_non_interactive(work_profile, monkeypatch, capsys):
    TokenStore().save_token("work", "keep-me")
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["auth", "logout"]) != 0

    assert "--yes" in capsys.readouterr().err
    assert TokenStore().has_token("work")  # still there


def test_profile_delete_yes_proceeds_when_non_interactive(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    _no_real_input(monkeypatch)

    assert cli.main(["profile", "delete", "work", "--yes"]) == 0
    assert not ProfileManager().exists("work")


# --- compact JSON agent contract ----------------------------------------------


def test_whoami_compact_is_single_line_json(work_profile, monkeypatch, capsys):
    assert cli.main(["whoami", "--compact"]) == 0

    out = capsys.readouterr().out.strip()
    assert "\n" not in out
    assert json.loads(out)["profile"] == "work"


@pytest.mark.parametrize("cmd", [
    ["account", "list"],
    ["account", "products"],
    ["contacts", "list"],
    ["calendar", "list"],
    ["calendar", "search", "query"],
    ["calendar", "show", "123"],
    ["mail", "folders"],
    ["mail", "threads"],
    ["drive", "folders"],
    ["drive", "tree"],
])
def test_new_compact_commands_produce_single_line_json_error_without_config(work_profile, monkeypatch, capsys, cmd):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    assert cli.main(cmd + ["--compact"]) != 0
    
    err = capsys.readouterr().err.strip()
    assert "\n" not in err
    parsed = json.loads(err)
    assert "error" in parsed


# --- missing-config errors carry the setup command -----------------------------


def test_mail_unread_missing_config_names_setup_command(work_profile, monkeypatch, capsys):
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")

    assert cli.main(["mail", "unread", "--json"]) != 0

    err = capsys.readouterr().err
    assert "auth mail" in err
