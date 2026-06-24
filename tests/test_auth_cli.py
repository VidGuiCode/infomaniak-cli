import io
import json
import sys

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, MailPasswordStore, TokenStore
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


def test_auth_logout_removes_only_selected_profile_main_token_by_default(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    ProfileManager().create_or_update("personal")
    TokenStore().save_token("work", "work-main-token")
    TokenStore().save_token("personal", "personal-main-token")
    MailPasswordStore().save_password("work", "work-mail-password")
    ContactsPasswordStore().save_password("work", "work-contacts-password")
    CalendarPasswordStore().save_password("work", "work-calendar-password")
    ChatTokenStore().save_token("work", "work-chat-token")

    assert cli.main(["auth", "logout", "--yes", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "removed": {
            "api_token": True,
            "calendar_password": False,
            "chat_token": False,
            "contacts_password": False,
            "mail_password": False,
        },
    }
    assert not TokenStore().has_token("work")
    assert TokenStore().load_token("personal") == "personal-main-token"
    assert MailPasswordStore().has_password("work")
    assert ContactsPasswordStore().has_password("work")
    assert CalendarPasswordStore().has_password("work")
    assert ChatTokenStore().has_token("work")


def test_auth_logout_all_removes_service_specific_local_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "work-main-token")
    MailPasswordStore().save_password("work", "work-mail-password")
    ContactsPasswordStore().save_password("work", "work-contacts-password")
    CalendarPasswordStore().save_password("work", "work-calendar-password")
    ChatTokenStore().save_token("work", "work-chat-token")

    assert cli.main(["auth", "logout", "--all", "--yes"]) == 0

    captured = capsys.readouterr()
    assert "work-main-token" not in captured.out
    assert "work-mail-password" not in captured.out
    assert not TokenStore().has_token("work")
    assert not MailPasswordStore().has_password("work")
    assert not ContactsPasswordStore().has_password("work")
    assert not CalendarPasswordStore().has_password("work")
    assert not ChatTokenStore().has_token("work")


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


def test_profile_rename_moves_metadata_tokens_and_current(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_name="Example Co", make_default=True)
    TokenStore().save_token("work", "main-token")
    MailPasswordStore().save_password("work", "mail-password")
    ContactsPasswordStore().save_password("work", "contacts-password")
    CalendarPasswordStore().save_password("work", "calendar-password")
    ChatTokenStore().save_token("work", "chat-token")

    assert cli.main(["profile", "rename", "work", "office", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"old": "work", "new": "office", "current": "office"}
    manager = ProfileManager()
    assert not manager.exists("work")
    assert manager.get("office").account_name == "Example Co"
    assert manager.get_current_name() == "office"
    assert not TokenStore().has_token("work")
    assert TokenStore().load_token("office") == "main-token"
    assert MailPasswordStore().load_password("office") == "mail-password"
    assert ContactsPasswordStore().load_password("office") == "contacts-password"
    assert CalendarPasswordStore().load_password("office") == "calendar-password"
    assert ChatTokenStore().load_token("office") == "chat-token"


def test_profile_rename_fails_if_target_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    ProfileManager().create_or_update("office")

    assert cli.main(["profile", "rename", "work", "office"]) == 1

    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert ProfileManager().exists("work")
    assert ProfileManager().exists("office")


def test_profile_rename_fails_before_metadata_change_if_target_secret_exists(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "work-token")
    TokenStore().save_token("office", "orphan-office-token")

    assert cli.main(["profile", "rename", "work", "office"]) == 1

    captured = capsys.readouterr()
    assert "api_token" in captured.err
    assert ProfileManager().exists("work")
    assert not ProfileManager().exists("office")
    assert TokenStore().load_token("work") == "work-token"
    assert TokenStore().load_token("office") == "orphan-office-token"


def test_profile_delete_yes_removes_profile_and_related_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    ProfileManager().create_or_update("personal")
    TokenStore().save_token("work", "work-main-token")
    TokenStore().save_token("personal", "personal-main-token")
    MailPasswordStore().save_password("work", "mail-password")
    ContactsPasswordStore().save_password("work", "contacts-password")
    CalendarPasswordStore().save_password("work", "calendar-password")
    ChatTokenStore().save_token("work", "chat-token")

    assert cli.main(["profile", "delete", "work", "--yes", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"deleted": "work", "current": "personal"}
    assert not ProfileManager().exists("work")
    assert ProfileManager().exists("personal")
    assert not TokenStore().has_token("work")
    assert TokenStore().load_token("personal") == "personal-main-token"
    assert not MailPasswordStore().has_password("work")
    assert not ContactsPasswordStore().has_password("work")
    assert not CalendarPasswordStore().has_password("work")
    assert not ChatTokenStore().has_token("work")


def test_ik_profile_env_is_used_when_profile_omitted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("IK_PROFILE", "personal")
    ProfileManager().create_or_update("work", make_default=True)
    ProfileManager().create_or_update("personal")
    TokenStore().save_token("personal", "personal-token")

    assert cli.main(["auth", "status", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "personal"
    assert output["token_configured"] is True


def test_explicit_profile_overrides_ik_profile_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("IK_PROFILE", "personal")
    ProfileManager().create_or_update("work", make_default=True)
    ProfileManager().create_or_update("personal")
    TokenStore().save_token("work", "work-token")

    assert cli.main(["--profile", "work", "auth", "status", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["token_configured"] is True


def test_missing_ik_profile_fails_clearly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("IK_PROFILE", "missing")
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["auth", "status"]) == 1

    captured = capsys.readouterr()
    assert "IK_PROFILE" in captured.err
    assert "missing" in captured.err


def test_whoami_compact_outputs_single_line_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_name="Example Co", make_default=True)

    assert cli.main(["whoami", "--compact"]) == 0

    captured = capsys.readouterr()
    assert "\n" not in captured.out.rstrip("\n")
    output = json.loads(captured.out)
    assert output["profile"] == "work"
    assert output["account_name"] == "Example Co"


def test_structured_json_error_for_missing_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))

    assert cli.main(["whoami", "--compact"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    output = json.loads(captured.err)
    assert output["error"]["type"] == "missing_profile"
    assert output["error"]["exit_code"] == 1
    assert "setup --profile" in output["error"]["message"]


def test_structured_json_errors_redact_tokens(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    token = "secret-token"
    TokenStore().save_token("work", token)
    fake_api = FakeAPI(
        error=InformaniakAPIError(
            401,
            "GET /2/profile failed with Authorization: Bearer secret-token",
            secrets=[token],
        )
    )
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["auth", "check", "--compact"]) == 1

    captured = capsys.readouterr()
    assert token not in captured.err
    assert "Authorization: Bearer ***" in json.loads(captured.err)["error"]["message"]


def test_table_conflicts_with_machine_readable_modes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", default_drive_id="drive-1", make_default=True)
    TokenStore().save_token("work", "secret-token")

    assert cli.main(["drive", "list", "--table", "--compact"]) == 1

    output = json.loads(capsys.readouterr().err)
    assert output["error"]["type"] == "validation_error"
    assert "--table cannot be combined" in output["error"]["message"]
