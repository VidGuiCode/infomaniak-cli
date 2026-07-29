import io
import json
import urllib.error

from infomaniak_cli import cli
from infomaniak_cli.auth import ChatTokenStore, TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.chat import (
    ChatClient,
    ChatError,
    normalize_emoji_name,
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

    def get_channel(self, channel_id):
        self.calls.append(("get_channel", channel_id))
        return {"id": channel_id, "name": channel_id}

    def resolve_channel(self, team_id, ref):
        self.calls.append(("resolve_channel", team_id, ref))
        return {"id": "channel-2", "team_id": team_id, "name": ref, "display_name": "Dev"}

    def create_post(self, channel_id, message):
        self.calls.append(("create_post", channel_id, message))
        return {"id": "post-new", "channel_id": channel_id, "message": message, "create_at": 1700000000000}


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


def test_search_posts_accepts_kchat_empty_list_shape():
    # Live kChat finding: an empty result serializes the post map as a JSON
    # list ({"order": [], "posts": []}), unlike Mattermost's documented
    # object shape. This used to raise "missing order/posts".
    def opener(request, timeout=30):
        return FakeResponse(
            json.dumps({"order": [], "posts": [], "matches": None, "has_limitation": None}).encode("utf-8")
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    assert client.search_posts("team-1", "no-match-query") == []


def test_search_posts_accepts_kchat_list_shape_with_items():
    def opener(request, timeout=30):
        return FakeResponse(
            json.dumps({"order": ["post-2", "post-1"], "posts": [POSTS[0], POSTS[1]]}).encode("utf-8")
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    posts = client.search_posts("team-1", "invoice")

    assert [post["id"] for post in posts] == ["post-2", "post-1"]


def test_get_thread_accepts_kchat_empty_list_shape():
    def opener(request, timeout=30):
        return FakeResponse(json.dumps({"order": [], "posts": []}).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    assert client.get_thread("post-1") == []


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


def test_get_channel_by_id_constructs_url_and_returns_channel():
    seen_requests = []

    def opener(request, timeout=30):
        seen_requests.append(request)
        return FakeResponse(json.dumps(CHANNELS[1]).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    channel = client.get_channel("channel-2")

    assert seen_requests[0].full_url.endswith("/api/v4/channels/channel-2")
    assert channel["id"] == "channel-2"


def test_resolve_channel_falls_back_from_name_to_id():
    def opener(request, timeout=30):
        if "/channels/name/" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return FakeResponse(json.dumps(CHANNELS[1]).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    channel = client.resolve_channel("team-1", "channel-2")

    assert channel["id"] == "channel-2"


def test_resolve_channel_both_fail_gives_actionable_error():
    def opener(request, timeout=30):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    try:
        client.resolve_channel("team-1", "nope")
    except ChatError as exc:
        assert "ik chat channels" in str(exc)
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
    assert is_trusted_infomaniak_kchat_url("https://acme.kchat.infomaniak.com")
    assert is_trusted_infomaniak_kchat_url("https://team-name.kchat.infomaniak.com/")
    assert not is_trusted_infomaniak_kchat_url("https://kchat.infomaniak.com")
    assert not is_trusted_infomaniak_kchat_url("https://example.com")
    assert not is_trusted_infomaniak_kchat_url("https://acme.kchat.infomaniak.com.example.com")


def test_parse_ksuite_browser_kchat_url():
    parsed = parse_ksuite_kchat_url(
        "https://ksuite.infomaniak.com/1234567/kchat/acme/channels/town-square"
    )

    assert parsed is not None
    assert parsed.account_id == "1234567"
    assert parsed.workspace_slug == "acme"
    assert parsed.channel_slug == "town-square"
    assert parsed.original_url == "https://ksuite.infomaniak.com/1234567/kchat/acme/channels/town-square"


def test_ksuite_like_urls_are_not_trusted_on_other_hosts():
    url = "https://example.com/1234567/kchat/acme/channels/town-square"

    assert parse_ksuite_kchat_url(url) is None
    assert derive_kchat_api_base_candidates(url) == []


def test_derive_kchat_api_base_candidate_from_ksuite_url():
    assert derive_kchat_api_base_candidates(
        "https://ksuite.infomaniak.com/1234567/kchat/acme/channels/town-square"
    ) == ["https://acme.kchat.infomaniak.com"]


def test_direct_trusted_kchat_url_candidate_is_normalized():
    assert derive_kchat_api_base_candidates("https://acme.kchat.infomaniak.com/some/path") == [
        "https://acme.kchat.infomaniak.com"
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
        "https://acme.kchat.infomaniak.com",
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
        kchat_url="https://acme.kchat.infomaniak.com",
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
        kchat_url="https://acme.kchat.infomaniak.com",
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
    assert created_clients[0].base_url == "https://acme.kchat.infomaniak.com"
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
        kchat_url="https://acme.kchat.infomaniak.com",
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
        kchat_url="https://acme.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    assert cli.main(["whoami", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["kchat_url"] == "https://acme.kchat.infomaniak.com"
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
        ("resolve_channel", "team-1", "dev"),
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


def test_chat_parser_exposes_the_protected_write_surface():
    parser = cli.build_parser()
    chat_parser = parser._subparsers._group_actions[0].choices["chat"]
    choices = chat_parser._subparsers._group_actions[0].choices

    # 0.2.4 added `post`; 0.2.16 added the conversation lifecycle. Every write
    # here acts on exactly one resolved target, and edit/delete are restricted
    # to the authenticated user's own posts.
    assert set(choices) == {
        "teams", "channels", "users", "search", "thread",
        "post", "reply", "react", "unreact", "edit", "delete",
    }
    # workspace administration stays out of the 0.2.x line entirely
    assert not {
        "create-channel", "join", "leave", "invite", "kick", "webhook", "moderate", "archive",
    } & set(choices)


# --- chat post (protected write) ------------------------------------------


def test_create_post_constructs_request_and_returns_post():
    seen = []

    def opener(request, timeout=30):
        seen.append(request)
        return FakeResponse(json.dumps({"id": "post-9", "channel_id": "channel-2", "message": "hi"}).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)
    post = client.create_post("channel-2", "hi")

    assert post["id"] == "post-9"
    request = seen[0]
    assert request.full_url.endswith("/api/v4/posts")
    assert request.get_method() == "POST"
    assert json.loads(request.data.decode("utf-8")) == {"channel_id": "channel-2", "message": "hi"}


def test_cli_chat_post_dry_run_does_not_post(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["chat", "post", "hello team", "--channel", "dev", "--dry-run", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["posted"] is False
    assert output["channel_id"] == "channel-2"
    assert output["message"] == "hello team"
    # resolved the channel but never posted
    assert ("resolve_channel", "team-1", "dev") in created[0].calls
    assert not any(call[0] == "create_post" for call in created[0].calls)


def test_cli_chat_post_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    # --yes but no explicit --profile: refuse, do not post.
    assert cli.main(["chat", "post", "hi", "--channel", "dev", "--yes"]) == 1
    err = capsys.readouterr().err
    assert "explicit" in err.lower()
    assert not any(call[0] == "create_post" for call in created[0].calls)


def test_cli_chat_post_yes_with_explicit_profile_posts(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    assert cli.main(["--profile", "work", "chat", "post", "ship it", "--channel", "dev", "--yes", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["posted"] is True
    assert output["post"]["id"] == "post-new"
    assert ("create_post", "channel-2", "ship it") in created[0].calls


def test_cli_chat_post_without_yes_in_non_interactive_errors(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)

    # No --yes, non-interactive (pytest stdin is not a TTY): must not post.
    assert cli.main(["--profile", "work", "chat", "post", "hi", "--channel", "dev"]) == 1
    err = capsys.readouterr().err
    assert "requires --yes" in err
    assert not any(call[0] == "create_post" for call in created[0].calls)


def test_cli_chat_post_empty_message_refused(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    monkeypatch.setattr(cli, "ChatClient", FakeChatClient)

    assert cli.main(["--profile", "work", "chat", "post", "   ", "--channel", "dev", "--yes"]) == 1
    assert "empty message" in capsys.readouterr().err.lower()


def test_cli_chat_post_interactive_confirm_posts(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)
    # Simulate a real terminal answering "y".
    monkeypatch.setattr(cli, "_is_non_interactive", lambda args: False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    assert cli.main(["--profile", "work", "chat", "post", "hi there", "--channel", "dev"]) == 0

    out = capsys.readouterr().out
    assert "Message:" in out
    assert "Posted to Dev" in out
    assert ("create_post", "channel-2", "hi there") in created[0].calls


def test_cli_chat_post_interactive_decline_does_not_post(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch, team_id="team-1")
    created = []

    def make_client(base_url, token, **kwargs):
        client = FakeChatClient(base_url, token)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", make_client)
    monkeypatch.setattr(cli, "_is_non_interactive", lambda args: False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    assert cli.main(["--profile", "work", "chat", "post", "hi", "--channel", "dev"]) == 2
    assert "cancelled" in capsys.readouterr().out.lower()
    assert not any(call[0] == "create_post" for call in created[0].calls)


# --- v0.2.16 conversation lifecycle ---------------------------------------


ME = {"id": "user-me", "username": "me"}
OWN_POST = {"id": "post-own", "user_id": "user-me", "channel_id": "channel-1", "message": "mine"}
OTHER_POST = {"id": "post-other", "user_id": "user-someone-else", "channel_id": "channel-1", "message": "theirs"}


def _routing_opener(routes, seen=None):
    """Route by (method, path-suffix) so ordering assumptions stay explicit."""

    def opener(request, timeout=30):
        if seen is not None:
            seen.append(request)
        method = request.get_method()
        for (want_method, suffix), payload in routes.items():
            if method == want_method and request.full_url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(f"unrouted {method} {request.full_url}")

    return opener


def test_me_returns_the_authenticated_user():
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({("GET", "/api/v4/users/me"): ME}),
    )

    assert client.me()["id"] == "user-me"


def test_require_own_post_accepts_a_post_owned_by_the_caller():
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({
            ("GET", "/api/v4/posts/post-own"): OWN_POST,
            ("GET", "/api/v4/users/me"): ME,
        }),
    )

    assert client.require_own_post("post-own")["id"] == "post-own"


def test_require_own_post_refuses_another_users_post_before_any_write():
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({
            ("GET", "/api/v4/posts/post-other"): OTHER_POST,
            ("GET", "/api/v4/users/me"): ME,
        }, seen),
    )

    try:
        client.require_own_post("post-other")
    except ChatError as exc:
        assert "belongs to another user" in str(exc)
    else:
        raise AssertionError("expected ChatError")

    # only reads happened; nothing mutating was issued
    assert {r.get_method() for r in seen} == {"GET"}


def test_create_post_sends_root_id_for_a_threaded_reply():
    captured = {}

    def opener(request, timeout=30):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(json.dumps({"id": "post-new"}).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    client.create_post("channel-1", "reply text", root_id="post-root")

    assert captured["body"]["root_id"] == "post-root"
    assert captured["body"]["channel_id"] == "channel-1"


def test_create_post_omits_root_id_and_file_ids_when_absent():
    captured = {}

    def opener(request, timeout=30):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(json.dumps({"id": "post-new"}).encode("utf-8"))

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    client.create_post("channel-1", "plain")

    assert "root_id" not in captured["body"]
    assert "file_ids" not in captured["body"]


def test_update_post_uses_put_with_the_post_id():
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({("PUT", "/api/v4/posts/post-own"): {"id": "post-own", "message": "edited"}}, seen),
    )

    result = client.update_post("post-own", "edited")

    assert result["message"] == "edited"
    assert seen[0].get_method() == "PUT"
    assert json.loads(seen[0].data.decode("utf-8")) == {"id": "post-own", "message": "edited"}


def test_delete_post_uses_delete():
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({("DELETE", "/api/v4/posts/post-own"): {"status": "OK"}}, seen),
    )

    client.delete_post("post-own")

    assert seen[0].get_method() == "DELETE"


def test_add_reaction_posts_user_post_and_emoji():
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({
            ("GET", "/api/v4/users/me"): ME,
            ("POST", "/api/v4/reactions"): {"user_id": "user-me", "emoji_name": "thumbsup"},
        }, seen),
    )

    client.add_reaction("post-own", ":thumbsup:")

    body = json.loads([r for r in seen if r.get_method() == "POST"][0].data.decode("utf-8"))
    assert body == {"user_id": "user-me", "post_id": "post-own", "emoji_name": "thumbsup"}


def test_remove_reaction_deletes_the_scoped_reaction_path():
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({
            ("GET", "/api/v4/users/me"): ME,
            ("DELETE", "/api/v4/users/user-me/posts/post-own/reactions/thumbsup"): {"status": "OK"},
        }, seen),
    )

    client.remove_reaction("post-own", "thumbsup")

    assert [r.get_method() for r in seen if r.get_method() == "DELETE"] == ["DELETE"]


def test_normalize_emoji_name_strips_colons_and_rejects_bad_names():
    assert normalize_emoji_name(":thumbsup:") == "thumbsup"
    assert normalize_emoji_name("  tada ") == "tada"
    for bad in ["", "  ", "::", "two words", "a/b", "a\\b"]:
        try:
            normalize_emoji_name(bad)
        except ChatError:
            continue
        raise AssertionError(f"expected ChatError for {bad!r}")


def test_upload_file_builds_a_multipart_body_with_the_file_bytes(tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"PDFDATA")
    seen = []
    client = ChatClient(
        "https://chat.example.test", "secret-chat-token",
        opener=_routing_opener({("POST", "/api/v4/files"): {"file_infos": [{"id": "file-1", "name": "report.pdf"}]}}, seen),
    )

    info = client.upload_file("channel-1", path)

    assert info["id"] == "file-1"
    request = seen[0]
    assert request.headers["Content-type"].startswith("multipart/form-data; boundary=")
    body = request.data
    assert b'name="channel_id"' in body
    assert b"channel-1" in body
    assert b'filename="report.pdf"' in body
    assert b"PDFDATA" in body


def test_upload_file_refuses_a_missing_path_and_a_directory(tmp_path):
    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=lambda *a, **k: None)

    try:
        client.upload_file("channel-1", tmp_path / "absent.pdf")
    except ChatError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("expected ChatError")

    folder = tmp_path / "dir"
    folder.mkdir()
    try:
        client.upload_file("channel-1", folder)
    except ChatError as exc:
        assert "not a single file" in str(exc)
    else:
        raise AssertionError("expected ChatError")


def test_lifecycle_errors_still_redact_the_token():
    def opener(request, timeout=30):
        raise urllib.error.HTTPError(
            request.full_url, 500, "boom", {},
            io.BytesIO(b'{"detail":"failed for secret-chat-token"}'),
        )

    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=opener)

    try:
        client.update_post("post-own", "edited")
    except ChatError as exc:
        assert "secret-chat-token" not in str(exc)
    else:
        raise AssertionError("expected ChatError")


# --- v0.2.16 CLI conversation lifecycle -----------------------------------


class _LifecycleChatClient:
    """Chat double covering the v0.2.16 CLI paths."""

    posts = {
        "post-own": {
            "id": "post-own", "user_id": "user-me", "channel_id": "channel-1",
            "message": "my original message", "root_id": "",
        },
        "post-other": {
            "id": "post-other", "user_id": "user-else", "channel_id": "channel-1",
            "message": "someone else's message", "root_id": "",
        },
        "post-reply": {
            "id": "post-reply", "user_id": "user-me", "channel_id": "channel-1",
            "message": "a reply", "root_id": "post-own",
        },
    }

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.edited = {}

    def get_post(self, post_id):
        self.calls.append(("get_post", post_id))
        if post_id not in self.posts:
            raise ChatError(f"kChat post not found: {post_id}")
        return dict(self.edited.get(post_id, self.posts[post_id]))

    def me(self):
        self.calls.append(("me",))
        return {"id": "user-me"}

    def require_own_post(self, post_id):
        self.calls.append(("require_own_post", post_id))
        post = self.get_post(post_id)
        if post.get("user_id") != "user-me":
            raise ChatError(
                f"Refusing to change kChat post {post_id}: it belongs to another user."
            )
        return post

    def create_post(self, channel_id, message, *, root_id=None, file_ids=None):
        self.calls.append(("create_post", channel_id, message, root_id, tuple(file_ids or ())))
        return {"id": "post-new", "channel_id": channel_id, "message": message, "root_id": root_id}

    def update_post(self, post_id, message):
        self.calls.append(("update_post", post_id, message))
        updated = dict(self.posts[post_id])
        updated["message"] = message
        self.edited[post_id] = updated
        return updated

    def delete_post(self, post_id):
        self.calls.append(("delete_post", post_id))
        return {"status": "OK"}

    def add_reaction(self, post_id, emoji, **kw):
        self.calls.append(("add_reaction", post_id, emoji))
        return {"post_id": post_id, "emoji_name": emoji}

    def remove_reaction(self, post_id, emoji, **kw):
        self.calls.append(("remove_reaction", post_id, emoji))
        return {"status": "OK"}

    def get_thread(self, post_id):
        self.calls.append(("get_thread", post_id))
        return [self.posts["post-own"], self.posts["post-reply"]]

    def upload_file(self, channel_id, path):
        self.calls.append(("upload_file", channel_id, str(path)))
        return {"id": "file-1", "name": "report.pdf"}


def _lifecycle_chat(tmp_path, monkeypatch):
    _configured_profile(tmp_path, monkeypatch)
    created = []

    def factory(*args, **kwargs):
        client = _LifecycleChatClient()
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ChatClient", factory)
    return created


def test_cli_chat_reply_threads_to_the_root_and_derives_the_channel(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main([
        "--profile", "work", "chat", "reply", "post-own", "--message", "Thanks.", "--yes", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["posted"] is True
    assert payload["root_id"] == "post-own"
    assert payload["channel_id"] == "channel-1"
    create = [c for c in clients[0].calls if c[0] == "create_post"][0]
    assert create[1] == "channel-1"
    assert create[3] == "post-own"


def test_cli_chat_reply_to_a_reply_threads_to_its_root(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main([
        "--profile", "work", "chat", "reply", "post-reply", "--message", "More.", "--yes", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    # threads stay one level deep: reply to the root, not to the reply
    assert payload["root_id"] == "post-own"


def test_cli_chat_reply_dry_run_uploads_nothing_and_posts_nothing(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"PDFDATA")

    assert cli.main([
        "chat", "reply", "post-own", "--message", "See attached.",
        "--attach", str(attachment), "--dry-run", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["posted"] is False
    assert payload["dry_run"] is True
    assert payload["attachments"][0]["name"] == "report.pdf"
    kinds = {c[0] for c in clients[0].calls}
    assert "upload_file" not in kinds
    assert "create_post" not in kinds


def test_cli_chat_reply_uploads_then_posts_with_file_ids(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"PDFDATA")

    assert cli.main([
        "--profile", "work", "chat", "reply", "post-own", "--message", "See attached.",
        "--attach", str(attachment), "--yes", "--json",
    ]) == 0

    calls = [c[0] for c in clients[0].calls]
    assert calls.index("upload_file") < calls.index("create_post")
    create = [c for c in clients[0].calls if c[0] == "create_post"][0]
    assert create[4] == ("file-1",)


def test_cli_chat_edit_refuses_another_users_post(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main([
        "--profile", "work", "chat", "edit", "post-other", "--message", "hijack", "--yes",
    ]) == 1

    assert "belongs to another user" in capsys.readouterr().err
    assert not any(c[0] == "update_post" for c in clients[0].calls)


def test_cli_chat_delete_refuses_another_users_post(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main(["--profile", "work", "chat", "delete", "post-other", "--yes"]) == 1

    assert "belongs to another user" in capsys.readouterr().err
    assert not any(c[0] == "delete_post" for c in clients[0].calls)


def test_cli_chat_edit_previews_before_and_after_then_reads_back(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main(["chat", "edit", "post-own", "--message", "corrected", "--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["edited"] is False
    assert preview["before"] == "my original message"
    assert preview["after"] == "corrected"
    assert not any(c[0] == "update_post" for c in clients[0].calls)

    assert cli.main([
        "--profile", "work", "chat", "edit", "post-own", "--message", "corrected", "--yes", "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["edited"] is True
    assert payload["post"]["message"] == "corrected"


def test_cli_chat_delete_dry_run_shows_thread_context_and_deletes_nothing(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main(["chat", "delete", "post-own", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted"] is False
    assert payload["thread_size"] == 2
    assert payload["post"]["message"] == "my original message"
    assert not any(c[0] == "delete_post" for c in clients[0].calls)


def test_cli_chat_react_and_unreact_normalize_the_emoji(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main(["--profile", "work", "chat", "react", "post-own", ":thumbsup:", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["emoji"] == "thumbsup"

    assert cli.main(["--profile", "work", "chat", "unreact", "post-own", "thumbsup", "--yes", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is True

    kinds = [c[0] for c in clients[0].calls if c[0] in {"add_reaction", "remove_reaction"}]
    assert kinds == ["add_reaction"] or kinds == []


def test_cli_chat_react_rejects_a_malformed_emoji(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)

    assert cli.main(["--profile", "work", "chat", "react", "post-own", "two words", "--yes"]) == 1

    assert "whitespace" in capsys.readouterr().err
    assert not any(c[0] == "add_reaction" for c in clients[0].calls)


def test_cli_chat_lifecycle_writes_require_an_explicit_profile_for_yes(tmp_path, monkeypatch, capsys):
    _lifecycle_chat(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    for argv in (
        ["chat", "reply", "post-own", "--message", "x", "--yes"],
        ["chat", "edit", "post-own", "--message", "x", "--yes"],
        ["chat", "delete", "post-own", "--yes"],
        ["chat", "react", "post-own", "thumbsup", "--yes"],
    ):
        assert cli.main(argv) == 1
        assert "profile is explicit" in capsys.readouterr().err


def test_chat_parser_exposes_lifecycle_but_no_admin_surface():
    parser = cli.build_parser()
    chat_parser = parser._subparsers._group_actions[0].choices["chat"]
    choices = set(chat_parser._subparsers._group_actions[0].choices)

    assert {"reply", "react", "unreact", "edit", "delete"} <= choices
    # channel creation, membership, moderation and webhooks stay out of 0.2.x
    assert not {"create-channel", "join", "leave", "invite", "kick", "webhook", "moderate"} & choices


def test_upload_file_refuses_a_file_over_the_size_cap(tmp_path):
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 2048)
    client = ChatClient("https://chat.example.test", "secret-chat-token", opener=lambda *a, **k: None)

    try:
        client.upload_file("channel-1", path, max_bytes=1024)
    except ChatError as exc:
        assert "exceeds the" in str(exc)
    else:
        raise AssertionError("expected ChatError")


def test_cli_chat_reply_reports_a_partial_upload_before_failing(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_chat(tmp_path, monkeypatch)
    first = tmp_path / "one.pdf"
    first.write_bytes(b"A")
    second = tmp_path / "two.pdf"
    second.write_bytes(b"B")

    def failing_upload(self, channel_id, path):
        self.calls.append(("upload_file", channel_id, str(path)))
        if str(path).endswith("two.pdf"):
            raise ChatError("kChat request failed: HTTP 507")
        return {"id": "file-1"}

    monkeypatch.setattr(_LifecycleChatClient, "upload_file", failing_upload)

    assert cli.main([
        "--profile", "work", "chat", "reply", "post-own", "--message", "See attached.",
        "--attach", str(first), "--attach", str(second), "--yes",
    ]) == 1

    err = capsys.readouterr().err
    assert "1 earlier file(s) were uploaded" in err
    assert not any(c[0] == "create_post" for c in clients[0].calls)
