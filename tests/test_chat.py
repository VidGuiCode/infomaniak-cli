import json
import urllib.error

from infomaniak_cli import cli
from infomaniak_cli.auth import ChatTokenStore, TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.chat import ChatClient, ChatError, is_trusted_infomaniak_kchat_url, slim_channel, slim_team, slim_user


TEAMS = [
    {"id": "team-1", "name": "ops", "display_name": "Ops", "description": "Operations", "raw": True},
    {"id": "team-2", "name": "dev", "display_name": "Dev", "description": "Development"},
]

CHANNELS = [
    {
        "id": "channel-1",
        "team_id": "team-1",
        "name": "town-square",
        "display_name": "Town Square",
        "type": "O",
        "purpose": "General updates",
        "header": "Welcome",
        "raw": True,
    },
    {
        "id": "channel-2",
        "team_id": "team-1",
        "name": "dev",
        "display_name": "Dev",
        "type": "P",
        "purpose": "",
        "header": "",
    },
]

USERS = [
    {
        "id": "user-1",
        "username": "alice",
        "nickname": "Ali",
        "first_name": "Alice",
        "last_name": "Admin",
        "email": "alice@example.com",
        "raw": True,
    },
    {
        "id": "user-2",
        "username": "bob",
        "nickname": "",
        "first_name": "Bob",
        "last_name": "Builder",
        "email": "bob@example.com",
    },
]


class FakeChatClient:
    def __init__(self, base_url, token, **kwargs):
        self.base_url = base_url
        self.token = token
        self.kwargs = kwargs
        self.calls = []

    def list_teams(self):
        self.calls.append(("list_teams",))
        return TEAMS

    def list_channels(self, team_id, *, limit=None):
        self.calls.append(("list_channels", team_id, limit))
        return CHANNELS[:limit] if limit is not None else CHANNELS

    def list_users(self, team_id, *, limit=None):
        self.calls.append(("list_users", team_id, limit))
        return USERS[:limit] if limit is not None else USERS


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _configured_profile(tmp_path, monkeypatch, *, team_id="team-1"):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://chat.example.test",
        kchat_team_id=team_id,
        make_default=True,
    )
    ChatTokenStore().save_token("work", "secret-chat-token")


def test_slim_team_projects_stable_fields():
    assert slim_team(TEAMS[0]) == {
        "id": "team-1",
        "name": "ops",
        "display_name": "Ops",
        "description": "Operations",
    }


def test_slim_channel_projects_stable_fields():
    assert slim_channel(CHANNELS[0]) == {
        "id": "channel-1",
        "team_id": "team-1",
        "name": "town-square",
        "display_name": "Town Square",
        "type": "O",
        "purpose": "General updates",
        "header": "Welcome",
    }


def test_slim_user_projects_stable_fields():
    assert slim_user(USERS[0]) == {
        "id": "user-1",
        "username": "alice",
        "nickname": "Ali",
        "first_name": "Alice",
        "last_name": "Admin",
        "email": "alice@example.com",
    }


def test_chat_client_constructs_teams_channels_and_users_requests():
    seen_requests = []

    def opener(request, timeout=30):
        seen_requests.append(request)
        url = request.full_url
        if url.endswith("/api/v4/users/me/teams"):
            return FakeResponse(json.dumps(TEAMS).encode("utf-8"))
        if url.endswith("/api/v4/teams/team-1/channels"):
            return FakeResponse(json.dumps(CHANNELS).encode("utf-8"))
        if url.endswith("/api/v4/users?in_team=team-1"):
            return FakeResponse(json.dumps(USERS).encode("utf-8"))
        raise AssertionError(url)

    client = ChatClient("https://chat.example.test/", "secret-chat-token", opener=opener)

    assert client.list_teams()[0]["id"] == "team-1"
    assert client.list_channels("team-1")[0]["id"] == "channel-1"
    assert client.list_users("team-1")[0]["id"] == "user-1"
    assert [request.get_method() for request in seen_requests] == ["GET", "GET", "GET"]
    assert seen_requests[0].headers["Authorization"] == "Bearer secret-chat-token"


def test_chat_client_errors_are_redacted():
    def opener(request, timeout=30):
        raise urllib.error.URLError("token=secret-chat-token refused")

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    try:
        client.list_teams()
    except ChatError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ChatError")

    assert "secret-chat-token" not in message
    assert "token=***" in message


def test_trusted_infomaniak_kchat_host_detection():
    assert is_trusted_infomaniak_kchat_url("https://cylro.kchat.infomaniak.com")
    assert is_trusted_infomaniak_kchat_url("https://team-name.kchat.infomaniak.com/")
    assert not is_trusted_infomaniak_kchat_url("https://kchat.infomaniak.com")
    assert not is_trusted_infomaniak_kchat_url("https://example.com")
    assert not is_trusted_infomaniak_kchat_url("https://cylro.kchat.infomaniak.com.example.com")


def test_chat_client_fallback_rejection_is_actionable_and_redacted():
    token = "secret-main-token"

    def opener(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            None,
        )

    client = ChatClient(
        "https://cylro.kchat.infomaniak.com",
        token,
        opener=opener,
        auth_source="main_token_fallback",
    )

    try:
        client.list_teams()
    except ChatError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ChatError")

    assert message == (
        "kChat rejected the main Informaniak API token. "
        "Run ik auth chat --url <url> --stdin to save a dedicated kChat token."
    )
    assert token not in message


def test_cli_chat_teams_slim_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "teams", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "count": 2,
        "teams": [
            {"id": "team-1", "name": "ops", "display_name": "Ops", "description": "Operations"},
            {"id": "team-2", "name": "dev", "display_name": "Dev", "description": "Development"},
        ],
    }
    assert created_clients[0].base_url == "https://chat.example.test"
    assert created_clients[0].token == "secret-chat-token"


def test_cli_chat_uses_explicit_chat_token_before_main_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://cylro.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")
    ChatTokenStore().save_token("work", "secret-chat-token")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "teams", "--json"]) == 0

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert created_clients[0].token == "secret-chat-token"
    assert created_clients[0].kwargs["auth_source"] == "explicit_chat_token"


def test_cli_chat_uses_main_token_fallback_for_trusted_host(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://cylro.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "teams", "--json"]) == 0

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert created_clients[0].base_url == "https://cylro.kchat.infomaniak.com"
    assert created_clients[0].token == "secret-main-token"
    assert created_clients[0].kwargs["auth_source"] == "main_token_fallback"


def test_cli_chat_refuses_main_token_fallback_for_untrusted_host(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://example.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    def fail_client(*args, **kwargs):
        raise AssertionError("main token must not be sent to untrusted hosts")

    monkeypatch.setattr(cli, "ChatClient", fail_client)

    assert cli.main(["chat", "teams", "--json"]) == 1

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert "No kChat token configured for profile: work" in captured.err
    assert "trusted Infomaniak kChat host" in captured.err


def test_cli_chat_fallback_rejection_does_not_leak_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://cylro.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    class RejectingClient(FakeChatClient):
        def list_teams(self):
            raise ChatError(
                "kChat rejected the main Informaniak API token. "
                "Run ik auth chat --url <url> --stdin to save a dedicated kChat token."
            )

    monkeypatch.setattr(cli, "ChatClient", RejectingClient)

    assert cli.main(["chat", "teams", "--json"]) == 1

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert "kChat rejected the main Informaniak API token" in captured.err


def test_whoami_distinguishes_chat_auth_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://cylro.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    assert cli.main(["whoami", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["kchat_url"] == "https://cylro.kchat.infomaniak.com"
    assert output["kchat_url_configured"] is True
    assert output["kchat_explicit_token_configured"] is False
    assert output["kchat_main_token_fallback_possible"] is True
    assert "secret-main-token" not in json.dumps(output)


def test_cli_chat_teams_raw_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "teams", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["teams"][0]["raw"] is True


def test_cli_chat_channels_uses_configured_team_id_and_limit(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "channels", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["team_id"] == "team-1"
    assert output["count"] == 1
    assert output["channels"][0]["id"] == "channel-1"
    assert created_clients[0].calls == [("list_channels", "team-1", 1)]


def test_cli_chat_channels_team_id_override(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "channels", "--team-id", "team-override", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["team_id"] == "team-override"
    assert created_clients[0].calls == [("list_channels", "team-override", None)]


def test_cli_chat_channels_requires_team_when_multiple_available(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id=None)
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "channels", "--json"]) == 1

    captured = capsys.readouterr()
    assert "No kChat team configured for profile: work" in captured.err
    assert "--team-id" in captured.err


def test_cli_chat_channels_uses_only_available_team(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id=None)

    class OneTeamClient(FakeChatClient):
        def list_teams(self):
            self.calls.append(("list_teams",))
            return [TEAMS[0]]

    monkeypatch.setattr(cli, "ChatClient", OneTeamClient)

    assert cli.main(["chat", "channels", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["team_id"] == "team-1"


def test_cli_chat_users_json_and_limit(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "users", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "team_id": "team-1",
        "count": 1,
        "users": [
            {
                "id": "user-1",
                "username": "alice",
                "nickname": "Ali",
                "first_name": "Alice",
                "last_name": "Admin",
                "email": "alice@example.com",
            }
        ],
    }


def test_cli_chat_requires_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["chat", "teams"]) == 1

    captured = capsys.readouterr()
    assert "No kChat configured for profile: work" in captured.err
    assert "auth chat" in captured.err


def test_chat_parser_exposes_no_write_commands():
    parser = cli.build_parser()
    chat_parser = parser._subparsers._group_actions[0].choices["chat"]
    choices = chat_parser._subparsers._group_actions[0].choices

    assert set(choices) == {"teams", "channels", "users"}
    assert not {"post", "create", "delete", "edit", "react", "webhook"} & set(choices)
