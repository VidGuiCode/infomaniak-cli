import json
import urllib.error

from infomaniak_cli import cli
from infomaniak_cli.auth import ChatTokenStore, TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.chat import (
    ChatClient,
    ChatError,
    derive_kchat_api_base_candidates,
    is_trusted_infomaniak_kchat_url,
    parse_ksuite_kchat_url,
    slim_channel,
    slim_post,
    slim_team,
    slim_user,
)


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


POSTS = [
    {
        "id": "post-1",
        "channel_id": "channel-1",
        "user_id": "user-1",
        "message": "Invoice 1001 is ready",
        "type": "",
        "create_at": 1700000000000,
        "raw": True,
    },
    {
        "id": "post-2",
        "channel_id": "channel-2",
        "user_id": "user-2",
        "message": "Reply about the invoice",
        "type": "",
        "create_at": 1700000100000,
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

    def search_posts(self, team_id, terms, *, is_or_search=False, limit=None):
        self.calls.append(("search_posts", team_id, terms, is_or_search, limit))
        return POSTS[:limit] if limit is not None else list(POSTS)

    def get_thread(self, post_id):
        self.calls.append(("get_thread", post_id))
        return list(POSTS)

    def get_channel_by_name(self, team_id, channel_name):
        self.calls.append(("get_channel_by_name", team_id, channel_name))
        return {"id": "channel-2", "team_id": team_id, "name": channel_name}


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


def test_slim_post_projects_stable_fields():
    assert slim_post(POSTS[0]) == {
        "id": "post-1",
        "channel_id": "channel-1",
        "user_id": "user-1",
        "message": "Invoice 1001 is ready",
        "type": "",
        "create_at": 1700000000000,
        "created_at": "2023-11-14T22:13:20+00:00",
    }


def test_slim_post_is_none_safe_for_missing_timestamp():
    slim = slim_post({"id": "post-9"})
    assert slim["create_at"] is None
    assert slim["created_at"] is None
    assert slim["message"] is None


def test_search_posts_constructs_post_request_and_orders():
    seen_requests = []

    def opener(request, timeout=30):
        seen_requests.append(request)
        assert request.full_url.endswith("/api/v4/teams/team-1/posts/search")
        return FakeResponse(
            json.dumps(
                {
                    "order": ["post-2", "post-1"],
                    "posts": {"post-1": POSTS[0], "post-2": POSTS[1]},
                }
            ).encode("utf-8")
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    posts = client.search_posts("team-1", "invoice")

    assert [post["id"] for post in posts] == ["post-2", "post-1"]
    request = seen_requests[0]
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer secret-chat-token"
    assert json.loads(request.data.decode("utf-8")) == {"terms": "invoice", "is_or_search": False}


def test_search_posts_passes_or_flag_and_limit():
    captured = {}

    def opener(request, timeout=30):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            json.dumps(
                {
                    "order": ["post-1", "post-2"],
                    "posts": {"post-1": POSTS[0], "post-2": POSTS[1]},
                }
            ).encode("utf-8")
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    posts = client.search_posts("team-1", "invoice", is_or_search=True, limit=1)

    assert captured["body"] == {"terms": "invoice", "is_or_search": True}
    assert [post["id"] for post in posts] == ["post-1"]


def test_search_posts_errors_are_redacted():
    def opener(request, timeout=30):
        raise urllib.error.URLError("token=secret-chat-token refused")

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    try:
        client.search_posts("team-1", "invoice")
    except ChatError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ChatError")

    assert "secret-chat-token" not in message
    assert "token=***" in message


def test_get_thread_orders_posts():
    seen_requests = []

    def opener(request, timeout=30):
        seen_requests.append(request)
        return FakeResponse(
            json.dumps(
                {
                    "order": ["post-1", "post-2"],
                    "posts": {"post-1": POSTS[0], "post-2": POSTS[1]},
                }
            ).encode("utf-8")
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    posts = client.get_thread("post-1")

    assert seen_requests[0].get_method() == "GET"
    assert seen_requests[0].full_url.endswith("/api/v4/posts/post-1/thread")
    assert [slim_post(post)["id"] for post in posts] == ["post-1", "post-2"]


def test_get_channel_by_name_constructs_url_and_returns_channel():
    seen_requests = []

    def opener(request, timeout=30):
        seen_requests.append(request)
        return FakeResponse(json.dumps(CHANNELS[1]).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    channel = client.get_channel_by_name("team-1", "dev")

    assert seen_requests[0].get_method() == "GET"
    assert seen_requests[0].full_url.endswith("/api/v4/teams/team-1/channels/name/dev")
    assert channel["id"] == "channel-2"


def test_get_channel_by_name_404_is_clear():
    def opener(request, timeout=30):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    try:
        client.get_channel_by_name("team-1", "missing")
    except ChatError as exc:
        assert str(exc) == "kChat channel not found: missing"
    else:
        raise AssertionError("expected ChatError")


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


def test_parse_ksuite_browser_kchat_url():
    parsed = parse_ksuite_kchat_url(
        "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square"
    )

    assert parsed is not None
    assert parsed.account_id == "1988835"
    assert parsed.workspace_slug == "cylro"
    assert parsed.channel_slug == "town-square"
    assert parsed.original_url == "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square"


def test_ksuite_like_urls_are_not_trusted_on_other_hosts():
    url = "https://example.com/1988835/kchat/cylro/channels/town-square"

    assert parse_ksuite_kchat_url(url) is None
    assert derive_kchat_api_base_candidates(url) == []


def test_derive_kchat_api_base_candidate_from_ksuite_url():
    assert derive_kchat_api_base_candidates(
        "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square"
    ) == ["https://cylro.kchat.infomaniak.com"]


def test_direct_trusted_kchat_url_candidate_is_normalized():
    assert derive_kchat_api_base_candidates("https://cylro.kchat.infomaniak.com/some/path") == [
        "https://cylro.kchat.infomaniak.com"
    ]


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


def test_cli_chat_channels_table_outputs_dense_human_table(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "channels", "--table"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("ID")
    assert "Town Square" in lines[2]
    assert "Dev" in lines[3]


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


def test_cli_chat_search_slim_json_with_limit(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "search", "invoice", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["team_id"] == "team-1"
    assert output["query"] == "invoice"
    assert output["count"] == 1
    assert output["posts"] == [
        {
            "id": "post-1",
            "channel_id": "channel-1",
            "user_id": "user-1",
            "message": "Invoice 1001 is ready",
            "type": "",
            "create_at": 1700000000000,
            "created_at": "2023-11-14T22:13:20+00:00",
        }
    ]
    assert created_clients[0].calls == [("search_posts", "team-1", "invoice", False, 1)]


def test_cli_chat_search_resolves_channel_and_filters(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "search", "invoice", "--channel", "dev", "--or", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert [post["id"] for post in output["posts"]] == ["post-2"]
    assert created_clients[0].calls == [
        ("get_channel_by_name", "team-1", "dev"),
        ("search_posts", "team-1", "invoice", True, None),
    ]


def test_cli_chat_search_raw_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "search", "invoice", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["posts"][0]["raw"] is True


def test_cli_chat_search_requires_team(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id=None)
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["chat", "search", "invoice", "--json"]) == 1

    captured = capsys.readouterr()
    assert "No kChat team configured for profile: work" in captured.err


def test_cli_chat_search_requires_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["chat", "search", "invoice"]) == 1

    captured = capsys.readouterr()
    assert "No kChat configured for profile: work" in captured.err


def test_cli_chat_thread_slim_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created_clients = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        client.kwargs = kwargs
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "thread", "post-1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["post_id"] == "post-1"
    assert output["count"] == 2
    assert [post["id"] for post in output["posts"]] == ["post-1", "post-2"]
    assert "created_at" in output["posts"][0]
    assert created_clients[0].calls == [("get_thread", "post-1")]


def test_cli_chat_thread_does_not_leak_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        kchat_url="https://workspace.kchat.infomaniak.com",
        kchat_team_id="team-1",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    class RejectingClient(FakeChatClient):
        def get_thread(self, post_id):
            raise ChatError(
                "kChat rejected the main Informaniak API token. "
                "Run ik auth chat --url <url> --stdin to save a dedicated kChat token."
            )

    monkeypatch.setattr(cli, "ChatClient", RejectingClient)

    assert cli.main(["chat", "thread", "post-1", "--json"]) == 1

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-main-token" not in captured.err
    assert "kChat rejected the main Informaniak API token" in captured.err


def test_chat_parser_exposes_no_write_commands():
    parser = cli.build_parser()
    chat_parser = parser._subparsers._group_actions[0].choices["chat"]
    choices = chat_parser._subparsers._group_actions[0].choices

    assert set(choices) == {"teams", "channels", "users", "search", "thread"}
    assert not {"post", "create", "delete", "edit", "react", "webhook"} & set(choices)
