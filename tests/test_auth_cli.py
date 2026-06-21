import io
import json
import sys

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.auth import TokenStore
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
    ProfileManager().create_or_update("cylro", make_default=True)
    token = "secret-token-from-stdin"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {token}\n\n"))

    assert cli.main(["auth", "token", "--stdin"]) == 0

    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err
    assert TokenStore().load_token("cylro") == token


def test_auth_token_argument_still_saves_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)

    assert cli.main(["auth", "token", "--token", "argument-token"]) == 0

    captured = capsys.readouterr()
    assert "argument-token" not in captured.out
    assert TokenStore().load_token("cylro") == "argument-token"


def test_auth_check_json_uses_token_base_url_and_resolves_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI({"result": "success", "data": {"email": "gui@example.com"}})
    seen_clients = []

    def make_client(token, *, base_url):
        seen_clients.append((token, base_url))
        return fake_api

    monkeypatch.setattr(cli, "InformaniakAPIClient", make_client)

    assert cli.main(["--base-url", "https://api.example.test", "auth", "check", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": True, "profile": "cylro", "user": "gui@example.com"}
    assert seen_clients == [("secret-token", "https://api.example.test")]
    assert fake_api.calls == [("/2/profile", None)]


def test_auth_check_auth_failure_is_clear_and_redacted(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)
    token = "secret-token"
    TokenStore().save_token("cylro", token)
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
