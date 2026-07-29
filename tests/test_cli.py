import json
import os
import subprocess
import sys

import pytest

from infomaniak_cli import cli


def run_ik(tmp_path, *args):
    env = os.environ.copy()
    env["IK_CONFIG_DIR"] = str(tmp_path / "config")
    env["PYTHONPATH"] = "src"
    # conftest's keyring mock is in-process only, so a subprocess would otherwise
    # reach the developer's real OS credential store. The failing backend makes
    # every keyring call raise, so the stores fall back to files under the
    # isolated IK_CONFIG_DIR and the suite stays offline.
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    return subprocess.run(
        [sys.executable, "-m", "infomaniak_cli.cli", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_run_ik_subprocesses_never_touch_the_real_os_keyring(tmp_path):
    """The offline suite must not read or write the developer's machine keyring.

    ``conftest``'s ``_mock_keyring`` only patches the in-process keyring, so any
    test that shells out through ``run_ik`` would otherwise fall through to the
    real OS credential store. A machine entry for a profile named ``work`` then
    leaks a token into the subprocess and turns offline tests into live API
    calls. Pinning a failing keyring backend forces the isolated
    ``IK_CONFIG_DIR`` file fallback instead.
    """
    setup = run_ik(tmp_path, "setup", "--profile", "work", "--non-interactive")
    assert setup.returncode == 0, setup.stderr

    saved = run_ik(tmp_path, "--profile", "work", "auth", "token", "--token", "offline-only-token")
    assert saved.returncode == 0, saved.stderr

    token_file = tmp_path / "config" / "tokens" / "work.token"
    assert token_file.exists(), (
        "token was not written to the isolated config dir, so the subprocess "
        "reached a real keyring backend"
    )
    assert token_file.read_text(encoding="utf-8").strip() == "offline-only-token"


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
    ("drive", "download", "--help"),
    ("drive", "upload", "--help"),
    ("drive", "move", "--help"),
    ("drive", "rename", "--help"),
    ("drive", "rm", "--help"),
    ("drive", "trash", "--help"),
    ("drive", "trash", "list", "--help"),
    ("drive", "trash", "show", "--help"),
    ("drive", "trash", "restore", "--help"),
    ("drive", "share-state", "--help"),
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
    ("calendar", "create", "--help"),
    ("calendar", "update", "--help"),
    ("calendar", "cancel", "--help"),
    ("calendar", "delete", "--help"),
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


def test_global_profile_and_base_url_are_normalized_from_any_depth():
    argv = [
        "calendar", "search", "invoice", "--json",
        "--profile", "work", "--base-url=https://api.example.test",
    ]

    assert cli._normalize_global_options(argv) == [
        "--profile", "work", "--base-url=https://api.example.test",
        "calendar", "search", "invoice", "--json",
    ]


def test_global_option_normalization_respects_double_dash():
    argv = ["chat", "post", "--", "message --profile work"]

    assert cli._normalize_global_options(argv) == argv


def test_main_accepts_global_options_after_subcommand(capsys):
    assert cli.main([
        "version", "--profile", "work", "--base-url", "https://api.example.test"
    ]) == 0

    assert capsys.readouterr().out.strip() == cli.__version__


def test_public_docs_advertise_only_implemented_mail_write_commands():
    docs = "\n".join(
        [
            open("README.md", encoding="utf-8").read(),
            open("docs/commands.md", encoding="utf-8").read(),
        ]
    )

    assert "ik auth login" not in docs
    assert "ik auth refresh" not in docs
    assert "ik admin" not in docs
    assert "ik mail send" in docs
    assert "ik mail draft" in docs


class _ReconfigurableStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, *, encoding=None, errors=None):
        self.calls.append((encoding, errors))


class _PlainStream:
    """A stream that does not support reconfigure (e.g. a non-text wrapper)."""


class _FailingStream:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def reconfigure(self, *, encoding=None, errors=None):
        self.calls += 1
        raise self._exc


def test_configure_output_encoding_sets_utf8_replace(monkeypatch):
    out = _ReconfigurableStream()
    err = _ReconfigurableStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    cli._configure_output_encoding()

    assert out.calls == [("utf-8", "replace")]
    assert err.calls == [("utf-8", "replace")]


def test_configure_output_encoding_ignores_streams_without_reconfigure(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _PlainStream())
    monkeypatch.setattr(sys, "stderr", _PlainStream())

    # Streams lacking reconfigure must be skipped without raising.
    cli._configure_output_encoding()


def test_configure_output_encoding_swallows_reconfigure_errors(monkeypatch):
    out = _FailingStream(ValueError("unsupported"))
    err = _FailingStream(OSError("detached"))
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    # A failing reconfigure() must never crash the CLI.
    cli._configure_output_encoding()

    assert out.calls == 1
    assert err.calls == 1
