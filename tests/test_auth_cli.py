import io
import json
import sys

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, TokenStore
from infomaniak_cli.profiles import ProfileManager


class FakeAPI:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.error:
            raise self.error
        return self.payload


def test_auth_token_stdin_strips_token_and_does_not_echo_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-token-from-stdin"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {token}\n\n"))

    assert cli.main(["auth", "token", "--stdin"]) == 0

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert TokenStore().load_token("work") == token


def test_auth_token_argument_still_saves_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "token", "--token", "argument-token"]) == 0

    captured = capsys.readouterr()
    assert "argument-token" not in captured.out
    assert TokenStore().load_token("work") == "argument-token"


def test_auth_contacts_stdin_saves_password_and_metadata_without_echo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    password = "secret-contacts-password"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {password}\n\n"))

    assert cli.main(
        [
            "auth",
            "contacts",
            "--url",
            "https://sync.example.test/addressbooks/user/default/",
            "--username",
            "user@example.com",
            "--stdin",
        ]
    ) == 0

    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err
    assert ContactsPasswordStore().load_password("work") == password
    profile = ProfileManager().get("work")
    assert profile.contacts_url == "https://sync.example.test/addressbooks/user/default/"
    assert profile.contacts_username == "user@example.com"


def test_auth_contacts_requires_url_and_username_first_time(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "contacts", "--password", "pw"]) == 2

    captured = capsys.readouterr()
    assert "--url is required" in captured.err
    assert not ContactsPasswordStore().has_password("work")


def test_auth_calendar_stdin_saves_password_and_metadata_without_echo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    password = "secret-calendar-password"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {password}\n\n"))

    assert cli.main(
        [
            "auth",
            "calendar",
            "--url",
            "https://sync.example.test/calendars/user/work/",
            "--username",
            "user@example.com",
            "--stdin",
        ]
    ) == 0

    captured = capsys.readouterr()
    assert password not in captured.out
    assert password not in captured.err
    assert CalendarPasswordStore().load_password("work") == password
    profile = ProfileManager().get("work")
    assert profile.calendar_url == "https://sync.example.test/calendars/user/work/"
    assert profile.calendar_username == "user@example.com"


def test_auth_calendar_requires_url_and_username_first_time(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "calendar", "--password", "pw"]) == 2

    captured = capsys.readouterr()
    assert "--url is required" in captured.err
    assert not CalendarPasswordStore().has_password("work")


def test_auth_chat_stdin_saves_token_and_metadata_without_echo(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-chat-token"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {token}\n\n"))

    assert cli.main(
        [
            "auth",
            "chat",
            "--url",
            "https://chat.example.test",
            "--team-id",
            "team-1",
            "--stdin",
        ]
    ) == 0

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert ChatTokenStore().load_token("work") == token
    profile = ProfileManager().get("work")
    assert profile.kchat_url == "https://chat.example.test"
    assert profile.kchat_team_id == "team-1"


def test_auth_chat_url_uses_main_token_fallback_for_trusted_host(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-main-token"
    TokenStore().save_token("work", token)

    assert cli.main(["auth", "chat", "--url", "https://cylro.kchat.infomaniak.com"]) == 0

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert not ChatTokenStore().has_token("work")
    profile = ProfileManager().get("work")
    assert profile.kchat_url == "https://cylro.kchat.infomaniak.com"
    assert "main Informaniak API token fallback" in captured.out


def test_auth_chat_ksuite_url_discovers_working_api_base(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-main-token"
    TokenStore().save_token("work", token)
    seen_clients = []

    class DiscoveryClient:
        def __init__(self, base_url, client_token, **kwargs):
            seen_clients.append((base_url, client_token, kwargs))

        def list_teams(self):
            return [{"id": "team-1"}]

    monkeypatch.setattr(cli, "ChatClient", DiscoveryClient)

    assert cli.main(
        [
            "auth",
            "chat",
            "--url",
            "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square",
        ]
    ) == 0

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert seen_clients == [
        (
            "https://cylro.kchat.infomaniak.com",
            token,
            {"auth_source": "main_token_fallback"},
        )
    ]
    profile = ProfileManager().get("work")
    assert profile.kchat_url == "https://cylro.kchat.infomaniak.com"
    assert profile.kchat_ksuite_url == "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square"
    assert profile.kchat_ksuite_account_id == "1988835"
    assert profile.kchat_workspace_slug == "cylro"
    assert profile.kchat_default_channel_slug == "town-square"


def test_auth_chat_ksuite_lookalike_does_not_probe_with_main_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-main-token")

    def fail_client(*args, **kwargs):
        raise AssertionError("main token must not be sent to untrusted hosts")

    monkeypatch.setattr(cli, "ChatClient", fail_client)

    assert cli.main(
        [
            "auth",
            "chat",
            "--url",
            "https://example.com/1988835/kchat/cylro/channels/town-square",
        ]
    ) == 2

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert "not trusted Infomaniak kChat hosts" in captured.err
    assert ProfileManager().get("work").kchat_url is None


def test_auth_chat_ksuite_discovery_failure_has_guidance(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-main-token"
    TokenStore().save_token("work", token)

    class RejectingDiscoveryClient:
        def __init__(self, base_url, client_token, **kwargs):
            self.base_url = base_url

        def list_teams(self):
            raise cli.ChatError("kChat rejected the main Informaniak API token. token=secret-main-token")

    monkeypatch.setattr(cli, "ChatClient", RejectingDiscoveryClient)

    assert cli.main(
        [
            "auth",
            "chat",
            "--url",
            "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square",
        ]
    ) == 2

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert "Could not confirm a working kChat API base URL" in captured.err
    assert "auth chat --url" in captured.err
    assert "--stdin" in captured.err
    profile = ProfileManager().get("work")
    assert profile.kchat_url is None
    assert profile.kchat_ksuite_account_id == "1988835"
    assert profile.kchat_workspace_slug == "cylro"


def test_auth_chat_url_needs_token_or_main_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "chat", "--url", "https://cylro.kchat.infomaniak.com"]) == 2

    captured = capsys.readouterr()
    assert "--token" in captured.err
    assert "trusted Infomaniak kChat host" in captured.err
    assert not ChatTokenStore().has_token("work")
    assert ProfileManager().get("work").kchat_url is None


def test_auth_chat_requires_url_first_time(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "chat", "--token", "secret-chat-token"]) == 2

    captured = capsys.readouterr()
    assert "--url is required" in captured.err
    assert not ChatTokenStore().has_token("work")


def test_auth_check_json_uses_token_base_url_and_resolves_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI({"result": "success", "data": {"email": "user@example.com"}})
    seen_clients = []

    def make_client(token, *, base_url):
        seen_clients.append((token, base_url))
        return fake_api

    monkeypatch.setattr(cli, "InformaniakAPIClient", make_client)

    assert cli.main(["--base-url", "https://api.example.test", "auth", "check", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": True, "profile": "work", "user": "user@example.com"}
    assert seen_clients == [("secret-token", "https://api.example.test")]
    assert fake_api.calls == [("/2/profile", None)]


def test_auth_check_auth_failure_is_clear_and_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-token"
    TokenStore().save_token("work", token)
    error = InformaniakAPIError(
        401,
        "GET /2/profile failed: authentication failed or insufficient scope (token secret-token expired)",
        secrets=[token],
    )
    fake_api = FakeAPI(error=error)
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["auth", "check"]) == 1

    captured = capsys.readouterr()
    assert "Auth check: failed" in captured.err
    assert "authentication failed or insufficient scope" in captured.err
    assert token not in captured.err
