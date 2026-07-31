"""CLI-level tests for SMTP resolution and `ik mail doctor` (0.3.6)."""

import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.auth import MailPasswordStore
from infomaniak_cli.profiles import ProfileManager


def _profile(tmp_path, monkeypatch, **metadata):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work", default_mailbox="user@example.com", make_default=True, **metadata
    )
    MailPasswordStore().save_password("work", "device-password")


def _args(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


# --- transport resolution: flag -> profile -> default ---


def test_defaults_are_starttls_on_587(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch)
    profile = ProfileManager().get("work")

    assert cli._smtp_settings(profile, _args()) == {
        "smtp_host": "mail.infomaniak.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
    }


def test_existing_profiles_without_smtp_config_migrate_to_587(tmp_path, monkeypatch):
    """Pre-0.3.6 profiles have no SMTP fields; they must not stay on 465."""
    _profile(tmp_path, monkeypatch, imap_host="mail.infomaniak.com", imap_port=993)
    profile = ProfileManager().get("work")

    settings = cli._smtp_settings(profile, _args())

    assert settings["smtp_port"] == 587
    assert settings["smtp_security"] == "starttls"


def test_profile_values_override_defaults(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, smtp_host="smtp.example.com", smtp_port=465, smtp_security="ssl")
    profile = ProfileManager().get("work")

    assert cli._smtp_settings(profile, _args()) == {
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
    }


def test_flags_override_the_profile(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, smtp_host="smtp.example.com", smtp_port=465, smtp_security="ssl")
    profile = ProfileManager().get("work")

    settings = cli._smtp_settings(
        profile, _args(smtp_host="override.example.com", smtp_port=2525, smtp_security="starttls")
    )

    assert settings == {
        "smtp_host": "override.example.com",
        "smtp_port": 2525,
        "smtp_security": "starttls",
    }


def test_smtp_host_is_independent_of_imap_host(tmp_path, monkeypatch):
    """Before 0.3.6 the IMAP host was reused for sending, misrouting mail."""
    _profile(tmp_path, monkeypatch, imap_host="imap.example.com")
    profile = ProfileManager().get("work")

    assert cli._smtp_settings(profile, _args())["smtp_host"] == "mail.infomaniak.com"


def test_smtp_client_is_built_from_the_resolved_settings(tmp_path, monkeypatch):
    _profile(tmp_path, monkeypatch, smtp_host="smtp.example.com", smtp_port=465, smtp_security="ssl")
    profile = ProfileManager().get("work")

    client = cli._smtp_client(profile, _args())

    assert (client.host, client.port, client.security) == ("smtp.example.com", 465, "ssl")
    assert client.username == "user@example.com"


# --- doctor reports the transport without connecting ---


def test_doctor_reports_the_smtp_transport(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)

    assert cli.main(["doctor", "--json"]) == 0

    capability = json.loads(capsys.readouterr().out)["capabilities"]["mail.send"]
    assert capability["smtp_host"] == "mail.infomaniak.com"
    assert capability["smtp_port"] == 587
    assert capability["smtp_security"] == "starttls"


# --- mail doctor ---


def _fake_probe(results):
    def probe(host, port, **kwargs):
        return {"host": host, "port": port, **results.get(port, {"reachable": True, "error": None})}

    return probe


def test_mail_doctor_separates_reachability_from_authentication(tmp_path, monkeypatch, capsys):
    """The reported bug: a blocked port must never read as an auth failure."""
    _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli,
        "probe_connectivity",
        _fake_probe({993: {"reachable": True, "error": None}, 587: {"reachable": False, "error": "timed out"}}),
    )

    assert cli.main(["mail", "doctor", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["imap"]["reachable"] is True
    assert result["smtp"]["reachable"] is False
    assert result["smtp"]["smtp_port"] == 587
    assert result["auth"]["attempted"] is False
    assert result["auth"]["authenticated"] is False
    assert result["sends_mail"] is False


def test_mail_doctor_human_output_names_the_network_cause(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli,
        "probe_connectivity",
        _fake_probe({993: {"reachable": True, "error": None}, 587: {"reachable": False, "error": "timed out"}}),
    )

    assert cli.main(["mail", "doctor"]) == 0

    out = capsys.readouterr().out
    assert "network problem, not a credential problem" in out
    assert "outbound TCP 587" in out


def test_mail_doctor_does_not_attempt_login_without_the_flag(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "probe_connectivity", _fake_probe({}))

    logins = []

    class FakeClient:
        username = "user@example.com"
        password = "device-password"

        def _connect(self):
            class Conn:
                def login(self, u, p):
                    logins.append(u)

                def quit(self):
                    pass

            return Conn()

    monkeypatch.setattr(cli, "_smtp_client", lambda profile, args=None: FakeClient())

    assert cli.main(["mail", "doctor", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["tls"]["negotiated"] is True
    assert logins == []
    assert result["auth"]["attempted"] is False


def test_mail_doctor_attempts_login_only_with_smtp_auth(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "probe_connectivity", _fake_probe({}))

    logins = []

    class FakeClient:
        username = "user@example.com"
        password = "device-password"

        def _connect(self):
            class Conn:
                def login(self, u, p):
                    logins.append(u)

                def quit(self):
                    pass

            return Conn()

    monkeypatch.setattr(cli, "_smtp_client", lambda profile, args=None: FakeClient())

    assert cli.main(["mail", "doctor", "--smtp-auth", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert logins == ["user@example.com"]
    assert result["auth"]["authenticated"] is True


def test_mail_doctor_never_leaks_the_password_on_auth_failure(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "probe_connectivity", _fake_probe({}))

    class FakeClient:
        username = "user@example.com"
        password = "device-password"

        def _connect(self):
            class Conn:
                def login(self, u, p):
                    raise RuntimeError("login failed for password=device-password")

                def quit(self):
                    pass

            return Conn()

    monkeypatch.setattr(cli, "_smtp_client", lambda profile, args=None: FakeClient())

    assert cli.main(["mail", "doctor", "--smtp-auth", "--json"]) == 0

    captured = capsys.readouterr()
    assert "device-password" not in captured.out
    assert json.loads(captured.out)["auth"]["authenticated"] is False


def test_mail_doctor_is_read_only_in_the_parser():
    """It probes and reports; it must never grow a write gate."""
    parser = cli.build_parser()
    import argparse as _argparse

    def walk(p, prefix=""):
        for action in p._actions:
            if isinstance(action, _argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    path = f"{prefix} {name}".strip()
                    yield path, sub
                    yield from walk(sub, path)

    doctor = dict(walk(parser))["mail doctor"]
    options = {opt for action in doctor._actions for opt in action.option_strings}

    assert "--yes" not in options
    assert "--dry-run" not in options


# --- the send path keeps its write contract ---


def test_mail_send_dry_run_reports_the_plan_without_sending(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)

    def explode(*args, **kwargs):
        raise AssertionError("dry run must not build an SMTP client")

    monkeypatch.setattr(cli, "_smtp_client", explode)

    assert cli.main([
        "mail", "send", "--to", "recipient@example.com", "--subject", "Test",
        "--body", "Body", "--dry-run", "--profile", "work", "--json",
    ]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["sent"] is False
    assert result["notified"] is False
    assert result["profile"] == "work"
    assert result["to"] == ["recipient@example.com"]
    assert result["subject"] == "Test"


def test_mail_send_yes_requires_an_explicit_profile(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("must not send without an explicit profile")

    monkeypatch.setattr(cli, "_smtp_client", explode)

    assert cli.main([
        "mail", "send", "--to", "recipient@example.com", "--subject", "Test",
        "--body", "Body", "--yes", "--json",
    ]) == 1

    assert "explicit" in capsys.readouterr().err


def test_mail_send_uses_the_flag_supplied_transport(tmp_path, monkeypatch, capsys):
    _profile(tmp_path, monkeypatch)
    built = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def send_message(self, message):
            return {"status": "sent"}

    def fake_client(profile, args=None):
        built.update(cli._smtp_settings(profile, args))
        return FakeSMTP()

    monkeypatch.setattr(cli, "_smtp_client", fake_client)

    assert cli.main([
        "mail", "send", "--to", "recipient@example.com", "--subject", "Test", "--body", "Body",
        "--smtp-host", "smtp.example.com", "--smtp-port", "2525", "--smtp-security", "ssl",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert built == {"smtp_host": "smtp.example.com", "smtp_port": 2525, "smtp_security": "ssl"}
